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

Commit runs exactly as generated. Do not hand-fix them; failures are data for the parse-rate
metric. Parse rate before repair comes from attempt 0, after repair from the last attempt.
