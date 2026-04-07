# Developer Setup Guide

Welcome to Engram development! This guide walks you through setting up your local environment to contribute code to the project.

## Prerequisites

Before you start, make sure you have:

- **Python 3.11 or higher**
  \\\ash
  python --version
  \\\

- **Git** (for version control)
  \\\ash
  git --version
  \\\

- **A code editor** (VS Code, PyCharm, or similar)

- **PostgreSQL** (optional, for team-mode testing)
  - Local development works with SQLite by default
  - Only needed if you're testing the \ENGRAM_DB_URL\ workflow


## Part 1: Fork and Clone the Repository

### 1.1 Fork on GitHub

1. Go to https://github.com/imadahmad9507-ops/Engram
2. Click the **Fork** button (top-right corner)
3. Select your GitHub username as the owner
4. Click **Create fork**

### 1.2 Clone Your Fork

\\\ash
git clone https://github.com/YOUR-USERNAME/Engram.git
cd Engram
\\\

Replace \YOUR-USERNAME\ with your actual GitHub username.

### 1.3 Add Upstream Reference

This lets you stay in sync with the main repository:

\\\ash
git remote add upstream https://github.com/imadahmad9507-ops/Engram.git
git remote -v  # Verify both origin and upstream are configured
\\\


## Part 2: Set Up Your Development Environment

### 2.1 Create a Python Virtual Environment

A virtual environment isolates project dependencies from your system Python.

**On Windows (PowerShell):**
\\\powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
\\\

**On macOS / Linux:**
\\\ash
python3.11 -m venv venv
source venv/bin/activate
\\\

You should see \(venv)\ appear at the start of your terminal prompt.

### 2.2 Upgrade pip

\\\ash
pip install --upgrade pip
\\\

### 2.3 Install Dependencies (with dev tools)

\\\ash
pip install -e ".[dev]"
\\\

This installs:
- Engram itself in editable mode (changes to code take effect immediately)
- All required dependencies
- Development tools for testing and linting


## Part 3: Verify the Setup

### 3.1 Check Python Path

\\\ash
where python       # Windows
which python       # macOS/Linux
\\\

### 3.2 Check Imports

\\\ash
python -c "import engram; print('✓ Engram imported successfully')"
\\\

### 3.3 Run the MCP Server Locally

\\\ash
python -m engram
\\\

Press \Ctrl+C\ to stop it.


## Part 4: Run Tests

### 4.1 Run All Tests

\\\ash
pytest tests/
\\\

### 4.2 Run Tests with Coverage Report

\\\ash
pytest tests/ --cov=src/engram
\\\

### 4.3 Run a Specific Test File

\\\ash
pytest tests/test_commit.py -v
\\\


## Part 5: Create a Feature Branch

Before making changes, create a branch:

\\\ash
# Update main from upstream
git checkout main
git pull upstream main

# Create your feature branch
git checkout -b feature/your-feature-name
\\\

**Good branch names:**
- \ix/conflict-detection-threshold\
- \docs/add-troubleshooting-guide\
- \eature/improve-entity-extraction\


## Part 6: Make Changes and Test

### 6.1 Edit Code

Make your changes in:
- Core logic: \/src/engram/\
- Tests: \/tests/\
- Documentation: \/docs/\ or \README.md\

### 6.2 Run Tests After Each Change

\\\ash
pytest tests/ --tb=short
\\\

### 6.3 Check Code Style (Optional)

\\\ash
# Format code
black src/engram tests/

# Check linting
flake8 src/engram tests/
\\\


## Part 7: Commit Your Work

### 7.1 Stage and Commit

\\\ash
# See what changed
git status

# Stage your changes
git add src/engram/ tests/

# Commit with a clear message
git commit -m "docs: add developer setup guide with troubleshooting section"
\\\

**Commit message format:**
- Start with \ix:\, \eat:\, \docs:\, \	est:\, or \chore:\
- First line: short summary (50 chars max)
- Add blank line + details if needed

### 7.2 Push to Your Fork

\\\ash
git push origin feature/your-feature-name
\\\


## Part 8: Submit a Pull Request

### 8.1 Open a PR on GitHub

1. Go to https://github.com/YOUR-USERNAME/Engram
2. Click **Compare & pull request**
3. Fill in the PR description explaining what you changed and why
4. Click **Create Pull Request**

### 8.2 Respond to Reviews

If maintainers suggest changes:
1. Make the changes on your branch
2. Commit: \git commit -am "Update based on review feedback"\
3. Push: \git push origin feature/your-feature-name\
4. The PR updates automatically


## Troubleshooting

### "pip install -e fails"

**Solution:**
Make sure you're in the \Engram\ directory and your venv is activated:
\\\ash
cd Engram
.\venv\Scripts\Activate.ps1  # Windows PowerShell
source venv/bin/activate     # macOS/Linux
pip install -e ".[dev]"
\\\

### "ModuleNotFoundError: No module named 'engram'"

**Solution:**
Reinstall in editable mode:
\\\ash
pip install -e ".[dev]" --force-reinstall
\\\

### "Tests fail with 'No such table: facts'"

**Solution:**
Initialize the database:
\\\ash
python -m engram --init-db
pytest tests/
\\\

### "Permission denied: install.sh"

**Solution:**
\\\ash
chmod +x install.sh
./install.sh
\\\


## Common Workflows

### Sync Your Fork with Latest Changes

\\\ash
git fetch upstream
git rebase upstream/main
git push origin main
\\\

### Run a Specific Test with Debug Output

\\\ash
pytest tests/test_file.py::test_name -vv -s
\\\


## Next Steps

1. **Read the Architecture:** See [docs/IMPLEMENTATION.md](./IMPLEMENTATION.md)
2. **Check Contribution Guidelines:** See [CONTRIBUTING.md](../CONTRIBUTING.md)
3. **Ask Questions:** Open a GitHub Discussion if needed

---

**Welcome to Engram development! We're glad you're here.** 🎉
