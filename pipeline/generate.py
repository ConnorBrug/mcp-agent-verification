"""Generate SMV models from tool schemas with an LLM, check each with nuXmv, and repair on failure.

Usage (from the repo root, inside WSL):
    .venv/bin/python -m pipeline.generate --list-models
    .venv/bin/python -m pipeline.generate --scenario banking --variant unguarded --runs 5 --model <id>
The default backend is a local OpenAI-compatible server (Ollama). Point it elsewhere with
--base-url or LOCAL_LLM_URL; use --backend amplify for Vanderbilt's Amplify API.

Each run writes models/generated/<scenario>/<variant>/run_NN/:
    attempt_K.txt   raw LLM reply for attempt K (0 = first try, 1..3 = repairs)
    attempt_K.smv   SMV extracted from that reply, if any
    final.smv       the last extracted model (the one metrics use)
    run.json        settings, prompt hash, and the check result of every attempt
Raw replies are saved exactly as returned. Do not hand-edit them.
"""
import argparse
import datetime
import json
import sys
import time
from pathlib import Path

from pipeline.check import check_model
from pipeline.llm import LOCAL_URL, AmplifyClient, LocalClient, list_local_models, list_models
from pipeline.prompt import VARIANTS, build_messages, extract_smv, load_schemas, prompt_sha256, repair_message

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "models" / "generated"


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _next_run_dir(base):
    base.mkdir(parents=True, exist_ok=True)
    taken = {int(p.name.split("_")[1]) for p in base.glob("run_*") if p.name.split("_")[1].isdigit()}
    n = 1
    while n in taken:
        n += 1
    d = base / f"run_{n:02d}"
    d.mkdir()
    return d


def generate_one(client, scenario, variant, max_repairs=3, out_dir=OUT_DIR, check=check_model):
    schemas = load_schemas(scenario)
    messages = build_messages(schemas, variant)
    run_dir = _next_run_dir(Path(out_dir) / scenario / variant)
    log = {
        "scenario": scenario,
        "variant": variant,
        "schema_source": schemas["source"],
        "llm": client.describe(),
        "prompt_sha256": prompt_sha256(messages),
        "max_repairs": max_repairs,
        "started_at": _now(),
        "attempts": [],
    }
    final_smv = None
    for k in range(max_repairs + 1):
        t0 = time.time()
        reply = client.chat(messages)
        (run_dir / f"attempt_{k}.txt").write_text(reply, encoding="utf-8")
        smv = extract_smv(reply)
        if smv is None:
            entry = {"attempt": k, "extracted": False, "ok": False}
            feedback = "- The reply contained no SMV model. Reply with the model in a ```smv code block."
        else:
            final_smv = smv
            (run_dir / f"attempt_{k}.smv").write_text(smv, encoding="utf-8")
            result = check(smv)
            entry = {"attempt": k, "extracted": True, **result.to_dict()}
            feedback = result.feedback()
        entry["seconds"] = round(time.time() - t0, 1)
        log["attempts"].append(entry)
        if entry["ok"]:
            break
        messages = messages + [{"role": "assistant", "content": reply}, repair_message(feedback)]
    if final_smv is not None:
        (run_dir / "final.smv").write_text(final_smv, encoding="utf-8")
    log["finished_at"] = _now()
    log["final_ok"] = log["attempts"][-1]["ok"]
    log["repairs_used"] = len(log["attempts"]) - 1
    (run_dir / "run.json").write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    return run_dir, log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("local", "amplify"), default="local")
    ap.add_argument("--base-url", default=LOCAL_URL, help="local server (default $LOCAL_LLM_URL or Ollama on localhost)")
    ap.add_argument("--list-models", action="store_true", help="print the backend's model ids and exit")
    ap.add_argument("--scenario")
    ap.add_argument("--variant", choices=VARIANTS)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", help="model id (see --list-models)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-repairs", type=int, default=3)
    args = ap.parse_args(argv)

    if args.list_models:
        if args.backend == "local":
            print("\n".join(list_local_models(args.base_url)))
        else:
            for m in list_models().get("data", {}).get("models", []):
                print(f"{m.get('id'):40} {m.get('provider', '')}")
        return
    if not (args.scenario and args.variant and args.model):
        ap.error("--scenario, --variant, and --model are required")

    if args.backend == "local":
        client = LocalClient(args.model, temperature=args.temperature, base_url=args.base_url)
    else:
        client = AmplifyClient(args.model, temperature=args.temperature)
    for _ in range(args.runs):
        run_dir, log = generate_one(client, args.scenario, args.variant, args.max_repairs)
        first, last = log["attempts"][0], log["attempts"][-1]
        shown = run_dir.relative_to(REPO) if run_dir.is_relative_to(REPO) else run_dir
        print(f"{shown}: first try {'ok' if first['ok'] else 'failed'}, "
              f"final {'ok' if last['ok'] else 'failed'} after {log['repairs_used']} repair(s)")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
