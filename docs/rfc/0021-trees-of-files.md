---
rfc: 0021
title: Trees of files
author: Roy Klopper <roy.klopper@stealthscale.io>
status: Accepted
created: 2026-10-06
updated: 2026-10-06
discussion: none
supersedes: none
superseded-by: none
produces-adr: none
---

# RFC-0021: Trees of files

## Summary

A test of code that reads or writes files builds a tree of files before
the code runs, and checks the files that the code leaves. The definition
names neither step. Each test suite writes its own helper for the first,
and reads files one at a time for the second. No corpus case can state a
file either, so the golden assertions have no vectors. This adds a tree
of files to the definition: entries at
relative paths, each a file with its bytes, a directory or a symbolic
link, and each with its permission bits where a test states them.
`files.workspace` writes a tree into a directory of the test's own.
`tree-equal`, `tree-contains`, `tree-unchanged` and `golden-match-tree`
compare trees. `path-absent`, `is-file`, `is-dir`, `links-to`,
`has-content` and `has-mode` check one path. A typed literal states a
tree, so a corpus case can state the files that an assertion reads.
Definition 5.1.0 adds them.

## Motivation

### Each suite builds its trees by hand

In the code bases that we read, a test of a tool that reads a directory
builds that directory itself. Its helper takes a map from
slash-separated paths to texts, creates each parent directory, and
writes each file into the test's temporary directory. Each code base
writes the helper again, and some write it more than once. No copy that
we read can state an empty directory, an executable file or a symbolic
link, and each one writes wherever a path points, `..` included.

The check after the call reads each file that the test names and
compares its text. A file that the code should not have written fails
no such check, because no test reads it. A missing file, an extra file
and a changed file report in three different ways, when they report at
all. A mode is checked rarely, although a key written with mode `0644`
instead of `0600` is a fault that no reading of the key reveals.

### No corpus case can state a file

A corpus case states its arguments as typed literals, and no literal
states a file or a directory, so the three golden assertions have no
vectors. Each implementation tests them itself, and the completeness
gate checks only that they are present. An assertion about files would
join them for the same reason, unless a literal can state a tree and a
runner can write it before the call.

### Why the definition, and not each library

An assertion belongs in the set when it states something that must be
true and fails when it is not, and when it means the same thing in every
target language. Comparing two trees is such a check, and so is checking
the kind, the content or the mode of one path. Every platform stores
the paths of a tree, the bytes of its files and the targets of its links
alike. A tree that keeps to those means the same thing in every
language. Permission bits mean the same thing on every platform that
records them, and the definition states what happens on one that does
not.

The workspace supplies an input, and the set itself excludes inputs. The
definition already specifies an input where its assertions consume one,
such as the clock that the waiting assertions read and the generators of
a property. The tree assertions consume a tree, and a corpus case has to
state one, so the definition specifies the tree and the workspace beside
them. A generator that emits suites in every target language then states
a test's workspace once for all, and reads one record of what differs.

## Detailed design

### The tree

A tree is a set of entries. Each entry has a path relative to the tree's
root, and a kind:

| Kind | States |
|---|---|
| File | Its content, a byte string, and whether its owner may execute it |
| Directory | Nothing more |
| Link | Its target, the text of a symbolic link |

A file or a directory may also state a mode: its nine permission bits,
read, write and execute for the owner, the group and others. A file that
states a mode states whether its owner may execute it through that mode.

These rules apply to every tree:

- A path is one or more names joined by `/`. A name is not empty, `.`
  or `..`, and contains no `/`, `\` or NUL.
- A tree states each path once. Paths order as the bytes of their UTF-8
  encoding.
- The directories of a tree are the ones it states and every parent of
  an entry. A tree needs to state a directory only when the directory is
  empty or when the tree states its mode.
- A file and a link have no entries, so a tree that states an entry
  below one is refused. A link has no mode.

A tree leaves out timestamps, owners, groups, extended attributes and
the setuid, setgid and sticky bits. Two names of one file read as two
files. A device, a socket and a pipe cannot be in a tree, and an
assertion that reads one ends the call with a fault.

### Comparing a tree with a wanted one

A comparison takes a wanted tree and a tree read from a directory. A path
differs when one of the two has it and the other does not, or when the
entries at it differ. Two entries at one path differ when:

- their kinds differ,
- two files have different contents,
- two links have different targets,
- the wanted entry states a mode, and the read entry has other
  permission bits, or
- the wanted file states no mode, and the owner's execute bit of the two
  files differs.

A wanted tree that states no mode compares the execute bit alone. A test
states a mode only where the mode is part of the contract.

Where a platform cannot store a tree as stated, the same rules apply in
every language. The definition states them. No overlay declares them:

- A file system that does not record permission bits reads every entry
  without a mode, and every file as not executable. A workspace there
  does not set any bit. The comparisons ignore modes and execute bits.
- A workspace ends the call with a fault at any other entry that the
  platform cannot store as stated. It writes over no entry. Such an
  entry is a symbolic link where the platform refuses to create one, or
  a name that the platform reserves, such as `CON` on Windows. It is
  also a second path that the file system maps to an entry already
  written. A file system that ignores case maps `a.txt` to `A.txt`.

### The literal

A typed literal of the type `tree` states a tree:

```json
{
  "type": "tree",
  "entries": [
    { "path": "bin/run", "text": "#!/bin/sh\necho ok\n", "executable": true },
    { "path": "cache", "directory": true },
    { "path": "current", "link": "bin/run" },
    { "path": "go.mod", "text": "module example.com/a\n" },
    { "path": "keys", "directory": true, "mode": 448 },
    { "path": "keys/id", "text": "secret\n", "mode": 384 },
    { "path": "logo.png", "bytes": "89504e470d0a1a0a" }
  ]
}
```

- `entries` lists the entries in path order. Each states `path` and
  exactly one of `text`, `bytes`, `directory` and `link`.
- `text` states a file's content as UTF-8 text, and `bytes` states it in
  lowercase hexadecimal, as the `bytes` literal does.
- `executable` may accompany `text` or `bytes`, and is false when
  absent. An entry that states `mode` states no `executable`, because
  the mode states the execute bit.
- `mode` is an integer from 0 to 511, the nine permission bits. A file
  or a directory may state one. In the example, 448 is `0o700` and 384
  is `0o600`.
- `directory` is `true`, and `link` states the target.
- In a record, a file whose content is longer than 65,536 bytes states
  `digest` and `size` in place of its content. `digest` is `sha256:`
  and 64 lowercase hexadecimal digits. A case never states that form in
  an argument.

Go decodes a tree literal to a `files.Tree`.

### Reading a tree

An assertion reads a tree from a directory. It walks the directory from
its root and follows no link: a link is an entry with its target. It
states each file's and each directory's mode where the file system
records permission bits. A language whose standard library defines an
interface for a file system, as Go's `io/fs` does, also reads a tree
through that interface, so a test can compare a tree that it keeps in
memory. Go reads the links of an `fs.FS` through `fs.ReadLinkFS`, which
`os.DirFS` and `fstest.MapFS` implement. A link in an `fs.FS` that does
not implement it ends the call with a fault.

### The workspace

`files.workspace` takes the seat and a tree. It returns the path of a
directory:

- It creates a directory of the test's own. The test removes it when it
  ends.
- It refuses a tree that breaks a rule of the tree before it writes
  anything.
- It creates every entry and writes over none.
- It never writes through a link, so no entry can be written outside
  the directory.
- It sets 0644 on each file that states no mode, and 0755 on each
  executable file and each directory that states none. The tree that it
  writes is then the same under any umask.
- It sets each mode after it writes the entry, and the mode of a
  directory after every entry below it. The umask cannot change a mode,
  and a directory's mode cannot stop a write below it.
- It writes a link's target as the tree states it, inside or outside the
  directory. It never follows the link.
- The test removes the directory when it ends, also when the mode of a
  directory in it leaves out the owner's write bit.

Each refusal and each error of the file system ends the call with a
fault, which stops the test. A golden file that cannot be written ends
its call the same way.

### The tree assertions

```yaml
"tree-equal":
  arity: 3
  package: files
  summary: >
    A tree read from a directory has the entries of a stated tree, no more
    and no fewer, each as the stated entry states it.
  detail_fields: [want, got, differences]

"tree-contains":
  arity: 3
  package: files
  summary: >
    A tree read from a directory has every entry of a stated tree, each as
    the stated entry states it. It may have more.
  detail_fields: [want, got, differences]

"tree-unchanged":
  arity: 3
  package: files
  summary: >
    A callable leaves the tree in a directory as it found it: the tree read
    after the call equals the tree read before it, modes included.
  detail_fields: [want, got, differences]

"golden-match-tree":
  arity: 3
  package: golden
  summary: >
    A tree read from a directory equals the golden tree in the directory
    that a name resolves to against the conventional directory. The
    comparison reads no mode of the golden tree, and compares execute
    bits. Under update, the call makes the golden directory equal the tree
    and passes.
  detail_fields: [want, got, differences]
```

`tree-equal` and `tree-contains` take the directory, the stated tree and
the message. `tree-unchanged` takes the directory, the callable and the
message. It reads the tree before it calls the callable and again after
it, and compares the two with the tree before the call as the wanted
one. A callable that raises or panics ends the assertion with that panic
or exception, and the assertion compares nothing. A write of the bytes
that a file already has leaves a tree unchanged, and so does a change of
a timestamp. A change of a mode does not.

A failure of each of the four states three fields:

| Field | States |
|---|---|
| `want` | A tree of the wanted entries at the paths that differ |
| `got` | A tree of the entries read at those paths |
| `differences` | The number of paths that differ |

The wanted tree is the stated tree for `tree-equal` and `tree-contains`,
the tree before the call for `tree-unchanged`, and the golden tree for
`golden-match-tree`. `tree-contains` compares the paths of the stated
tree alone, so an extra entry is no difference. `want` and `got` state
at most the first 64 paths that differ, in path order. A missing entry
appears in `want` alone, an extra one in `got` alone, and a changed one
in both.

An entry of `got` states its mode only where the wanted entry at its path
states one, and a file of `got` that states no mode states whether its
owner may execute it. The record then states what the comparison read,
and the umask of the code under test does not change it.

### Golden trees

`golden-match-tree` takes a name, the directory of the output and
`update`, as `golden-match` takes a name, the output and `update`:

- It resolves the name against the conventional directory, as
  `golden-match` does. The golden tree is the directory there. A name
  follows the rules of a path, so it cannot leave the conventional
  directory.
- It does not read the modes of the golden tree, and compares execute
  bits alone. A checkout writes the modes of a golden tree by the umask
  of whoever checks it out. The execute bit is the one that git records.
- Without `update`, a golden tree that differs fails. So does a missing
  golden directory. Its record states `want` null, `got` the first 64
  entries of the output, and `differences` the number of the output's
  entries.
- With `update`, it makes the golden directory equal the output and
  passes. It removes each entry that the output lacks. It writes each
  entry that the directory lacks or has in another form. It removes a
  link, and never the entry that the link points to.
- Its scrubbers apply to the content of every file that is valid UTF-8
  text, on both sides. Under `update` it writes the scrubbed content, as
  `golden-match` writes the scrubbed output.

### The path assertions

```yaml
"path-absent":
  arity: 2
  package: files
  summary: >
    Nothing is at a path: no file, no directory and no link, a link whose
    target is missing included. got is the kind of the entry there.
  detail_fields: [got]

"is-file":
  arity: 2
  package: files
  summary: >
    A file is at a path. A link to a file is a link. got is the kind of the
    entry there, or null for none.
  detail_fields: [got]

"is-dir":
  arity: 2
  package: files
  summary: >
    A directory is at a path. A link to a directory is a link. got is the
    kind of the entry there, or null for none.
  detail_fields: [got]

"links-to":
  arity: 3
  package: files
  summary: >
    A symbolic link with a stated target is at a path. The target compares
    as text. got is the link's target, or null when no link is there, and
    kind is the kind of the entry there, or null for none.
  detail_fields: [want, got, kind]

"has-content":
  arity: 3
  package: files
  summary: >
    A file whose bytes equal stated text or bytes is at a path. got is the
    file's content, as text when it is valid UTF-8 and as bytes otherwise,
    or null when no file is there, and kind is the kind of the entry there.
  detail_fields: [want, got, kind]

"has-mode":
  arity: 3
  package: files
  summary: >
    A file or a directory whose nine permission bits equal a stated mode is
    at a path. A link has no mode. got is the entry's permission bits, or
    null when no file or directory is there, and kind is the kind of the
    entry there.
  detail_fields: [want, got, kind]
```

Each reads the entry at the path itself. Like a tree's reader, it
follows no link there. The platform resolves the names before the last
one, and follows a link among them. Nothing is at a path below a file. A
path is a location in the language's own form: a string in Go, Python,
Rust and TypeScript, and a `java.nio.file.Path` in Java and Kotlin.

| Field | States |
|---|---|
| `got` of `path-absent`, `is-file`, `is-dir` | The kind of the entry at the path, `file`, `directory` or `link`, or null for none |
| `kind` | The same kind, for the three assertions that compare a value |
| `want` of `links-to` | The stated target |
| `got` of `links-to` | The target of the link at the path, or null when no link is there |
| `want` of `has-content` | The stated content, as text or as bytes |
| `got` of `has-content` | The file's content: text when it is valid UTF-8, bytes otherwise, or null when no file is there |
| `want` of `has-mode` | The stated mode, an integer from 0 to 511 |
| `got` of `has-mode` | The entry's nine permission bits, or null when no file or directory is there |

On a file system that does not record permission bits, `has-mode` ends
the call with a fault. It would otherwise compare bits that the
platform does not store. `has-content` compares bytes. A file with
`\r\n` does not equal text with `\n`.

`files.read` takes the seat and a path. It returns the content of the
file there, and ends the call with a fault when no file is at the path
or the file cannot be read. A test composes it with the text
assertions, so `contains`, `matches`, `has-prefix` and the rest apply to
a file without a file form of each.

The ten assertions stop the test on a failure and have no recording
form, as the golden assertions do.

### Go

```go
// Package files builds trees of files for a test, and checks the files that
// the code under test reads and writes.
package files

// Tree is a tree of files: each entry at its path, relative to the tree's
// root and separated by slashes.
type Tree map[string]Entry

// MarshalJSON returns the tree literal of t, its entries in the order of
// their paths' bytes.
func (t Tree) MarshalJSON() ([]byte, error)

// UnmarshalJSON sets t to the tree that the tree literal data states, and
// leaves t unchanged for a text that is no tree literal.
func (t *Tree) UnmarshalJSON(data []byte) error

// Entry is a file, a directory or a symbolic link of a tree. The zero
// Entry states nothing, and a tree that contains one is refused.
type Entry struct {
	// The kind, the content, the execute bit, the mode and the target,
	// unexported.
}

// Text returns a file whose content is text.
func Text(text string) Entry

// Bytes returns a file whose content is content.
func Bytes(content []byte) Entry

// Executable returns a file whose content is text, which its owner may
// execute.
func Executable(text string) Entry

// Dir returns a directory.
func Dir() Entry

// Link returns a symbolic link to target.
func Link(target string) Entry

// WithMode returns e with the nine permission bits of mode. It panics for
// a link, and for a mode with any other bit set.
func (e Entry) WithMode(mode fs.FileMode) Entry

// Workspace writes tree into a directory of the test's own, which the test
// removes when it ends, and returns the directory's path. It writes through
// os.Root, which refuses every operation that a link would take outside
// the directory. Where the tree states no mode, a file gets 0644, and an
// executable file and a directory get 0755.
func Workspace(tb testing.TB, tree Tree) string

// Read returns the content of the file at path. It ends the test with a
// fault when no file is there or the file cannot be read.
func Read(tb assert.TB, path string) string

// Equal stops the test when the tree in got differs from want.
func Equal(tb assert.TB, got fs.FS, want Tree, msg string)

// Contains stops the test when the tree in got lacks an entry of want, or
// has it in another form.
func Contains(tb assert.TB, got fs.FS, want Tree, msg string)

// Unchanged calls fn, and stops the test when the tree in fsys after the
// call differs from the tree in it before the call.
func Unchanged(tb assert.TB, fsys fs.FS, fn func(), msg string)

// Absent stops the test when a file, a directory or a link is at path.
func Absent(tb assert.TB, path, msg string)

// IsFile stops the test when no file is at path.
func IsFile(tb assert.TB, path, msg string)

// IsDir stops the test when no directory is at path.
func IsDir(tb assert.TB, path, msg string)

// LinksTo stops the test when no symbolic link to target is at path.
func LinksTo(tb assert.TB, path, target, msg string)

// HasContent stops the test when no file whose content is want is at path.
func HasContent(tb assert.TB, path, want, msg string)

// HasMode stops the test when no file or directory whose permission bits
// are want is at path.
func HasMode(tb assert.TB, path string, want fs.FileMode, msg string)
```

```go
// MatchTree compares the tree in got with the golden tree in
// testdata/golden/name, and stops the test when they differ. update
// rewrites the golden tree to equal the tree in got.
func MatchTree(tb assert.TB, name string, got fs.FS, update bool, scrubbers ...Scrubber)
```

A test of a tool that renames a function:

```go
dir := files.Workspace(t, files.Tree{
	"go.mod": files.Text("module example.com/a\n"),
	"a/a.go": files.Text("package a\n\nfunc Old() {}\n"),
	"b/b.go": files.Text("package b\n\nimport \"example.com/a\"\n\nvar _ = a.Old\n"),
})
assert.NoError(t, rename.Run(dir, "a.Old", "New"), "the rename succeeds")
files.Equal(t, os.DirFS(dir), files.Tree{
	"go.mod": files.Text("module example.com/a\n"),
	"a/a.go": files.Text("package a\n\nfunc New() {}\n"),
	"b/b.go": files.Text("package b\n\nimport \"example.com/a\"\n\nvar _ = a.New\n"),
}, "the rename rewrites the declaration and every use")
```

For a key that a tool writes, a dry run, and the tree that a generator
writes:

```go
files.HasMode(t, filepath.Join(home, ".config/tool/key"), 0o600, "the key is private")
files.Unchanged(t, os.DirFS(dir), func() { _ = migrate.DryRun(dir) },
	"a dry run writes nothing")
golden.MatchTree(t, "api", os.DirFS(out), golden.ShouldUpdate())
```

`Workspace` takes a `testing.TB`, because it needs the test's
`TempDir`, which the three methods of `assert.TB` do not include. A path
assertion takes a path of the operating system, as `os.Stat` does. A
tree assertion takes an `fs.FS`, so it reads a tree in memory as well
as a directory, through `os.DirFS`.

The text of a failure prints each entry of `want` and `got` as the `files`
expression that states it, such as `files.Text("secret\n").WithMode(0o600)`,
and a file longer than 65,536 bytes as its size and its digest. A test
then copies an entry from the failure into its wanted tree.

### Names

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| `tree-equal` | `files.Equal` | `files.equal` | `files::equal` | `files.equal` | `FileTrees.equal` | `FileTrees.equal` |
| `tree-contains` | `files.Contains` | `files.contains` | `files::contains` | `files.contains` | `FileTrees.contains` | `FileTrees.contains` |
| `tree-unchanged` | `files.Unchanged` | `files.unchanged` | `files::unchanged` | `files.unchanged` | `FileTrees.unchanged` | `FileTrees.unchanged` |
| `golden-match-tree` | `golden.MatchTree` | `golden.match_tree` | `golden::matches_tree` | `golden.matchTree` | `Golden.matchTree` | `Golden.matchTree` |
| `path-absent` | `files.Absent` | `files.absent` | `files::absent` | `files.absent` | `FileTrees.absent` | `FileTrees.absent` |
| `is-file` | `files.IsFile` | `files.is_file` | `files::is_file` | `files.isFile` | `FileTrees.isFile` | `FileTrees.isFile` |
| `is-dir` | `files.IsDir` | `files.is_dir` | `files::is_dir` | `files.isDir` | `FileTrees.isDir` | `FileTrees.isDir` |
| `links-to` | `files.LinksTo` | `files.links_to` | `files::links_to` | `files.linksTo` | `FileTrees.linksTo` | `FileTrees.linksTo` |
| `has-content` | `files.HasContent` | `files.has_content` | `files::has_content` | `files.hasContent` | `FileTrees.hasContent` | `FileTrees.hasContent` |
| `has-mode` | `files.HasMode` | `files.has_mode` | `files::has_mode` | `files.hasMode` | `FileTrees.hasMode` | `FileTrees.hasMode` |

The surface table gains two types, seven helpers and a member:

| Id | Go | Python | Rust | TypeScript | Java | Kotlin |
|---|---|---|---|---|---|---|
| type `tree` | `files.Tree` | `files.Tree` | `files::Tree` | `files.Tree` | `FileTree` | `FileTree` |
| type `entry` | `files.Entry` | `files.Entry` | `files::Entry` | `files.Entry` | `FileTree.Entry` | `FileTree.Entry` |
| `files.workspace` | `files.Workspace` | `files.workspace` | `files::workspace` | `files.workspace` | `FileTrees.workspace` | `FileTrees.workspace` |
| `files.read` | `files.Read` | `files.read` | `files::read` | `files.read` | `FileTrees.read` | `FileTrees.read` |
| `files.text` | `files.Text` | `files.text` | `files::text` | `files.text` | `FileTrees.text` | `FileTrees.text` |
| `files.bytes` | `files.Bytes` | `files.bytes` | `files::bytes` | `files.bytes` | `FileTrees.bytes` | `FileTrees.bytes` |
| `files.executable` | `files.Executable` | `files.executable` | `files::executable` | `files.executable` | `FileTrees.executable` | `FileTrees.executable` |
| `files.directory` | `files.Dir` | `files.directory` | `files::directory` | `files.directory` | `FileTrees.directory` | `FileTrees.directory` |
| `files.link` | `files.Link` | `files.link` | `files::link` | `files.link` | `FileTrees.link` | `FileTrees.link` |
| `entry.with-mode` | `WithMode` | `with_mode` | `with_mode` | `withMode` | `withMode` | `withMode` |

Two spellings differ, each for a reason of its language:

- Java and Kotlin name the tree `FileTree` and the class of the
  assertions and helpers `FileTrees`, as the JDK pairs `Path` with
  `Paths`. A Java test reads and writes files through
  `java.nio.file.Files`, and a second class of that name would make every
  such test qualify one of the two.
- Go spells the directory constructor `Dir`, as `io/fs` spells
  `ReadDir` and `DirEntry`.

### Who supplies it

Every language supplies the ten assertions and the helpers. The
standard library of each creates, reads and removes files, directories
and symbolic links, and reads and sets permission bits on a platform that
records them. The rules of the platform are in the definition, so no
overlay declares a limit for them.

### Conformance

The cases of the ten assertions are vectors, as the cases of the property
engine and of the history are. People write the inputs of each vector in
`corpus/files/<assertion>.yaml`. `make render` computes the outputs with
an executable reference in `tools/files/`, and writes the JSON beside the
YAML:

| Key | Written by | States |
|---|---|---|
| `workspace` | People | The tree that the runner writes with the language's workspace before the call |
| `args` | People | The assertion's arguments as typed literals, without the directory and the message |
| `subject` | People | The callable of a vector of `tree-unchanged`, in place of `args` |
| `golden` | People | The golden tree of a vector of `golden-match-tree`, or null for none |
| `expect` | People | `pass` or `fail` |
| `detail` | `make render` | The record of a failure |
| `after` | `make render` | The golden tree that a call under `update` leaves |

`make render` refuses a vector whose `expect` differs from the verdict of
the reference. The runner passes the workspace's directory where a tree
assertion takes a directory. It passes the path of the operating system
where an argument states a path relative to the workspace's root. It
writes the golden tree where the language's conventional directory
resolves the vector's name, in a working directory of the vector's own.

A runner on a platform that does not record permission bits skips each
vector that states a mode or an executable file, and each vector of
`has-mode`. A runner on a platform that refuses to create links skips
each vector that states a link. These skips follow from the rules of the
platform, so no vector declares them.

`tree-unchanged` takes a callable, so it gains four subjects:

```yaml
"leaves-files-alone":
  summary: >
    Reads every file of the workspace, and writes nothing.
"rewrites-files":
  summary: >
    Writes every file of the workspace again, with the bytes that the file
    has.
"writes-a-file":
  summary: >
    Writes the file new.txt, with the text new, at the root of the
    workspace.
"writes-a-large-file":
  summary: >
    Writes the file large.bin, 65,537 bytes of the letter a, at the root of
    the workspace.
```

`writes-a-large-file` writes one byte more than a record states in full,
so its vector pins the digest form, and no vector states 65,537 bytes of
content.

The vectors are these:

| Assertion | Vectors |
|---|---|
| `tree-equal` | Equal trees pass. A missing file, an extra file, another content of text and of bytes, another execute bit, another link target, a file in place of a directory, an extra empty directory and another stated mode each fail. A stated directory that an entry already implies passes, and so does a read mode that the wanted tree does not state. The modes that a workspace sets where its tree states none pass as 0644 and 0755. 65 files of other content fail with 64 listed and `differences` 65 |
| `tree-contains` | A stated subset passes, and so does an entry below a stated directory. A missing entry fails, and so do another content and another stated mode |
| `tree-unchanged` | `leaves-files-alone` and `rewrites-files` pass. `writes-a-file` fails, and `writes-a-large-file` fails with the digest of `large.bin` |
| `golden-match-tree` | An equal golden tree passes, and so does one whose modes differ in no execute bit. A golden tree that differs fails. A missing golden tree fails with `want` null. Under `update`, a missing golden tree is written, a golden tree that differs is rewritten without its extra file, directory and link, and an equal one is left as it is |
| `path-absent` | Nothing at the path passes, and so does a path below a file. A file fails, and so does a link whose target is missing |
| `is-file` | A file passes. A directory, a link to a file and nothing at the path each fail |
| `is-dir` | A directory passes. A file, a link to a directory and nothing at the path each fail |
| `links-to` | The stated target passes, and so does a target outside the workspace. Another target, a file and nothing at the path each fail |
| `has-content` | Equal text passes, and so do equal bytes. Text that ends in `\r\n` fails against text that ends in `\n`, and other bytes fail with the file's bytes. A directory and nothing at the path each fail |
| `has-mode` | The stated mode of a file passes, and so does a directory's. Another mode, a link and nothing at the path each fail |

### Version

Adding an assertion is a minor version change. A literal that no
existing case states does not change any answer, so adding one is minor
too. Definition 5.1.0 adds the ten assertions, the tree literal, four
subjects, two types, seven helpers and a member. None of the ten has a
property form, because they read a file system, as the golden
assertions do. The assertion table grows from 100 entries to 110. 39 of
the 71 assertions have corpus cases, and the ten that read files have 57
vectors. Every overlay extends 5.1.0.

## Alternatives considered

### A. A broader family of path assertions

Libraries in other languages offer more checks of one path: whether the
test process may read, write or execute it, its size, its timestamps,
its owner, its digest, and a file form of each text assertion.

**Why not:** each of them either checks something other than the file,
or repeats a check that the definition already has.

- Whether the process may read, write or execute a path depends on who
  runs the test. A test that runs as root passes the read and the write
  check whatever the mode. `has-mode` checks the bits that the file
  stores, which root reads as any other user does.
- `has-content` states a file's size, and a size alone passes a file of
  the right length with the wrong bytes.
- File systems keep timestamps at different resolutions, and a checkout
  rewrites them.
- A test runs as whatever user its runner picks, and Windows has no
  numeric owner.
- A digest checks the content, which `has-content` checks and shows as a
  diff.
- `files.read` composes with every text assertion, so the definition
  does not need a file form of `contains`, `matches` or `has-prefix`.

This would change if tests often need a check of one path that none of
the ten states and no composition covers.

### B. A text archive for trees

A txtar archive states a tree of text files as one text: a `-- name --`
line before each file's content. The go command's tests use it, and it
diffs well in review.

**Why not:** its own documentation lists binary data, file modes and
symbolic links as non-goals. Each language's map literal states a tree
of text files as compactly. The corpus states trees as typed literals.
A golden tree is a directory, so a review shows each golden file beside
the code that writes it.

### C. Each language's own libraries

Go's testing package, pytest and JUnit each give a test a temporary
directory of its own, and libraries outside that tooling add the rest.
In Go, gotest.tools/v3/fs builds a directory from operations such as
`WithFile`, `WithDir`, `WithMode` and `WithSymlink`, and compares a
directory with a manifest. In Rust, assert_fs writes the children of a
temporary directory and checks paths with predicates.

**Why not:** each library has its own model of a tree and its own
report, so a test written with one does not port to another language. A
generator that emits suites in every language then has no one way to
state a workspace, and no corpus case can check a library outside the
definition.

### D. A file system in memory

The library would provide a file system in memory, and tests would hand
it to the code under test.

**Why not:** code that reads an interface for a file system already
accepts one in memory, such as Go's `fstest.MapFS`. `tree-equal` reads
through the same interface. Code that writes to a directory needs a
directory, and whether the code under test writes through such a layer
is a decision about that code.

### E. A relaxation of tree-equal for extra entries

`tree-equal` would accept a relaxation under which the tree read may
have more entries than the stated one.

**Why not:** both relaxations of the definition make two values equal
that would otherwise differ. Whether a tree may have more entries is a
different question, and an assertion of its own states it in its name.
Its record also has no extra entries to report.

### F. Modes compared on every entry

A tree read from a directory would compare every mode bit, as the
manifests of gotest.tools compare a mode unless a test opts out.

**Why not:** the modes of a tree that a checkout or a process writes
depend on the umask in force. Two machines then disagree about a tree
that neither test stated a mode for. A wanted tree states a mode where
the mode is part of the contract. Everywhere else the comparison reads
the execute bit.

### G. Line endings read alike

The comparison would read `\r\n` as `\n`. gotest.tools offers this with
`MatchContentIgnoreCarriageReturn`.

**Why not:** a carriage return that the code under test wrote is a real
difference, and that comparison passes it. A golden tree that a checkout
rewrites with `\r\n` fails instead. `-text` for the golden directory in
`.gitattributes` prevents that rewrite.

## Drawbacks

- The definition gains 10 assertions, a literal type, 4 subjects, 2
  types, 7 helpers and a member. The naming table gains 20 rows of 6
  names.
- Each of the six implementations builds a tree type, a reader that
  follows no link, a writer that writes over nothing and through no
  link, a bounded record, six checks of one path, and a golden update
  that removes files. We have not measured the size of an
  implementation yet.
- A tree that a workspace writes on one platform can fault on another:
  a link where the platform refuses links, a name that the platform
  reserves, or two paths that a file system maps to one entry.
- On a platform without permission bits, a tree comparison ignores the
  modes that a test states. Only `has-mode` refuses there, with a fault.
- A tree record lists 64 paths, and states a digest in place of a file
  over 65,536 bytes. A test with more differences reads their number and
  the first 64.
- `golden-match-tree` under `update` removes files from a golden
  directory. A test that passes another test's name rewrites that
  test's golden tree.
- The 100% coverage gate of an implementation needs a test for each
  error of the file system. A permission cannot cause one in a test that
  runs as root.
- The corpus gains 57 vectors, and the definition an executable
  reference of 850 lines in `tools/files/`, with 644 lines of tests, that
  computes their records.

## Unresolved and future work

- Vectors for `golden-match`, `golden-match-at` and
  `golden-match-json-field` are not proposed here. A case can state
  their golden files through a workspace, but their vectors pin results
  that the definition does not state yet, such as how
  `golden-match-json-field` compares numbers.
- A golden tree outside the conventional directory is not proposed here.
- Leaving out of a comparison the paths that a pattern matches is not
  proposed here.

## References

| What | Where |
|---|---|
| Git's three modes of a file: 100644, 100755 and 120000 | Pro Git, 10.2 Git Objects, <https://git-scm.com/book/en/v2/Git-Internals-Git-Objects> |
| `os.CopyFS`, `os.Root`, `fs.ReadLinkFS`, and `fstest.MapFS` with links | Go 1.27.1, `src/os/dir.go` lines 128 to 146, `src/os/root.go` lines 34 to 46 and 239 to 249, `src/io/fs/readlink.go`, `src/testing/fstest/mapfs.go` lines 156 to 170 |
| gotest.tools/v3/fs: `NewDir`, the `With` operations, `Expected`, `Equal` and the `Match` operations | <https://pkg.go.dev/gotest.tools/v3/fs>, v3.5.2 |
| assert_fs: fixtures and path assertions | <https://docs.rs/assert_fs> |
| txtar, its goals and its non-goals | `golang.org/x/tools/txtar`, `archive.go` |
| pytest's `tmp_path` | <https://docs.pytest.org/en/stable/how-to/tmp_path.html> |
| JUnit's `@TempDir` | <https://junit.org/junit5/docs/current/api/org.junit.jupiter.api/org/junit/jupiter/api/io/TempDir.html> |
| The file assertions of testify, PHPUnit and AssertJ | `assert/assertions.go`, `src/Framework/Assert.php`, `AbstractPathAssert.java` and `AbstractFileAssert.java` in their repositories |
