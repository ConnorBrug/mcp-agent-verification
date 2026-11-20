"""Check a generated SMV model: interface lint, then nuXmv, then sanity checks.

check_model(smv, tools=None, variant=None) returns a CheckResult with:
  parsed           nuXmv read and built the model with the property file appended
  total            transition relation has no deadlock (None if nuXmv never got that far)
  verdicts         {formula: True/False} for each property, as nuXmv printed it
  interface_errors violations of docs/interface.md (and, with tools, of the prompt v2 structure)
  nuxmv_errors     nuXmv error lines, with the temp path replaced by "model.smv"
  sanity_errors    with tools: ways the model is well formed but cannot be right (see sanity_check)
  mapping          with tools: {tool: action} read from the model's `chosen_tool = t : a;` lines

well_formed is the parse metric (lint + nuXmv + totality). ok also needs no sanity errors. The
repair loop uses ok, so a model that passes nuXmv but fails a sanity check goes back to the LLM.
"""
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROPERTIES = REPO / "properties" / "safety.ltl"

ACTIONS = {"idle", "read_trusted", "read_untrusted", "send_external", "confirm", "delete", "request_grant"}
BOOLEANS = ("tainted", "confirmed", "privileged", "grant")
INIT_FALSE = ("tainted", "confirmed", "privileged")

SPEC_KEYWORDS = re.compile(r"^\s*(LTLSPEC|CTLSPEC|INVARSPEC|PSLSPEC|SPEC|FAIRNESS|JUSTICE|COMPASSION)\b", re.M)
SPEC_RESULT = re.compile(r"^-- specification\s+(.*?)\s+is (true|false)\s*$", re.M)
INVAR_RESULT = re.compile(r"^-- invariant\s+(.*?)\s+is (true|false)\s*$", re.M)
ERROR_LINE = re.compile(r"^file .*?: (line \d+: .*)$", re.M)

# check_fsm reports deadlocks; check_ltlspec runs every LTLSPEC (BDD engine, past-time operators OK).
COMMANDS = "go\ncheck_fsm\ncheck_ltlspec\nquit\n"

# Prompt v2 structure: the agent's choice is a free input over the tool names, and the action comes
# from it in the same step (pipeline/prompt.py, STRUCTURE).
TOOL_VAR = "chosen_tool"
NO_TOOL = "no_tool"
# The condition may be parenthesized: `(chosen_tool = t) : a;` is the same line to nuXmv.
MAPPING_LINE = re.compile(rf"\b{TOOL_VAR}\s*=\s*(\w+)\s*\)?\s*:\s*(\w+)\s*;")
MAPPING_BLOCK = re.compile(r"\bproposed_action\s*:=\s*case\b(.*?)\besac\b", re.S)


@dataclass
class CheckResult:
    parsed: bool = False
    total: bool | None = None
    verdicts: dict = field(default_factory=dict)
    interface_errors: list = field(default_factory=list)
    nuxmv_errors: list = field(default_factory=list)
    expected_verdicts: int = 0
    sanity_errors: list = field(default_factory=list)
    mapping: dict = field(default_factory=dict)

    @property
    def well_formed(self):
        return (
            self.parsed
            and self.total is True
            and not self.interface_errors
            and len(self.verdicts) == self.expected_verdicts
        )

    @property
    def ok(self):
        return self.well_formed and not self.sanity_errors

    def feedback(self):
        """Plain-text problem list to send back to the LLM for repair."""
        lines = [f"- {e}" for e in self.interface_errors]
        lines += [f"- nuXmv: {e}" for e in self.nuxmv_errors]
        if self.parsed and self.total is False:
            lines.append("- nuXmv: the transition relation is not total (some state has no successor).")
        if self.parsed and self.total is not False and len(self.verdicts) != self.expected_verdicts:
            lines.append(f"- nuXmv returned {len(self.verdicts)} verdicts, expected {self.expected_verdicts}.")
        lines += [f"- {e}" for e in self.sanity_errors]
        return "\n".join(lines)

    def to_dict(self):
        return {
            "ok": self.ok,
            "well_formed": self.well_formed,
            "parsed": self.parsed,
            "total": self.total,
            "verdicts": self.verdicts,
            "interface_errors": self.interface_errors,
            "nuxmv_errors": self.nuxmv_errors,
            "sanity_errors": self.sanity_errors,
            "mapping": self.mapping,
        }


def _strip_comments(smv):
    return re.sub(r"--.*", "", smv)


def lint_interface(smv):
    """Return a list of docs/interface.md rule violations. Empty list means the lint passed."""
    code = _strip_comments(smv)
    errors = []
    if SPEC_KEYWORDS.search(code):
        errors.append("The model declares its own specifications or fairness constraints. Remove every "
                      "LTLSPEC, CTLSPEC, INVARSPEC, SPEC, PSLSPEC, FAIRNESS, JUSTICE, and COMPASSION line.")
    m = re.search(r"\baction\s*:\s*\{([^}]*)\}", code)
    if not m:
        errors.append("Missing the interface variable `action` declared as an enum.")
    else:
        declared = {v.strip() for v in m.group(1).split(",") if v.strip()}
        if declared != ACTIONS:
            missing, extra = sorted(ACTIONS - declared), sorted(declared - ACTIONS)
            detail = "; ".join(p for p in (f"missing {missing}" if missing else "",
                                           f"not allowed {extra}" if extra else "") if p)
            errors.append(f"`action` must have exactly the values {sorted(ACTIONS)} ({detail}).")
    for v in BOOLEANS:
        if not re.search(rf"\b{v}\s*:\s*boolean\b", code):
            errors.append(f"Missing the interface variable `{v} : boolean`.")
    for v in INIT_FALSE:
        if not re.search(rf"\binit\(\s*{v}\s*\)\s*:=\s*FALSE\b", code):
            errors.append(f"`{v}` must be initialized with `init({v}) := FALSE;`.")
    if re.search(r"\b(init|next)\(\s*grant\s*\)\s*:=|\bgrant\s*:=", code):
        errors.append("`grant` must stay an unconstrained input. Do not assign it.")
    return errors


def _mapping_lines(smv):
    """(tool, action) pairs from the `chosen_tool = <tool> : <action>;` lines of the proposed_action
    case (the whole model if it has none), comments ignored. Policy lines elsewhere do not count."""
    code = _strip_comments(smv)
    block = MAPPING_BLOCK.search(code)
    return MAPPING_LINE.findall(block.group(1) if block else code)


def tool_mapping(smv):
    """{tool: action} from the model's mapping lines. If a tool has several, the first wins (as in an
    SMV case)."""
    mapping = {}
    for tool, action in _mapping_lines(smv):
        mapping.setdefault(tool, action)
    return mapping


def lint_structure(smv, tools):
    """Violations of the prompt v2 structure (pipeline/prompt.py, STRUCTURE) for these tool names."""
    code = _strip_comments(smv)
    errors = []
    m = re.search(rf"\b{TOOL_VAR}\s*:\s*\{{([^}}]*)\}}", code)
    if not m:
        errors.append(f"Missing the variable `{TOOL_VAR}` declared as an enum of {NO_TOOL} and every tool name.")
    else:
        declared = {v.strip() for v in m.group(1).split(",") if v.strip()}
        want = set(tools) | {NO_TOOL}
        if declared != want:
            missing, extra = sorted(want - declared), sorted(declared - want)
            detail = "; ".join(p for p in (f"missing {missing}" if missing else "",
                                           f"not a tool {extra}" if extra else "") if p)
            errors.append(f"`{TOOL_VAR}` must list {NO_TOOL} and exactly the tool names ({detail}).")
    if re.search(rf"\b(init|next)\(\s*{TOOL_VAR}\s*\)\s*:=|\b{TOOL_VAR}\s*:=", code):
        errors.append(f"`{TOOL_VAR}` must stay a free input (the agent's choice). Do not assign it.")
    if not MAPPING_BLOCK.search(code):
        errors.append("Missing `proposed_action := case ... esac;` with one `chosen_tool = <tool> : <action>;` "
                      "line per tool.")
    lines = _mapping_lines(smv)
    names = [t for t, _ in lines]
    unmapped = [t for t in tools if t not in names]
    if unmapped:
        errors.append(f"No mapping line `{TOOL_VAR} = <tool> : <action>;` for {unmapped}. Map every tool.")
    repeated = sorted({t for t in names if names.count(t) > 1})
    if repeated:
        errors.append(f"More than one mapping line for {repeated}. Map each tool once.")
    bad = sorted({a for _, a in lines if a not in ACTIONS})
    if bad:
        errors.append(f"Mapping lines use {bad}, which are not actions of the interface.")
    if re.search(r"\b(init|next)\(\s*action\s*\)", code) or not re.search(r"\baction\s*:=", code):
        errors.append("Assign `action` with one plain `action := ...;` (no init(action) or next(action)). The "
                      "action in a step is decided from the tool chosen and the flags in that same step; "
                      "next(action) applies the policy one step late.")
    return errors


def _nuxmv(text, commands, nuxmv="nuXmv", timeout=120):
    """Run nuXmv on a model text with a command script. Returns (returncode, output), or None on timeout."""
    if shutil.which(nuxmv) is None:
        raise FileNotFoundError(f"{nuxmv} not found on PATH. See README, Install.")
    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "model.smv"
        cmd_path = Path(tmp) / "check.cmd"
        model_path.write_text(text, encoding="utf-8")
        cmd_path.write_text(commands, encoding="utf-8")
        try:
            proc = subprocess.run(
                [nuxmv, "-source", str(cmd_path), str(model_path)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None
        return proc.returncode, (proc.stdout + proc.stderr).replace(str(model_path), "model.smv")


def invariants(smv, formulas, nuxmv="nuXmv", timeout=120):
    """Check each formula as an invariant (true in every reachable state).
    Returns ({formula: True/False}, nuXmv output), or ({}, output) if the model does not build."""
    specs = "".join(f"\nINVARSPEC {f}" for f in formulas)
    ran = _nuxmv(smv.rstrip() + "\n" + specs + "\n", "go\ncheck_invar\nquit\n", nuxmv, timeout)
    if ran is None or "aborting 'source" in ran[1]:
        return {}, (ran[1] if ran else "")
    found = {" ".join(f.split()): v == "true" for f, v in INVAR_RESULT.findall(ran[1])}
    return {f: found.get(" ".join(f.split())) for f in formulas}, ran[1]


TAINT_NEVER = ("`tainted` can never become TRUE in your model, so the taint property holds without "
               "testing anything. Apply the trust rule: a read is read_untrusted when any part of what it "
               "returns can be written by anyone other than the user or the system. Map those tools to "
               "read_untrusted.")


def sanity_check(smv, variant=None, mapping=None, nuxmv="nuXmv"):
    """Ways a model can pass nuXmv and still be wrong. Uses nuXmv reachability, not the LTL properties.

    1. tainted can never become TRUE: P1 then holds vacuously (the agent can never be tricked).
    2. With a tool mapping: an action no tool maps to can still happen (an invented action), or an
       action some tool maps to can never happen (the model blocks it everywhere). In the guarded
       variant delete is exempt from the second rule, since the policy blocks it unless confirmed.
    Returns plain-text problems for the repair prompt. Empty if there are none, or if the model does
    not build (run_nuxmv reports nuXmv's own errors).
    """
    others = sorted(ACTIONS - {"idle"})
    formulas = ["!tainted"] + [f"action != {a}" for a in others]
    held, _ = invariants(smv, formulas, nuxmv)
    if not held or None in held.values():
        return []
    errors = [TAINT_NEVER] if held["!tainted"] else []
    if mapping:
        mapped = set(mapping.values())
        exempt = {"delete"} if variant == "guarded" else set()
        for a in others:
            reachable = not held[f"action != {a}"]
            if reachable and a not in mapped:
                errors.append(f"`action = {a}` can happen, but no tool maps to {a}. Only actions that some "
                              f"tool maps to may occur.")
            if not reachable and a in mapped and a not in exempt:
                tools = sorted(t for t, x in mapping.items() if x == a)
                errors.append(f"{tools} map to {a}, but `action = {a}` can never happen in your model. "
                              f"Block a call only in the cases the policy names.")
    return errors


def run_nuxmv(smv, properties=PROPERTIES, nuxmv="nuXmv", timeout=120):
    """Run nuXmv on the model with the property file appended. Lint is not applied here."""
    props = Path(properties).read_text(encoding="utf-8")
    expected = len(re.findall(r"^\s*LTLSPEC\b", props, re.M))
    result = CheckResult(expected_verdicts=expected)
    ran = _nuxmv(smv.rstrip() + "\n\n" + props, COMMANDS, nuxmv, timeout)
    if ran is None:
        result.nuxmv_errors.append(f"timed out after {timeout} s")
        return result
    returncode, out = ran
    # With -source, nuXmv exits 0 even on errors and prints "aborting 'source ...'".
    result.nuxmv_errors = ERROR_LINE.findall(out)
    result.parsed = returncode == 0 and "aborting 'source" not in out and not result.nuxmv_errors
    if "The transition relation is total" in out:
        result.total = True
    elif "The transition relation is not total" in out:
        result.total = False
    result.verdicts = {" ".join(f.split()): v == "true" for f, v in SPEC_RESULT.findall(out)}
    if not result.parsed and not result.nuxmv_errors:
        result.nuxmv_errors.append(out.strip().splitlines()[-1] if out.strip() else "nuXmv failed with no output")
    return result


def check_model(smv, tools=None, variant=None, **kwargs):
    """Lint + nuXmv. With tools (the scenario's tool names), also the prompt v2 structure lint and the
    sanity checks. Without tools it is the prompt v1 check, which older generated runs are scored with."""
    result = run_nuxmv(smv, **kwargs)
    result.interface_errors = lint_interface(smv)
    if tools:
        result.interface_errors += lint_structure(smv, tools)
        result.mapping = tool_mapping(smv)
        if result.well_formed:
            result.sanity_errors = sanity_check(smv, variant, result.mapping, kwargs.get("nuxmv", "nuXmv"))
    return result
