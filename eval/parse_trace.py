#!/usr/bin/env python3
"""Extract counterexamples from a nuXmv output file as JSON.

Usage: python3 eval/parse_trace.py traces/agent_unguarded.out > traces/agent_unguarded.json

Output is a JSON list with one object per violated property:
  {"spec": "<formula as nuXmv printed it>",
   "loop_starts": [<0-based state indices nuXmv marked "Loop starts here">],
   "states": [{"action": ..., "tainted": ..., "confirmed": ..., "privileged": ..., "grant": ...}, ...]}

nuXmv prints only the variables that changed since the previous state, so each state starts as a
copy of the one before it. Only the interface variables (docs/interface.md) are kept.
"""
import json
import re
import sys

INTERFACE = ("action", "tainted", "confirmed", "privileged", "grant")

SPEC_RE = re.compile(r"^-- specification\s+(.*?)\s+is (true|false)\s*$")
STATE_RE = re.compile(r"^\s*-> State: \d+\.\d+ <-")
INPUT_RE = re.compile(r"^\s*-> Input: \d+\.\d+ <-")
ASSIGN_RE = re.compile(r"^\s*([\w.\[\]]+) = (\S+)\s*$")


def value(text):
    return {"TRUE": True, "FALSE": False}.get(text, text)


def parse(lines):
    traces, cex, current, in_input, loop_next = [], None, {}, False, False
    for line in lines:
        m = SPEC_RE.match(line)
        if m:
            cex = None
            if m.group(2) == "false":
                cex = {"spec": " ".join(m.group(1).split()), "loop_starts": [], "states": []}
                traces.append(cex)
                current, in_input, loop_next = {}, False, False
            continue
        if cex is None:
            continue
        if "Loop starts here" in line:
            loop_next = True
        elif STATE_RE.match(line):
            if loop_next:
                cex["loop_starts"].append(len(cex["states"]))
                loop_next = False
            current = dict(current)
            cex["states"].append(current)
            in_input = False
        elif INPUT_RE.match(line):
            in_input = True  # IVAR assignments, not part of the state
        else:
            m = ASSIGN_RE.match(line)
            if m and cex["states"] and not in_input:
                current[m.group(1)] = value(m.group(2))

    for cex in traces:
        cex["states"] = [{k: s.get(k) for k in INTERFACE} for s in cex["states"]]
        missing = {k for s in cex["states"] for k, v in s.items() if v is None}
        if missing:
            print(f"warning: {cex['spec']}: missing interface vars {sorted(missing)}", file=sys.stderr)
    return traces


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        json.dump(parse(f), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
