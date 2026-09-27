# models/generated

SMV models produced by the LLM pipeline in `pipeline/`. One file per (tool schema, generation run).
Every file must follow `docs/interface.md` so `properties/safety.ltl` runs against it unchanged.
Commit the raw model exactly as generated. Do not hand-fix it; parse failures are data for the parse-rate metric.
