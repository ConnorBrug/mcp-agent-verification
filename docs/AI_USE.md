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

## 2026-11-02: Sandbox replay
- **Tool and model:** Claude Code, Claude Sonnet 5.5.
- **Who ran it:** Xiaodi Shao.
- **What it produced:** 'traces/agent_unguarded.json'; 'traces/replay/'; assisted in 'sandbox/replay.py'
- **Prompt summary:** Claude walked me through the process of running the counterexample and summarized the results into a table (in the report). 
- **Human review:** Xiaodi Shao, the user, ran the code and reviewed both the code and the results. 

## 2026-11-15: Local model setup and demo

- **Tool and model:** Claude Code, Claude Fable 5.2.
- **Who ran it:** Connor Brugger.
- **What it produced:** Assisted with the SMV syntax section in `pipeline/prompt.py`,
  `pipeline/demo.py`, tests, the CI workflow, and README updates. Helped set up the local model
  server. The files in `models/generated/` are output of the pipeline's LLMs, not of this tool.
- **Prompt summary:** Set up a local model for the pipeline, run the banking generations, and
  make the results easy to check and present.
- **Human review:** Connor Brugger ran the tests and the demo with nuXmv, and read the prompt's
  syntax section and a generated model against the demo output.

## 2026-11-19: Prompt version 2 and the running example

- **Tool and model:** Claude Code, Claude Opus 5.5 (written) and Claude Fable 5.2 (review and fixes).
- **Who ran it:** Connor Brugger.
- **What it produced:** Prompt version 2 in `pipeline/prompt.py` (trust rule, tool-only actions,
  required structure), the structure lint and sanity checks in `pipeline/check.py`, prompt-version
  handling in `pipeline/demo.py`, `pipeline/example.py` (`make example`), new tests, and README
  updates. No LLM-generated models were added; the v2 rerun is still to do. Also `eval/metrics.py`
  (`make metrics`), `sandbox/replay_banking.py` (`make replay-banking`) and its result in
  `traces/replay/banking_rent_scam.json`, and `make generate-all`.
- **Prompt summary:** Raise verdict agreement and lower the false-safe rate on banking, and build
  a one-minute running example for the poster, as the instructor asked after the milestone.
- **Human review:** Pending.
