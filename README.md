# mcp-agent-verification

Formal models of MCP-style tool-using AI agents. CS 3892, Vanderbilt University, Fall 2026.
Topic 8: formal models of agentic AI.

We model a tool-using agent as a transition system in SMV, state safety properties in LTL, and use
the nuXmv model checker to find violations as counterexample traces. We replay those traces against
a sandboxed agent to see which violations reproduce. An LLM generates SMV models from tool schemas,
and we measure how faithful those models are against hand-written references.

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
| Teo Kitanovski | TBD |
| Connor Brugger | TBD |
| Xiaodi Shao | TBD |

## Repository layout

| Path | Contents |
|---|---|
| `models/reference/` | Hand-written SMV models |
| `models/generated/` | LLM-produced SMV models |
| `properties/` | LTL property files (`safety.ltl`) |
| `traces/` | nuXmv output and parsed counterexamples |
| `pipeline/` | Schema-to-SMV translation code |
| `sandbox/` | Containerized agent and replay harness |
| `eval/` | Verdict comparison and metrics scripts |
| `docs/` | Interface spec, metric definitions, AI-use log |

Every model uses the variable interface in `docs/interface.md`, so one property file checks all of
them.

## Install

You need nuXmv, GNU make, and Python 3.9 or newer. The Makefile runs on Linux and macOS. On
Windows, use WSL (Ubuntu) and run everything inside it.

### nuXmv

nuXmv is free for academic and non-commercial use but is not redistributable. Do not commit
the binary or the archive to this repo. Each person downloads it.

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
pip install -r requirements.txt    # only needed for pipeline/ work, not for the run guide
```

`eval/parse_trace.py` uses only the Python standard library.

## Run guide: reproduce the headline result

Headline result: the unguarded reference agent violates all three safety properties, and adding
the policy layer (guarded agent) makes all three hold.

1. Clone and enter the repo:

   ```sh
   git clone <repo-url> mcp-agent-verification
   cd mcp-agent-verification
   ```

2. Check both reference models against the property file:

   ```sh
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

   nuXmv may list properties in a different order. Full logs are in `traces/agent_unguarded.out`
   and `traces/agent_guarded.out`. The concatenated inputs nuXmv ran are
   `traces/agent_unguarded.smv` and `traces/agent_guarded.smv`.

3. Extract the unguarded counterexamples as JSON (the sandbox replay input format):

   ```sh
   make traces-json
   ```

   This writes `traces/agent_unguarded.json`: one object per violated property with the formula,
   the loop-start indices, and the per-step values of `action`, `tainted`, `confirmed`,
   `privileged`, `grant`. Steps are 0-indexed. In our run, the taint counterexample reads
   untrusted content with an injection at step 1, is tainted at step 2, and sends externally at
   step 2. Exact traces can differ between nuXmv versions.

   To parse any nuXmv log directly:

   ```sh
   python3 eval/parse_trace.py traces/agent_unguarded.out
   ```

Other targets: `make check-unguarded`, `make check-guarded`, `make clean`.

## Docs

- `docs/interface.md`: canonical variable interface every model must use.
- `docs/metrics.md`: formulas for parse rate, verdict agreement, trace admissibility, and confirmed-violation rate.
- `docs/AI_USE.md`: log of AI tool use, for the report's disclosure.
