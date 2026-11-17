"""Demo: run nuXmv live on the reference models and on every LLM-written model, and compare.

Usage (from the repo root):
    make demo
    python3 -m pipeline.demo [--scenario banking] [--model <id>] [--recorded]

Needs only nuXmv and Python 3.10+ (standard library). No GPU, no LLM, no network.

Nothing here is hard-coded to today's results. Every run re-checks models/reference/ and
models/generated/ against the current properties/safety.ltl, so the tables follow any change to
the reference models, the property file, or the set of generated runs.

--recorded skips nuXmv for the generated models and shows the verdicts saved in each run.json at
generation time. It is also the automatic fallback when nuXmv is not installed.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from pipeline.check import PROPERTIES, check_model

REPO = Path(__file__).resolve().parent.parent
REFERENCE = REPO / "models" / "reference"
GENERATED = REPO / "models" / "generated"


def _shape(formula):
    """Formula with spaces and parentheses removed. nuXmv reprints formulas with its own
    parenthesization (G (a != b) comes back as G a != b), so this is how we match them."""
    return re.sub(r"[\s()]", "", formula)


def property_order(path=PROPERTIES):
    """Shapes of the LTLSPEC formulas in file order, so P1 is the first spec in safety.ltl."""
    order = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("--", 1)[0].strip()
        m = re.match(r"LTLSPEC\b(?:\s+NAME\s+\w+\s*:=)?\s*(.+)", line)
        if m:
            order.append(_shape(m.group(1)))
    return order


def _mark(holds):
    return "holds" if holds else "VIOLATED"


def _reference(scenario, variant, live):
    """Verdicts of the hand-written reference model, or (None, reason)."""
    path = REFERENCE / f"{scenario}_{variant}.smv"
    if not path.exists():
        return None, f"no reference model at {path.relative_to(REPO)}"
    if not live:
        return None, "nuXmv not available, reference not checked"
    result = check_model(path.read_text(encoding="utf-8"))
    if not result.verdicts:
        problems = result.interface_errors + result.nuxmv_errors
        return None, "reference model did not check: " + ("; ".join(problems) or "no verdicts")
    return result.verdicts, None


def _generated(run_dir, live):
    """(log, verdicts or None, problem or None) for one run folder."""
    log_path, model_path = run_dir / "run.json", run_dir / "final.smv"
    if not log_path.exists():
        return None, None, "no run.json (run did not finish)"
    log = json.loads(log_path.read_text(encoding="utf-8"))
    if not live:
        last = log["attempts"][-1]
        return log, (last.get("verdicts") if last.get("ok") else None), None if last.get("ok") else "did not parse"
    if not model_path.exists():
        return log, None, "the LLM never produced an SMV model"
    result = check_model(model_path.read_text(encoding="utf-8"))
    if result.ok:
        return log, result.verdicts, None
    problems = result.interface_errors + result.nuxmv_errors
    if result.parsed and result.total is False:
        problems.append("transition relation is not total")
    return log, None, (problems[0] if problems else "did not parse")


STATE_LINE = re.compile(r"^\s*-> State: \d+\.\d+ <-")
ASSIGN_LINE = re.compile(r"^\s*([\w.]+) = (\S+)\s*$")


def _paint(text, color, on):
    codes = {"red": "31;1", "green": "32", "dim": "2", "bold": "1"}
    return f"\033[{codes[color]}m{text}\033[0m" if on else text


def attack_trace(model_path, prop_index=0):
    """nuXmv's counterexample to property number prop_index + 1 (file order) on one model.

    Returns a list of states, each a dict of every variable nuXmv printed (nuXmv prints only the
    variables that changed, so each state starts as a copy of the previous one). The list is cut at
    the first state where P1's bad condition (tainted and send_external) holds. None if the
    property holds or nuXmv is missing.
    """
    if shutil.which("nuXmv") is None:
        return None
    props = PROPERTIES.read_text(encoding="utf-8")
    want = property_order()[prop_index]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "model.smv"
        path.write_text(Path(model_path).read_text(encoding="utf-8").rstrip() + "\n\n" + props, encoding="utf-8")
        out = subprocess.run(["nuXmv", str(path)], stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=120).stdout
    states, current, inside = [], {}, False
    for line in out.splitlines():
        if line.startswith("-- specification"):
            inside = line.rstrip().endswith("is false") and _shape(line[len("-- specification"):].rsplit(" is ", 1)[0]) == want
            continue
        if not inside:
            continue
        if STATE_LINE.match(line):
            current = dict(current)
            states.append(current)
        else:
            m = ASSIGN_LINE.match(line)
            if m and states:
                current[m.group(1)] = m.group(2)
    if not states:
        return None
    for i, s in enumerate(states):
        if s.get("tainted") == "TRUE" and s.get("action") == "send_external":
            return states[: i + 1]
    return states


def compact(args, live):
    """One screen: verdict per model and property, agreement with the reference, one attack trace."""
    color = sys.stdout.isatty()
    start = time.time()
    names = {1: "P1 taint", 2: "P2 delete", 3: "P3 priv."}
    order = property_order()

    def by_number(verdicts):
        out = {}
        for f, v in verdicts.items():
            shape = _shape(f)
            if shape in order:
                out[order.index(shape) + 1] = v
        return out

    def cell(holds):
        return _paint(f"{'safe':<10}", "green", color) if holds else _paint(f"{'ATTACK':<10}", "red", color)

    def short(model):
        return model.split(":")[-1].upper() if ":" in model else model

    scenarios = sorted(p.name for p in GENERATED.iterdir() if p.is_dir()) if GENERATED.exists() else []
    if args.scenario:
        scenarios = [s for s in scenarios if s == args.scenario]
    if not scenarios:
        print("No generated runs found under models/generated/.")
        return 1

    per_llm = defaultdict(lambda: defaultdict(float))
    n_models = 0
    print(_paint("nuXmv, running now on every model in the repo" if live else
                 "Verdicts saved at generation time (nuXmv not run)", "bold", color))
    print("  safe         = nuXmv proved it holds on every possible run")
    print("  ATTACK       = nuXmv found a run that breaks it")
    print("  hand-written = our answer key. Numbered rows = models the LLM wrote.")
    for scenario in scenarios:
        for variant_dir in sorted((p for p in (GENERATED / scenario).iterdir() if p.is_dir()), reverse=True):
            variant = variant_dir.name
            ref, _ = _reference(scenario, variant, live)
            ref = by_number(ref) if ref else None
            n_models += ref is not None
            label = "tools as they are" if variant == "unguarded" else "tools + a safety policy"
            print()
            print(_paint(f"{scenario} {variant.upper()} ({label})", "bold", color))
            print(f"  {'':16}" + "".join(f"{names[n]:<10}" for n in (1, 2, 3)) + "same as hand-written?")
            if ref is not None:
                print(f"  {'hand-written':16}" + "".join(cell(ref[n]) for n in (1, 2, 3))
                      + _paint("(answer key)", "dim", color))
            for run_dir in sorted(variant_dir.glob("run_*")):
                log, verdicts, problem = _generated(run_dir, live)
                if log is None:
                    continue
                model = log["llm"].get("model", "?")
                if args.model and model != args.model:
                    continue
                n_models += 1
                s = per_llm[model]
                s["runs"] += 1
                tag = f"{run_dir.name[-2:]} by {short(model)}"
                if verdicts is None:
                    print(f"  {tag:16}" + _paint("nuXmv could not parse it", "dim", color))
                    continue
                s["parsed"] += 1
                v = by_number(verdicts)
                line = f"  {tag:16}" + "".join(cell(v[n]) for n in (1, 2, 3))
                if ref is not None:
                    same = sum(v[n] == ref[n] for n in (1, 2, 3))
                    s["compared"] += 1
                    s["agree"] += same / 3
                    for n in (1, 2, 3):
                        if not ref[n]:
                            s["ref_attacks"] += 1
                            s["missed"] += v[n]
                    line += _paint("yes", "green", color) if same == 3 else f"{same} of 3"
                print(line)

    print()
    print(_paint("Summary per LLM", "bold", color))
    print(f"  {'':20}{'parses':<10}{'agreement':<12}real attacks it called safe")
    for model, s in sorted(per_llm.items()):
        n = int(s["runs"])
        missed = f"{int(s['missed'])} of {int(s['ref_attacks'])}" if s["ref_attacks"] else "n/a"
        parses = "%d/%d" % (s["parsed"], n)
        agreement = "%.2f" % (s["agree"] / n) if s["compared"] else "n/a"
        print(f"  {model:20}{parses:<10}{agreement:<12}{missed}")

    ref_path = REFERENCE / f"{scenarios[0]}_unguarded.smv"
    trace = attack_trace(ref_path) if live and ref_path.exists() else None
    if trace:
        print()
        print(_paint(f"nuXmv's attack trace for P1 on the hand-written {scenarios[0]} model", "bold", color))
        print(_paint(f"  {'':8}{'tool the agent calls':30}{'action':16}{'taint':9}", "dim", color))
        for i, s in enumerate(trace, 1):
            tool = s.get("chosen_tool", "")
            inject = any(v == "TRUE" for k, v in s.items() if "inject" in k)
            note = ""
            if inject and s.get("action") == "read_untrusted":
                note = _paint("<- attacker injects", "red", color)
            elif s.get("tainted") == "TRUE" and s.get("action") == "send_external":
                note = _paint("<- P1 broken", "red", color)
            tainted = "tainted" if s.get("tainted") == "TRUE" else "clean"
            print(f"  step {i}  {tool:30}{s.get('action', ''):16}{tainted:9}{note}")

    print()
    print(_paint(f"{n_models} models checked in {time.time() - start:.1f} s", "dim", color))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", help="only this scenario (default: every folder in models/generated)")
    ap.add_argument("--model", help="only runs generated by this model id")
    ap.add_argument("--recorded", action="store_true", help="show verdicts saved in run.json instead of re-running nuXmv")
    ap.add_argument("--compact", action="store_true",
                    help="short layout for a projector: one row per model, a summary per LLM, and one attack trace")
    args = ap.parse_args(argv)

    have_nuxmv = shutil.which("nuXmv") is not None
    live = have_nuxmv and not args.recorded
    if args.compact:
        return compact(args, live)
    if not have_nuxmv:
        print("NOTE: nuXmv is not on PATH. Showing the verdicts recorded at generation time.")
        print("      Install nuXmv (README, Install) to run the checks live.\n")
    print("Verdicts are " + ("computed live by nuXmv right now." if live else "read from each run.json."))

    scenarios = sorted(p.name for p in GENERATED.iterdir() if p.is_dir()) if GENERATED.exists() else []
    if args.scenario:
        scenarios = [s for s in scenarios if s == args.scenario]
    if not scenarios:
        print("No generated runs found under models/generated/.")
        return 1

    # per (model, scenario, variant): counters for the summary
    stats = defaultdict(lambda: defaultdict(float))
    # Number properties by their position in properties/safety.ltl, not by how nuXmv orders its
    # output or how the formula strings sort. A formula not found there gets the next free number.
    order = property_order()
    formulas = {}  # number -> formula as nuXmv printed it, for the legend

    def number(formula):
        shape = _shape(formula)
        if shape not in order:
            order.append(shape)
        n = order.index(shape) + 1
        formulas.setdefault(n, formula)
        return n

    def label(formula):
        return f"P{number(formula)}"

    def in_order(verdicts):
        return sorted(verdicts, key=number)

    for scenario in scenarios:
        for variant_dir in sorted(p for p in (GENERATED / scenario).iterdir() if p.is_dir()):
            variant = variant_dir.name
            ref, ref_problem = _reference(scenario, variant, live)
            print(f"\n== {scenario} / {variant}")
            if ref is None:
                print(f"   reference: {ref_problem}")
            else:
                print("   reference (hand-written):   " + "   ".join(f"{label(f)} {_mark(ref[f])}" for f in in_order(ref)))
            for run_dir in sorted(variant_dir.glob("run_*")):
                log, verdicts, problem = _generated(run_dir, live)
                if log is None:
                    print(f"   {run_dir.name}  skipped: {problem}")
                    continue
                model = log["llm"].get("model", "?")
                if args.model and model != args.model:
                    continue
                s = stats[(model, scenario, variant)]
                s["runs"] += 1
                s["first"] += bool(log["attempts"][0].get("ok"))
                if verdicts is None:
                    print(f"   {run_dir.name}  {model:20}  DOES NOT PARSE: {str(problem)[:70]}")
                    continue
                s["parsed"] += 1
                cells = "   ".join(f"{label(f)} {_mark(verdicts[f])}" for f in in_order(verdicts))
                note = ""
                if ref is not None:
                    shared = [f for f in ref if f in verdicts]
                    same = sum(verdicts[f] == ref[f] for f in shared)
                    s["compared"] += 1
                    s["agree"] += same / len(ref)
                    s["exact"] += same == len(ref)
                    for f in shared:
                        if not ref[f]:
                            s["ref_violations"] += 1
                            s["false_safe"] += verdicts[f]
                    note = "   matches reference" if same == len(ref) else f"   agrees on {same} of {len(ref)}"
                print(f"   {run_dir.name}  {model:20}  {cells}{note}")

    print("\nProperties (properties/safety.ltl):")
    for n in sorted(formulas):
        print(f"   P{n}  {formulas[n]}")

    print("\nSummary")
    print(f"   {'model':20} {'scenario/variant':20} {'parse 1st try':>13} {'parse final':>11} "
          f"{'agreement':>9} {'exact match':>11} {'false-safe':>10}")
    for (model, scenario, variant), s in sorted(stats.items()):
        n, parsed, compared = int(s["runs"]), int(s["parsed"]), int(s["compared"])
        agreement = f"{s['agree'] / n:.2f}" if compared else "n/a"
        exact = f"{int(s['exact'])} of {parsed}" if compared else "n/a"
        false_safe = f"{int(s['false_safe'])} of {int(s['ref_violations'])}" if s["ref_violations"] else "n/a"
        first = "%d of %d" % (s["first"], n)
        final = "%d of %d" % (parsed, n)
        cell = scenario + "/" + variant
        print(f"   {model:20} {cell:20} {first:>13} {final:>11} {agreement:>9} {exact:>11} {false_safe:>10}")
    print("\n   parse 1st try  from run.json: the LLM's first reply passed the check, before any repair")
    print("   parse final    the committed final.smv passes the interface lint and nuXmv" + (" (live)" if live else ""))
    print("   agreement      share of properties with the same verdict as the reference; a model that")
    print("                  does not parse counts as 0 (strict rate, docs/metrics.md)")
    print("   false-safe     reference violations that the generated model reports as holding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
