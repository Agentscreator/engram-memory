.DEFAULT_GOAL := help

PYTHON ?= python
PIP ?= $(PYTHON) -m pip
PYTEST ?= $(PYTHON) -m pytest
RUFF ?= $(PYTHON) -m ruff
DOCKER_COMPOSE ?= docker compose
TEST_ARGS ?= tests/ -x --tb=short
TEST_ALL_ARGS ?= tests/

export PYTHONPATH := src

.PHONY: help install install-dev test test-all lint format format-check check build clean serve docker-build docker-up docker-up-sqlite docker-up-postgres docker-down docker-logs

help:
	@echo "Engram development commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install            Install Engram with development dependencies"
	@echo "  make install-dev        Alias for make install"
	@echo "                          Override Python with PYTHON=/path/to/python"
	@echo ""
	@echo "Quality:"
	@echo "  make test               Run the CI-style pytest suite"
	@echo "                          Override with TEST_ARGS='tests/test_file.py -q'"
	@echo "  make test-all           Run the full pytest suite without fail-fast"
	@echo "  make lint               Run ruff lint checks"
	@echo "  make format             Format Python files with ruff"
	@echo "  make format-check       Check formatting without modifying files"
	@echo "  make check              Run lint, format-check, and tests"
	@echo ""
	@echo "Runtime:"
	@echo "  make serve              Run the local HTTP MCP server"
	@echo "  make build              Build Python package artifacts"
	@echo "  make clean              Remove local build and Python cache artifacts"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build       Build Docker images"
	@echo "  make docker-up          Start the SQLite Docker profile"
	@echo "  make docker-up-sqlite   Start the SQLite Docker profile"
	@echo "  make docker-up-postgres Start the PostgreSQL Docker profile"
	@echo "  make docker-down        Stop Docker Compose services"
	@echo "  make docker-logs        Follow Docker Compose logs"

install:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

install-dev: install

test:
	$(PYTEST) $(TEST_ARGS)

test-all:
	$(PYTEST) $(TEST_ALL_ARGS)

lint:
	$(RUFF) check .

format:
	$(RUFF) format .

format-check:
	$(RUFF) format --check .

check: lint format-check test

build:
	$(PIP) install --upgrade build
	$(PYTHON) -m build

clean:
	$(PYTHON) -c "import pathlib, shutil; targets=[pathlib.Path('.pytest_cache'), pathlib.Path('.ruff_cache'), pathlib.Path('build'), pathlib.Path('dist')]; targets += list(pathlib.Path('.').rglob('__pycache__')); targets += list(pathlib.Path('.').glob('*.egg-info')); [shutil.rmtree(path, ignore_errors=True) for path in targets]"

serve:
	$(PYTHON) -m engram.cli serve --http

docker-build:
	$(DOCKER_COMPOSE) --profile sqlite --profile postgres build

docker-up: docker-up-sqlite

docker-up-sqlite:
	$(DOCKER_COMPOSE) --profile sqlite up --build

docker-up-postgres:
	$(DOCKER_COMPOSE) --profile postgres up --build

docker-down:
	$(DOCKER_COMPOSE) down

docker-logs:
	$(DOCKER_COMPOSE) logs -f
