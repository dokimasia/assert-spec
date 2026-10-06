---
rfc: 0024
title: Accessors of the failure record
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-06
updated: 2026-10-06
discussion: https://github.com/dokimasia/assert-spec/issues/8
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0024: Accessors of the failure record

## Summary

`rejects` yields the failure records of the check that it drives, and a
caller reads from them why the check rejected its subject. The caller
reads each field of a record's detail by a name that it spells as a
string, and casts the value. A misspelt name reads as a missing value,
and the check then fails as if the subject had reported another one.

This proposal adds three members to the failure record:

- `want` returns the field `want` of the detail.
- `got` returns the field `got` of the detail.
- `case-failure` returns the failure record of the failing case, which
  the field `failure` of a property's detail contains.

Each member returns the value and whether the record's assertion
declares the field. Definition 6.0.0 adds the three members.

## Motivation

### A caller spells every field it reads

A conformance suite that proves each case rejects its mutant at the claim
that the mutant breaks reads two fields of the records that `rejects`
yields. In Go it pins both names as constants:

```go
const (
	// failureField is the field of a property's record that contains the
	// record of the failing case.
	failureField = "failure"
	// wantField is the field of a failure record that contains what the
	// assertion wanted.
	wantField = "want"
)
```

It then reads the fields through the detail map, with a type assertion
for the nested record:

```go
if inner, ok := failure.Detail[failureField].(assert.Failure); ok {
	failure = inner
}
assert.Equal(t, got[0].Detail[wantField], any(tt.want),
	"the case wants the error that the mutant does not return")
```

A misspelt name reads nil. The second assertion then fails, and its
message names the subject's value, not the misspelt name.

### The fields that the families share

The definition declares 44 detail field names over its 110 assertions.
`got`, `failure` and `want` appear across the families of assertions:

| Field | Assertions that declare it |
|---|---|
| `got` | 45 |
| `failure` | 40, every property assertion |
| `want` | 26 |

`want` and `got` are the values that an assertion compared. `failure` is
the record of a property's failing case, whose own `want` and `got` state
why the property failed.

## Detailed design

### The members

| Id | Returns |
|---|---|
| `failure.want` | The value of the detail's field `want`, and whether the record's assertion declares `want` |
| `failure.got` | The value of the detail's field `got`, and whether the record's assertion declares `got` |
| `failure.case-failure` | The failure record that the detail's field `failure` contains, and whether the field contains one |

A record's detail contains exactly the fields that its assertion
declares, so a field that the detail contains is a declared field. A
declared field can contain null, as `got` of an `equal` failure over a
null value does. `want` and `got` then return null and report the field
as declared.

`failure` contains the minimal case of a run that ended as
`counterexample`, and the case that the replay contradicted in a run that
ended as `flaky`. A run that ended as `rejected`, `coverage-unmet` or
`vacuous` states null. `case-failure` reports no record for such a run,
and none for an assertion that declares no `failure`.

### Absence in each language

Each language states an undeclared field in its own idiom, and keeps it
apart from a declared field whose value is null:

| Language | An undeclared field |
|---|---|
| Go | The second result is false |
| Python | The member raises `KeyError` |
| Rust | `None`, beside `Some` of a null value |
| TypeScript | `undefined`, beside `null` |
| Java, Kotlin | The member throws `NoSuchElementException` |

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `failure.want` | `Want` | `want` | `want` | `want` | `want` | `want` |
| `failure.got` | `Got` | `got` | `got` | `got` | `got` | `got` |
| `failure.case-failure` | `CaseFailure` | `case_failure` | `case_failure` | `caseFailure` | `caseFailure` | `caseFailure` |

The rows join the members of `failure` in the surface section of the
naming table, beside `assertion`, `contract` and `detail`. No language
declines them.

### Go

```go
// Want returns the field want of the record's detail, and whether the
// record's assertion declares want. A declared want can be nil.
//
// # Allocation contract
//
// Want allocates nothing.
func (f Failure) Want() (any, bool)

// Got returns the field got of the record's detail, and whether the
// record's assertion declares got. A declared got can be nil.
//
// # Allocation contract
//
// Got allocates nothing.
func (f Failure) Got() (any, bool)

// CaseFailure returns the failure record of the failing case, which the
// field failure of a property's record contains, and whether the record
// contains one. A record of an assertion that declares no failure, and a
// property's record whose failure is nil, contain none.
//
// # Allocation contract
//
// CaseFailure allocates nothing.
func (f Failure) CaseFailure() (Failure, bool)
```

`assert.Failure` and `expect.Failure` are aliases of one type, so the
three methods serve both surfaces. The reads of the motivation become:

```go
if inner, ok := failure.CaseFailure(); ok {
	failure = inner
}
want, _ := got[0].Want()
assert.Equal(t, want, any(tt.want), "the case wants the error that the mutant does not return")
```

### Conformance

The corpus states each record's detail field by field already, so no
corpus case changes. The completeness gate checks that each language
names the three members.

### Version

Adding members to the surface table is a minor version change. Definition
6.0.0 adds them, together with the change to the allocation ceilings,
which makes the release a major version. Every overlay extends 6.0.0.

## Alternatives considered

### A. One generic accessor of any field

`DetailOf[T](f, name) (T, bool)` returns any field as a value of the type
that the caller states, and reports a missing field and a value of
another type.

**Why not:** the caller still spells the name, so a misspelt name reads
as a missing field. The accessor removes the cast and keeps the cause of
the failure that the motivation shows.

### B. A constant for each field name

Each language declares the 44 field names as constants, such as
`FieldWant`.

**Why not:** a constant removes the misspelling and keeps the cast. The
naming table would gain 44 rows and 264 names, and most of the fields are
read by no caller.

### C. A detail type for each assertion

Each assertion's record has a detail of a type of its own, such as
`EqualDetail{Want, Got}`.

**Why not:** the record would change type with its assertion, and a caller
of `rejects` reads records of many assertions in one list. Each language
would declare a type for each of the 103 assertions that declare a field.

### D. A member for every declared field

Each of the 44 field names would get a member of the record.

**Why not:** 25 of the 44 fields belong to one or two assertions each.
`want`, `got` and `case-failure` cover the fields that the families
share.

## Drawbacks

- **The members cover 3 of the 44 field names.** A caller reads every
  other field through the detail, by name.
- **`want` and `got` return a value of any type.** A caller who compares
  them with a typed value still converts them, in a language that types
  its comparisons.
- **The naming table grows by three rows and 18 names.**
- **In Go, the methods are declared on an internal type** that
  `assert.Failure` and `expect.Failure` alias. `go doc` lists no method of
  an alias, so the doc comment of each alias lists the three methods.

## Unresolved and future work

- An accessor of `where`, the call site, is not proposed here. The
  record states it as a field of its own in every language already.

## References

| What | Where |
|---|---|
| opentest4j 1.3.0, `AssertionFailedError` with `getExpected`, `getActual`, `isExpectedDefined` and `isActualDefined` | <https://ota4j-team.github.io/opentest4j/docs/current/api/org/opentest4j/AssertionFailedError.html> |
| The failure record, its detail and the declared field names | `spec/assertions.yaml`, `detail_fields` of each assertion |
| The field `failure` of a property's detail | `spec/recording.md`, The detail |
