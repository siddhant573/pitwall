import plistlib
import subprocess

from pitwall import service


class Rec:
    def __init__(self, out=None):
        self.calls, self.out = [], out or {}

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        key = argv[1] if len(argv) > 1 else ""
        code, stdout = self.out.get(key, (0, ""))
        return subprocess.CompletedProcess(argv, code, stdout=stdout, stderr="")


def test_plist_contents(tmp_path):
    data = plistlib.loads(service.plist("/u/bin/pitwall", tmp_path / "serve.log"))
    assert data["Label"] == "io.github.siddhant573.pitwall"
    assert data["ProgramArguments"] == ["/u/bin/pitwall", "serve", "--log-file", str(tmp_path / "serve.log")]
    assert data["RunAtLoad"] is True and data["KeepAlive"] is True
    assert data["StandardOutPath"] == data["StandardErrorPath"] == str(tmp_path / "serve.out")


def test_install_writes_plist_and_bootstraps(tmp_path):
    run = Rec()
    p = service.install(program="/u/bin/pitwall", agents_dir=tmp_path, run=run)
    assert p.exists() and p.name == "io.github.siddhant573.pitwall.plist"
    verbs = [c[1] for c in run.calls]
    assert verbs == ["bootout", "bootstrap"]
    assert run.calls[1][2].startswith("gui/") and run.calls[1][3] == str(p)


def test_uninstall_removes(tmp_path):
    run = Rec()
    p = service.install(program="/u/bin/pitwall", agents_dir=tmp_path, run=run)
    assert service.uninstall(agents_dir=tmp_path, run=run) is True
    assert not p.exists()
    assert service.uninstall(agents_dir=tmp_path, run=run) is False


def test_status(tmp_path):
    assert service.status(agents_dir=tmp_path, run=Rec()) == "not installed"
    service.install(program="/u/bin/pitwall", agents_dir=tmp_path, run=Rec())
    assert service.status(agents_dir=tmp_path, run=Rec({"print": (0, "state = running\n\tpid = 4242\n")})) == "running (pid 4242)"
    assert service.status(agents_dir=tmp_path, run=Rec({"print": (113, "")})) == "installed, not running"


def test_paused_stops_and_restarts_only_if_running(tmp_path):
    service.install(program="/u/bin/pitwall", agents_dir=tmp_path, run=Rec())
    run = Rec({"print": (0, "pid = 7\n")})
    with service.paused(agents_dir=tmp_path, run=run):
        pass
    assert [c[1] for c in run.calls] == ["print", "bootout", "bootstrap"]
    run = Rec({"print": (113, "")})
    with service.paused(agents_dir=tmp_path, run=run):
        pass
    assert [c[1] for c in run.calls] == ["print"]


def test_install_reports_bootstrap_failure(tmp_path):
    import pytest
    run = Rec({"bootstrap": (5, "")})
    with pytest.raises(service.ServiceError):
        service.install(program="/u/bin/pitwall", agents_dir=tmp_path, run=run)


def test_program_falls_back_to_an_absolute_path(monkeypatch):
    monkeypatch.setattr(service.shutil, "which", lambda n: None)
    assert service.program_path().startswith("/")
