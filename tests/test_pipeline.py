"""Pipeline tests. nuXmv tests are skipped when nuXmv is not on PATH.

Run from the repo root inside WSL:  .venv/bin/python -m pytest -q tests
"""
import json
import shutil
from pathlib import Path

import pytest

from pipeline.check import check_model, lint_interface, run_nuxmv
from pipeline.generate import generate_one
from pipeline.llm import ReplayClient
from pipeline.prompt import build_messages, extract_smv, load_schemas

REPO = Path(__file__).resolve().parent.parent
GUARDED = (REPO / "models/reference/agent_guarded.smv").read_text()
UNGUARDED = (REPO / "models/reference/agent_unguarded.smv").read_text()
needs_nuxmv = pytest.mark.skipif(shutil.which("nuXmv") is None, reason="nuXmv not on PATH")

BROKEN = "MODULE main\nVAR x : boolean;\nASSIGN next(x) := y;\n"


# --- prompt ------------------------------------------------------------------

def test_extract_smv_from_fenced_block():
    reply = "Here it is:\n```smv\n" + GUARDED + "```\nDone."
    assert extract_smv(reply).startswith("-- agent_guarded.smv")


def test_extract_smv_without_fence():
    assert extract_smv("Sure.\n" + GUARDED).startswith("MODULE main")


def test_extract_smv_none():
    assert extract_smv("I cannot help with that.") is None


def test_prompt_lists_every_tool_and_policy_only_when_guarded():
    schemas = load_schemas("banking")
    unguarded = build_messages(schemas, "unguarded")[1]["content"]
    guarded = build_messages(schemas, "guarded")[1]["content"]
    for tool in schemas["tools"]:
        assert f'"name": "{tool["name"]}"' in unguarded
    assert "## Policy" in guarded and "## Policy" not in unguarded
    assert "no policy layer" in unguarded


# --- interface lint ----------------------------------------------------------

def test_lint_passes_reference_models():
    assert lint_interface(GUARDED) == []
    assert lint_interface(UNGUARDED) == []


def test_lint_catches_own_specs():
    errors = lint_interface(GUARDED + "\nLTLSPEC G TRUE\n")
    assert any("own specifications" in e for e in errors)


def test_lint_catches_wrong_action_enum():
    bad = GUARDED.replace("request_grant}", "request_grant, shell}")
    assert any("`action` must have exactly" in e for e in lint_interface(bad))


def test_lint_catches_constrained_grant():
    bad = GUARDED.replace("ASSIGN\n", "ASSIGN\n  next(grant) := FALSE;\n", 1)
    assert any("unconstrained" in e for e in lint_interface(bad))


def test_lint_ignores_comments():
    assert lint_interface(GUARDED + "\n-- LTLSPEC G TRUE is not a real spec here\n") == []


# --- nuXmv ---------------------------------------------------------------------

@needs_nuxmv
def test_nuxmv_guarded_holds():
    r = check_model(GUARDED)
    assert r.ok and r.total is True
    assert len(r.verdicts) == 3 and all(r.verdicts.values())


@needs_nuxmv
def test_nuxmv_unguarded_violates_all():
    r = check_model(UNGUARDED)
    assert r.ok
    assert len(r.verdicts) == 3 and not any(r.verdicts.values())


@needs_nuxmv
def test_nuxmv_reports_parse_error_with_line():
    r = run_nuxmv(BROKEN)
    assert not r.parsed and not r.ok
    assert any("line 3" in e and "undefined" in e for e in r.nuxmv_errors)


@needs_nuxmv
def test_nuxmv_reports_deadlock():
    deadlock = GUARDED.replace("ASSIGN\n", "TRANS action != delete\nASSIGN\n", 1)
    r = check_model(deadlock)
    assert r.parsed and r.total is False and not r.ok
    assert "not total" in r.feedback()


# --- generate loop ------------------------------------------------------------

@needs_nuxmv
def test_generate_repairs_after_bad_first_reply(tmp_path):
    client = ReplayClient(["```smv\n" + BROKEN + "```", "```smv\n" + GUARDED + "```"])
    run_dir, log = generate_one(client, "banking", "guarded", max_repairs=3, out_dir=tmp_path)
    assert [a["ok"] for a in log["attempts"]] == [False, True]
    assert log["final_ok"] and log["repairs_used"] == 1
    # the repair request carried nuXmv's error back to the LLM
    assert "undefined" in client.calls[1][-1]["content"]
    assert (run_dir / "final.smv").read_text() == extract_smv("```smv\n" + GUARDED + "```")
    saved = json.loads((run_dir / "run.json").read_text())
    assert saved["scenario"] == "banking" and saved["variant"] == "guarded"


@needs_nuxmv
def test_generate_gives_up_after_max_repairs(tmp_path):
    client = ReplayClient(["no model here"] * 4)
    _, log = generate_one(client, "banking", "unguarded", max_repairs=3, out_dir=tmp_path)
    assert len(log["attempts"]) == 4 and not log["final_ok"]
    assert not (tmp_path / "banking/unguarded/run_01/final.smv").exists()


# --- local OpenAI-compatible client (fake server, no model) -------------------

@pytest.fixture
def fake_server():
    import http.server
    import threading

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            data = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send({"data": [{"id": "fake-coder:14b"}]})

        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self._send({"choices": [{"message": {"content": "```smv\n" + GUARDED + "```"}}]})

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_local_client_round_trip(fake_server):
    from pipeline.llm import LocalClient, list_local_models

    url, seen = fake_server
    client = LocalClient("fake-coder:14b", temperature=0.2, base_url=url)
    reply = client.chat([{"role": "user", "content": "hi"}])
    assert extract_smv(reply).startswith("-- agent_guarded.smv")
    assert seen[0]["model"] == "fake-coder:14b" and seen[0]["temperature"] == 0.2
    assert seen[0]["stream"] is False
    assert list_local_models(url) == ["fake-coder:14b"]


@needs_nuxmv
def test_generate_cli_with_local_backend(fake_server, tmp_path, monkeypatch, capsys):
    import pipeline.generate as gen

    url, _ = fake_server
    monkeypatch.setattr(gen, "OUT_DIR", tmp_path)
    monkeypatch.setattr(gen.generate_one, "__defaults__", (3, tmp_path, check_model))
    gen.main(["--scenario", "banking", "--variant", "guarded", "--model", "fake-coder:14b", "--base-url", url])
    log = json.loads((tmp_path / "banking/guarded/run_01/run.json").read_text())
    assert log["final_ok"] and log["llm"]["client"] == "local" and log["llm"]["base_url"] == url
    assert "first try ok" in capsys.readouterr().out


def test_run_dirs_do_not_overwrite(tmp_path, monkeypatch):
    class Ok:
        ok = True
        def to_dict(self): return {"ok": True}
        def feedback(self): return ""
    client = ReplayClient(["```smv\n" + GUARDED + "```"] * 2)
    a, _ = generate_one(client, "slack", "guarded", out_dir=tmp_path, check=lambda smv: Ok())
    b, _ = generate_one(client, "slack", "guarded", out_dir=tmp_path, check=lambda smv: Ok())
    assert a.name == "run_01" and b.name == "run_02"
