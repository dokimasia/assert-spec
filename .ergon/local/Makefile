# Copyright Dokimasia B.V. 2026
# SPDX-License-Identifier: MIT

# The targets of assert-spec, which ergon init appends to the Makefile. render writes the JSON that
# an implementation reads from the YAML that people edit, and spec writes the manifest of the files
# that an implementation vendors. The step generate of check-python runs render and fails when the
# committed JSON or manifest differs from the output.

##@ Repository

.PHONY: render zones validate forms

render: ## Render the JSON of the definition from its YAML, and write the manifest
	$(UV) run --locked python tools/render.py
	$(SPEC) manifest

zones: ## Recompute spec/zones.json from the pinned tzdata release, which needs the network, zic and zdump
	$(UV) run --locked python tools/zones.py
	$(SPEC) manifest

validate: ## Check the definition, the corpus and the overlays against their rules
	$(UV) run --locked python tools/validate.py

forms: ## Check that GitHub renders the issue forms
	$(UV) run --locked python tools/issue_forms.py

check-python: validate forms
