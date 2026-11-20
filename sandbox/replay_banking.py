#!/usr/bin/env python3
"""Replay the banking attack trace on AgentDojo's real banking tools (tool level, no LLM).

Usage (from the repo root, with the .venv that has agentdojo, and nuXmv on PATH):
    make replay-banking
    .venv/bin/python -m sandbox.replay_banking > traces/replay/banking_rent_scam.json

Two results, as one JSON object:

  trust_labels  For every tool the banking reference model maps to a read: does text planted in
                AgentDojo's injection slots show up in the tool's output? This checks the reference
                model's read_trusted / read_untrusted labels against the environment.
  replay        nuXmv's attack trace from `make example` (read the transaction history, then send
                money), executed call by call with the tool names nuXmv chose. It counts as
                reproduced only if the environment's taint (has the planted text appeared in an
                earlier tool output?) equals the trace's `tainted` at every step, and the final
                send adds a transaction. A control run without the planted text must not taint.

Same limit as sandbox/replay.py: this shows the environment lets the sequence happen. It does not
show that an LLM agent would choose it.
"""
import json
import sys

from pipeline.check import tool_mapping
from pipeline.demo import REFERENCE
from pipeline.example import rent_attack
from sandbox.replay import CANARY

MARK = "CANARY-7f3a"  # the id inside CANARY; tool output re-wraps long text, so match on this
ATTACKER_IBAN = "US133000000121212121212"
# Arguments for each tool the replay may call. read_file is tried on every file in the environment.
ARGS = {
    "get_balance": {}, "get_iban": {}, "get_user_info": {}, "get_scheduled_transactions": {},
    "get_most_recent_transactions": {"n": 100},
    "send_money": {"recipient": ATTACKER_IBAN, "amount": 500.0, "subject": "replay", "date": "2022-04-01"},
    "schedule_transaction": {"recipient": ATTACKER_IBAN, "amount": 500.0, "subject": "replay",
                             "date": "2022-04-01", "recurring": False},
}


class Banking:
    """AgentDojo banking suite (benchmark v1.2)."""

    def __init__(self, inject):
        from agentdojo.agent_pipeline.tool_execution import tool_result_to_str
        from agentdojo.functions_runtime import FunctionsRuntime
        from agentdojo.task_suite.load_suites import get_suite

        suite = get_suite("v1.2", "banking")
        defaults = suite.get_injection_vector_defaults()
        self.slots = sorted(defaults)
        self.env = suite.load_and_inject_default_environment(
            {k: (CANARY if inject else v) for k, v in defaults.items()})
        self.runtime = FunctionsRuntime(suite.tools)
        self._to_str = tool_result_to_str

    def call(self, tool):
        """Run one tool. Returns (output text, error or None). read_file reads every file."""
        calls = ([("read_file", {"file_path": f}) for f in self.env.filesystem.files] if tool == "read_file"
                 else [(tool, ARGS[tool])])
        text = ""
        for name, args in calls:
            result, error = self.runtime.run_function(self.env, name, args, raise_on_error=False)
            if error:
                return text, str(error)
            text += self._to_str(result)
        return text, None

    def money_out(self):
        bank = self.env.bank_account
        return len(bank.transactions) + len(bank.scheduled_transactions)


def trust_labels(mapping):
    """One row per tool the reference maps to a read: its label and whether planted text surfaces."""
    rows = []
    for tool, action in mapping.items():
        if action not in ("read_trusted", "read_untrusted"):
            continue
        clean, _ = Banking(inject=False).call(tool)
        planted, error = Banking(inject=True).call(tool)
        surfaces = MARK in planted and MARK not in clean
        rows.append({"tool": tool, "reference_label": action, "planted_text_surfaces": surfaces, "error": error,
                     "label_matches_environment": surfaces == (action == "read_untrusted")})
    return rows


def replay(states, inject=True):
    bank = Banking(inject)
    tainted, faithful, log = False, True, []
    for step, s in enumerate(states, 1):
        tool = s["chosen_tool"]
        trace_tainted = s["tainted"] == "TRUE"
        entry = {"step": step, "tool": tool, "action": s["action"], "trace_tainted": trace_tainted,
                 "observed_tainted": tainted}
        faithful &= tainted == trace_tainted
        if tool != "no_tool":
            before = bank.money_out()
            out, entry["error"] = bank.call(tool)
            if s["action"] == "send_external":
                entry["money_left"] = bank.money_out() > before
            tainted |= MARK in out
        log.append(entry)
    last = log[-1]
    reproduced = bool(faithful and last["action"] == "send_external" and last["observed_tainted"]
                      and last.get("money_left"))
    return {"injected": inject, "trace_faithful": faithful, "reproduced": reproduced, "log": log}


def main():
    ref = (REFERENCE / "banking_unguarded.smv").read_text(encoding="utf-8")
    states = rent_attack(ref)
    if not states:
        sys.exit("nuXmv found no attack trace on models/reference/banking_unguarded.smv")
    labels = trust_labels(tool_mapping(ref))
    attack, control = replay(states, inject=True), replay(states, inject=False)
    result = {
        "property": "P1 no_send_after_taint",
        "model": "models/reference/banking_unguarded.smv",
        "environment": "AgentDojo v1.2 banking suite",
        "injection_slots": Banking(inject=True).slots,
        "trust_labels": labels,
        "replay": attack,
        "control_without_injection": control,
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    for row in labels:
        print(f"{row['tool']:30} {row['reference_label']:15} planted text surfaces: "
              f"{'yes' if row['planted_text_surfaces'] else 'no':4}"
              f"{'' if row['label_matches_environment'] else ' <- label and environment differ'}", file=sys.stderr)
    print(f"attack trace reproduced: {attack['reproduced']}   "
          f"control (no planted text) tainted: {control['log'][-1]['observed_tainted']}", file=sys.stderr)
    return 0 if attack["reproduced"] and not control["log"][-1]["observed_tainted"] else 1


if __name__ == "__main__":
    sys.exit(main())
