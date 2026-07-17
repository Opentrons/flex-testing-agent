.PHONY: sync
sync:
	uv sync --all-extras

.PHONY: lint
lint:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy

.PHONY: format
format:
	uv run ruff check --fix src tests
	uv run ruff format src tests

.PHONY: test
test:
	uv run pytest

.PHONY: test-robot
test-robot:
	uv run pytest -m requires_robot

.PHONY: inspect
inspect:
	uv run flex-test inspect

.PHONY: releases
releases:
	uv run flex-test releases

.PHONY: install
install:
	uv run flex-test install $(VERSION)

.PHONY: migrate
migrate:
	uv run alembic upgrade head

.PHONY: pages
pages:
	uv run python scripts/publish_test_suggestions_pages.py --output-dir pages
