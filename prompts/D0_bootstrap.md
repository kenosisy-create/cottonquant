Read prompts/MASTER_ORCHESTRATOR.md and implement D0.

Tasks:
1. Create the repository skeleton exactly following the target structure.
2. Create AGENTS.md with the project rules.
3. Create pyproject.toml for Python 3.11+ with minimal dependencies:
   pandas, polars, pyarrow, duckdb, pydantic, pandera, typer, jinja2, plotly,
   pytest, ruff.
4. Create src/cotton_factor/cli/main.py with a Typer CLI placeholder.
5. Create Makefile targets: install, lint, test, smoke, clean.
6. Create docs/ARCHITECTURE.md summarizing four-layer architecture and T+1 rule.
7. Create configs/products/CF.yaml, SR.yaml, AP.yaml, M.yaml, C.yaml, Y.yaml with
   placeholder product metadata.
8. Run tests and ruff.

Acceptance:
- python -m pytest passes.
- python -m ruff check src tests passes.
- python -m cotton_factor.cli.main --help or equivalent CLI help works.
