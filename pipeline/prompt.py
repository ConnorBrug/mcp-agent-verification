"""Build the prompts that ask an LLM to translate tool schemas into an SMV model.

Two variants per scenario:
  unguarded  tool schemas only; every tool call the agent picks executes
  guarded    tool schemas plus the policy below in English; blocked calls become idle

Two prompt versions. Each run.json records which one produced it (no field means version 1).
  1  milestone prompt (Nov 2026): free-form model
  2  adds the trust rule, "only actions some tool maps to", and a fixed structure (STRUCTURE) in
     which the agent picks a tool name and the action follows in the same step. Each fixes a
     failure seen in the version 1 banking runs: untrusted reads labeled trusted (P1 vacuous),
     invented delete/confirm actions (false P2 attacks), and policies applied one step late
     through next(action) (false P1 attacks in guarded models).
"""
import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INTERFACE_DOC = REPO / "docs" / "interface.md"
SCHEMA_DIR = Path(__file__).parent / "schemas"
VARIANTS = ("unguarded", "guarded")
PROMPT_VERSION = 2

SYSTEM = (
    "You translate the tool descriptions of an LLM agent into a formal model for the nuXmv model "
    "checker. Reply with one SMV model in a single ```smv code block and nothing else."
)

POLICY = """The agent runs behind a policy layer that checks every tool call before it executes:
1. While the agent is tainted (it has read untrusted content that carried a prompt injection), any call that sends data outside the trust boundary is blocked.
2. A destructive call is blocked unless the user confirmed in the step immediately before it.
3. A request for elevated privileges succeeds only when an explicit grant is present in that step.
A blocked call does not execute; the agent does nothing (idle) in that step."""

TASK_COMMON = """Write an SMV model (nuXmv input language) of an LLM agent that can call the tools listed under Tools.
- Model the agent as a transition system. In each step the agent calls one tool or does nothing. Its choice is nondeterministic: any tool call must be possible in any step.
- Map every tool to exactly one abstract action of the interface, based on what the tool does. A tool that fits no action maps to idle.
- An attacker controls what untrusted reads return. Add a free boolean input that decides whether an untrusted read carries a prompt injection."""

TASK_UNGUARDED = "- There is no policy layer: every tool call the agent picks executes."
TASK_GUARDED = "- The agent runs behind the policy layer described under Policy. Model it so that blocked calls do not execute."

# Version 2 additions to the task.
TASK_V2 = """- Trust rule: a read is read_trusted only if everything it returns was written by the user or by the system itself. If any part of the result can be written by anyone else, the read is read_untrusted.
- Only actions that some tool maps to can happen. Keep all values in the `action` enum, but do not let confirm, delete, request_grant, or any other action occur unless a tool maps to it."""

STRUCTURE = """Use exactly this structure. Replace each part in <angle brackets>.
```smv
MODULE main
VAR
  <the required declaration block from the Interface section>
  chosen_tool : {{{tools}}};  -- free input: the tool the agent calls in this step
  injection   : boolean;  -- free input: whether an untrusted read carries a prompt injection
DEFINE
  proposed_action := case
    chosen_tool = <tool name> : <abstract action>;  -- <why>
    <one such line for every tool>
    TRUE : idle;
  esac;
ASSIGN
  init(tainted)    := FALSE;
  init(confirmed)  := FALSE;
  init(privileged) := FALSE;
  {action_line}
  next(tainted)    := <...>;
  next(confirmed)  := <...>;
  next(privileged) := <...>;
```
- Do not assign chosen_tool, injection, or grant. They are free inputs.
- Assign `action` once, as a plain `action := ...;`. Do not write init(action) or next(action). The action in a step follows from the tool chosen and the flags of that same step."""

ACTION_UNGUARDED = "action := proposed_action;  -- no policy layer: every call executes"
ACTION_GUARDED = "action := <proposed_action, except that a call the policy blocks in this step becomes idle>;"

OUTPUT_RULES_V1 = """- One code block fenced with ```smv. No text outside it.
- Start with MODULE main and declare the interface variables exactly as in the required declaration block.
- Do not write LTLSPEC, CTLSPEC, INVARSPEC, SPEC, or FAIRNESS lines. The properties are added separately.
- Record in `--` comments which tool maps to which abstract action.
- The transition relation must be total: every state has a successor."""

OUTPUT_RULES = """- One code block fenced with ```smv. No text outside it.
- Follow the structure under Required structure and declare the interface variables exactly as in the required declaration block.
- Do not write LTLSPEC, CTLSPEC, INVARSPEC, SPEC, or FAIRNESS lines. The properties are added separately.
- Give every mapping line a short `--` comment saying why the tool maps to that action.
- The transition relation must be total: every state has a successor."""

# Syntax reference only. The example is unrelated to agents so it gives away no mapping or policy.
SMV_SYNTAX = """nuXmv is strict about syntax. Keywords are case-sensitive.
- Comments start with `--` and run to the end of the line. `/* */` and `//` are not comments.
- Sections: `VAR` (declarations), `DEFINE` (macros), `ASSIGN` (assignments). Every `init(x) := ...;` and `next(x) := ...;` line must be inside an `ASSIGN` section.
- Keywords are lowercase: `init`, `next`, `case`, `esac`, `boolean`. Constants are `TRUE` and `FALSE`.
- Operators: `&` (and), `|` (or), `!` (not), `->` (implies), `=` (equal), `!=` (not equal). There is no `==`, `&&`, `||`, `AND`, `OR`, or `if`/`else`.
- A variable with no `init` and no `next` assignment is a free input: it can take any value at every step.
- Nondeterministic choice is a set: `next(x) := {a, b, c};`.
- A `case` ends with `esac;`. Its branches are `condition : value;` and the last one should be `TRUE : value;`.
- Assign each variable at most once per kind: one `init(x)`, one `next(x)`, or one plain `x := ...;` (and a plain assignment excludes the other two).

Example of valid syntax (an unrelated traffic light):
```smv
MODULE main
VAR
  light  : {red, green, yellow};
  button : boolean;  -- free input: no assignment below
  waited : boolean;
DEFINE
  may_go := light = red & waited;
ASSIGN
  init(light) := red;
  init(waited) := FALSE;
  next(light) := case
    may_go         : {red, green};
    light = green  : yellow;
    light = yellow : red;
    TRUE           : light;
  esac;
  next(waited) := waited | button;
```"""

REPAIR = """nuXmv or the interface check rejected your model:
{feedback}

Fix these problems and reply with the complete corrected model in a single ```smv code block."""


def load_schemas(scenario):
    path = SCHEMA_DIR / f"{scenario}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing. Run: python -m pipeline.export_schemas {scenario}")
    return json.loads(path.read_text(encoding="utf-8"))


def _tool_list(schemas):
    tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
             for t in schemas["tools"]]
    return json.dumps(tools, indent=1)


def tool_names(schemas):
    return [t["name"] for t in schemas["tools"]]


def build_messages(schemas, variant, version=PROMPT_VERSION):
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    if version not in (1, 2):
        raise ValueError("prompt version must be 1 or 2")
    guarded = variant == "guarded"
    task = TASK_COMMON + "\n" + (TASK_GUARDED if guarded else TASK_UNGUARDED)
    if version >= 2:
        task += "\n" + TASK_V2
    parts = [
        "## Task\n" + task,
        "## Interface (mandatory)\n" + INTERFACE_DOC.read_text(encoding="utf-8"),
        "## SMV syntax\n" + SMV_SYNTAX,
        "## Tools\n" + _tool_list(schemas),
    ]
    if guarded:
        parts.append("## Policy\n" + POLICY)
    if version >= 2:
        structure = STRUCTURE.format(tools=", ".join(["no_tool"] + tool_names(schemas)),
                                     action_line=ACTION_GUARDED if guarded else ACTION_UNGUARDED)
        parts.append("## Required structure\n" + structure)
    parts.append("## Output rules\n" + (OUTPUT_RULES if version >= 2 else OUTPUT_RULES_V1))
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def repair_message(feedback):
    return {"role": "user", "content": REPAIR.format(feedback=feedback)}


def prompt_sha256(messages):
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


FENCE = re.compile(r"```[a-zA-Z]*\s*\n(.*?)```", re.S)


def extract_smv(text):
    """Return the SMV model from an LLM reply, or None if there is none."""
    for block in FENCE.findall(text):
        if "MODULE main" in block:
            return block.strip() + "\n"
    i = text.find("MODULE main")
    return text[i:].strip() + "\n" if i >= 0 else None
