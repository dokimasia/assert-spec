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

Rendering adds an entry to `assertions.json` and a row to `naming.json`
for each property form, by the rule that each table states in its
`forms` section. Nobody edits a form's entry by hand.

`zones.json` states the zone list and every offset change of its zones
from 1900 to 2100, computed from one tzdata release. `make zones`
recomputes it, and needs the network, `zic` and `zdump`.

## Quoting

Every id and every name is quoted. YAML reads an unquoted `true`,
`false`, `yes`, `no`, `on` or `off` as a boolean, and four of those are
assertion ids or Go identifiers here. One rule for every string is
simpler than a list of exceptions.

## Corpus coverage by assertion

A case states its arguments as typed literals, or names a subject from a
small vocabulary that each implementation builds natively. 39 of the 61
assertions have corpus cases:

- 18 take data.
- 21 take a callable that a subject describes.

The other 22 take an error value, a predicate, a callable that no
subject describes, a golden file, a benchmark, a property's body, a
model or a recorded history. Each language tests them itself, and the
completeness gate checks only that they are present. The standard checks
an implementation's meaning where a case can state it, and its membership
everywhere else.

The engine behind `prop-for-all` is data in and data out, so the vectors
under `corpus/prop/` pin the decoding of every generator, the generation
from a seed, the shrinking, the coverage test, the fuzz bridge, the
replay token, the detail of a run, and the store's entries, file names
and verdicts. They also pin the values each shape generates, the
choices that produce a value, the shape each fixture type reads as, the
case that known draws state, a passing and a failing run of each
property form, and the call records of a property's runs.
`prop-max-allocs` and `prop-max-allocs-with-setup` have no vector,
because no case can state an allocation count. People write each vector's inputs in
`corpus/prop/<kind>.yaml`. `make render` computes the outputs with the
executable reference in `tools/prop/` and writes the JSON beside them.

The history and the checkers behind `linearizable`, `serializable` and
`snapshot-isolation` are data in and data out as well. The vectors under
`corpus/history/` pin the events that a script or a list of intervals
records, the entry that the history refuses, and the verdict, the steps
and the record of a check. A vector of `linearizable` names a model from
the `models` section of `assertions.yaml`, as a case names a subject, and
each implementation builds every named model natively. A vector of an
isolation level states a history of list-append transactions, and every
history appears once at each level. People write the inputs in
`corpus/history/<kind>.yaml`, and `make render` computes the outputs with
the executable reference in `tools/history/`.

The steps of a machine and the task scheduler are data in and data out
too. A vector under `corpus/stateful/` names a machine subject from the
`machines` section of `assertions.yaml`, and each implementation builds
every machine subject natively: the subject, its machine, its draws and
its model. The vectors pin the detail of a run of each subject, the
minimal steps of each fault, the traces that a run follows or refuses,
and the label and the step that a divergence names. People write the inputs in `corpus/stateful/machines.yaml`, and
`make render` computes the outputs with the executable reference in
`tools/stateful/`.
