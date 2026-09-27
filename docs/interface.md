# Canonical model interface

Every SMV model in this repo, reference or generated, must declare the variables below in
`MODULE main` with exactly these names, types, and meanings. The property files in `properties/`
refer only to these variables, so the same properties run against every model without edits.

A model may declare extra variables (agent internals, attacker inputs, policy state). Properties
must never refer to them, and the metrics in `docs/metrics.md` project traces onto the interface
variables only.

## Time

SMV models are synchronous. One step of the transition system is one agent turn. A state at step
`t` records the action the agent performs at step `t` together with the flags that hold when that
action is taken. Flags updated by an action become visible at step `t+1`.

## Variables

| Name | Type | Meaning |
|---|---|---|
| `action` | enum, see below | The tool action the agent executes at this step, after any policy filtering. |
| `tainted` | boolean | Untrusted content carrying an injection has entered the agent's context at some earlier step. |
| `confirmed` | boolean | The user confirmed at the immediately preceding step. |
| `privileged` | boolean | The agent currently holds elevated permissions. |
| `grant` | boolean | An explicit privilege grant from the user or an authority is present at this step. |

### `action`

```
action : {idle, read_trusted, read_untrusted, send_external, confirm, delete, request_grant};
```

| Value | Meaning |
|---|---|
| `idle` | No tool call this step. Also the action a policy layer substitutes when it blocks a request. |
| `read_trusted` | Read from a trusted source (local file the user owns, system config). Cannot taint. |
| `read_untrusted` | Read from an untrusted source (web page, email, third-party tool output). May carry an injection. |
| `send_external` | Send data outside the trust boundary (email, HTTP POST, message to another service). The exfiltration channel. |
| `confirm` | The user explicitly confirms the next action. Models a human-in-the-loop approval prompt. |
| `delete` | Destructive, irreversible operation (delete file, drop record). |
| `request_grant` | The agent asks for elevated permissions. |

### `tainted`

- Initially `FALSE`.
- Becomes `TRUE` at step `t+1` if at step `t` the action is `read_untrusted` and the read carried
  an injection. Whether a read carries an injection is an environment (attacker) choice, not part of
  the interface.
- Never returns to `FALSE`. Once injected content is in context, it stays there.

### `confirmed`

- Initially `FALSE`.
- At step `t+1`, `confirmed` is `TRUE` exactly when the action at step `t` is `confirm`.
- It is a one-step flag. A confirmation authorizes only the action immediately after it. It is not
  a standing approval.

### `privileged`

- Initially `FALSE`.
- May become `TRUE` only through `request_grant`. Models decide whether a grant is required. The
  guarded reference requires `grant`; the unguarded one does not.
- Once `TRUE`, stays `TRUE` in the reference models. Generated models may drop privilege, which
  does not affect the property set.

### `grant`

- An unconstrained environment input. Its value at step `t` says whether an explicit grant is being
  given at that step.
- A privilege change from step `t` to step `t+1` is authorized only by `grant` at step `t`, the step
  where `request_grant` executes.

## Required declaration block

Copy this into every model:

```smv
VAR
  action     : {idle, read_trusted, read_untrusted, send_external, confirm, delete, request_grant};
  tainted    : boolean;
  confirmed  : boolean;
  privileged : boolean;
  grant      : boolean;
```

## Rules for generated models

1. Use the names and enum literals above exactly. No renaming, no extra enum values on `action`.
2. `tainted`, `confirmed`, and `privileged` must be initialized to `FALSE`.
3. `grant` must stay an unconstrained input. Constraining it hides privilege bugs.
4. The model must not declare its own `LTLSPEC`, `CTLSPEC`, `INVARSPEC`, or `FAIRNESS`. The
   Makefile appends the shared property file.
5. The transition relation must be total (no deadlock states), or LTL results are unreliable.
