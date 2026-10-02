#!/usr/bin/env python3
"""Write spec/zones.json: the definition's zones and every offset change of each.

The zoned-date-time and wall-time shapes generate a value near an offset
change of its zone in one case of four. This tool computes each change of
the zones in ZONES from FROM_YEAR to UNTIL_YEAR, from the IANA tzdata
release RELEASE. It refuses a download whose SHA-512 differs from SHA512,
compiles the release with zic, and lists each zone's transitions with
zdump. A transition counts when the offset from UTC changes. A change of
abbreviation or of the daylight-saving flag alone does not count.

The tool needs the network, zic and zdump, so the gate does not run it.
The validator checks the file it writes. A change to the table is a major
version of the definition, because a stored case decodes an index into it.

Run with:

    python3 tools/zones.py
"""

from __future__ import annotations

import calendar
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent

#: The release the table is computed from, and the SHA-512 of its tarball.
#: Its signature verifies against Paul Eggert's key, fingerprint 7E37 92A9
#: D8AC F7D6 33BC 1588 ED97 E90E 62AA 7E34.
RELEASE: Final = "2026e"
SHA512: Final = (
    "5be2f875f73b75e5783c474bf7a6c768e433cc90283f8fc6a75e3d05bd92aec9"
    "7936e8a55ccca5e880b5dacc18ba65932bab0e783e1ed5d2af4a3a4df95512be"
)
URL: Final = f"https://data.iana.org/time-zones/releases/tzdata{RELEASE}.tar.gz"

#: The years the table covers: from the start of FROM_YEAR to the start of
#: UNTIL_YEAR.
FROM_YEAR: Final = 1900
UNTIL_YEAR: Final = 2100

#: The zone list, in the order a zone shape samples it. Each zone covers a
#: rule that code which handles time zones gets wrong.
ZONES: Final = (
    "UTC",  # No offset and no change.
    "Europe/Amsterdam",  # Northern daylight saving under the European rules.
    "America/New_York",  # Northern daylight saving under the US rules.
    "Australia/Sydney",  # Southern daylight saving.
    "Australia/Lord_Howe",  # A daylight-saving shift of 30 minutes.
    "Pacific/Chatham",  # Offsets of +12:45 and +13:45.
    "Asia/Kolkata",  # +05:30, unchanged since 1945.
    "Asia/Kathmandu",  # +05:45, since 1986.
    "America/St_Johns",  # -03:30 with daylight saving.
    "Asia/Tehran",  # +03:30, with daylight saving until 2022.
    "America/Sao_Paulo",  # Southern daylight saving until 2019.
    "Pacific/Kiritimati",  # +14:00, which skipped 31 December 1994.
    "Pacific/Apia",  # A skipped day, 30 December 2011.
    "Europe/Dublin",  # Daylight saving that tzdata states as negative.
    "Africa/Casablanca",  # An offset lowered by one hour during Ramadan.
    "Antarctica/Troll",  # A daylight-saving shift of two hours.
)

#: The source files of a release that define the listed zones and links.
SOURCES: Final = (
    "africa",
    "antarctica",
    "asia",
    "australasia",
    "europe",
    "northamerica",
    "southamerica",
    "etcetera",
    "backward",
)

#: One line of zdump -v: a UTC time, and the offset in force at it.
LINE: Final = re.compile(
    r"^\S+\s+\w{3} (?P<month>\w{3})\s+(?P<day>\d+) "
    r"(?P<hour>\d\d):(?P<minute>\d\d):(?P<second>\d\d) (?P<year>\d+) UT = "
    r".* gmtoff=(?P<offset>-?\d+)$"
)

#: The months zdump names, in calendar order.
MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

#: A change: the first second of the new offset, the offset before it and
#: the offset after it, all in seconds.
Change = tuple[int, int, int]


class ZonesError(RuntimeError):
    """A release that cannot be fetched, verified, compiled or listed."""


def readings(listing: str) -> list[tuple[int, int]]:
    """Return each time zdump -v lists, in seconds since the epoch, with its offset.

    A line whose time zdump could not convert names no UT time, and is
    skipped. So is a line outside the table's years, such as the last
    time zdump can represent.
    """
    out: list[tuple[int, int]] = []
    for line in listing.splitlines():
        match = LINE.match(line)
        if match is None or not FROM_YEAR - 1 <= int(match["year"]) <= UNTIL_YEAR:
            continue
        instant = calendar.timegm(
            (
                int(match["year"]),
                MONTHS.index(match["month"]) + 1,
                int(match["day"]),
                int(match["hour"]),
                int(match["minute"]),
                int(match["second"]),
            )
        )
        out.append((instant, int(match["offset"])))
    return out


def changes(listing: str) -> list[Change]:
    """Return the offset changes of one zone from its zdump -v listing.

    zdump lists each transition as the last second of the old offset
    followed by the first second of the new one. A pair whose offsets are
    equal changes only an abbreviation or a flag, and is no change. A
    change outside the table's years is left out.
    """
    lower = calendar.timegm((FROM_YEAR, 1, 1, 0, 0, 0))
    upper = calendar.timegm((UNTIL_YEAR, 1, 1, 0, 0, 0))
    listed = readings(listing)
    found: list[Change] = []
    for (before_at, before), (at, after) in itertools.pairwise(listed):
        if at == before_at + 1 and before != after and lower <= at < upper:
            found.append((at, before, after))
    return found


def render(table: dict[str, list[Change]]) -> str:
    """Return the JSON of the table, with one change per line."""
    zones = ",\n".join(_zone(name, found) for name, found in table.items())
    return (
        "{\n"
        f'  "release": {json.dumps(RELEASE)},\n'
        f'  "sha512": {json.dumps(SHA512)},\n'
        f'  "from": {FROM_YEAR},\n'
        f'  "until": {UNTIL_YEAR},\n'
        f'  "zones": [\n{zones}\n  ]\n'
        "}\n"
    )


def _zone(name: str, found: list[Change]) -> str:
    """Return one zone's JSON object, indented to sit in the list of zones."""
    changed = "[]"
    if found:
        rows = ",\n".join(f"        [{at}, {old}, {new}]" for at, old, new in found)
        changed = f"[\n{rows}\n      ]"
    return (
        f'    {{\n      "name": {json.dumps(name)},\n      "changes": {changed}\n    }}'
    )


def fetch(directory: Path) -> Path:
    """Download the release into directory, and return the tarball's path.

    Raises:
        ZonesError: the tarball's SHA-512 differs from SHA512.
    """
    target = directory / f"tzdata{RELEASE}.tar.gz"
    with urllib.request.urlopen(URL, timeout=60) as response:
        target.write_bytes(response.read())
    digest = hashlib.sha512(target.read_bytes()).hexdigest()
    if digest != SHA512:
        raise ZonesError(f"tzdata{RELEASE}.tar.gz has SHA-512 {digest}")
    return target


def compile_zones(tarball: Path, directory: Path) -> Path:
    """Extract the release, compile it with zic, and return the zone directory.

    Raises:
        ZonesError: zic refuses the sources.
    """
    source = directory / "source"
    with tarfile.open(tarball) as archive:
        archive.extractall(source, filter="data")
    compiled = directory / "zoneinfo"
    result = subprocess.run(
        ["zic", "-d", str(compiled), *(str(source / s) for s in SOURCES)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ZonesError(f"zic: {result.stderr.strip()}")
    return compiled


def list_zone(zone: str, compiled: Path) -> str:
    """Return zdump's verbose listing of one compiled zone over the table's years.

    Raises:
        ZonesError: zdump fails, or the compiled release lacks the zone.
    """
    if not (compiled / zone).is_file():
        raise ZonesError(f"tzdata{RELEASE} has no zone {zone}")
    result = subprocess.run(
        ["zdump", "-v", "-c", f"{FROM_YEAR},{UNTIL_YEAR}", zone],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "TZDIR": str(compiled)},
    )
    if result.returncode != 0:
        raise ZonesError(f"zdump {zone}: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    """Compute the table from the pinned release, and write spec/zones.json."""
    with tempfile.TemporaryDirectory(prefix="assert-spec-zones-") as scratch:
        directory = Path(scratch)
        compiled = compile_zones(fetch(directory), directory)
        table = {zone: changes(list_zone(zone, compiled)) for zone in ZONES}
    (ROOT / "spec" / "zones.json").write_text(render(table))
    total = sum(len(found) for found in table.values())
    print(f"spec/zones.json: {total} offset changes in {len(table)} zones")
    return 0


if __name__ == "__main__":
    sys.exit(main())
