#!/usr/bin/env sh
# Refresh the vendored copy of the definition.
#
# The script fetches a pinned ref, so the same command copies the same
# files on a laptop and on a runner. A copy taken from an uncommitted
# sibling checkout matches the manifest beside it and matches no copy on
# any other machine.
#
# SPEC_LOCAL takes a sibling checkout instead, to try a change before it
# is pushed. The script prints a warning, because no other machine can
# reproduce the copy it leaves.
set -eu

DEST=${1:?usage: spec-sync.sh <destination directory> [overlay language]}
LANG=${2:-}
REF=${SPEC_REF:-main}
RAW="https://raw.githubusercontent.com/dokimasia/assert-spec/$REF"

FILES="VERSION spec/assertions.json spec/naming.json spec/manifest.json"

fetch() {
    # $1 repository-relative path, $2 the destination file
    if [ -n "${SPEC_LOCAL:-}" ]; then
        cp "$SPEC_LOCAL/$1" "$2"
    else
        curl -fsSL "$RAW/$1" -o "$2"
    fi
}

if [ -n "${SPEC_LOCAL:-}" ]; then
    echo "spec: taking $SPEC_LOCAL, not $REF"
    echo "spec: the copy this leaves is reproducible nowhere else; do not commit it"
fi

mkdir -p "$DEST/corpus"

for f in $FILES; do
    fetch "$f" "$DEST/$(basename "$f")"
done

if [ -n "$LANG" ]; then
    fetch "overlays/$LANG.json" "$DEST/overlay.json"
fi

# The manifest lists the corpus, so a corpus file the definition dropped
# is deleted here and not kept by a glob. A corpus file may sit in a
# subdirectory, such as corpus/prop/.
names=$(python3 -c "
import json
m = json.load(open('$DEST/manifest.json'))
print(' '.join(n[len('corpus/'):-len('.json')] for n in m['files'] if n.startswith('corpus/')))")

find "$DEST/corpus" -type f -name '*.json' -delete
for name in $names; do
    mkdir -p "$(dirname "$DEST/corpus/$name.json")"
    fetch "corpus/$name.json" "$DEST/corpus/$name.json"
done

# The scripts are vendored with the definition, so every implementation
# runs the same copy. Each is renamed into place, so the copy running
# now is never written through.
TOOLS=$(dirname "$0")
for script in spec-sync.sh spec-check.sh; do
    fetch "tools/$script" "$TOOLS/$script.new"
    chmod +x "$TOOLS/$script.new"
    mv "$TOOLS/$script.new" "$TOOLS/$script"
done

[ -n "${SPEC_LOCAL:-}" ] || echo "spec: fetched $REF"
exec "$(dirname "$0")/spec-check.sh" "$DEST"
