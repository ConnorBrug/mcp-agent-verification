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

.PHONY: check check-unguarded check-guarded traces-json clean

check: check-unguarded check-guarded

check-unguarded:
	$(call run_check,agent_unguarded)

check-guarded:
	$(call run_check,agent_guarded)

# Parse the unguarded counterexamples into the JSON format the sandbox replay consumes.
traces-json: check-unguarded
	@$(PYTHON) eval/parse_trace.py $(TRACES)/agent_unguarded.out > $(TRACES)/agent_unguarded.json
	@echo "wrote $(TRACES)/agent_unguarded.json"

clean:
	rm -f $(TRACES)/*.out $(TRACES)/*.smv

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
