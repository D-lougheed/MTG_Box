"""Every privileged command the app runs must be exactly one sudoers grants.

This is the test that would have caught the update-restart bug, and the reason
it is written against `deploy/mtgkiosk-sudoers` rather than against a literal.

The code ran:

    systemd-run --on-active=2 sudo /usr/bin/systemctl restart mtgkiosk.service

so the first thing actually executed was an **unprivileged** `systemd-run`. In
system mode that has to call StartTransientUnit on the system manager, which
polkit gates behind `auth_admin_keep`; a `User=admin` system service has no
login session, so polkit has nobody to prompt and refuses. The transient unit
was never created, so the `sudo systemctl restart` inside it never ran. The
`sudo` was on the inner command - one level too deep to help.

The existing tests asserted the *shape* of the call ("systemd-run appears
somewhere in the argv") and stayed green throughout, because that only proves
we ran the command we meant to run. It says nothing about whether that command
can actually run. Pinning argv against the sudoers file instead means the two
cannot drift apart: change one without the other and this fails.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from fastapi.testclient import TestClient

from mtgkiosk import app as app_module

SUDOERS = Path(__file__).resolve().parents[1] / "deploy" / "mtgkiosk-sudoers"


def granted_commands() -> list[list[str]]:
    """The exact argvs /etc/sudoers.d/mtgkiosk permits, split as sudo matches them."""
    granted = []
    for line in SUDOERS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        _, marker, spec = line.partition("NOPASSWD:")
        if marker and spec.strip():
            granted.append(spec.split())
    return granted


def capture_commands(monkeypatch, endpoint: str) -> list[list[str]]:
    """Run an endpoint with every subprocess stubbed, returning the argvs it tried."""
    calls: list[list[str]] = []

    class FakeResult:
        returncode = 0

    def fake_run(args, *a, **kw):
        calls.append(list(args))
        return FakeResult()

    monkeypatch.setattr(app_module, "apply_update", lambda repo_dir: None)
    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    TestClient(app_module.app).post(endpoint)
    return calls


def assert_runs_a_granted_command(calls: list[list[str]], needle: str) -> None:
    matching = [c for c in calls if needle in " ".join(c)]
    assert matching, f"no command containing {needle!r} was run at all"
    argv = matching[0]

    assert PurePosixPath(argv[0]).name == "sudo", (
        f"privileged command starts with {argv[0]!r}, not sudo. Anything else "
        "runs as the unprivileged service user and needs polkit to touch the "
        "system manager, which a session-less system service cannot satisfy."
    )

    granted = granted_commands()
    assert argv[1:] in granted, (
        f"{' '.join(argv[1:])!r} is not granted by deploy/mtgkiosk-sudoers.\n"
        f"granted: {[' '.join(g) for g in granted]}"
    )


def test_sudoers_file_parses_to_at_least_one_grant():
    assert granted_commands(), "no NOPASSWD grants found - the parser or the file is wrong"


def test_update_restart_runs_a_command_sudoers_actually_grants(monkeypatch):
    calls = capture_commands(monkeypatch, "/api/update/apply")
    assert_runs_a_granted_command(calls, "systemctl")


def test_power_off_runs_a_command_sudoers_actually_grants(monkeypatch):
    calls = capture_commands(monkeypatch, "/api/power/off")
    assert_runs_a_granted_command(calls, "systemctl")


def test_every_granted_command_names_binaries_by_absolute_path():
    """sudo matches the literal argv, so a bare binary name would never match -
    and a relative one would be a PATH-hijack waiting to happen. Parsed as
    POSIX because these are paths on the Pi, not on whatever runs the tests."""
    for argv in granted_commands():
        assert PurePosixPath(argv[0]).is_absolute(), (
            f"grant starts with {argv[0]!r}, which is not an absolute path")
        for token in argv[1:]:
            # Subcommands and unit names ("restart", "mtgkiosk.service") carry
            # no slash; anything that does is meant to be a path.
            if "/" in token:
                assert PurePosixPath(token).is_absolute(), (
                    f"{token!r} in deploy/mtgkiosk-sudoers is not an absolute path")
