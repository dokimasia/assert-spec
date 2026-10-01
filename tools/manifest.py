#!/usr/bin/env python3
"""List every file an implementation vendors, with a digest of each.

An implementation keeps its own copy of the definition, so its build
runs without network access. The version does not identify a copy's
bytes, so the manifest lists a digest of each file. An implementation
compares its copy with the digests it vendored to detect a corrupted or
hand-edited copy. It compares those digests with this file upstream to
detect that its copy is behind.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: What an implementation copies. A file an implementation reads and this
#: list omits can change without any check detecting it.
VENDORED = (
    "VERSION",
    "spec/assertions.json",
    "spec/naming.json",
    # The sync scripts are vendored with the definition and held to the
    # same digests, so that every implementation runs the same copy.
    "tools/spec-sync.sh",
    "tools/spec-check.sh",
)

#: The files listed by pattern: the corpus at any depth, and every overlay.
GLOBS = ("corpus/**/*.json", "overlays/*.json")


def digest(path: Path) -> str:
    """Return the sha256 of one file's bytes on disk."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def files() -> dict[str, str]:
    """Return every vendored file's digest, by repository-relative path."""
    found = {name: digest(ROOT / name) for name in VENDORED}
    for pattern in GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            found[path.relative_to(ROOT).as_posix()] = digest(path)
    return found


def build() -> dict[str, object]:
    """Return the manifest, including a digest over the whole set.

    The set digest is taken over the sorted `path sha` lines, so it does
    not depend on the order the files were read in, and a reader can
    recompute it without the files.
    """
    listed = files()
    joined = "".join(f"{name} {sha}\n" for name, sha in sorted(listed.items()))
    return {
        "version": (ROOT / "VERSION").read_text().strip(),
        "digest": "sha256:" + hashlib.sha256(joined.encode()).hexdigest(),
        "files": listed,
    }


def main() -> int:
    """Write the manifest, and print whether it changed."""
    target = ROOT / "spec" / "manifest.json"
    rendered = json.dumps(build(), indent=4, sort_keys=True) + "\n"

    if target.exists() and target.read_text() == rendered:
        print("spec/manifest.json: unchanged")
        return 0

    if "--check" in sys.argv:
        print("spec/manifest.json: stale; run make manifest and commit")
        return 1

    target.write_text(rendered)
    print("spec/manifest.json: written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
