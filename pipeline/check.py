"""Check a generated SMV model: interface lint, then nuXmv.

check_model(smv) returns a CheckResult with:
  parsed           nuXmv read and built the model with the property file appended
  total            transition relation has no deadlock (None if nuXmv never got that far)
  verdicts         {formula: True/False} for each property, as nuXmv printed it
  interface_errors violations of docs/interface.md found by the lint
  nuxmv_errors     nuXmv error lines, with the temp path replaced by "model.smv"
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
ERROR_LINE = re.compile(r"^file .*?: (line \d+: .*)$", re.M)

# check_fsm reports deadlocks; check_ltlspec runs every LTLSPEC (BDD engine, past-time operators OK).
COMMANDS = "go\ncheck_fsm\ncheck_ltlspec\nquit\n"


@dataclass
class CheckResult:
    parsed: bool = False
    total: bool | None = None
    verdicts: dict = field(default_factory=dict)
    interface_errors: list = field(default_factory=list)
    nuxmv_errors: list = field(default_factory=list)
    expected_verdicts: int = 0

    @property
    def ok(self):
        return (
            self.parsed
            and self.total is True
            and not self.interface_errors
            and len(self.verdicts) == self.expected_verdicts
        )

    def feedback(self):
        """Plain-text problem list to send back to the LLM for repair."""
        lines = [f"- {e}" for e in self.interface_errors]
        lines += [f"- nuXmv: {e}" for e in self.nuxmv_errors]
        if self.parsed and self.total is False:
            lines.append("- nuXmv: the transition relation is not total (some state has no successor).")
        if self.parsed and self.total is not False and len(self.verdicts) != self.expected_verdicts:
            lines.append(f"- nuXmv returned {len(self.verdicts)} verdicts, expected {self.expected_verdicts}.")
        return "\n".join(lines)

    def to_dict(self):
        return {
            "ok": self.ok,
            "parsed": self.parsed,
            "total": self.total,
            "verdicts": self.verdicts,
            "interface_errors": self.interface_errors,
            "nuxmv_errors": self.nuxmv_errors,
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


def run_nuxmv(smv, properties=PROPERTIES, nuxmv="nuXmv", timeout=120):
    """Run nuXmv on the model with the property file appended. Lint is not applied here."""
    props = Path(properties).read_text(encoding="utf-8")
    expected = len(re.findall(r"^\s*LTLSPEC\b", props, re.M))
    result = CheckResult(expected_verdicts=expected)
    if shutil.which(nuxmv) is None:
        raise FileNotFoundError(f"{nuxmv} not found on PATH. See README, Install.")
    with tempfile.TemporaryDirectory() as tmp:
        model_path = Path(tmp) / "model.smv"
        cmd_path = Path(tmp) / "check.cmd"
        model_path.write_text(smv.rstrip() + "\n\n" + props, encoding="utf-8")
        cmd_path.write_text(COMMANDS, encoding="utf-8")
        try:
            proc = subprocess.run(
                [nuxmv, "-source", str(cmd_path), str(model_path)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            result.nuxmv_errors.append(f"timed out after {timeout} s")
            return result
        out = (proc.stdout + proc.stderr).replace(str(model_path), "model.smv")
    # With -source, nuXmv exits 0 even on errors and prints "aborting 'source ...'".
    result.nuxmv_errors = ERROR_LINE.findall(out)
    result.parsed = proc.returncode == 0 and "aborting 'source" not in out and not result.nuxmv_errors
    if "The transition relation is total" in out:
        result.total = True
    elif "The transition relation is not total" in out:
        result.total = False
    result.verdicts = {" ".join(f.split()): v == "true" for f, v in SPEC_RESULT.findall(out)}
    if not result.parsed and not result.nuxmv_errors:
        result.nuxmv_errors.append(out.strip().splitlines()[-1] if out.strip() else "nuXmv failed with no output")
    return result


def check_model(smv, **kwargs):
    result = run_nuxmv(smv, **kwargs)
    result.interface_errors = lint_interface(smv)
    return result
