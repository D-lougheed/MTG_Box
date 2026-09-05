import re
import tomllib
from pathlib import Path

from mtgkiosk import __version__


def test_package_is_importable_and_versioned():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_package_version_matches_pyproject():
    """The Settings screen shows __version__, so a drifting pyproject is a lie.

    Asserting they agree, rather than pinning a literal, means a version bump
    is a one-line change instead of a bump plus a test edit - the previous
    version of this test hardcoded "0.1.0" and just had to be kept in step.
    """
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    assert declared == __version__
