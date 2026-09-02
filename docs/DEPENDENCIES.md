# Dependencies

The D0 dependency set follows the project plan and keeps the stack local and
reviewable.

| Dependency | Purpose |
| --- | --- |
| pandas | Familiar dataframe fallback and fixture manipulation. |
| polars | Fast dataframe engine for local research tables. |
| pyarrow | Parquet IO for raw/core/research/archive artifacts. |
| duckdb | Local analytical queries over parquet artifacts. |
| pydantic | Typed config and manifest models. |
| pandera | Dataframe schema validation for core and research tables. |
| typer | Public CLI surface. |
| jinja2 | HTML report templates. |
| plotly | Report charts and interactive diagnostics. |
| openpyxl | Inspect manual Excel inputs and detect unrefreshed iFinD formula workbooks. |
| PyYAML | Parse nested, versioned strategy specifications and the strategy registry. |
| pytest | Test runner. |
| ruff | Linting and import ordering. |

## Reproducible Environment

The current reproducible baseline is CPython 3.12.10, recorded in
`.python-version`. `uv.lock` pins the complete dependency graph and package
checksums. The broad dependency declarations in `pyproject.toml` remain the
human-maintained compatibility intent; the lock file is the executable local
research environment.

On Windows, install `uv` once and synchronize the locked development
environment:

```powershell
py -3.12 -m pip install --user uv
py -3.12 -m uv sync --extra dev --frozen
```

Run commands inside that environment with `py -3.12 -m uv run`, for example:

```powershell
py -3.12 -m uv run python -m pytest
py -3.12 -m uv run python -m ruff check src tests
```

Dependency changes must update both `pyproject.toml` and `uv.lock`. CI or local
verification should run `py -3.12 -m uv lock --check` so an outdated lock file
cannot silently pass.

Do not use a blind `pip freeze` from a user-wide Python installation as the
project lock. It can include unrelated packages and does not describe optional
dependency intent.
