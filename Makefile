.PHONY: help install test lint typecheck verify doctor examples clean

help:
	@echo "AgentForge targets: install test lint verify doctor examples clean"

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	python -m ruff check agentforge tests || true

typecheck:
	python -m mypy agentforge || true

doctor:
	agentforge doctor --full

examples:
	@for d in examples/*/workflow.yaml; do \
		echo "== $$d"; \
		agentforge validate "$$d"; \
	done

verify: install test doctor
	@echo "verify OK"

clean:
	rm -rf .agentforge generated dist build *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
