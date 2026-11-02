"""Export the tool schemas for each scenario in MCP tool format.

Usage (from the repo root, inside WSL):
    .venv/bin/python -m pipeline.export_schemas            # all scenarios
    .venv/bin/python -m pipeline.export_schemas banking    # one scenario

Writes pipeline/schemas/<scenario>.json:
    {"scenario": ..., "source": ..., "exported_at": ..., "tools": [{"name", "description", "inputSchema"}]}

AgentDojo suites are read from the installed agentdojo package. The MCP scenario starts the
official fetch, git, and filesystem servers over stdio and asks each one for tools/list, the
same call an MCP client makes.
"""
import asyncio
import datetime
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA_DIR = Path(__file__).parent / "schemas"
AGENTDOJO_SUITES = ("workspace", "travel", "banking", "slack")
AGENTDOJO_VERSION = "v1.2"

# MCP reference servers: (label, command, args). The filesystem server is TypeScript and runs
# through npx; fetch and git are Python and run through uvx.
MCP_SERVERS = [
    ("fetch", "uvx", ["mcp-server-fetch"]),
    ("git", "uvx", ["mcp-server-git"]),
    ("filesystem", "npx", ["-y", "@modelcontextprotocol/server-filesystem", "{tmpdir}"]),
]


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def export_agentdojo(suite_name):
    from agentdojo.task_suite.load_suites import get_suites

    suite = get_suites(AGENTDOJO_VERSION)[suite_name]
    tools = [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.parameters.model_json_schema(),
        }
        for t in suite.tools
    ]
    return {
        "scenario": suite_name,
        "source": f"agentdojo {importlib.metadata.version('agentdojo')}, suite {suite_name}, benchmark {AGENTDOJO_VERSION}",
        "exported_at": _now(),
        "tools": sorted(tools, key=lambda t: t["name"]),
    }


async def _list_mcp_tools(command, args):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=command, args=args)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            result = await session.list_tools()
            # The mcp SDK renamed camelCase fields to snake_case in 2.x; accept either.
            info = getattr(init, "server_info", None) or getattr(init, "serverInfo")
            server = f"{info.name} {info.version}"
            tools = [
                {"name": t.name, "description": t.description or "",
                 "inputSchema": getattr(t, "input_schema", None) or getattr(t, "inputSchema")}
                for t in result.tools
            ]
            return server, tools


def _path_for(command, path):
    """Under WSL, a Windows binary (e.g. /mnt/c/.../npx) needs a Windows path."""
    exe = shutil.which(command) or ""
    if exe.startswith("/mnt/"):
        return subprocess.check_output(["wslpath", "-w", path], text=True).strip()
    return path


def export_mcp():
    servers, tools = [], []
    # Temp dir inside the repo so a Windows npx under WSL can also see it.
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent.parent) as tmpdir:
        for label, command, args in MCP_SERVERS:
            args = [a.replace("{tmpdir}", _path_for(command, tmpdir)) for a in args]
            server, server_tools = asyncio.run(_list_mcp_tools(command, args))
            servers.append(server)
            for t in server_tools:
                t["server"] = label
            tools.extend(server_tools)
    return {
        "scenario": "mcp",
        "source": "MCP reference servers via tools/list: " + ", ".join(servers),
        "exported_at": _now(),
        "tools": sorted(tools, key=lambda t: (t["server"], t["name"])),
    }


def export(scenario):
    data = export_mcp() if scenario == "mcp" else export_agentdojo(scenario)
    SCHEMA_DIR.mkdir(exist_ok=True)
    out = SCHEMA_DIR / f"{scenario}.json"
    out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{scenario}: {len(data['tools'])} tools -> {out}")


def main():
    scenarios = sys.argv[1:] or [*AGENTDOJO_SUITES, "mcp"]
    for s in scenarios:
        if s != "mcp" and s not in AGENTDOJO_SUITES:
            sys.exit(f"unknown scenario {s!r}; choose from {', '.join(AGENTDOJO_SUITES)}, mcp")
        export(s)


if __name__ == "__main__":
    main()
