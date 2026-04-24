# Developer Setup Guide

Welcome to Engram development. This guide walks through setting up a local environment for contributing code to the project.

## Prerequisites

Before you start, make sure you have:

- Python 3.11 or higher
- Git
- Make
- A code editor such as VS Code or PyCharm
- Docker, optional for container-based development
- PostgreSQL, optional for testing the `ENGRAM_DB_URL` workflow

Verify the core tools:

```bash
python --version
git --version
make help
```

Local development uses SQLite by default, so PostgreSQL is only needed when you are explicitly testing the team-mode database path.

## Fork and Clone

1. Fork the repository on GitHub.
2. Clone your fork:

```bash
git clone https://github.com/YOUR-USERNAME/Engram.git
cd Engram
```

3. Add the upstream remote:

```bash
git remote add upstream https://github.com/Agentscreator/engram-memory.git
git remote -v
```

Replace `YOUR-USERNAME` with your GitHub username.

## Set Up Python

Create and activate a virtual environment.

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
python3.11 -m venv venv
source venv/bin/activate
```

Then install Engram and development dependencies:

```bash
make install
```

This installs Engram in editable mode, project dependencies, and development tools such as pytest and ruff.

If your machine has multiple Python installations, pin the interpreter explicitly:

```bash
make install PYTHON=/path/to/python
make test PYTHON=/path/to/python
```

## Verify the Setup

Check that Engram imports correctly:

```bash
python -c "import engram; print('Engram imported successfully')"
```

Run the local HTTP MCP server:

```bash
make serve
```

Open the local dashboard at:

```text
http://127.0.0.1:7474/dashboard
```

Press `Ctrl+C` to stop the server.

## Common Commands

Use the root `Makefile` as the canonical command entry point:

```bash
make help
```

Common targets:

```bash
make install        # Install development dependencies
make test           # Run CI-style tests
make lint           # Run ruff lint checks
make format         # Format Python files with ruff
make format-check   # Check formatting without writing changes
make check          # Run lint, format-check, and tests
make build          # Build Python package artifacts
make clean          # Remove local build/cache artifacts
make serve          # Run the local HTTP MCP server
```

Docker targets:

```bash
make docker-build
make docker-up
make docker-up-sqlite
make docker-up-postgres
make docker-down
make docker-logs
```

`make docker-up` starts the SQLite profile by default. Use `make docker-up-postgres` when you need the PostgreSQL profile.

## Development Workflow

Create a feature branch before making changes:

```bash
git checkout main
git pull upstream main
git checkout -b feature/your-feature-name
```

Good branch names:

- `fix/conflict-detection-threshold`
- `docs/add-troubleshooting-guide`
- `feature/improve-entity-extraction`

Make your changes in the relevant area:

- Core logic: `src/engram/`
- Tests: `tests/`
- Documentation: `docs/`, `README.md`, or contributor docs

Before opening a PR, run:

```bash
make check
```

For focused testing:

```bash
make test
make test TEST_ARGS="tests/test_file.py::test_name -vv -s"
```

## Commit and Push

Review your changes:

```bash
git status
git diff
```

Stage and commit:

```bash
git add <changed-files>
git commit -m "docs: update developer setup workflow"
```

Use conventional commit prefixes such as `fix:`, `feat:`, `docs:`, `test:`, or `chore:`.

Push your branch:

```bash
git push origin feature/your-feature-name
```

## Submit a Pull Request

1. Open your fork on GitHub.
2. Click **Compare & pull request**.
3. Explain what changed, why it changed, and how you tested it.
4. Create the pull request.

If maintainers request changes, update your branch and push again. The PR updates automatically.

## Troubleshooting

### `make install` fails

Make sure you are in the repository root and your virtual environment is active:

```bash
cd Engram
make install
```

### `ModuleNotFoundError: No module named 'engram'`

Reinstall the editable package:

```bash
make install
```

### Tests fail with missing database tables

Initialize the local database, then rerun tests:

```bash
python -m engram --init-db
make test
```

### Docker services do not start

Check Docker is running and inspect the logs:

```bash
docker --version
make docker-logs
```

For PostgreSQL profile testing, set required overrides in a local `.env` file and never commit secrets.

## Next Steps

1. Read [docs/IMPLEMENTATION.md](./IMPLEMENTATION.md).
2. Review [CONTRIBUTING.md](../CONTRIBUTING.md).
3. Open a GitHub Discussion if you need design alignment before implementing.
