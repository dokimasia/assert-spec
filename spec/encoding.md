# The typed-literal encoding

A corpus case states its values in a language-neutral form. Each
library turns them into native values.

A value is an object with a `type` key.

| `type` | Extra keys | Go value |
|---|---|---|
| `null` | | `nil` |
| `bool` | `value` | `bool` |
| `int` | `value` | `int` |
| `float` | `value` | `float64` |
| `string` | `value` | `string` |
| `bytes` | `value`, in lowercase hexadecimal | `[]byte` |
| `list` | `of`, `value` | `[]T` |
| `list` | `items`, a list of typed literals | `[]any` |
| `map` | `key`, `of`, `value` | `map[K]V` |
| `map` | `entries`, a list of key and value literal pairs | `map[K]V` |
| `record` | `fields`, a list of name and value literal pairs | The value `prop.OfShape` decodes |
| `variant` | `name`, and `payload` when the variant has one | The value `prop.OfShape` decodes |

`of` and `key` name a scalar type: `bool`, `int`, `float`, `string`.

A `list` states `of` and `value` when its elements share one scalar
type, and `items` otherwise, such as for a list of lists or of byte
strings. A `map` with `key`, `of` and `value` has string keys, because
the keys of a JSON object are strings. A `map` with `entries` has keys
of any type, listed in the order the map produced them.

A `list` whose `value` is `[]` is an empty list, and does not equal
`null`. The `equal/null-against-empty-list` case pins that.

A `list` with `of` and a `value` of `null` is an absent list of that
type, and a `map` with `key`, `of` and a `value` of `null` is an absent
map. Go decodes them to a nil slice and a nil map of the stated types,
and a language without typed absence decodes them to its null. The
`equate-empty` cases compare an absent container with an empty one of
the same type through this form.

An `int` within ±(2^53 − 1) is a JSON number. A larger one is a decimal
string, such as `"18446744073709551615"`, because a JavaScript reader
rounds a larger JSON number.

JSON has no NaN or infinity. A `float` accepts the strings `NaN`,
`Inf` and `-Inf` in place of a number.

Both rules apply to the elements of a `value` list and to the values of
a `value` map, as they apply to a scalar on its own.

A `record` states its fields in declaration order, and names each field
once. Two records are equal when their fields are equal, in order.
Field order decides which choices a field consumes, so a `map`, whose
entries compare in any order, cannot state a record.

A `variant` is one variant of an enum. It states its `name`, and its
`payload` literal when the variant has a payload. A variant without a
payload states no `payload` key. A variant whose payload is optional
and absent states a `null` payload, so the two differ.

## Opaque values

The detail of a call record, which `recording.md` states, can contain a
value of any type, and the typed literals state data alone. A call
record states every other value as an opaque literal:

```json
{ "type": "opaque", "text": "func(int) bool" }
```

`text` is the language's own rendering of the value, as its failure
sentence prints it. A function, a channel, a cancellation handle and an
error value are opaque. A value whose literal would nest more than 61
levels is opaque too: the store bounds an entry at 64 levels, which
leaves 61 to the value of a draw. A reader shows an opaque value and
does not compare it. A corpus case never states one.

## Options

A case of an assertion that accepts relaxations may name them:

```json
"options": ["equate-nans"]
```

Each option is the id of a relaxation that the assertion accepts, named
once. The runner passes each as the language's relaxation for this call.
A case whose options name a relaxation that a language's overlay
declines does not apply to that language, as a declared skip does not.

## Skips

A case that a language cannot express states a reason:

```json
"skip": { "go": "a type mismatch is a compile error under generics" }
```

A skip is a claim. People read the reason.
