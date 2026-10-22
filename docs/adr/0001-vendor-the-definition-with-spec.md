---
adr: 0001
title: Vendor the definition with spec
status: Accepted
date: 2026-10-22
supersedes: RFC-0014, in part
superseded-by: none
rfc: none
---

<!--
  ~ Copyright Dokimasia B.V. 2026
  ~ SPDX-License-Identifier: MIT
-->

# ADR-0001: Vendor the definition with spec

## Status

Accepted

## Context

Each of the five implementations vendors a copy of the definition. `tools/spec-sync.sh` downloaded the files of one ref from raw.githubusercontent.com, and `tools/spec-check.sh` compared a copy with the manifest beside it and with the manifest of `main`. `tools/manifest.py` wrote the manifest, and each implementation ran a workflow that opened an issue when its copy was behind.

The scripts had these costs:

- Each implementation kept a copy of both scripts, and `spec-sync.sh` replaced them on every sync. The manifest listed the scripts, so a change of a script changed the digest of the definition.
- A copy recorded a digest and no commit. A copy from a checkout that nobody pushed matched no commit, and `spec-check.sh` reported the same difference for a copy that is behind and for a copy that is ahead.
- A copy put the files in one directory and renamed the overlay to `overlay.json`, so each implementation read another layout than this repository has.
- A copy that was behind produced an issue, and a person ran the sync and opened the pull request.

[spec](https://github.com/stealth-scale/spec) vendors a definition into implementations of any language. It writes the manifest of a definition and writes each copy with the commit that the copy comes from. It checks a copy offline and against the branch of its entry, and it opens the pull request that updates a copy.

## Decision

We vendor the definition with spec. `.spec.yaml` lists the files that an implementation vendors and the overlay of each language. `spec manifest` writes `spec/manifest.json`, and `make render` runs it after the JSON.

Each implementation declares its copy in its own `.spec.yaml`. It runs `spec check --remote` in CI and the workflow `propose.yml` of spec on weekdays. We delete `tools/manifest.py`, `tools/spec-sync.sh`, `tools/spec-check.sh` and the test of `spec-check.sh`. Every implementation moves to spec in the same change, so no implementation runs the scripts afterwards.

This decision supersedes the row of `spec-check.sh` in the table of the checks around the corpus in RFC-0014, and the sentence of that RFC on the tests of `spec-check.sh`. `spec check` compares each file of a copy with the digest in the manifest of the copy, and it checks the languages and the commit of the copy.

## Alternatives Considered

### Fix the gaps of the scripts

A commit in each copy, the paths of the definition and a pull request in place of an issue each need more code in the scripts. It lost because spec does each of them with its own tests. spec is one binary for Linux, macOS and Windows, and the scripts need sh, curl and Python.

### A git submodule of this repository

A submodule pins a commit. It lost because it vendors the whole repository, the YAML sources and the tools included, and a build of an implementation then needs a recursive clone.

## Consequences

**Positive:**

- A copy records the commit that it comes from, and `spec check --remote` fails when that commit is not on `main`.
- A copy keeps the paths of this repository, such as `spec/assertions.json` and `overlays/go.json`.
- An implementation whose copy is behind `main` gets a pull request with the new copy.
- No implementation carries a script of this repository.

**Negative:**

- Each implementation needs spec in CI and for a sync on a laptop. The action `setup-spec` of spec installs it with the Go toolchain of the runner.
- `spec sync` and `spec check --remote` read GitHub through its API, so they need a token. `spec check` without `--remote` runs offline.
- The digest of definition 9.0.0 changed without a new version, because the manifest no longer lists the two scripts.
