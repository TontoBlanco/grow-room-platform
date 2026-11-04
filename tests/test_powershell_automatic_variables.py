"""Assignments to PowerShell automatic variables fail on Windows PowerShell 5.1.

Variable names are case-insensitive, so `$Home = ...` overwrites `$HOME` and the
engine raises VariableNotWritable. These checks scan the aws-poc scripts and
anything they dot-source.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]

# about_Automatic_Variables (Windows PowerShell 5.1), compared case-insensitively.
# $null is omitted: `$null = command` is the supported way to discard output.
AUTOMATIC = frozenset(
    {
        "args",
        "consolefilename",
        "error",
        "event",
        "eventargs",
        "eventsubscriber",
        "executioncontext",
        "false",
        "foreach",
        "home",
        "host",
        "input",
        "lastexitcode",
        "matches",
        "myinvocation",
        "nestedpromptlevel",
        "ofs",
        "pid",
        "profile",
        "psboundparameters",
        "pscmdlet",
        "pscommandpath",
        "psculture",
        "psdebugcontext",
        "pshome",
        "psitem",
        "psscriptroot",
        "pssenderinfo",
        "psuiculture",
        "psversiontable",
        "pwd",
        "sender",
        "shellid",
        "stacktrace",
        "switch",
        "this",
        "true",
        "_",
        "$",
        "?",
        "^",
    }
)

_ASSIGN = re.compile(
    r"""
    \$(?:(?P<scope>script|global|local|private|using|workflow|variable):)?
    (?P<name>[A-Za-z_][A-Za-z0-9_]*|\$|\?|\^)
    \s*
    (?:\+\+|--|(?:[+\-*/%])?=)
    (?!=)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_FOREACH = re.compile(
    r"\bforeach\s*\(\s*\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+in\b",
    re.IGNORECASE,
)
_PARAM_START = re.compile(r"(?i)\b(?:param|function\s+[A-Za-z_][\w-]*)\s*\(")
_PARAM_NAME = re.compile(r"(?:(?<=\()|(?<=,))\s*\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_SET_VARIABLE = re.compile(
    r"""
    (?i)
    \b(?:Set-Variable|New-Variable)\b
    [^\r\n]*?
    -Name
    \s+
    (?:
        '(?P<sq>[A-Za-z_][A-Za-z0-9_]*)'
      | "(?P<dq>[A-Za-z_][A-Za-z0-9_]*)"
      | (?P<bare>[A-Za-z_][A-Za-z0-9_]*)
    )
    """,
    re.VERBOSE,
)


class Hit(NamedTuple):
    line: int
    name: str
    kind: str


def powershell_scripts() -> list[Path]:
    pending = sorted((ROOT / "scripts").glob("*.ps1"))
    seen: set[Path] = set()
    ordered: list[Path] = []
    while pending:
        path = pending.pop(0).resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        ordered.append(path)
        text = path.read_text(encoding="utf-8")
        for raw in dot_source_targets(text):
            resolved = resolve_dot_source(path, raw)
            if resolved is not None and resolved not in seen:
                pending.append(resolved)
    return ordered


def dot_source_targets(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not re.match(r"^\.\s", stripped):
            continue
        for match in re.finditer(r"""['"]([^'"]+\.ps1)['"]""", stripped):
            found.append(match.group(1))
    return found


def resolve_dot_source(script: Path, raw: str) -> Path | None:
    rel = Path(raw.replace("\\", "/"))
    for candidate in (script.parent / rel, ROOT / rel):
        if candidate.is_file():
            return candidate.resolve()
    return None


def mask_non_code(text: str) -> str:
    """Replace comments and string literals with spaces, preserving newlines."""
    chars = list(text)
    n = len(chars)
    i = 0
    here: str | None = None

    def blank(start: int, end: int) -> None:
        for j in range(start, end):
            if chars[j] != "\n":
                chars[j] = " "

    while i < n:
        if here is not None:
            if chars[i] == "\n":
                rest = "".join(chars[i + 1 : i + 1 + len(here)])
                if rest == here:
                    blank(i + 1, i + 1 + len(here))
                    i = i + 1 + len(here)
                    here = None
                    continue
            elif chars[i] != "\n":
                chars[i] = " "
            i += 1
            continue
        if chars[i] == "<" and i + 1 < n and chars[i + 1] == "#":
            end = text.find("#>", i + 2)
            if end < 0:
                blank(i, n)
                break
            blank(i, end + 2)
            i = end + 2
            continue
        if (
            chars[i] == "@"
            and i + 1 < n
            and chars[i + 1] in {'"', "'"}
            and (i == 0 or chars[i - 1] in " \t=")
        ):
            j = i + 2
            if j < n and chars[j] == "\r":
                j += 1
            if j < n and chars[j] == "\n":
                here = chars[i + 1] + "@"
                blank(i, j)
                i = j
                continue
        if chars[i] == "#":
            end = text.find("\n", i)
            blank(i, n if end < 0 else end)
            i = n if end < 0 else end
            continue
        if chars[i] == "'":
            j = i + 1
            while j < n and chars[j] != "\n":
                if chars[j] == "'" and j + 1 < n and chars[j + 1] == "'":
                    j += 2
                    continue
                if chars[j] == "'":
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
            continue
        if chars[i] == '"':
            j = i + 1
            while j < n and chars[j] != "\n":
                if chars[j] == "`" and j + 1 < n:
                    j += 2
                    continue
                if chars[j] == '"':
                    j += 1
                    break
                j += 1
            blank(i, j)
            i = j
            continue
        i += 1
    return "".join(chars)


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _match_paren(code: str, open_index: int) -> int | None:
    depth = 0
    for i in range(open_index, len(code)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _strip_brackets(text: str) -> str:
    out: list[str] = []
    depth = 0
    for char in text:
        if char == "[":
            depth += 1
            out.append(" ")
        elif char == "]" and depth:
            depth -= 1
            out.append(" ")
        elif depth == 0:
            out.append(char)
        elif char == "\n":
            out.append("\n")
        else:
            out.append(" ")
    return "".join(out)


def find_hits(text: str) -> list[Hit]:
    code = mask_non_code(text)
    hits: list[Hit] = []

    def add(index: int, name: str, kind: str) -> None:
        if name.lower() in AUTOMATIC:
            hits.append(Hit(_line_of(text, index), name, kind))

    for match in _ASSIGN.finditer(code):
        # $env:HOME is the environment drive, not the automatic variable.
        # The scope group does not include env, so that form never matches.
        add(match.start(), match.group("name"), "assignment")
    for match in _FOREACH.finditer(code):
        add(match.start("name"), match.group("name"), "foreach")
    for match in _SET_VARIABLE.finditer(code):
        name = match.group("sq") or match.group("dq") or match.group("bare")
        add(match.start(), name, "set-variable")
    for match in _PARAM_START.finditer(code):
        open_paren = match.end() - 1
        close = _match_paren(code, open_paren)
        if close is None:
            continue
        body = _strip_brackets(code[open_paren : close + 1])
        for name_match in _PARAM_NAME.finditer(body):
            add(open_paren + name_match.start(), name_match.group("name"), "parameter")
    return hits


def test_aws_poc_powershell_does_not_assign_automatic_variables():
    collisions = [
        f"{path.relative_to(ROOT)}:{hit.line}: {hit.kind} ${hit.name}"
        for path in powershell_scripts()
        for hit in find_hits(path.read_text(encoding="utf-8"))
    ]
    assert collisions == []


def test_scanner_follows_the_aws_poc_dot_source():
    names = {path.name for path in powershell_scripts()}
    assert names == {"aws-poc.ps1", "aws-poc-ha.ps1"}
    source = (ROOT / "scripts" / "aws-poc.ps1").read_text(encoding="utf-8")
    assert dot_source_targets(source) == ["aws-poc-ha.ps1"]


def test_scanner_flags_automatic_assignments_and_ignores_lookalikes():
    sample = textwrap.dedent(
        """\
        $home = 1
        $HOME += 2
        $script:Host = 'x'
        foreach ($Input in $items) {}
        param([string]$Profile)
        function Get-Thing([int]$PID) {}
        $_ = 1
        Set-Variable -Name Error -Value @()
        $pid++
        $Matches = @{}
        $args = @()
        $pwd = 'C:\\'
        $ErrorActionPreference = 'Stop'
        $AwsProfile = 'GrowRoom'  # NOT $Profile - automatic
        $AppFqdn = 'app.example'  # NOT $event = also automatic
        $env:HOME = 'C:\\users\\me'
        $value = $Matches[1]
        $err = $_
        $null = Get-Date
        $found = $false
        $awsArgs += @('--token')
        foreach ($name in $names) {}
        param(
          [Parameter(Mandatory = $true)]
          [string]$Action
        )
        # $pwd = 'comment'
        $app = @"
        $pid = 1
        "@
        """
    )
    hits = find_hits(sample)
    flagged = {(hit.name.lower(), hit.kind) for hit in hits}
    assert flagged == {
        ("home", "assignment"),
        ("host", "assignment"),
        ("input", "foreach"),
        ("profile", "parameter"),
        ("pid", "parameter"),
        ("pid", "assignment"),
        ("_", "assignment"),
        ("error", "set-variable"),
        ("matches", "assignment"),
        ("args", "assignment"),
        ("pwd", "assignment"),
    }
    counts: dict[tuple[str, str], int] = {}
    for hit in hits:
        key = (hit.name.lower(), hit.kind)
        counts[key] = counts.get(key, 0) + 1
    # One $pid++ assignment. The here-string "$pid = 1" and the comment
    # "$event = ..." are not code, so they must not add hits.
    assert counts[("pid", "assignment")] == 1
    assert counts[("pwd", "assignment")] == 1
    assert counts[("host", "assignment")] == 1
    assert "event" not in {hit.name.lower() for hit in hits}
    home = [hit for hit in hits if hit.name.lower() == "home"]
    assert [hit.line for hit in home] == [1, 2]


def test_withha_dry_run_returns_before_stop_upload_or_apply():
    text = (ROOT / "scripts" / "aws-poc.ps1").read_text(encoding="utf-8")
    up = text.split("function Do-Up", 1)[1].split("function Invoke-UpStack", 1)[0]
    # Plain up returns before prepare. The -WithHA path prepares, then returns
    # on a dry run before the second Invoke-UpStack call.
    assert up.index("if (-not $WithHA)") < up.index("Invoke-WithHaPrepare")
    with_ha = up.split("Invoke-WithHaPrepare", 1)[1]
    assert with_ha.index("if ($script:HaDryRunStop)") < with_ha.index("Invoke-UpStack")
    dry_message = "Home Assistant was not stopped. Nothing was uploaded. Terraform was not applied."
    assert dry_message in with_ha

    helper = (ROOT / "scripts" / "aws-poc-ha.ps1").read_text(encoding="utf-8")
    dry = helper.split("function Invoke-HaDryRunChecks", 1)[1].split("\nfunction ", 1)[0]
    for banned in ("Stop-HomeHa", "Start-HomeHa", "Backup-HomeConfigToS3", "Send-VerifiedBackup"):
        assert banned not in dry
    prepare = helper.split("function Invoke-WithHaPrepare", 1)[1].split("\nfunction ", 1)[0]
    dry_plan = prepare.index('if ($plan.action -eq "dry-run")')
    assert dry_plan < prepare.index("Stop-HomeHa")
    assert dry_plan < prepare.index("Backup-HomeConfigToS3")
    assert "$HomeRunning = Test-HomeHaRunning" in prepare
