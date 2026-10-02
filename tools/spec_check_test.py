#!/usr/bin/env python3
"""spec-check.sh, run against vendored copies it must refuse.

A check that only ever sees an intact copy passes with every rule deleted.
Each case vendors this repository's definition into a scratch directory as
spec-sync.sh does, breaks the copy one way, and requires the script to
report it. Upstream is this checkout, read through a file:// URL, so no
case needs the network.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, final, override

ROOT = Path(__file__).resolve().parent.parent

#: The language whose overlay each scratch copy vendors.
LANGUAGE = "go"

#: The corpus file the cases edit.
EDITED = "corpus/in-range.json"


def _digest(data: bytes) -> str:
    """Return the manifest's spelling of the sha256 of data."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _set_digest(files: dict[str, str]) -> str:
    """Return the digest over the sorted `path sha` lines of files."""
    joined = "".join(f"{name} {sha}\n" for name, sha in sorted(files.items()))
    return _digest(joined.encode())


@final
class SpecCheck(unittest.TestCase):
    """Each case vendors the definition, breaks the copy, and runs the check."""

    #: The scratch directory: tools/ contains the scripts and spec/ the copy.
    tree: Path
    #: The vendored copy.
    dest: Path

    @override
    def setUp(self) -> None:
        """Vendor the definition and the scripts as spec-sync.sh does."""
        self.tree = Path(tempfile.mkdtemp(prefix="spec-check-"))
        self.addCleanup(shutil.rmtree, self.tree, ignore_errors=True)
        (self.tree / "tools").mkdir()
        for script in ("spec-check.sh", "spec-sync.sh"):
            shutil.copy2(ROOT / "tools" / script, self.tree / "tools" / script)
        self.dest = self.tree / "spec"
        manifest = json.loads((ROOT / "spec" / "manifest.json").read_text())
        for name in manifest["files"]:
            if name.startswith("tools/") or name.startswith("overlays/"):
                continue
            target = self.dest / (
                name if name.startswith("corpus/") else Path(name).name
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        shutil.copy2(ROOT / "spec" / "manifest.json", self.dest / "manifest.json")
        shutil.copy2(ROOT / "overlays" / f"{LANGUAGE}.json", self.dest / "overlay.json")

    def check(
        self, *args: str, raw: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the vendored script over the copy, against raw as upstream."""
        env = dict(os.environ, SPEC_RAW=raw or ROOT.as_uri())
        return subprocess.run(
            ["sh", str(self.tree / "tools" / "spec-check.sh"), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def manifest(self) -> Any:
        """Return the vendored manifest."""
        return json.loads((self.dest / "manifest.json").read_text())

    def write_manifest(self, manifest: Any) -> None:
        """Replace the vendored manifest."""
        (self.dest / "manifest.json").write_text(
            json.dumps(manifest, indent=4, sort_keys=True) + "\n"
        )

    def drop_a_case(self) -> None:
        """Remove the last case of the edited corpus file."""
        path = self.dest / EDITED
        document = json.loads(path.read_text())
        document["cases"].pop()
        path.write_text(json.dumps(document, indent=2) + "\n")

    def assert_fails(
        self, result: subprocess.CompletedProcess[str], status: int, phrase: str
    ) -> None:
        """Require the script to exit with status and to print phrase."""
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        self.assertIn(phrase, result.stdout)

    def test_an_intact_copy_passes(self) -> None:
        """The copy itself is intact, or every other case proves nothing."""
        result = self.check(str(self.dest), "--strict")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("files intact", result.stdout)
        self.assertIn("spec: matches", result.stdout)

    def test_the_flag_may_come_before_the_directory(self) -> None:
        """The arguments are read by what they are, not by where they are."""
        result = self.check("--strict", str(self.dest))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("spec: matches", result.stdout)

    def test_an_edited_file_is_caught(self) -> None:
        """A file that differs from its digest fails."""
        self.drop_a_case()
        self.assert_fails(self.check(str(self.dest)), 1, EDITED)

    def test_a_missing_file_is_caught(self) -> None:
        """A file the manifest lists and the copy lacks fails."""
        (self.dest / EDITED).unlink()
        self.assert_fails(self.check(str(self.dest)), 1, "is missing " + EDITED)

    def test_an_edited_overlay_is_caught(self) -> None:
        """The overlay must match the manifest entry of its language."""
        path = self.dest / "overlay.json"
        overlay = json.loads(path.read_text())
        overlay["limits"] = []
        path.write_text(json.dumps(overlay, indent=2))
        self.assert_fails(self.check(str(self.dest)), 1, f"overlays/{LANGUAGE}.json")

    def test_an_overlay_of_an_unlisted_language_is_caught(self) -> None:
        """An overlay whose language the manifest does not list fails."""
        path = self.dest / "overlay.json"
        overlay = json.loads(path.read_text())
        overlay["language"] = "cobol"
        path.write_text(json.dumps(overlay, indent=2))
        self.assert_fails(self.check(str(self.dest)), 1, "lists no overlay for it")

    def test_a_file_edited_with_its_digest_is_caught(self) -> None:
        """A file and its entry edited together leave the set digest stale."""
        self.drop_a_case()
        manifest = self.manifest()
        manifest["files"][EDITED] = _digest((self.dest / EDITED).read_bytes())
        self.write_manifest(manifest)
        self.assert_fails(
            self.check(str(self.dest), "--strict"),
            1,
            "the manifest's digest is not the digest of the files it lists",
        )

    def test_a_consistent_copy_that_differs_from_upstream(self) -> None:
        """Strict fails on a copy that matches no upstream; the default reports."""
        self.drop_a_case()
        manifest = self.manifest()
        manifest["files"][EDITED] = _digest((self.dest / EDITED).read_bytes())
        manifest["digest"] = _set_digest(manifest["files"])
        self.write_manifest(manifest)
        self.assert_fails(self.check(str(self.dest), "--strict"), 1, "differs from")
        lenient = self.check(str(self.dest))
        self.assertEqual(lenient.returncode, 0, lenient.stdout + lenient.stderr)
        self.assertIn("differs from", lenient.stdout)

    def test_an_unreachable_upstream_fails_strict(self) -> None:
        """Strict asks for a comparison, so a comparison that cannot run fails."""
        missing = (self.tree / "nowhere").as_uri()
        self.assert_fails(
            self.check(str(self.dest), "--strict", raw=missing), 3, "could not reach"
        )

    def test_an_unreachable_upstream_passes_by_default(self) -> None:
        """The default compares when it can, and reports when it could not."""
        missing = (self.tree / "nowhere").as_uri()
        result = self.check(str(self.dest), raw=missing)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("could not reach", result.stdout)

    def test_an_edited_script_is_caught(self) -> None:
        """The scripts are vendored with the definition and checked against it."""
        script = self.tree / "tools" / "spec-check.sh"
        script.write_text(script.read_text() + "\n# edited\n")
        self.assert_fails(self.check(str(self.dest)), 1, "tools/spec-check.sh")


if __name__ == "__main__":
    unittest.main()
