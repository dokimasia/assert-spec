# Everything runs through uv, which fetches its own Python. A clone and
# `make check` is the whole setup; nothing here needs a system Python,
# a yq binary or a global pip install.
.PHONY: help install render stale validate forms test fmt lint lint-md check

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Create the environment
	uv sync --extra dev

render: ## Render the JSON an implementation reads from the YAML people edit
	@uv run python tools/render.py
	@uv run python tools/manifest.py

manifest: ## Rebuild the digest of everything an implementation vendors
	@uv run python tools/manifest.py

stale: ## Fail when the rendered JSON does not match the YAML
	@uv run python tools/manifest.py --check
	@git diff --quiet -- spec/*.json || { \
		echo "spec: the rendered JSON is stale; run make render and commit"; exit 1; }
	@echo "spec: the rendered JSON matches the YAML"

validate: ## Hold the definition, the corpus and the overlays to their rules
	@uv run python tools/validate.py

forms: ## Check the issue forms are ones GitHub will render
	@uv run python tools/issue_forms.py

test: ## Check the validator catches the faults it claims to
	@uv run python -m unittest discover -q -s tools -p '*_test.py'

fmt: ## Format the tools and fix what can be fixed
	uv run ruff format tools
	uv run ruff check --fix tools

lint: ## Lint the tools, and check formatting without changing anything
	uv run ruff check tools
	uv run ruff format --check tools
	uv run mypy
	uv run basedpyright tools

lint-md: ## Lint the Markdown
	@if command -v markdownlint >/dev/null 2>&1; then \
		markdownlint '**/*.md'; \
	elif command -v npx >/dev/null 2>&1; then \
		npx --yes markdownlint-cli '**/*.md'; \
	else \
		echo "lint-md: no markdownlint and no npx; skipped"; exit 1; \
	fi
	@echo "lint-md: markdown is clean"

check: render stale validate forms test lint lint-md ## The full pre-merge gate
	@echo "spec: every stage passed"
