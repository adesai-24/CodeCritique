# CodeCritique

CodeCritique is a local development tool designed to evaluate your code before you push it to a GitHub repository. It acts as a final check to ensure code quality by integrating several static analysis tools into a single, unified feedback loop.

## Features

- **Integrated Linting**: Uses `Ruff` for style and error checking.
- **Type Checking**: Uses `Mypy` for static type analysis.
- **Security Auditing**: Uses `Bandit` to find common security vulnerabilities.
- **Coverage Reports**: Checks test coverage using `Coverage.py`.
- **Incremental Checking**: Optionally checks only the files that have changed in your current branch.
- **Severity Levels**: Categorizes issues into "Fatal" (blocks pushes) and "Warnings" (actionable feedback).

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/yourusername/CodeCritique.git
   cd CodeCritique
   ```

2. **Set up a virtual environment**:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -e .
   ```

## Usage

### Manual Check

Run the critique on only your modified files:

```bash
critique check
```

Run the critique on specific files:

```bash
critique check path/to/file.py
```

Run a full scan of all Python files in the repository:

```bash
critique check --no-incremental
```

### Git Hooks

To automate this tool, you can install it as a Git `pre-push` hook. This will prevent you from pushing code to GitHub if it contains any "Fatal" errors.

```bash
critique install-hooks
```

## Git Hooks Explained

The `install-hooks` command creates a script in `.git/hooks/pre-push`.

Each time you run `git push`, your computer automatically runs `critique check --incremental` first. If the tool finds critical issues (like a syntax error or security hole), it will return a failure code to Git, which then cancels your push. This ensures that only high-quality, verified code reaches your remote repository.

## Configuration

Currently, the tool uses default configurations for the underlying tools:

- **Coverage**: Hardcoded threshold of 80%.
- **Linter**: Uses the default Ruff configuration.
- **Incremental Mode**: Compares current branch changes against `origin/main`.

Future versions will support a `critique.toml` file for custom thresholds and rule exclusions.
