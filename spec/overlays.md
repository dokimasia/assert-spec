# Overlays

Every assertion in the set is required. No assertion is marked
optional, because marking one optional makes a language that cannot
supply it look identical to a language whose author ran out of time.

An overlay is where a language says which of those two it is.

```json
{
  "extends": "spec://assertions@1.0.0",
  "language": "php",
  "diverge": [
    {
      "id": "bench-max-allocs",
      "stance": "blocked",
      "why": "PHP exposes no per-iteration allocation counter",
      "remedy": "none known"
    }
  ]
}
```

One file per language, named for the language, in `overlays/`. A
language with nothing to declare still carries a file with an empty
`diverge`, so full compliance is something someone stated rather than
something nobody checked.

| Key | Meaning |
|---|---|
| `extends` | `spec://assertions@<version>`, the version this overlay was written against |
| `language` | The language, matching both the filename and a column in the naming table |
| `diverge` | Every assertion this language does not supply |

A divergence carries `id`, `stance` and `why`. `remedy` is optional and
says what would close the gap.

## Limits

A divergence says an assertion is absent. A limit says it is there and
there is a case it cannot see, which is a different thing and worth
telling apart.

```json
"limits": [
  {
    "id": "no-task-leaks",
    "what": "Sees platform threads. A leaked virtual thread is not reported.",
    "why": "Virtual threads appear in no standard enumeration on any JVM version."
  }
]
```

`what` is written for someone deciding whether to rely on the check:
say what it does see, then what it does not. An assertion cannot be
both diverged from and limited, because a divergence has to be absent
and a limit has to be present.

`why` is the whole point. A gap nobody could close and a gap nobody got
to look the same from outside, and only the reason tells them apart.
Write it for someone deciding whether to depend on the library.

## What the gate does with one

An assertion missing with no matching entry fails the build. An entry
naming an assertion the library does implement fails the build too, so a
library cannot claim a gap it does not have.

`extends` pins the version. An overlay left behind by a change to the
standard fails validation rather than passing quietly.

The stance vocabulary is not closed. `blocked` is the one in use.
