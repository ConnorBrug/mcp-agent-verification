# Model checking targets. Run from the repo root on Linux, macOS, or WSL.
#
# nuXmv has no include mechanism for a separate property file, so each target concatenates the
# model and properties/safety.ltl into traces/<model>.smv, runs nuXmv in batch mode on it, saves
# the full log to traces/<model>.out, and prints one line per property.
#
# Override the checker with: make check NUXMV=NuSMV

NUXMV  ?= nuXmv
PYTHON ?= python3
PROPS  := properties/safety.ltl
REF    := models/reference
TRACES := traces

VENV   := .venv/bin/python

.PHONY: check check-unguarded check-guarded traces-json clean test generate
.PHONY: check-banking check-banking-unguarded check-banking-guarded

check: check-unguarded check-guarded

check-unguarded:
	$(call run_check,agent_unguarded)

check-guarded:
	$(call run_check,agent_guarded)

# Check the banking reference models separately from the toy models.
check-banking: check-banking-unguarded check-banking-guarded

check-banking-unguarded:
	$(call run_check,banking_unguarded)

check-banking-guarded:
	$(call run_check,banking_guarded)

# Parse the unguarded counterexamples into the JSON format the sandbox replay consumes.
traces-json: check-unguarded
	@$(PYTHON) eval/parse_trace.py $(TRACES)/agent_unguarded.out > $(TRACES)/agent_unguarded.json
	@echo "wrote $(TRACES)/agent_unguarded.json"

clean:
	rm -f $(TRACES)/*.out $(TRACES)/*.smv

# Pipeline tests (needs the .venv from the README; nuXmv tests skip if nuXmv is missing).
test:
	$(VENV) -m pytest -q tests

# LLM model generation, e.g. make generate SCENARIO=banking VARIANT=unguarded RUNS=5 MODEL=<id>
RUNS ?= 1
generate:
	$(VENV) -m pipeline.generate --scenario $(SCENARIO) --variant $(VARIANT) --runs $(RUNS) --model $(MODEL)

# Every scenario, both variants, e.g. make generate-all MODEL=qwen3.8:27b RUNS=5
# Limit the scenarios with SCENARIOS="banking slack".
SCENARIOS ?= banking workspace slack travel mcp
.PHONY: generate-all
generate-all:
	@for s in $(SCENARIOS); do for v in unguarded guarded; do \
		$(VENV) -m pipeline.generate --scenario $$s --variant $$v --runs $(RUNS) --model $(MODEL) || exit 1; \
	done; done

# Demo: nuXmv live on the reference models and every LLM-written model, compared with the reference.
# Needs only nuXmv and python3 (no .venv, no GPU, no LLM). `make demo` is the short layout for a
# projector (plus one attack trace); `make demo-full` prints every formula and the metric table.
# Filter with DEMO_ARGS, e.g.
#   make demo DEMO_ARGS="--model qwen3.8:27b"
.PHONY: demo demo-full demo-before example
demo:
	@$(PYTHON) -m pipeline.demo --compact $(DEMO_ARGS)

demo-full:
	@$(PYTHON) -m pipeline.demo $(DEMO_ARGS)

# The same table for the milestone (prompt v1) runs, to compare with the newest prompt.
demo-before:
	@$(PYTHON) -m pipeline.demo --compact --prompt-version 1 $(DEMO_ARGS)

# The one-minute running example for the poster: the rent scam on one banking agent.
example:
	@$(PYTHON) -m pipeline.example $(EXAMPLE_ARGS)

# Trace admissibility and confirmed-violation rate (docs/metrics.md, sections 3 and 4). Needs nuXmv.
.PHONY: metrics replay-banking
metrics:
	@$(PYTHON) -m eval.metrics $(METRICS_ARGS)

# Replay the rent-scam trace on AgentDojo's real banking tools (needs the .venv and nuXmv).
replay-banking:
	@mkdir -p $(TRACES)/replay
	@$(VENV) -W ignore -m sandbox.replay_banking > $(TRACES)/replay/banking_rent_scam.json
	@echo "wrote $(TRACES)/replay/banking_rent_scam.json"

# $(1) = model name without extension, looked up in $(REF)
define run_check
	@command -v $(NUXMV) >/dev/null 2>&1 || { echo "error: '$(NUXMV)' not on PATH. See README, Install."; exit 1; }
	@mkdir -p $(TRACES)
	@{ cat $(REF)/$(1).smv; echo; cat $(PROPS); } > $(TRACES)/$(1).smv
	@$(NUXMV) $(TRACES)/$(1).smv > $(TRACES)/$(1).out 2>&1 || { echo "error: $(NUXMV) failed on $(1). Log: $(TRACES)/$(1).out"; tail -n 5 $(TRACES)/$(1).out; exit 1; }
	@echo "== $(1)"
	@sed -n -e 's/^-- specification *\(.*[^ ]\) *is true$$/  HOLDS           \1/p' \
	        -e 's/^-- specification *\(.*[^ ]\) *is false$$/  COUNTEREXAMPLE  \1/p' $(TRACES)/$(1).out
endef
