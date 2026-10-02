#!/usr/bin/env sh
# Hold the vendored copy of the definition to two questions.
#
# Is it intact? Every file is compared against the manifest vendored
# beside it, the overlay included, and the manifest's own digest against
# the files it lists. A hand-edited or half-copied file fails, offline.
#
# Does it match upstream? The manifest at the pinned ref is fetched and
# the digests compared. This reports by default, because an
# implementation is allowed to lag a change while it catches up.
#
# Pass --strict to make a difference fail. CI uses that on a change that
# touches the vendored copy: falling behind is fine, and committing a
# copy that matches nothing anyone else has is not. Under --strict, an
# upstream that cannot be read fails too, because the comparison the
# flag asks for did not happen.
#
# Exit status: 0 when the checks pass, 1 when the copy is not intact or,
# under --strict, differs from upstream, and 3 when --strict cannot read
# upstream.
#
# SPEC_REF names the ref to compare against, main by default. SPEC_RAW
# replaces the whole base URL, such as a file:// URL of a checkout, so a
# test can run the comparison offline.
set -eu

STRICT=0
DEST=""
for arg in "$@"; do
    case "$arg" in
        --strict) STRICT=1 ;;
        *) if [ -z "$DEST" ]; then DEST=$arg; fi ;;
    esac
done
[ -n "$DEST" ] || { echo "usage: spec-check.sh <vendored directory> [--strict]"; exit 2; }
REF=${SPEC_REF:-main}
RAW=${SPEC_RAW:-https://raw.githubusercontent.com/dokimasia/assert-spec/$REF}

python3 - "$DEST" "$(dirname "$0")" <<'PY_INNER'
import hashlib, json, pathlib, sys

dest = pathlib.Path(sys.argv[1])
tools = pathlib.Path(sys.argv[2])
manifest = json.loads((dest / "manifest.json").read_text())
files = manifest["files"]

# The overlay of one language is vendored as overlay.json. The language it
# declares names the manifest entry that applies to it.
overlay = dest / "overlay.json"
language = json.loads(overlay.read_text()).get("language") if overlay.exists() else None

def local(name):
    if name.startswith("corpus/"):
        return dest / name
    if name.startswith("overlays/"):
        return overlay if name == f"overlays/{language}.json" else None
    if name.startswith("tools/"):
        return tools / pathlib.Path(name).name
    return dest / pathlib.Path(name).name

problems = []
if language is not None and f"overlays/{language}.json" not in files:
    problems.append(f"overlay.json declares {language!r}, and the manifest lists no overlay for it")

joined = "".join(f"{name} {sha}\n" for name, sha in sorted(files.items()))
if "sha256:" + hashlib.sha256(joined.encode()).hexdigest() != manifest["digest"]:
    problems.append("the manifest's digest is not the digest of the files it lists")

checked, wrong, missing = 0, [], []
for name, want in sorted(files.items()):
    path = local(name)
    if path is None:
        continue
    if not path.exists():
        missing.append(name)
        continue
    got = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    checked += 1
    if got != want:
        wrong.append(name)

if missing:
    problems.append("vendored copy is missing " + ", ".join(missing))
if wrong:
    problems.append("these do not match the manifest beside them: " + ", ".join(wrong))
for problem in problems:
    print("spec: " + problem)
if problems:
    raise SystemExit(1)

print(f"spec: {checked} files intact at {manifest['version']} {manifest['digest'][:19]}")
PY_INNER

mine=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["digest"])' "$DEST/manifest.json")
theirs=$(curl -fsSL --max-time 20 "$RAW/spec/manifest.json" 2>/dev/null \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["digest"])' 2>/dev/null) || theirs=""

if [ -z "$theirs" ]; then
    echo "spec: could not reach $REF, so it was not compared"
    if [ "$STRICT" = "1" ]; then
        echo "spec: this change touches the vendored copy, so it has to be compared"
        exit 3
    fi
    exit 0
fi

if [ "$mine" = "$theirs" ]; then
    echo "spec: matches $REF"
    exit 0
fi

# Behind, ahead, or taken from a checkout nobody pushed. One fetch
# cannot tell those apart, so it prints both digests.
echo "spec: differs from $REF"
echo "  vendored $mine"
echo "  upstream $theirs"
echo "  run: ./tools/spec-sync.sh $DEST <language>"

if [ "$STRICT" = "1" ]; then
    echo "spec: this change touches the vendored copy, so it has to match"
    exit 1
fi
