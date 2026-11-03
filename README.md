# mcp-agent-verification

Formal models of MCP-style tool-using AI agents. CS 3892, Vanderbilt University, Fall 2026.
Topic 8: formal models of agentic AI.

We model a tool-using agent as a transition system in SMV, state safety properties in LTL, and use
the nuXmv model checker to find violations as counterexample traces. An open-weight LLM, run
locally, writes SMV models from real tool schemas, and we measure how accurate those models are
against hand-written references. We replay counterexample traces in the AgentDojo sandbox to see
which violations reproduce.

## Research questions

1. Translation accuracy. How accurately can an LLM translate real MCP tool schemas into a
   formal transition-system model? Measured against hand-written reference models by parse rate,
   verdict agreement, and trace admissibility (`docs/metrics.md`).
2. Violations found. What security violations can we discover by model checking the
   LLM-generated models? A violation is confirmed only if the reference model also admits the
   counterexample.
3. Trace reproducibility. How many of the attack traces produced by the model checker
   reproduce against a sandboxed agent that uses the corresponding real tools?

## Team

| Name | Role |
|---|---|
| Teo Kitanovski | Hand-written reference models, nuXmv runs, metric scripts in `eval/` (RQ2) |
| Connor Brugger | LLM generation pipeline in `pipeline/` (RQ1) |
| Xiaodi Shao | Sandbox replay in `sandbox/` (RQ3) |

## Repository layout

| Path | Contents |
|---|---|
| `models/reference/` | Hand-written SMV models |
| `models/generated/` | LLM-written SMV models and their run logs |
| `properties/` | LTL property file (`safety.ltl`) |
| `pipeline/` | Tool schema export, prompts, LLM clients, nuXmv check and repair loop |
| `sandbox/` | Replay of counterexamples as real tool calls in AgentDojo |
| `eval/` | Counterexample parser (`parse_trace.py`); metric scripts to come |
| `traces/` | nuXmv counterexamples as JSON, and replay results in `traces/replay/` |
| `tests/` | Pipeline tests |
| `docs/` | Interface spec, metric definitions, AI-use log |

Every model uses the variable interface in `docs/interface.md`, so one property file checks all of
them.

## Install

You need nuXmv, GNU make, and Python. The toy run guide below needs only the Python standard
library. The pipeline and the sandbox need a Python 3.12 environment (see below).

Everything runs on Linux, macOS, or WSL. On Windows, run commands inside WSL (Ubuntu). From a
Windows terminal, use a login shell so `~/.local/bin` is on the PATH:

```sh
wsl bash -lc "make check"
```

Plain `wsl make check` fails with `make: command not found` when make and nuXmv are installed in
`~/.local/bin`.

### nuXmv

nuXmv is free for academic and non-commercial use but is not redistributable. Do not commit the
binary or the archive to this repo. Each person downloads it.

1. Go to the download page: <https://nuxmv.fbk.eu/download.html>. Read and accept the license.
2. Download the archive for your OS (`nuXmv-<version>-linux64.tar.xz` or `-macos64.tar.xz`) and
   its `.sha256sum` file. This project was tested with nuXmv 2.2.0 (linux64, under WSL).
3. Verify and extract outside the repo:

   ```sh
   mkdir -p ~/opt && cd ~/opt
   sha256sum -c nuXmv-2.2.0-linux64.tar.xz.sha256sum
   tar xf nuXmv-2.2.0-linux64.tar.xz
   ```

4. The archive ships a wrapper at `usr/local/bin/nuXmv.sh` that sets the library path. Put a
   launcher named `nuXmv` on your `PATH`:

   ```sh
   mkdir -p ~/.local/bin
   printf '#!/bin/sh\nexec %s "$@"\n' ~/opt/nuXmv-2.2.0-linux64/usr/local/bin/nuXmv.sh > ~/.local/bin/nuXmv
   chmod +x ~/.local/bin/nuXmv
   nuXmv -h | head -1
   ```

   Make sure `~/.local/bin` is on your `PATH`.

**Troubleshooting: `GLIBC_2.38 not found (required by libstdc++.so.6)`.** On newer distros (seen
on Ubuntu 26.04) the glibc bundled with nuXmv conflicts with the system `libstdc++`. Load every
bundled library except `libc` and `libm` instead of using the wrapper:

```sh
L=~/opt/nuXmv-2.2.0-linux64/usr/local/lib/x86_64-linux-gnu
mkdir -p ~/opt/nuxmv-libs
for f in "$L"/*.so*; do case "$(basename "$f")" in libc.so.6|libm.so.6) ;; *) ln -sf "$f" ~/opt/nuxmv-libs/ ;; esac; done
cat > ~/.local/bin/nuXmv <<EOF
#!/bin/sh
LD_LIBRARY_PATH="$HOME/opt/nuxmv-libs\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}" exec $HOME/opt/nuXmv-2.2.0-linux64/usr/local/bin/nuXmv "\$@"
EOF
chmod +x ~/.local/bin/nuXmv
```

### NuSMV fallback

If you cannot use nuXmv, NuSMV (open source, LGPL) reads the same models and supports the
past-time operator used in `properties/safety.ltl`. Download from <https://nusmv.fbk.eu/> and pass
it to make:

```sh
make check NUXMV=NuSMV
```

The NuSMV fallback has not been tested on this repo yet.

### make and Python

```sh
sudo apt install make python3      # Debian/Ubuntu/WSL
```

### Python 3.12 environment (pipeline and sandbox)

AgentDojo does not support Python versions newer than 3.12 yet. With
[uv](https://docs.astral.sh/uv/):

```sh
uv venv -p 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
make test
```

Model generation uses an open-weight model served by Ollama (or any OpenAI-compatible server).
Vanderbilt's Amplify API is supported as an alternative; its key goes in `.env` as
`AMPLIFY_API_KEY=...`. `.env` is gitignored; never commit a key. See `pipeline/README.md`.

Exporting the MCP scenario's tool schemas (`python -m pipeline.export_schemas mcp`) also needs
Node.js, because the filesystem server is written in TypeScript. The exported schemas are already
committed in `pipeline/schemas/`, so this is only needed to re-export.

## Run guide

### 1. Model-check the toy reference models

Toy headline result: the unguarded reference agent violates all three safety properties, and adding
the policy layer (guarded agent) makes all three hold.

```sh
git clone https://github.com/ConnorBrug/mcp-agent-verification.git
cd mcp-agent-verification
make check
```

Expected output:

```
== agent_unguarded
  COUNTEREXAMPLE  G (action = delete ->  Y action = confirm)
  COUNTEREXAMPLE  G (tainted ->  G action != send_external)
  COUNTEREXAMPLE  G ((!privileged &  X privileged) -> grant)
== agent_guarded
  HOLDS           G (tainted ->  G action != send_external)
  HOLDS           G (action = delete ->  Y action = confirm)
  HOLDS           G ((!privileged &  X privileged) -> grant)
```

nuXmv may list properties in a different order. Full logs are in `traces/agent_unguarded.out` and
`traces/agent_guarded.out`.

### 2. Extract counterexamples as JSON

```sh
make traces-json
```

This writes `traces/agent_unguarded.json`: one object per violated property with the formula, the
loop-start indices, and the per-step values of `action`, `tainted`, `confirmed`, `privileged`,
`grant`. Steps are 0-indexed. In the committed run, the taint counterexample reads untrusted
content with an injection at step 1, is tainted at step 2, and sends externally at step 2. Exact
traces can differ between nuXmv versions.

### 3. Replay the counterexamples in AgentDojo

```sh
.venv/bin/python -m sandbox.replay traces/agent_unguarded.json --all > traces/replay/all_agentdojo.json
```

Each abstract action becomes a real tool call in AgentDojo's workspace suite (for example,
`send_external` becomes `send_email` to an outside address). A violation counts as reproduced only
if the environment's taint matches the trace at every step and the violating call changes the
environment. Expected status lines:

```
reproduced      G (action = delete -> Y action = confirm)
reproduced      G (tainted -> G action != send_external)
not_replayable  G ((!privileged & X privileged) -> grant)
```

The privilege trace is not replayable because the workspace suite has no tool that changes the
agent's privileges.

Limit: this is tool-level replay. It shows the environment allows the attack sequence, not that an
LLM agent would choose it. Agent-driven replay is planned. See `sandbox/README.md`.

### 4. Generate LLM-written models

See `pipeline/README.md`. In short, with a model served by Ollama:

```sh
make generate SCENARIO=banking VARIANT=unguarded RUNS=5 MODEL=<model id>
```

### Make targets

| Target | What it does |
|---|---|
| `make check` | Model-check both toy reference models |
| `make check-unguarded`, `make check-guarded` | One of them |
| `make traces-json` | Parse the unguarded counterexamples to JSON |
| `make test` | Pipeline tests (needs the `.venv`) |
| `make generate` | LLM model generation (`SCENARIO`, `VARIANT`, `RUNS`, `MODEL`) |
| `make clean` | Delete nuXmv logs and temp files in `traces/` |

## Docs

- `docs/interface.md`: variable interface every model must use.
- `docs/metrics.md`: formulas for parse rate, verdict agreement, trace admissibility, and
  confirmed-violation rate.
- `docs/AI_USE.md`: log of AI tool use, for the report's disclosure.
- `pipeline/README.md`: LLM backend setup and how to run generation.
- `models/generated/README.md`: layout of generated runs and their logs.
- `sandbox/README.md`: replay details and limits.
