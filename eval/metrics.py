#!/usr/bin/env python3
"""Trace admissibility (TA) and confirmed-violation rate (CV), docs/metrics.md sections 3 and 4.

Usage (from the repo root):
    make metrics
    python3 -m eval.metrics [--scenario banking] [--prompt-version 1] [--list]

Both metrics ask the same question of nuXmv: does model M have a run that matches counterexample
pi on the interface variables at every step? (adm in docs/metrics.md.)

  TA  For each attack nuXmv finds on the hand-written reference: does the LLM-written model allow
      the same run? Low TA means the LLM's model cannot do things the real agent can.
  CV  For each attack nuXmv finds on an LLM-written model: does the reference allow the same run?
      If not, the "attack" comes from a translation mistake, not from the tools.

Each counterexample is cut at its bad prefix: the shortest prefix that already breaks the property.
All three properties are safety properties, so that prefix is the whole violation; what nuXmv
prints after it (the loop that makes the run infinite) is arbitrary and is not compared.

Needs nuXmv. Uses the newest prompt version present unless --prompt-version is given, like the demo.
"""
import argparse
import sys
from collections import defaultdict

from eval.parse_trace import INTERFACE, parse
from pipeline.check import COMMANDS, PROPERTIES, SPEC_RESULT, _nuxmv, check_model
from pipeline.demo import GENERATED, REFERENCE, _load_log, _shape, _tools, _version, pick_version, property_order


def counterexamples(smv):
    """nuXmv's counterexamples to properties/safety.ltl on a model, each cut at its bad prefix.
    Returns a list of {"property": 1-based number, "states": [...]}."""
    ran = _nuxmv(smv.rstrip() + "\n\n" + PROPERTIES.read_text(encoding="utf-8"), COMMANDS)
    if ran is None:
        return []
    order = property_order()
    out = []
    for cex in parse(ran[1].splitlines()):
        shape = _shape(cex["spec"])
        if shape not in order:
            continue
        number = order.index(shape) + 1
        out.append({"property": number, "states": bad_prefix(number, cex["states"])})
    return out


def bad_prefix(number, states):
    """The shortest prefix of the trace that breaks property P<number>. The whole trace if none does."""
    for i, s in enumerate(states):
        if number == 1 and s["tainted"] and s["action"] == "send_external":
            return states[: i + 1]
        if number == 2 and s["action"] == "delete" and (i == 0 or states[i - 1]["action"] != "confirm"):
            return states[: i + 1]
        if number == 3 and i + 1 < len(states) and not s["privileged"] and states[i + 1]["privileged"] and not s["grant"]:
            return states[: i + 2]
    return states


def _state_formula(state):
    parts = []
    for var in INTERFACE:
        value = state[var]
        parts.append(f"action = {value}" if var == "action" else (var if value else f"!{var}"))
    return "(" + " & ".join(parts) + ")"


def trace_formula(states):
    """LTL formula that is FALSE on a model exactly when the model has a run starting with these states."""
    formula = _state_formula(states[-1])
    for state in reversed(states[:-1]):
        formula = f"({_state_formula(state)} & X {formula})"
    return f"!{formula}"


def admits(smv, states):
    """True if the model has a run matching the states on the interface variables. None if nuXmv fails."""
    ran = _nuxmv(smv.rstrip() + "\n\nLTLSPEC " + trace_formula(states) + "\n", "go\ncheck_ltlspec\nquit\n")
    if ran is None:
        return None
    verdicts = SPEC_RESULT.findall(ran[1])
    return verdicts[0][1] == "false" if len(verdicts) == 1 else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", help="only this scenario (default: every scenario with a reference model)")
    ap.add_argument("--prompt-version", type=int, help="only runs from this prompt version (default: the newest present)")
    ap.add_argument("--list", action="store_true", help="also print one line per counterexample")
    args = ap.parse_args(argv)

    scenarios = sorted(p.name for p in GENERATED.iterdir() if p.is_dir()) if GENERATED.exists() else []
    if args.scenario:
        scenarios = [s for s in scenarios if s == args.scenario]
    version = pick_version(scenarios, args.prompt_version)
    stats = defaultdict(lambda: defaultdict(float))
    print(f"Trace admissibility and confirmed violations, LLM models from prompt version {version}")
    for scenario in scenarios:
        for variant in ("unguarded", "guarded"):
            ref_path = REFERENCE / f"{scenario}_{variant}.smv"
            if not ref_path.exists():
                print(f"  {scenario}/{variant}: no reference model, skipped")
                continue
            ref = ref_path.read_text(encoding="utf-8")
            ref_cex = counterexamples(ref)
            for run_dir in sorted((GENERATED / scenario / variant).glob("run_*")):
                log, model_path = _load_log(run_dir), run_dir / "final.smv"
                if log is None or _version(log) != version or not model_path.exists():
                    continue
                smv = model_path.read_text(encoding="utf-8")
                tools = _tools(scenario) if version >= 2 else None
                if not check_model(smv, tools=tools, variant=variant).well_formed:
                    continue  # both metrics are over parsing models only
                s = stats[log["llm"].get("model", "?")]
                if ref_cex:  # TA is undefined where the reference has no counterexample
                    admitted = [admits(smv, c["states"]) for c in ref_cex]
                    s["ta_models"] += 1
                    s["ta_sum"] += sum(bool(a) for a in admitted) / len(ref_cex)
                    if args.list:
                        for c, a in zip(ref_cex, admitted):
                            print(f"    TA {scenario}/{variant}/{run_dir.name}: reference attack on P{c['property']} "
                                  f"{'admitted' if a else 'NOT admitted'}")
                for c in counterexamples(smv):
                    confirmed = admits(ref, c["states"])
                    s["found"] += 1
                    s["confirmed"] += bool(confirmed)
                    if args.list:
                        steps = " -> ".join(st["action"] for st in c["states"])
                        print(f"    CV {scenario}/{variant}/{run_dir.name}: P{c['property']} [{steps}] "
                              f"{'confirmed by the reference' if confirmed else 'not possible in the reference'}")

    print(f"\n  {'':20}{'TA':<8}{'CV':<8}confirmed / found")
    for model, s in sorted(stats.items()):
        ta = "%.2f" % (s["ta_sum"] / s["ta_models"]) if s["ta_models"] else "n/a"
        cv = "%.2f" % (s["confirmed"] / s["found"]) if s["found"] else "n/a"
        print(f"  {model:20}{ta:<8}{cv:<8}{int(s['confirmed'])} / {int(s['found'])}")
    print("\n  TA  share of the reference's attacks that the LLM's model also allows (parsing unguarded models)")
    print("  CV  share of the attacks found in LLM models that the reference also allows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
