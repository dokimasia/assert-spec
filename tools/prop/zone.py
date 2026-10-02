"""The zone list and every offset change of its zones, as spec/zones.json states them.

The zone shapes sample the list, and the zoned-date-time and wall-time
shapes generate a value near one of a zone's changes in one case of four.
The list's order is the definition's: UTC first, so a zone shrinks to UTC.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

#: The table the definition publishes beside the assertion table.
TABLE: Final = Path(__file__).resolve().parents[2] / "spec" / "zones.json"


@dataclass(frozen=True)
class Change:
    """One offset change: its first second and the offsets before and after it.

    at is in seconds since 1970-01-01T00:00:00Z, and the offsets are in
    seconds east of UTC.
    """

    at: int
    before: int
    after: int


@dataclass(frozen=True)
class Zone:
    """A zone of the list, and its offset changes in time order."""

    name: str
    changes: tuple[Change, ...]


@functools.cache
def zones() -> tuple[Zone, ...]:
    """Return the zone list, in the definition's order."""
    document = json.loads(TABLE.read_text())
    return tuple(
        Zone(
            str(zone["name"]),
            tuple(Change(int(at), int(b), int(a)) for at, b, a in zone["changes"]),
        )
        for zone in document["zones"]
    )
