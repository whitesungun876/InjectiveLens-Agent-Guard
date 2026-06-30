from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE_DIR = ROOT / "fixtures" / "demo_wallets"


class FixtureNotFoundError(KeyError):
    """Raised when a named demo fixture cannot be found."""


class FixtureRepository:
    """Loads Day 2 demo wallet fixtures.

    The repository returns deep copies so tests and later workflow code can
    mutate fixture dictionaries without contaminating other runs.
    """

    def __init__(self, fixture_dir: Path | str = DEFAULT_FIXTURE_DIR) -> None:
        self.fixture_dir = Path(fixture_dir)

    def list_fixture_ids(self) -> list[str]:
        return sorted(path.stem for path in self.fixture_dir.glob("*.json"))

    def load(self, fixture_id: str) -> dict[str, Any]:
        path = self.fixture_dir / f"{fixture_id}.json"
        if not path.exists():
            raise FixtureNotFoundError(f"Unknown fixture: {fixture_id}")
        return json.loads(path.read_text())

    def load_copy(self, fixture_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.load(fixture_id))

    def load_all(self) -> list[dict[str, Any]]:
        return [self.load_copy(fixture_id) for fixture_id in self.list_fixture_ids()]
