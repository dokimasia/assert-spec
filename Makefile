.PHONY: help render validate test lint check

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

render: ## Render the JSON an implementation reads from the YAML people edit
	@for name in assertions naming; do \
		yq -o=json "spec/$$name.yaml" | python3 -m json.tool --sort-keys > "spec/$$name.json"; \
		echo "rendered spec/$$name.json"; \
	done

stale: ## Fail when the rendered JSON does not match the YAML
	@git diff --quiet -- spec/*.json || { \
		echo "spec: the rendered JSON is stale; run make render and commit"; exit 1; }
	@echo "spec: the rendered JSON matches the YAML"

validate: ## Hold the definition, the corpus and the overlays to their rules
	@python3 tools/validate.py

test: ## Check the validator catches the faults it claims to
	@python3 -m unittest discover -q -s tools -p '*_test.py'

lint: ## Lint the Markdown
	@if command -v markdownlint >/dev/null 2>&1; then \
		markdownlint '**/*.md'; \
	elif command -v npx >/dev/null 2>&1; then \
		npx --yes markdownlint-cli '**/*.md'; \
	else \
		echo "lint: no markdownlint and no npx; skipped"; exit 1; \
	fi
	@echo "lint: markdown is clean"

check: render stale validate test lint ## The full pre-merge gate
	@echo "spec: every stage passed"
