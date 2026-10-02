"""The zone table's tool: what it reads from zdump, and what it writes."""

from __future__ import annotations

import calendar
import contextlib
import hashlib
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from typing import final, override
from unittest import mock

import zones
from zones import (
    FROM_YEAR,
    RELEASE,
    ROOT,
    SHA512,
    SOURCES,
    UNTIL_YEAR,
    ZONES,
    ZonesError,
    changes,
    readings,
    render,
)

#: A zone that springs forward on 1 April 1990 and falls back on 1 October,
#: in the source format zic reads.
SPRING_AND_FALL = """\
Rule Test 1990 only - Apr 1 2:00 1:00 D
Rule Test 1990 only - Oct 1 2:00 0 S
Zone Test/Zone 1:00 Test C%sT
"""

#: The start of each line zdump -v prints for one zone.
ZONE = "Europe/Amsterdam  "


def _line(utc: str, local: str, offset: int) -> str:
    """Return a line of zdump -v for a time it converted: UT, local time, offset."""
    return f"{ZONE}{utc} UT = {local} isdst=0 gmtoff={offset}"


#: zdump -v lines in the form glibc's zdump prints them: two times it
#: cannot convert, a spring forward and a fall back of 1937, a change of
#: the daylight-saving flag alone, and the last time it can represent.
LISTING = "\n".join(
    [
        f"{ZONE}-9223372036854775808 (gmtime failed) = "
        "-9223372036854775808 (localtime failed)",
        f"{ZONE}-67768040609741850 (gmtime failed) = "
        "Thu Jan  1 00:00:00 -2147481748 LMT isdst=0 gmtoff=1050",
        _line("Sun Apr  4 01:59:59 1937", "Sun Apr  4 01:59:59 1937 WET", 0),
        _line("Sun Apr  4 02:00:00 1937", "Sun Apr  4 03:00:00 1937 WEST", 3600),
        _line("Sun Oct  3 01:59:59 1937", "Sun Oct  3 02:59:59 1937 WEST", 3600),
        _line("Sun Oct  3 02:00:00 1937", "Sun Oct  3 02:00:00 1937 WET", 0),
        _line("Sun Oct 27 01:59:59 1968", "Sun Oct 27 02:59:59 1968 BST", 3600),
        _line("Sun Oct 27 02:00:00 1968", "Sun Oct 27 03:00:00 1968 BST", 3600),
        _line(
            "Wed Dec 31 22:59:59 2147485547", "Wed Dec 31 23:59:59 2147485547 CET", 3600
        ),
        f"{ZONE}Wed Dec 31 23:00:00 2147485547 UT = "
        "67768036191673200 (localtime failed)",
    ]
)


def _at(year: int, month: int, day: int, hour: int) -> int:
    """Return the seconds since the epoch of a UTC hour."""
    return calendar.timegm((year, month, day, hour, 0, 0))


@final
class ListingTest(unittest.TestCase):
    """What the tool reads from a zone's zdump -v listing."""

    def test_a_line_with_no_convertible_time_is_skipped(self) -> None:
        """Only lines with a UT time and an offset inside the years are read."""
        self.assertEqual(len(readings(LISTING)), 6)

    def test_each_transition_that_changes_the_offset_is_a_change(self) -> None:
        """The flag-only transition of 1968 changes no offset."""
        self.assertEqual(
            changes(LISTING),
            [(_at(1937, 4, 4, 2), 0, 3600), (_at(1937, 10, 3, 2), 3600, 0)],
        )

    def test_a_change_outside_the_years_is_left_out(self) -> None:
        """The table stops at the start of its last year."""
        late = (
            "Z  Thu Dec 31 23:59:59 2099 UT = x isdst=0 gmtoff=0\n"
            "Z  Fri Jan  1 00:00:00 2100 UT = x isdst=0 gmtoff=3600\n"
        )
        self.assertEqual(changes(late), [])

    def test_two_readings_that_are_not_one_second_apart_are_no_change(self) -> None:
        """A change is the last second of an offset and the first of the next."""
        apart = (
            "Z  Sun Apr  4 01:59:58 1937 UT = x isdst=0 gmtoff=0\n"
            "Z  Sun Apr  4 02:00:00 1937 UT = x isdst=1 gmtoff=3600\n"
        )
        self.assertEqual(changes(apart), [])


@final
class TableTest(unittest.TestCase):
    """The file the tool writes, and the file the definition contains."""

    def test_the_rendered_table_reads_back(self) -> None:
        """One change per line is still JSON."""
        table = {"UTC": [], "Z": [(1, 0, 3600), (2, 3600, 0)]}
        self.assertEqual(
            json.loads(render(table)),
            {
                "release": RELEASE,
                "sha512": SHA512,
                "from": FROM_YEAR,
                "until": UNTIL_YEAR,
                "zones": [
                    {"name": "UTC", "changes": []},
                    {"name": "Z", "changes": [[1, 0, 3600], [2, 3600, 0]]},
                ],
            },
        )

    def test_the_definitions_table_is_the_tools(self) -> None:
        """The file states the release, the years and the zones the tool states."""
        table = json.loads((ROOT / "spec" / "zones.json").read_text())
        self.assertEqual(table["release"], RELEASE)
        self.assertEqual(table["sha512"], SHA512)
        self.assertEqual((table["from"], table["until"]), (FROM_YEAR, UNTIL_YEAR))
        self.assertEqual([zone["name"] for zone in table["zones"]], list(ZONES))


@final
class ReleaseTest(unittest.TestCase):
    """Fetching, compiling and listing a release that the test writes itself.

    zic and zdump are the system's, as they are when the tool runs.
    """

    #: A scratch directory for the release and what the tool makes of it.
    scratch: Path

    @override
    def setUp(self) -> None:
        """Make a scratch directory."""
        self.scratch = Path(tempfile.mkdtemp(prefix="zones-"))
        self.addCleanup(shutil.rmtree, self.scratch, ignore_errors=True)

    def tarball(self, sources: dict[str, str]) -> Path:
        """Write a release whose source files hold sources, and the rest nothing."""
        target = self.scratch / "release.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            for name in SOURCES:
                data = sources.get(name, "").encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return target

    def test_a_release_whose_digest_matches_is_kept(self) -> None:
        """The download is the file the URL names."""
        release = self.tarball({})
        digest = hashlib.sha512(release.read_bytes()).hexdigest()
        directory = self.scratch / "download"
        directory.mkdir()
        with (
            mock.patch.object(zones, "URL", release.as_uri()),
            mock.patch.object(zones, "SHA512", digest),
        ):
            fetched = zones.fetch(directory)
        self.assertEqual(fetched.read_bytes(), release.read_bytes())

    def test_a_release_whose_digest_differs_is_refused(self) -> None:
        """The pinned digest is not the digest of another file."""
        release = self.tarball({})
        with (
            mock.patch.object(zones, "URL", release.as_uri()),
            self.assertRaisesRegex(ZonesError, "has SHA-512"),
        ):
            zones.fetch(self.scratch)

    def test_a_compiled_zone_lists_its_offset_changes(self) -> None:
        """A spring forward at 01:00 UTC and a fall back at 00:00 UTC."""
        compiled = zones.compile_zones(
            self.tarball({"europe": SPRING_AND_FALL}), self.scratch
        )
        self.assertEqual(
            changes(zones.list_zone("Test/Zone", compiled)),
            [
                (calendar.timegm((1990, 4, 1, 1, 0, 0)), 3600, 7200),
                (calendar.timegm((1990, 10, 1, 0, 0, 0)), 7200, 3600),
            ],
        )

    def test_sources_that_zic_refuses_raise(self) -> None:
        """A zone line without its offset."""
        release = self.tarball({"europe": "Zone Broken\n"})
        with self.assertRaisesRegex(ZonesError, "zic: "):
            zones.compile_zones(release, self.scratch)

    def test_a_zone_the_release_lacks_raises(self) -> None:
        """The tool lists only zones the release compiles."""
        compiled = zones.compile_zones(
            self.tarball({"europe": SPRING_AND_FALL}), self.scratch
        )
        with self.assertRaisesRegex(ZonesError, "has no zone No/Such"):
            zones.list_zone("No/Such", compiled)

    def test_a_zdump_that_fails_raises(self) -> None:
        """A zdump that exits with an error stops the tool."""
        compiled = zones.compile_zones(
            self.tarball({"europe": SPRING_AND_FALL}), self.scratch
        )
        bin_dir = self.scratch / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "zdump"
        fake.write_text("#!/bin/sh\necho broken >&2\nexit 1\n")
        fake.chmod(0o755)
        path = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
        with (
            mock.patch.dict(os.environ, {"PATH": path}),
            self.assertRaisesRegex(ZonesError, "zdump Test/Zone: broken"),
        ):
            zones.list_zone("Test/Zone", compiled)

    def test_the_tool_writes_the_table_of_the_release_it_fetched(self) -> None:
        """One zone with two changes, written under the tool's root."""
        release = self.tarball({"europe": SPRING_AND_FALL})
        (self.scratch / "root" / "spec").mkdir(parents=True)
        printed = io.StringIO()

        def fetch(directory: Path) -> Path:
            del directory
            return release

        with (
            mock.patch.object(zones, "fetch", fetch),
            mock.patch.object(zones, "ZONES", ("Test/Zone",)),
            mock.patch.object(zones, "ROOT", self.scratch / "root"),
            contextlib.redirect_stdout(printed),
        ):
            self.assertEqual(zones.main(), 0)
        table = json.loads((self.scratch / "root" / "spec" / "zones.json").read_text())
        self.assertEqual([zone["name"] for zone in table["zones"]], ["Test/Zone"])
        self.assertEqual(len(table["zones"][0]["changes"]), 2)
        self.assertIn("2 offset changes in 1 zones", printed.getvalue())
