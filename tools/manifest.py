#!/usr/bin/env python3
"""List every file an implementation vendors, with a digest of each.

An implementation keeps its own copy of the definition so its build
fails on its own without reaching the network. What it cannot tell from
a copy alone is whether the copy is current, and the version does not
answer that: adding the relaxations changed the definition without
changing the version, and by this repository's own rule it should not
have.

So the manifest carries a digest of the bytes rather than a version of
the meaning. An implementation compares its own copy against the digest
it vendored to catch a corrupted or hand-edited copy, and compares that
digest against this file upstream to learn whether it has fallen behind.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: What an implementation copies. Anything an implementation reads
#: belongs here, or a change to it is a change nothing can detect.
VENDORED = (
    "VERSION",
    "spec/assertions.json",
    "spec/naming.json",
    # The sync tooling itself. Five copies of a script drift exactly the
    # way five copies of the definition did, so the scripts are vendored
    # from here and held to the same digest as everything else.
    "tools/spec-sync.sh",
    "tools/spec-check.sh",
)


def digest(path: Path) -> str:
    """The sha256 of one file, as it sits on disk."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def files() -> dict[str, str]:
    """Every vendored file, by repository-relative path."""
    found = {name: digest(ROOT / name) for name in VENDORED}
    for group in ("corpus", "overlays"):
        for path in sorted((ROOT / group).glob("*.json")):
            found[str(path.relative_to(ROOT))] = digest(path)
    return found


def build() -> dict[str, object]:
    """The manifest, including a digest over the whole set.

    The set digest is taken over the sorted `path sha` lines rather than
    over the files themselves, so it does not depend on the order they
    were read in and a reader can recompute it without the files.
    """
    listed = files()
    joined = "".join(f"{name} {sha}\n" for name, sha in sorted(listed.items()))
    return {
        "version": (ROOT / "VERSION").read_text().strip(),
        "digest": "sha256:" + hashlib.sha256(joined.encode()).hexdigest(),
        "files": listed,
    }


def main() -> int:
    """Write the manifest, and say whether it changed."""
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
