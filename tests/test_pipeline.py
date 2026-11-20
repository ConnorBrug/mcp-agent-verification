"""Pipeline tests. nuXmv tests are skipped when nuXmv is not on PATH.

Run from the repo root inside WSL:  .venv/bin/python -m pytest -q tests
"""
import json
import shutil
from pathlib import Path

import pytest

from pipeline.check import check_model, lint_interface, lint_structure, run_nuxmv, sanity_check, tool_mapping
from pipeline.generate import generate_one
from pipeline.llm import ReplayClient
from pipeline.prompt import build_messages, extract_smv, load_schemas, prompt_sha256, tool_names

REPO = Path(__file__).resolve().parent.parent
GUARDED = (REPO / "models/reference/agent_guarded.smv").read_text()
UNGUARDED = (REPO / "models/reference/agent_unguarded.smv").read_text()
BANK_GUARDED = (REPO / "models/reference/banking_guarded.smv").read_text()
BANK_UNGUARDED = (REPO / "models/reference/banking_unguarded.smv").read_text()
BANK_TOOLS = tool_names(load_schemas("banking"))
# The milestone failure: every read labeled trusted, so the agent can never be tricked.
BANK_TRUSTING = (BANK_UNGUARDED
                 .replace("get_most_recent_transactions : read_untrusted", "get_most_recent_transactions : read_trusted")
                 .replace("get_scheduled_transactions : read_untrusted", "get_scheduled_transactions : read_trusted")
                 .replace("read_file : read_untrusted", "read_file : read_trusted"))
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


def test_prompt_has_syntax_section_that_leaks_no_mapping():
    from pipeline.prompt import SMV_SYNTAX

    schemas = load_schemas("banking")
    prompt = build_messages(schemas, "unguarded")[1]["content"]
    assert "## SMV syntax" in prompt and SMV_SYNTAX in prompt
    # the syntax section must not mention any tool or any abstract action of the interface
    for word in [t["name"] for t in schemas["tools"]] + ["read_untrusted", "send_external", "request_grant", "tainted"]:
        assert word not in SMV_SYNTAX


@pytest.mark.skipif(shutil.which("nuXmv") is None, reason="nuXmv not on PATH")
def test_prompt_syntax_example_is_valid_smv():
    from pipeline.prompt import SMV_SYNTAX

    example = extract_smv(SMV_SYNTAX)
    r = run_nuxmv(example, properties=REPO / "tests" / "empty.ltl")
    assert r.parsed and r.total is True


def test_prompt_v2_adds_trust_rule_and_structure_v1_does_not():
    schemas = load_schemas("banking")
    v1 = build_messages(schemas, "unguarded", version=1)[1]["content"]
    unguarded = build_messages(schemas, "unguarded")[1]["content"]
    guarded = build_messages(schemas, "guarded")[1]["content"]
    for text in (unguarded, guarded):
        assert "Trust rule" in text and "## Required structure" in text
        assert "chosen_tool : {no_tool, " + ", ".join(BANK_TOOLS) + "}" in text
    assert "action := proposed_action;" in unguarded and "policy blocks" in guarded
    assert "Trust rule" not in v1 and "## Required structure" not in v1


def test_prompt_v1_still_reproduces_the_milestone_runs():
    schemas = load_schemas("banking")
    for variant in ("unguarded", "guarded"):
        saved = json.loads((REPO / f"models/generated/banking/{variant}/run_06/run.json").read_text())
        assert prompt_sha256(build_messages(schemas, variant, version=1)) == saved["prompt_sha256"]


# --- prompt v2 structure lint -------------------------------------------------

def test_structure_lint_passes_banking_references():
    assert lint_structure(BANK_UNGUARDED, BANK_TOOLS) == []
    assert lint_structure(BANK_GUARDED, BANK_TOOLS) == []


def test_structure_lint_catches_missing_tool_and_late_action():
    no_tool = BANK_UNGUARDED.replace("    chosen_tool = get_iban : read_trusted;\n", "")
    assert any("No mapping line" in e and "get_iban" in e for e in lint_structure(no_tool, BANK_TOOLS))
    late = BANK_UNGUARDED.replace("action := proposed_action;", "init(action) := idle;\n  next(action) := proposed_action;")
    assert any("one step late" in e for e in lint_structure(late, BANK_TOOLS))
    assigned = BANK_UNGUARDED.replace("  action := proposed_action;", "  action := proposed_action;\n  next(chosen_tool) := send_money;")
    assert any("free input" in e for e in lint_structure(assigned, BANK_TOOLS))
    assert lint_structure(UNGUARDED, BANK_TOOLS)  # a v1-style model has no chosen_tool at all


def test_tool_mapping_reads_only_the_proposed_action_case():
    mapping = tool_mapping(BANK_GUARDED)
    assert len(mapping) == len(BANK_TOOLS) and mapping["get_most_recent_transactions"] == "read_untrusted"
    policy_on_tool = BANK_GUARDED.replace("proposed_action = send_external & tainted : idle;",
                                          "tainted & chosen_tool = send_money : idle;")
    assert tool_mapping(policy_on_tool)["send_money"] == "send_external"
    assert lint_structure(policy_on_tool, BANK_TOOLS) == []


def test_tool_mapping_accepts_parenthesized_conditions():
    import re

    paren = re.sub(r"chosen_tool = (\w+) : (\w+);", r"(chosen_tool = \1) : \2;", BANK_UNGUARDED)
    assert tool_mapping(paren) == tool_mapping(BANK_UNGUARDED)
    assert lint_structure(paren, BANK_TOOLS) == []


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


@needs_nuxmv
def test_v2_check_accepts_both_banking_references():
    for smv, variant in ((BANK_UNGUARDED, "unguarded"), (BANK_GUARDED, "guarded")):
        r = check_model(smv, tools=BANK_TOOLS, variant=variant)
        assert r.ok and r.well_formed and r.sanity_errors == []


@needs_nuxmv
def test_sanity_catches_an_agent_that_can_never_be_tricked():
    r = check_model(BANK_TRUSTING, tools=BANK_TOOLS, variant="unguarded")
    assert r.well_formed and not r.ok
    assert any("can never become TRUE" in e for e in r.sanity_errors)
    # works without a mapping too, which is how make example checks a prompt v1 model
    assert sanity_check(BANK_TRUSTING) and sanity_check(BANK_UNGUARDED) == []


@needs_nuxmv
def test_sanity_catches_invented_and_blocked_actions():
    invented = BANK_UNGUARDED.replace(
        "action := proposed_action;", "action := case chosen_tool = no_tool : {idle, delete}; TRUE : proposed_action; esac;")
    errors = check_model(invented, tools=BANK_TOOLS, variant="unguarded").sanity_errors
    assert any("no tool maps to delete" in e for e in errors)
    blocked = BANK_GUARDED.replace("proposed_action = send_external & tainted : idle;",
                                   "proposed_action = send_external : idle;")
    errors = check_model(blocked, tools=BANK_TOOLS, variant="guarded").sanity_errors
    assert any("send_external` can never happen" in e for e in errors)


# --- generate loop ------------------------------------------------------------

@needs_nuxmv
def test_generate_repairs_after_bad_first_reply(tmp_path):
    client = ReplayClient(["```smv\n" + BROKEN + "```", "```smv\n" + BANK_GUARDED + "```"])
    run_dir, log = generate_one(client, "banking", "guarded", max_repairs=3, out_dir=tmp_path)
    assert [a["ok"] for a in log["attempts"]] == [False, True]
    assert log["final_ok"] and log["repairs_used"] == 1
    # the repair request carried nuXmv's error back to the LLM
    assert "undefined" in client.calls[1][-1]["content"]
    assert (run_dir / "final.smv").read_text() == extract_smv("```smv\n" + BANK_GUARDED + "```")
    saved = json.loads((run_dir / "run.json").read_text())
    assert saved["scenario"] == "banking" and saved["variant"] == "guarded"
    assert saved["prompt_version"] == 2


@needs_nuxmv
def test_generate_sends_vacuous_model_back_for_repair(tmp_path):
    client = ReplayClient(["```smv\n" + BANK_TRUSTING + "```", "```smv\n" + BANK_UNGUARDED + "```"])
    _, log = generate_one(client, "banking", "unguarded", max_repairs=3, out_dir=tmp_path)
    first, last = log["attempts"]
    assert first["well_formed"] and not first["ok"] and first["sanity_errors"]
    assert last["ok"] and last["mapping"]["get_most_recent_transactions"] == "read_untrusted"
    assert "can never become TRUE" in client.calls[1][-1]["content"]


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


# --- demo ---------------------------------------------------------------------

def _fake_run(root, scenario, variant, name, model, smv, verdicts):
    run = root / scenario / variant / name
    run.mkdir(parents=True)
    ok = smv is not None
    if ok:
        (run / "final.smv").write_text(smv)
    attempt = {"attempt": 0, "extracted": ok, "ok": ok, "verdicts": verdicts}
    (run / "run.json").write_text(json.dumps({"llm": {"model": model}, "attempts": [attempt], "final_ok": ok}))


def test_demo_recorded_mode_needs_no_nuxmv(tmp_path, monkeypatch, capsys):
    import pipeline.demo as demo

    _fake_run(tmp_path, "banking", "guarded", "run_01", "fake:1b", GUARDED, {"G p": True})
    _fake_run(tmp_path, "banking", "guarded", "run_02", "fake:1b", None, {})
    (tmp_path / "banking" / "guarded" / "run_03").mkdir()  # a run that crashed before writing anything
    monkeypatch.setattr(demo, "GENERATED", tmp_path)
    assert demo.main(["--recorded"]) == 0
    out = capsys.readouterr().out
    assert "read from each run.json" in out
    assert "DOES NOT PARSE" in out and "run_03  skipped" in out
    assert "1 of 2" in out  # parse rate for fake:1b


@needs_nuxmv
def test_demo_live_compares_with_reference_and_survives_a_missing_one(tmp_path, monkeypatch, capsys):
    import pipeline.demo as demo

    ref = tmp_path / "reference"
    ref.mkdir()
    (ref / "toy_guarded.smv").write_text(GUARDED)
    gen = tmp_path / "generated"
    _fake_run(gen, "toy", "guarded", "run_01", "fake:1b", GUARDED, {})
    _fake_run(gen, "toy", "guarded", "run_02", "fake:1b", UNGUARDED, {})
    _fake_run(gen, "toy", "unguarded", "run_01", "fake:1b", UNGUARDED, {})  # no reference for this cell
    monkeypatch.setattr(demo, "GENERATED", gen)
    monkeypatch.setattr(demo, "REFERENCE", ref)
    monkeypatch.setattr(demo, "REPO", tmp_path)
    assert demo.main([]) == 0
    out = capsys.readouterr().out
    assert "matches reference" in out and "agrees on 0 of 3" in out
    assert "no reference model at reference/toy_unguarded.smv" in out


def test_demo_compact_recorded_needs_no_nuxmv(tmp_path, monkeypatch, capsys):
    import pipeline.demo as demo

    verdicts = {
        "G (tainted -> G action != send_external)": False,
        "G (action = delete -> Y action = confirm)": True,
        "G ((!privileged & X privileged) -> grant)": True,
    }
    _fake_run(tmp_path, "banking", "unguarded", "run_01", "fake:1b", UNGUARDED, verdicts)
    _fake_run(tmp_path, "banking", "unguarded", "run_02", "fake:1b", None, {})
    monkeypatch.setattr(demo, "GENERATED", tmp_path)
    assert demo.main(["--compact", "--recorded"]) == 0
    out = capsys.readouterr().out
    assert "01 by 1B" in out and "ATTACK" in out and "nuXmv could not parse it" in out
    assert "1/2" in out  # parses, per LLM


@needs_nuxmv
def test_demo_attack_trace_on_banking_reference():
    import pipeline.demo as demo

    trace = demo.attack_trace(demo.REFERENCE / "banking_unguarded.smv")
    assert trace and trace[-1]["action"] == "send_external" and trace[-1]["tainted"] == "TRUE"
    assert any(s["action"] == "read_untrusted" for s in trace)


def test_demo_numbers_properties_as_in_safety_ltl():
    import pipeline.demo as demo

    # Formulas as nuXmv prints them, in the order nuXmv prints them (not file order).
    printed = [
        "G (action = delete -> Y action = confirm)",
        "G ((!privileged & X privileged) -> grant)",
        "G (tainted -> G action != send_external)",
    ]
    order = demo.property_order()
    assert len(order) == 3
    assert [order.index(demo._shape(f)) + 1 for f in printed] == [2, 3, 1]


def test_demo_shows_the_newest_prompt_version_unless_asked(tmp_path, monkeypatch, capsys):
    import pipeline.demo as demo

    verdicts = {
        "G (tainted -> G action != send_external)": False,
        "G (action = delete -> Y action = confirm)": True,
        "G ((!privileged & X privileged) -> grant)": True,
    }
    _fake_run(tmp_path, "banking", "unguarded", "run_01", "old:1b", UNGUARDED, verdicts)
    _fake_run(tmp_path, "banking", "unguarded", "run_02", "new:1b", None, {})
    log = tmp_path / "banking/unguarded/run_02/run.json"
    log.write_text(json.dumps({**json.loads(log.read_text()), "prompt_version": 2}))
    monkeypatch.setattr(demo, "GENERATED", tmp_path)
    assert demo.main(["--compact", "--recorded"]) == 0
    out = capsys.readouterr().out
    assert "prompt v2" in out and "new:1b" in out and "old:1b" not in out
    assert demo.main(["--compact", "--recorded", "--prompt-version", "1"]) == 0
    out = capsys.readouterr().out
    assert "old:1b" in out and "new:1b" not in out


@needs_nuxmv
def test_example_tells_the_rent_scam(capsys):
    import pipeline.example as example

    assert example.main([]) == 0
    out = capsys.readouterr().out
    assert "step 1  get_most_recent_transactions" in out and "step 2  send_money" in out
    assert "P1: ATTACK" in out and "<- wrong" in out and "NO -> sent back" in out


# --- eval/metrics.py -----------------------------------------------------------

def _state(action, tainted=False, confirmed=False, privileged=False, grant=False):
    return {"action": action, "tainted": tainted, "confirmed": confirmed, "privileged": privileged, "grant": grant}


def test_metrics_bad_prefix_cuts_at_the_violation():
    from eval.metrics import bad_prefix, trace_formula

    p1 = [_state("read_untrusted"), _state("send_external", tainted=True), _state("idle", tainted=True)]
    assert len(bad_prefix(1, p1)) == 2
    p2 = [_state("idle"), _state("delete"), _state("idle")]
    assert len(bad_prefix(2, p2)) == 2
    p3 = [_state("request_grant"), _state("idle", privileged=True), _state("idle", privileged=True)]
    assert len(bad_prefix(3, p3)) == 2
    formula = trace_formula(p1[:2])
    assert formula.startswith("!((action = read_untrusted & !tainted") and " & X (action = send_external & tainted" in formula


@needs_nuxmv
def test_metrics_admits_follows_the_reference_models():
    from eval.metrics import admits, counterexamples

    attacks = counterexamples(BANK_UNGUARDED)
    assert [c["property"] for c in attacks] == [1]
    states = attacks[0]["states"]
    assert states[-1]["action"] == "send_external" and states[-1]["tainted"]
    assert admits(BANK_UNGUARDED, states) is True
    assert admits(BANK_GUARDED, states) is False
    assert counterexamples(BANK_GUARDED) == []


def test_run_dirs_do_not_overwrite(tmp_path, monkeypatch):
    class Ok:
        ok = True
        def to_dict(self): return {"ok": True}
        def feedback(self): return ""
    client = ReplayClient(["```smv\n" + GUARDED + "```"] * 2)
    a, _ = generate_one(client, "slack", "guarded", out_dir=tmp_path, check=lambda smv: Ok())
    b, _ = generate_one(client, "slack", "guarded", out_dir=tmp_path, check=lambda smv: Ok())
    assert a.name == "run_01" and b.name == "run_02"
