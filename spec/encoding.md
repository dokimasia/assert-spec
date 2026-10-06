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
| `tree` | `entries`, a list of entries in path order | `files.Tree` |
| `reference` | `id`, and `value`, the literal of the object's value | A pointer to the value |

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

## Trees

A `tree` states a tree of files: entries at paths relative to the tree's
root, each a file, a directory or a symbolic link.

```json
{
  "type": "tree",
  "entries": [
    { "path": "bin/run", "text": "#!/bin/sh\necho ok\n", "executable": true },
    { "path": "cache", "directory": true },
    { "path": "current", "link": "bin/run" },
    { "path": "keys", "directory": true, "mode": 448 },
    { "path": "keys/id", "text": "secret\n", "mode": 384 },
    { "path": "logo.png", "bytes": "89504e470d0a1a0a" }
  ]
}
```

- A path is one or more names joined by `/`. A name is not empty, `.` or
  `..`, and contains no `\` and no NUL.
- `entries` lists each path once, in the order of the bytes of its UTF-8.
- An entry states `path` and exactly one of `text`, `bytes`, `directory`
  and `link`. `text` states a file's content as UTF-8 text, and `bytes`
  states it in lowercase hexadecimal. `directory` is `true`, and `link`
  states a link's target, as text of any form.
- A file may state `executable`, which is false when absent.
- A file or a directory may state `mode`, its nine permission bits as an
  integer from 0 to 511: 448 is `0o700` and 384 is `0o600`. A file that
  states a mode states no `executable`, because the mode states the
  execute bit. A link has no mode.
- Every parent of an entry is a directory of the tree, stated or not. A
  file and a link have no entries, so no entry is below one.

A record states a file whose content is longer than 65,536 bytes by
`digest` and `size` in place of `text` or `bytes`. `digest` is `sha256:`
and 64 lowercase hexadecimal digits, and `size` is the number of bytes. A
case states the content of every file it writes, so only a record states
this form.

## References

A `reference` states one object of a case: its `id`, and the literal of
the object's value.

```json
{ "type": "reference", "id": "a", "value": { "type": "int", "value": 1 } }
```

- Within one case, every `reference` of one `id` is one object, and each
  states the same value. A runner decodes the first literal of an id to a
  new object of the value, and each later literal of the id to that
  object.
- The value is not `null`, because a reference refers to an object.
- A record states a reference by the literal of its value. The record is
  kept after the objects of its run are gone.

`by-identity` compares two references by the objects that they refer to.
Each language states what a reference is, and when two references refer
to the same object:

| Language | References | The same object |
|---|---|---|
| Go | Pointers, maps, slices, channels and functions | The same address. Two slices are the same object when they start at the same address and have the same length |
| Python | Every object but `None`, a `bool`, an `int`, a `float`, a `str`, `bytes` and a `tuple`, whose items compare one by one | `is` |
| Java, Kotlin | Every object but a `String` and the box of a primitive | `==` in Java, `===` in Kotlin |
| TypeScript | Objects, arrays and functions | `===` |

A value that is no reference compares as it compares without
`by-identity`. Rust's overlay declines the modifier.

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
