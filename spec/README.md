# The definition

`assertions.yaml` and `naming.yaml` are the definition. People edit
those.

`assertions.json` and `naming.json` are rendered from them and
committed. They are what an implementation reads: every target language
parses JSON from its standard library, and several would otherwise take
a dependency to read the definition at all.

Re-render after editing:

    make render

## Quoting

Every id and every name is quoted. YAML reads an unquoted `true`,
`false`, `yes`, `no`, `on` or `off` as a boolean, and four of those are
assertion ids or Go identifiers here. Quoting all of them is one rule
rather than a list of exceptions to remember.

## What the corpus covers

A case states its arguments as typed literals, so it covers only
assertions whose arguments cross a language boundary as data. That is
17 of the 41.

The other 24 take a callable, a cancellation handle, a predicate, a
golden file or a benchmark. None of those is data, so each language
tests them itself, and the completeness gate checks only that they are
present. An implementation is held to the standard on meaning where
meaning can be stated, and on membership everywhere else.
