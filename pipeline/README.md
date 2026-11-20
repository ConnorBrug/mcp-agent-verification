# pipeline

Schema-to-SMV translation (RQ1). An LLM reads a scenario's tool schemas and writes an SMV model
that uses the interface in `docs/interface.md`. nuXmv checks it. If the model fails, the errors go
back to the LLM, up to 3 repair rounds. Every reply and check result is logged.

| File | What it does |
|---|---|
| `export_schemas.py` | Writes `schemas/<scenario>.json`: each tool's name, description, and inputSchema (MCP tool format). |
| `prompt.py` | Builds the prompt (task, interface, SMV syntax, tools, policy for the guarded variant, required structure, output rules) and extracts SMV from a reply. Version 1 is the milestone prompt; version 2 is the default (see below). |
| `llm.py` | LLM clients: local OpenAI-compatible server (default), Amplify API, and a replay client for tests. |
| `check.py` | Interface lint, then nuXmv: parse, deadlock check (`check_fsm`), and a verdict per property. For prompt v2 also the structure lint and the sanity checks. |
| `generate.py` | The generate, check, repair loop and the run logs. |
| `demo.py` | `make demo`: nuXmv live on the reference models and every generated model, with a comparison table. |
| `example.py` | `make example`: the one-minute running example on one banking agent (the rent scam). |

Scenarios: `workspace`, `travel`, `banking`, `slack` (AgentDojo v1.2), and `mcp` (fetch, git,
filesystem reference servers). Variants: `unguarded` (schemas only) and `guarded` (schemas plus the
policy in English).

## LLM backend

The default backend is an open-weight model served by [Ollama](https://ollama.com) through its
OpenAI-compatible API. LM Studio and vLLM work the same way.

1. Install Ollama and pull a model, e.g. `ollama pull qwen2.5-coder:14b`.
2. Raise Ollama's context length before starting the server. The default depends on VRAM and is
   4096 tokens below 24 GB. The banking prompt alone is about 3400 tokens, so with the default the
   prompt and the repair history are cut off without any error. The runs in this repo used 32768:

   ```sh
   OLLAMA_CONTEXT_LENGTH=32768 ollama serve      # or set it as a user environment variable on Windows
   ollama ps                                     # CONTEXT column shows the value in effect
   ```

3. If Ollama runs on another machine, start it with `OLLAMA_HOST=0.0.0.0` on that machine and set
   `LOCAL_LLM_URL=http://<host>:11434` where the pipeline runs (or pass `--base-url`).
   Ollama on Windows with the pipeline in WSL on the same PC: add `networkingMode=mirrored` under
   `[wsl2]` in `%UserProfile%\.wslconfig` and run `wsl --shutdown`. WSL then reaches Ollama on
   `localhost` and no URL setting is needed.
4. Check the connection: `.venv/bin/python -m pipeline.generate --list-models`

`--backend amplify` uses Vanderbilt's Amplify API instead. It needs `AMPLIFY_API_KEY` in `.env`,
and Amplify only issues keys against a university billing account.

## Run

From the repo root, inside WSL, after the setup in the main README:

```sh
make test                                   # 39 tests, no model needed
make generate SCENARIO=banking VARIANT=unguarded RUNS=5 MODEL=<model id>
make demo                                   # check every generated model against the references
```

Output goes to `models/generated/<scenario>/<variant>/run_NN/` (see that folder's README). The
model id, temperature, and server URL are recorded in each run's `run.json`. The context length
and the Ollama version are not recorded there; they are listed in `models/generated/README.md`.

## The SMV syntax section of the prompt

The prompt has a section that states nuXmv's syntax rules (comment style, `ASSIGN`, lowercase
`init`/`next`/`case`/`esac`, the operators) and shows one small valid model of a traffic light. It
does not mention any tool, any abstract action, or the policy, and a test checks that.

It was added after the first screening. Without it, small open models wrote SMV that nuXmv could
not parse: C-style `/* */` comments, `==`, uppercase `NEXT`/`CASE`/`ESAC`, and `init`/`next` lines
outside an `ASSIGN` section. The repair rounds did not fix these.

| Screening on banking, 3 unguarded + 3 guarded runs | Parse, first try | Parse, after repair |
|---|---|---|
| `qwen2.5-coder:14b`, prompt without the syntax section | 0 of 6 | 0 of 6 |
| `qwen2.5-coder:14b`, prompt with the syntax section | 4 of 6 | 6 of 6 |

`mimo-v2.6:9b-q8_0` was also screened with the old prompt and parsed 0 of 8 extracted models. The
screening runs were written outside the repo and are not part of the data. All runs in
`models/generated/` use the prompt with the syntax section. This is a methods choice to report:
RQ1 measures translation given a syntax reference, not knowledge of SMV syntax.

## Results so far: banking

Two models, 5 unguarded and 5 guarded runs each, temperature 0.7, up to 3 repairs. `make demo`
recomputes this table from the current reference models and property file, so run it for current
numbers. The table below was produced on 2026-11-15 against the references in commit `6ce7e3e`.

| Model | Variant | Parse, first try | Parse, after repair | Agreement (strict) | All 3 verdicts match | False-safe |
|---|---|---|---|---|---|---|
| `qwen2.5-coder:14b` | unguarded | 1 of 5 | 4 of 5 | 0.53 | 0 of 4 | 0 of 4 |
| `qwen2.5-coder:14b` | guarded | 3 of 5 | 4 of 5 | 0.27 | 0 of 4 | n/a |
| `qwen3.8:27b` | unguarded | 5 of 5 | 5 of 5 | 0.73 | 1 of 5 | 3 of 5 |
| `qwen3.8:27b` | guarded | 5 of 5 | 5 of 5 | 0.73 | 3 of 5 | n/a |

Metric definitions are in `docs/metrics.md`. False-safe counts reference violations that the
generated model reports as holding; the guarded reference has no violations, so it is n/a there.
With 5 runs per cell these rates are rough.

What the disagreements are, from reading the generated models and nuXmv's counterexamples:

- **False-safe in `qwen3.8:27b` unguarded (runs 06, 09, 10).** These models map `read_file` to
  `read_trusted`, so no tool maps to `read_untrusted`, and they restrict the agent to the actions
  that have a tool: `next(action) := {idle, read_trusted, send_external}`. The agent can then never
  become tainted, and the taint property holds trivially. The reference maps `read_file` and the
  two transaction-history tools to `read_untrusted`. Run 08 maps `read_file` to `read_untrusted`
  and matches the reference on all three properties. The error is a trust classification of one
  tool, not a syntax or structure problem.
- **Delete violations in unguarded models (`qwen2.5-coder:14b` runs 02 to 05, `qwen3.8:27b` run
  07).** These models let the agent choose any of the seven abstract actions in every step,
  including `delete` and `confirm`, although no banking tool maps to them. The reference only
  allows actions that some tool maps to, so `delete` never occurs there.
- **Taint and delete violations in guarded models.** These models do contain the policy, but it is
  off by one step. They pick the next action from the current value of `tainted`, while `tainted`
  itself only becomes true in that same next step. nuXmv's counterexample for
  `guarded/run_07` is: `read_untrusted` with an injection at step 1, then `send_external` at step 2
  with `tainted` already true. Some of them also leave the initial action unconstrained, so
  `delete` can be the very first action, before any `confirm`. Three `qwen3.8:27b` guarded models
  (runs 06, 08, 09) hold all three properties, as the reference does.
- **The two runs that never parsed** (`qwen2.5-coder:14b`, `unguarded/run_01` and
  `guarded/run_05`) used tool names such as `get_balance` as if they were declared symbols.

Trace admissibility (TA) and the confirmed-violation rate (CV), from `make metrics` on the v1
runs (2026-11-19):

| Model | TA | CV | Confirmed / found |
|---|---|---|---|
| `qwen2.5-coder:14b` | 0.00 | 0.25 | 4 of 16 |
| `qwen3.8:27b` | 0.00 | 0.29 | 2 of 7 |

- **TA is 0 for every v1 model, for one reason.** They all start with `init(action) := idle`, so
  the agent's first step is always idle. The reference's P1 attack starts with a tool call at step
  1, and admissibility compares runs step by step from the first state. With one idle step put in
  front, `unguarded/run_08` admits the attack. So this 0 measures a modeling habit, not a missing
  attack. The v2 structure has no `init(action)`.
- **CV is far below the 0.7 target.** The confirmed violations are the P1 attacks in unguarded
  models. The unconfirmed ones are the invented `delete` actions and every violation in a guarded
  model (the guarded reference admits none), which come from the one-step-late policy.

## Prompt version 2

Each failure above has a fix in prompt version 2 (`PROMPT_VERSION` in `prompt.py`). The runs in
`models/generated/banking/` so far are all version 1; `make demo-before` keeps showing them.

| Failure in v1 | Fix in the prompt | Check that catches it if the LLM still gets it wrong |
|---|---|---|
| Untrusted reads labeled trusted, so the agent can never be tricked and P1 holds trivially | Trust rule: a read is `read_trusted` only if the user or the system wrote everything it returns | Sanity check: nuXmv tests whether `tainted` can ever become true. If not, the model goes back for repair |
| `delete` and `confirm` allowed although no tool maps to them | Only actions some tool maps to may occur | Sanity check: every action that can happen must have a tool mapped to it |
| Policy applied one step late through `next(action)` | Required structure: the agent picks a tool name (`chosen_tool`), and `action` follows from it in the same step | Structure lint: `action` must be a plain `action := ...;` |

The required structure is the shape of the reference models: a free input `chosen_tool` over the
tool names, one `chosen_tool = <tool> : <action>;` line per tool in a `proposed_action` case, and
`action := proposed_action` (unguarded) or the policy applied to it (guarded). The LLM still
decides every mapping and writes the policy and the flag updates. The structure makes the mapping
readable by the checker, so the demo also reports **tool labels right**: the share of tools mapped
to the same action as in the reference.

The sanity checks use nuXmv reachability (invariants), not the safety properties:

- `tainted` can never become true: P1 would hold vacuously.
- An action that no tool maps to can happen (an invented action).
- An action some tool maps to can never happen (a policy that blocks everything). `delete` is
  exempt in the guarded variant, since the policy blocks it unless the user just confirmed.

A model that passes nuXmv but fails a sanity check still counts as parsed. It only goes back to the
LLM for repair. The v1 prompt is still in `prompt.py` (`build_messages(..., version=1)`), and a test
checks that it reproduces the milestone runs' prompt hash.

To rerun banking with v2 (on the machine with the GPU):

```sh
for v in unguarded guarded; do
  make generate SCENARIO=banking VARIANT=$v RUNS=5 MODEL=qwen3.8:27b
  make generate SCENARIO=banking VARIANT=$v RUNS=5 MODEL=qwen2.5-coder:14b
done
make demo           # v2 runs
make demo-before    # v1 runs, for the before/after table
```
