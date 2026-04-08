.PHONY: lint format format-fix test test-bats test-python shellcheck syntax-check check-all help

SHELL_SCRIPTS := $(shell find skills -name '*.sh' | sort)

lint: ## Run ruff linter on Python code
	ruff check tests/ skills/

format: ## Check Python code formatting
	ruff format --check tests/ skills/

format-fix: ## Auto-fix Python code formatting
	ruff format tests/ skills/

test-python: ## Run Python regression tests with coverage
	pytest tests/ -v --cov=skills --cov=tests --cov-report=term-missing

test-bats: ## Run Bats shell unit tests
	bats tests/*.bats

test: test-python test-bats ## Run all tests (Python + Bats)

syntax-check: ## Syntax-check all shell scripts
	@echo "Syntax-checking $(words $(SHELL_SCRIPTS)) shell scripts..."
	@for f in $(SHELL_SCRIPTS); do bash -n "$$f" || exit 1; done

shellcheck: ## Run ShellCheck on all shell scripts
	shellcheck --severity=warning $(SHELL_SCRIPTS)

check-all: lint format syntax-check shellcheck test ## Run full CI check suite

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
