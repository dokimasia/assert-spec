.PHONY: help render check

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

render: ## Render the JSON an implementation reads from the YAML people edit
	@for name in assertions naming; do \
		yq -o=json "spec/$$name.yaml" | python3 -m json.tool --sort-keys > "spec/$$name.json"; \
		echo "rendered spec/$$name.json"; \
	done

check: render ## Fail when the rendered JSON is stale
	@git diff --quiet -- spec/*.json || { \
		echo "spec: the rendered JSON is stale; run make render and commit"; exit 1; }
	@echo "spec: the rendered JSON matches the YAML"
