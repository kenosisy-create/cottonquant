Read the repository in read-only mode.

Task:

Create docs/CURRENT_STATE_RESEARCH_MAP.md.

Map existing modules into the new research workflow:

1. Production data ingestion candidates
2. Raw preservation
3. Core quote table
4. Contract master
5. Chain map
6. Trade mapping
7. Continuous price
8. Factors
9. Forward returns
10. Backtest
11. Reports
12. Archive/logging

For each module, classify:

- USE_AS_IS
- REUSE_WITH_SIMPLIFICATION
- KEEP_BUT_NOT_PRIORITY
- PAUSE
- MISSING

Also identify:

- files likely useful for the research path
- files likely platform-heavy
- missing CF production data components
- missing daily research report components

Do not edit code for this task.

Acceptance:

- docs/CURRENT_STATE_RESEARCH_MAP.md exists.
- It gives a clear next implementation order.
- It does not recommend platform hardening as the next priority.

Run:

```bash
python -m pytest
python -m ruff check src tests
```
