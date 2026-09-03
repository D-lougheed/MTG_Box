"""Git-based update mechanism: check for and apply updates from the configured remote.

Uses --ff-only on apply deliberately: a diverged local history (e.g. from
a manual edit on the Pi) fails loudly here rather than silently clobbering
whatever was there, per the Slice 1 design spec's error-handling table.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class UpdateError(Exception):
    pass


_CREDENTIAL_RE = re.compile(r"://[^/\s@]+@")


def _scrub(message: str) -> str:
    return _CREDENTIAL_RE.sub("://***@", message)


@dataclass
class UpdateStatus:
    up_to_date: bool
    local_commit: str
    remote_commit: str
    commits_behind: int


def _run(repo_dir: Path, *args: str, timeout: float = 15) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise UpdateError(_scrub(f"git {' '.join(args)} timed out after {timeout}s")) from e
    if result.returncode != 0:
        raise UpdateError(_scrub(result.stderr.strip()))
    return result.stdout.strip()


def _current_branch(repo_dir: Path) -> str:
    return _run(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")


def check(repo_dir: Path) -> UpdateStatus:
    _run(repo_dir, "fetch", "origin")
    branch = _current_branch(repo_dir)
    local_commit = _run(repo_dir, "rev-parse", "HEAD")
    remote_commit = _run(repo_dir, "rev-parse", f"origin/{branch}")
    commits_behind = int(_run(repo_dir, "rev-list", "--count", f"{local_commit}..{remote_commit}"))
    return UpdateStatus(
        up_to_date=commits_behind == 0,
        local_commit=local_commit,
        remote_commit=remote_commit,
        commits_behind=commits_behind,
    )


def apply(repo_dir: Path) -> None:
    _run(repo_dir, "pull", "--ff-only")
