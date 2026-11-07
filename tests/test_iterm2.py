import subprocess

from pitwall import terminals
from pitwall.terminals import iterm2


class FakeRun:
    def __init__(self, stdout="ok\n", code=0, exc=None):
        self.stdout, self.code, self.exc, self.calls = stdout, code, exc, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.code, stdout=self.stdout, stderr="")


def test_focus_passes_ref_as_argv_not_in_script():
    run = FakeRun()
    ref = 'ABC" & do shell script "rm -rf ~'
    assert iterm2.focus(ref, run=run) == "ok"
    argv, kw = run.calls[0]
    assert argv == ["osascript", "-", ref]
    assert ref not in kw["input"]
    assert "on run argv" in kw["input"]
    assert kw["timeout"] == 3


def test_focus_status_missing_error_timeout_not_running():
    assert iterm2.focus("X", run=FakeRun(stdout="missing\n")) == "missing"
    assert iterm2.focus("X", run=FakeRun(stdout="not_running\n")) == "error"
    assert iterm2.focus("X", run=FakeRun(code=1, stdout="")) == "error"
    assert iterm2.focus("X", run=FakeRun(exc=subprocess.TimeoutExpired("osascript", 3))) == "error"
    assert iterm2.focus("X", run=FakeRun(exc=FileNotFoundError())) == "error"


def test_script_never_launches_iterm():
    assert 'application "iTerm2" is running' in iterm2.SCRIPT


def test_dispatch(monkeypatch):
    seen = []
    monkeypatch.setattr(iterm2, "focus", lambda ref, run=None: seen.append(ref) or "ok")
    assert terminals.focus({"kind": "iterm2", "ref": "R"}) == "ok"
    assert seen == ["R"]
    assert terminals.focus(None) == "error"
    assert terminals.focus({"kind": "ghostty", "ref": "R"}) == "error"
    assert terminals.focus({"kind": "iterm2"}) == "error"


def test_clean_title():
    c = iterm2.clean_title
    assert c("✳ Fix flaky login test (-zsh)") == "Fix flaky login test"
    assert c("◑ release-notes (caffeinate)") == "release-notes"
    assert c("variables: api explore (node\")") == "variables: api explore"
    assert c("⠋ Building (claude)") == "Building"
    assert c("~/work/api (-zsh)") is None      # just a path, not a session title
    assert c("-zsh") is None and c("") is None and c("  ") is None
    assert c("Claude Code (-zsh)") is None               # the default title says nothing


def test_titles_parses_script_output():
    run = FakeRun(stdout="A1\t✳ sage (claude)\nB2\t~/x (-zsh)\n\nbad line\n")
    assert iterm2.titles(run=run) == {"A1": "sage", "B2": None}
    assert iterm2.titles(run=FakeRun(stdout="not_running\n")) == {}
    assert iterm2.titles(run=FakeRun(exc=subprocess.TimeoutExpired("osascript", 3))) == {}
