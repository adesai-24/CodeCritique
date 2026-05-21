import subprocess

from critique.git_utils import get_changed_files, install_pre_push_hook


def test_get_changed_files_filters_py_and_existing(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("not python\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("y = 2\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(cmd, capture_output, text, check):
        return Result("a.py\nb.txt\nsub/c.py\nmissing.py\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    files = get_changed_files()

    assert files == [
        str((tmp_path / "a.py").resolve()),
        str((tmp_path / "sub" / "c.py").resolve()),
    ]


def test_install_pre_push_hook_creates_hook(tmp_path, monkeypatch):
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    monkeypatch.chdir(tmp_path)

    install_pre_push_hook()

    hook_path = hooks_dir / "pre-push"
    assert hook_path.exists()

    content = hook_path.read_text(encoding="utf-8")
    assert "CodeCritique Hook" in content
    assert "critique.cli" in content
