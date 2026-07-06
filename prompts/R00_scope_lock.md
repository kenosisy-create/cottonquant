Read AGENTS.md and prompts/MASTER_RESEARCH_WORKBENCH.md.

Task:

Create or update docs/PROJECT_DIRECTION.md.

The document must explain:

1. This project is now a research-grade production data decision workbench, not
   a production-grade factor platform.
2. CF is the only production research target for now.
3. Engineering exists to support research correctness and daily trading
   analysis.
4. Platform features are downgraded or paused.
5. The current priority is real CF data -> core facts -> factors -> research
   backtest -> daily research brief.

Also update README.md with a short "Current Direction" section.

Do not remove existing platform documentation. Mark old platform documents as
historical architecture references.

Acceptance:

- docs/PROJECT_DIRECTION.md exists.
- README.md clearly states the new project direction.
- Existing D0-D23 work is referenced as foundation, not as the next execution
  path.
- No code behavior changes unless needed for documentation links.

Run:

```bash
python -m pytest
python -m ruff check src tests
```
