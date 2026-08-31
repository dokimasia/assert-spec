# The failure record

A failing assertion reports a record, not a sentence. The record is the
same shape in every language; the sentence a person reads is rendered
from it and is not standardised.

## The record

| Field | Holds |
|---|---|
| `assertion` | The canonical id, as `assertions.json` names it |
| `contract` | The caller's message, unchanged |
| `detail` | The values named by that assertion's `detail_fields` |
| `where` | The file and line the assertion was called from |

`contract` is exactly what the caller passed. `detail` carries every
field the assertion declares and no others, so a reader that knows the
assertion knows the keys without inspecting them.

```json
{
  "assertion": "equal",
  "contract": "the count is right",
  "detail": { "want": 2, "got": 1 },
  "where": { "file": "store_test.go", "line": 42 }
}
```

`where` is optional. A language supplies it when it can do so without a
cost the standard should not impose: Rust from `#[track_caller]`, Go
from the runtime, Python from the frame. A language that cannot omits
it, and no conformance check requires it.

## What the fields mean

`got` is what the assertion observed. `want` is what it required. An
assertion whose failure holds neither states no fields, and `true`,
`false` and `rejects` are of that kind: the contract is the whole
report.

Where those two names would mislead, the assertion names its values
directly. `contains` carries `haystack` and `needle`, `in-range`
carries `got`, `low` and `high`, and `pairwise` carries the `index` of
the failing pair with the `first` and `second` items in it.

## What a corpus case states

A case expecting a failure states the detail it expects, using the
typed-literal encoding the arguments already use:

```json
{
  "id": "equal/differing-ints",
  "args": [ {"type": "int", "value": 1}, {"type": "int", "value": 2} ],
  "expect": "fail",
  "detail": { "want": {"type": "int", "value": 2},
              "got":  {"type": "int", "value": 1} }
}
```

Typed literals keep an int and a float apart, so a case cannot be
satisfied by a value of the wrong type that renders alike.

A case states the fields it cares about. What it states must match;
what it omits is not checked. Every key a case states must be one the
assertion declares, which the validator enforces.

## Rendering

A record renders to the sentence a person reads:

```text
the count is right: want 2, got 1
```

The rendering is per-language. A Go developer and a Python developer
read different conventions, and the standard fixes the record behind
the sentence rather than the sentence.
