# Managed by ergon init, with .ergon/local/Makefile merged in. Change the repository's settings there and run ergon init sync.
#
# make check is the gate of the repository. lint-common lints the Markdown files, and lint-github
# lints the workflows. Each language adds its own fmt, lint, test, generate, audit and check
# targets as prerequisites of the targets below. CI runs make check-<language> per language. It
# runs lint-common and lint-github in jobs of their own. Every target runs its tools through ergon
# tool run, which installs the version that .ergon.yaml names. make help lists the targets in
# groups. A line ##@ <name> starts a group: the common targets, the targets of the GitHub files and
# of spec, then the targets of each language, and the targets of .ergon/local/Makefile after a line
# of its own.

.DEFAULT_GOAL := check

# The command that runs ergon for the tools of the targets. The key ergon of the section common of
# .ergon.yaml sets it.
ERGON ?= ergon

# The tools of the common targets, which ergon installs at the versions of the section common.
RUMDL := $(ERGON) tool run common.rumdl --

# verify-generated runs the command of the variable $(1) and fails when the run changes a file of
# the repository, with the target $(2) that updates the files in its message. It compares the
# changes of the working tree before and after the run, so it also runs on a tree with uncommitted
# changes.
verify-generated = before="$$(git diff HEAD --binary 2>/dev/null; git ls-files --others --exclude-standard)"; \
	$($(1)) || exit 1; \
	after="$$(git diff HEAD --binary 2>/dev/null; git ls-files --others --exclude-standard)"; \
	if [ "$$before" != "$$after" ]; then \
	echo "$(2): the generated files are out of date, so run make $(2) and commit the result:" >&2; \
	git status --short >&2; exit 1; fi

.PHONY: help fmt lint test generate audit check lint-common

##@ Common

help: ## List the targets in groups
	@awk 'BEGIN {FS = ":.*## "} /^##@ / {group = substr($$0, 5); next} /^[a-z][a-z-]*:.*## / {if (group != shown) {printf "%s%s\n", (shown == "" ? "" : "\n"), group; shown = group} printf "  %-28s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

fmt: ## Format the sources of every language
lint: ## Lint the Markdown files, the workflows and the sources of every language
test: ## Run the tests of every language
generate: ## Run the generators of every language
audit: ## Run the vulnerability scan of every language
check: ## Run the gate of every language, and lint the Markdown files and the workflows
lint: lint-common
check: lint-common

lint-common: ## Lint the Markdown files with rumdl and the rules of .markdownlint.yml
	$(RUMDL) check --no-cache .

##@ GitHub
#
# The section github of .ergon.yaml sets the tools of the GitHub targets.

# The tools of the GitHub targets, which ergon installs at the versions of the section github.
ACTIONLINT := $(ERGON) tool run github.actionlint --

.PHONY: lint-github
lint: lint-github
check: lint-github

# actionlint runs shellcheck and pyflakes on the scripts of the steps, and the flags turn both off.
# ergon pins neither program, so actionlint would run the versions that the machine has.
lint-github: ## Lint the workflows with actionlint and the configuration of .github/actionlint.yaml
	$(ACTIONLINT) -shellcheck= -pyflakes=

##@ Spec
#
# The section spec of .ergon.yaml sets the roles of the repository and the release of spec. spec
# reads its own configuration from .spec.yaml.

# The program spec, which ergon installs at the version of the section spec.
SPEC := $(ERGON) tool run spec.spec --

.PHONY: generate-spec verify-generate-spec
generate: generate-spec
check: verify-generate-spec

generate-spec: ## Write the manifest of the definition with spec
	$(SPEC) manifest
verify-generate-spec: ## Fail when the manifest of the definition differs from its files
	$(SPEC) manifest --check

##@ Python
#
# The section python of .ergon.yaml sets the tools and the options of the Python targets, and the
# steps of check-python. One run overrides an option on the command line, such as
# make test-python PYTHON_TEST_ARGS=-x.

# The tools of the Python targets, which ergon installs at the versions of the section python.
UV := $(ERGON) tool run python.uv --
RUFF := $(ERGON) tool run python.ruff --
MYPY := $(ERGON) tool run python.mypy --
PYTEST := $(ERGON) tool run python.pytest --
PIP_AUDIT := $(ERGON) tool run python.pip-audit --

# The options of the section python.
PYTHON_PATHS ?= .
PYTHON_TEST_ARGS ?=
PYTHON_AUDIT_IGNORE ?=
PYTHON_AUDIT_SKIP ?=
PYTHON_GENERATE ?= make render

# The error codes of mypy that neither its defaults nor --strict turn on.
MYPY_CODES := $(foreach code,redundant-expr possibly-undefined truthy-bool truthy-iterable ignore-without-code \
	unused-awaitable redundant-self explicit-override mutable-override unimported-reveal exhaustive-match deprecated,\
	--enable-error-code $(code))

.PHONY: fmt-python lint-python test-python generate-python verify-generate-python audit-python check-python
fmt: fmt-python
lint: lint-python
test: test-python
generate: generate-python
audit: audit-python
check: check-python

fmt-python: ## Format the Python sources
	$(RUFF) format $(PYTHON_PATHS)
lint-python: ## Check the Python sources with ruff.toml and with mypy in its strictest mode
	$(RUFF) check --no-fix $(PYTHON_PATHS)
	$(RUFF) format --check $(PYTHON_PATHS)
	$(MYPY) --strict --warn-unreachable --strict-equality-for-none $(MYPY_CODES) --exclude-gitignore $(PYTHON_PATHS)
test-python: ## Run the Python tests
	$(PYTEST) $(PYTHON_TEST_ARGS)
generate-python: ## Run the generators of Python
	$(PYTHON_GENERATE)
verify-generate-python: ## Fail when the generators of Python change a file of the repository
	@$(call verify-generated,PYTHON_GENERATE,generate-python)
audit-python: ## Scan the packages of uv.lock for known vulnerabilities
	@dir="$$(mktemp -d)"; \
	$(UV) export --frozen --all-packages --all-extras --all-groups --no-emit-local \
		$(foreach package,$(PYTHON_AUDIT_SKIP),--no-emit-package $(package)) --format pylock.toml \
		--quiet --output-file "$$dir/pylock.toml"; status=$$?; \
	if [ $$status -eq 0 ] && ! grep -q '^\[\[packages\]\]' "$$dir/pylock.toml"; then \
		echo "audit-python: uv.lock has no package to scan"; \
	elif [ $$status -eq 0 ]; then \
		$(PIP_AUDIT) --locked --strict $(foreach id,$(PYTHON_AUDIT_IGNORE),--ignore-vuln $(id)) "$$dir"; status=$$?; \
	fi; \
	rm -rf "$$dir"; exit $$status
check-python: lint-python test-python verify-generate-python audit-python ## Run the gate of Python

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
