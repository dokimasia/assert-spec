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
| `list` | `of`, `value` | `[]T` |
| `map` | `key`, `of`, `value` | `map[K]V` |

`of` and `key` name a scalar type: `bool`, `int`, `float`, `string`.

A `list` whose `value` is `[]` is an empty list, and does not equal
`null`. The `equal/null-list-vs-empty-list` case pins that.

JSON has no NaN or infinity. A `float` accepts the strings `NaN`,
`Inf` and `-Inf` in place of a number.

## Skips

A case a language cannot express carries a reason:

```json
"skip": { "go": "a type mismatch is a compile error under generics" }
```

A skip is a claim. People read the reason.
