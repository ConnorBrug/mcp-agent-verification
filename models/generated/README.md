# models/generated

SMV models produced by the LLM pipeline in `pipeline/`. Every model must follow `docs/interface.md`
so `properties/safety.ltl` runs against it unchanged.

Layout: `<scenario>/<variant>/run_NN/`

| File | Contents |
|---|---|
| `attempt_K.txt` | Raw LLM reply. K = 0 is the first try; 1 to 3 are repairs. |
| `attempt_K.smv` | SMV extracted from that reply, if any. |
| `final.smv` | The last extracted model. Metrics use this one. |
| `run.json` | Model id, temperature, prompt hash, schema source, and the check result of every attempt. |

## Runs in this folder

| Scenario | Runs | LLM | Generated (UTC) |
|---|---|---|---|
| banking | `unguarded/run_01` to `run_05`, `guarded/run_01` to `run_05` | `qwen2.5-coder:14b` | 2026-11-16 |
| banking | `unguarded/run_06` to `run_10`, `guarded/run_06` to `run_10` | `qwen3.8:27b` | 2026-11-16 |

Settings shared by all of them, including the ones `run.json` does not record:

| Setting | Value |
|---|---|
| Server | Ollama 0.40.16 on Windows 11, pipeline in WSL (Ubuntu 24.04), nuXmv 2.2.0 |
| Quantization | Q4_K_M (the default tag of both models) |
| Context length | 32768 tokens (`OLLAMA_CONTEXT_LENGTH`) |
| Temperature, reply cap | 0.7, 8000 tokens |
| Seed | none, so runs are not reproducible token for token |
| Repairs | up to 3 |
| Hardware | RTX 4080 16 GB. `qwen2.5-coder:14b` ran 93% on the GPU, `qwen3.8:27b` 65% GPU and 35% CPU |
| Prompt | version 1, with the SMV syntax section (`pipeline/README.md`). Hashes start `ecbdf3f0` (unguarded) and `0b64730c` (guarded) |

`guarded/run_10` was generated a few minutes after the others. The first attempt at it was lost
when the machine crashed before the run wrote any file, so it was run again. No run was discarded
for its content.

The model id in `run.json` is the Ollama tag. It names the model, not an exact build, so record
the digest from `ollama list` if a run has to be tied to one. For these runs: `9ec8897f747e`
(`qwen2.5-coder:14b`) and `aaee06c39dcf` (`qwen3.8:27b`).

Runs made with prompt version 2 or later record `prompt_version` in `run.json`; runs without it
are version 1. Add their settings to the table above when they are committed.

To see the verdicts of every run next to the reference models, run `make demo` from the repo root
(newest prompt version) or `make demo-before` (version 1).

Commit runs exactly as generated. Do not hand-fix them; failures are data for the parse-rate
metric. Parse rate before repair comes from attempt 0, after repair from the last attempt.
