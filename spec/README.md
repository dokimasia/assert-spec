# The definition

People edit `assertions.yaml` and `naming.yaml`, which are the
definition.

`make render` writes `assertions.json` and `naming.json` from them, and
both are committed. An implementation reads the JSON: every target
language parses JSON with its standard library, and none of them has a
YAML parser there.

Re-render after editing:

```sh
make render
```

## Quoting

Every id and every name is quoted. YAML reads an unquoted `true`,
`false`, `yes`, `no`, `on` or `off` as a boolean, and four of those are
assertion ids or Go identifiers here. One rule for every string is
simpler than a list of exceptions.

## Corpus coverage by assertion

A case states its arguments as typed literals, or names a subject from a
small vocabulary that each implementation builds natively. 25 of the 43
assertions have corpus cases:

- 17 take data.
- 8 take a callable that a subject describes.

The other 18 take an error value, a predicate, a callable that no
subject describes, a golden file, a benchmark or a property's body. Each
language tests them itself, and the completeness gate checks only that
they are present. The standard checks an implementation's meaning where
a case can state it, and its membership everywhere else.

The engine behind `prop-for-all` is data in and data out, so the vectors
under `corpus/prop/` pin the decoding of every generator, the generation
from a seed, the shrinking, the coverage test, the fuzz bridge, the
replay token, the detail of a run, and the store's entries, file names
and verdicts. People write each vector's inputs
in `corpus/prop/<kind>.yaml`. `make render` computes the outputs with
the executable reference in `tools/prop/` and writes the JSON beside
them.
