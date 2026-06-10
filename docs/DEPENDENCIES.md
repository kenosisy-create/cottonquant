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
| pytest | Test runner. |
| ruff | Linting and import ordering. |
