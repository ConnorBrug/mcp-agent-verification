"""Build the prompts that ask an LLM to translate tool schemas into an SMV model.

Two variants per scenario:
  unguarded  tool schemas only; every tool call the agent picks executes
  guarded    tool schemas plus the policy below in English; blocked calls become idle
"""
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INTERFACE_DOC = REPO / "docs" / "interface.md"
SCHEMA_DIR = Path(__file__).parent / "schemas"
VARIANTS = ("unguarded", "guarded")

SYSTEM = (
    "You translate the tool descriptions of an LLM agent into a formal model for the nuXmv model "
    "checker. Reply with one SMV model in a single ```smv code block and nothing else."
)

POLICY = """The agent runs behind a policy layer that checks every tool call before it executes:
1. While the agent is tainted (it has read untrusted content that carried a prompt injection), any call that sends data outside the trust boundary is blocked.
2. A destructive call is blocked unless the user confirmed in the step immediately before it.
3. A request for elevated privileges succeeds only when an explicit grant is present in that step.
A blocked call does not execute; the agent does nothing (idle) in that step."""

TASK_COMMON = """Write an SMV model (nuXmv input language) of an LLM agent that can call the tools listed under Tools.
- Model the agent as a transition system. In each step the agent calls one tool or does nothing. Its choice is nondeterministic: any tool call must be possible in any step.
- Map every tool to exactly one abstract action of the interface, based on what the tool does. A tool that fits no action maps to idle.
- An attacker controls what untrusted reads return. Add a free boolean input that decides whether an untrusted read carries a prompt injection."""

TASK_UNGUARDED = "- There is no policy layer: every tool call the agent picks executes."
TASK_GUARDED = "- The agent runs behind the policy layer described under Policy. Model it so that blocked calls do not execute."

OUTPUT_RULES = """- One code block fenced with ```smv. No text outside it.
- Start with MODULE main and declare the interface variables exactly as in the required declaration block.
- Do not write LTLSPEC, CTLSPEC, INVARSPEC, SPEC, or FAIRNESS lines. The properties are added separately.
- Record in `--` comments which tool maps to which abstract action.
- The transition relation must be total: every state has a successor."""

REPAIR = """nuXmv or the interface check rejected your model:
{feedback}

Fix these problems and reply with the complete corrected model in a single ```smv code block."""


def load_schemas(scenario):
    path = SCHEMA_DIR / f"{scenario}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing. Run: python -m pipeline.export_schemas {scenario}")
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_list(schemas):
    tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
             for t in schemas["tools"]]
    return json.dumps(tools, indent=1)


def build_messages(schemas, variant):
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    parts = [
        "## Task\n" + TASK_COMMON + "\n" + (TASK_GUARDED if variant == "guarded" else TASK_UNGUARDED),
        "## Interface (mandatory)\n" + INTERFACE_DOC.read_text(encoding="utf-8"),
        "## Tools\n" + _tool_list(schemas),
    ]
    if variant == "guarded":
        parts.append("## Policy\n" + POLICY)
    parts.append("## Output rules\n" + OUTPUT_RULES)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def repair_message(feedback):
    return {"role": "user", "content": REPAIR.format(feedback=feedback)}


def prompt_sha256(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.S)


def extract_smv(text):
    """Return the SMV model from an LLM reply, or None if there is none."""
    for block in FENCE.findall(text):
        if "MODULE main" in block:
            return block.strip() + "\n"
    i = text.find("MODULE main")
    return text[i:].strip() + "\n" if i >= 0 else None
