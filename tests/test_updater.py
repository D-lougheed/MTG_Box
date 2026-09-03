import subprocess
from pathlib import Path

import pytest

from mtgkiosk.updater import UpdateError, apply, check, _scrub


def _git(repo_dir: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo_dir), *args], check=True, capture_output=True)


def _init_remote_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q")
    _git(remote, "config", "user.email", "test@example.com")
    _git(remote, "config", "user.name", "Test")
    (remote / "file.txt").write_text("v1")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "initial")

    local = tmp_path / "local"
    subprocess.run(["git", "clone", "-q", str(remote), str(local)], check=True, capture_output=True)
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test")
    return remote, local


def test_check_reports_up_to_date_immediately_after_clone(tmp_path):
    _remote, local = _init_remote_and_clone(tmp_path)
    status = check(local)
    assert status.up_to_date is True
    assert status.commits_behind == 0


def test_check_detects_new_remote_commit(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    (remote / "file.txt").write_text("v2")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "second")

    status = check(local)
    assert status.up_to_date is False
    assert status.commits_behind == 1


def test_apply_pulls_new_commit(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    (remote / "file.txt").write_text("v2")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "second")

    apply(local)
    assert (local / "file.txt").read_text() == "v2"


def test_apply_raises_on_diverged_local_history(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    (remote / "file.txt").write_text("v2-remote")
    _git(remote, "add", "file.txt")
    _git(remote, "commit", "-q", "-m", "remote-diverges")

    (local / "file.txt").write_text("v2-local")
    _git(local, "add", "file.txt")
    _git(local, "commit", "-q", "-m", "local-diverges")

    with pytest.raises(UpdateError):
        apply(local)


def test_check_counts_multiple_commits_behind(tmp_path):
    remote, local = _init_remote_and_clone(tmp_path)
    for i in range(3):
        (remote / "file.txt").write_text(f"v{i}")
        _git(remote, "add", "file.txt")
        _git(remote, "commit", "-q", "-m", f"commit {i}")

    status = check(local)
    assert status.commits_behind == 3


def test_scrub_handles_credential_containing_at_sign():
    message = "fatal: could not read Password for 'https://user@example.com:pass@github.com/x'"
    assert "pass" not in _scrub(message)
