# AI use log

Running record of where AI tools were used in this project, for the AI-use disclosure in the final
report. Add an entry every time an AI tool writes or substantially edits code, models, properties,
data, or text that ends up in the repo or the report. Newest entries at the bottom.

This log is separate from the LLM that is part of the research pipeline (`pipeline/` generates SMV
models from tool schemas). Pipeline runs are experimental data and are recorded with their outputs,
not here.

Entry format:

- **Date**
- **Tool and model**
- **Who ran it**
- **What it produced** (files or sections)
- **Prompt summary**
- **Human review** (what was checked or changed by hand, and by whom)

---

## 2026-09-27: Repository scaffolding

- **Tool and model:** Claude Code, Claude Opus 5.5.
- **Who ran it:** Connor Brugger.
- **What it produced:** Initial repo structure and all files in the first commits:
  `README.md`, `.gitignore`, `.gitattributes`, `requirements.txt`, directory READMEs,
  `docs/interface.md`, `docs/metrics.md`, `docs/AI_USE.md`,
  `models/reference/agent_unguarded.smv`, `models/reference/agent_guarded.smv`,
  `properties/safety.ltl`, `Makefile`, `eval/parse_trace.py`.
- **Prompt summary:** A written spec listing the directory layout, the canonical variable
  interface, the two reference models and their intended behavior, the three LTL properties, the
  Makefile targets, the trace JSON format, and the three metrics to define.
- **Human review:** Pending. To verify: model semantics match the intended threat model, the
  interface timing conventions (taint visible the step after an injected read, one-step
  `confirmed` flag) are what the team wants, and the metric formulas match what the report will
  compute. The tool ran `make check` and `eval/parse_trace.py` with nuXmv 2.2.0 and reported the
  unguarded model violating all three properties and the guarded model satisfying all three.

## 2026-09-27: Proposal report draft

- **Tool and model:** Claude Code, Claude Opus 5.5.
- **Who ran it:** Connor Brugger.
- **What it produced:** `docs/proposal/proposal.tex` and `proposal.pdf`: the full draft of every
  required section. It also installed AgentDojo 0.1.35 and cloned the MCP reference servers to get
  the tool and task counts cited as evidence of access.
- **Prompt summary:** The assignment's list of required sections, plus the course's lightning-talk
  slides for format and grading context.
- **Human review:** Pending. Team names, group letter, role assignments, success thresholds, and
  the scenario count need team sign-off before submission.
