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
