# pipeline

Schema-to-SMV translation (RQ1). An LLM reads a scenario's tool schemas and writes an SMV model
that uses the interface in `docs/interface.md`. nuXmv checks it. If the model fails, the errors go
back to the LLM, up to 3 repair rounds. Every reply and check result is logged.

| File | What it does |
|---|---|
| `export_schemas.py` | Writes `schemas/<scenario>.json`: each tool's name, description, and inputSchema (MCP tool format). |
| `prompt.py` | Builds the prompt (task, interface, tools, policy for the guarded variant, output rules) and extracts SMV from a reply. |
| `llm.py` | LLM clients: local OpenAI-compatible server (default), Amplify API, and a replay client for tests. |
| `check.py` | Interface lint, then nuXmv: parse, deadlock check (`check_fsm`), and a verdict per property. |
| `generate.py` | The generate, check, repair loop and the run logs. |

Scenarios: `workspace`, `travel`, `banking`, `slack` (AgentDojo v1.2), and `mcp` (fetch, git,
filesystem reference servers). Variants: `unguarded` (schemas only) and `guarded` (schemas plus the
policy in English).

## LLM backend

The default backend is an open-weight model served by [Ollama](https://ollama.com) through its
OpenAI-compatible API. LM Studio and vLLM work the same way.

1. Install Ollama and pull a model, e.g. `ollama pull <model>`.
2. If Ollama runs on another machine, start it with `OLLAMA_HOST=0.0.0.0` on that machine and set
   `LOCAL_LLM_URL=http://<host>:11434` where the pipeline runs (or pass `--base-url`).
3. Check the connection: `.venv/bin/python -m pipeline.generate --list-models`

`--backend amplify` uses Vanderbilt's Amplify API instead. It needs `AMPLIFY_API_KEY` in `.env`,
and Amplify only issues keys against a university billing account.

## Run

From the repo root, inside WSL, after the setup in the main README:

```sh
make test                                   # 18 tests, no model needed
make generate SCENARIO=banking VARIANT=unguarded RUNS=5 MODEL=<model id>
```

Output goes to `models/generated/<scenario>/<variant>/run_NN/` (see that folder's README). The
model id, temperature, and server URL are recorded in each run's `run.json`.
