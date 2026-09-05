"""CLI entry point for rebuilding data/cards.sqlite from Scryfall.

The implementation lives in mtgkiosk.ingest, because POST /api/cards/update
drives the same code on a background thread. This file exists so the rebuild
can also be run by hand:

    python scripts/ingest_cards.py [db_path]
"""

from __future__ import annotations

import sys
from pathlib import Path

# `python scripts/ingest_cards.py` puts scripts/ on sys.path, not src/, and the
# package is not pip-installed on the Pi: deploy/install.sh only installs
# requirements.txt, and the service reaches mtgkiosk through uvicorn's
# --app-dir src. Without this the script runs on a dev machine (editable
# install) and fails on the appliance, which is the worst possible split.
_SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from mtgkiosk.ingest import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
