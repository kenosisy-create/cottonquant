PYTHON ?= py -3.12

.PHONY: install lint test smoke clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check src tests

test:
	$(PYTHON) -m pytest

smoke:
	$(PYTHON) -m cotton_factor.cli.main smoke cf --start 2024-01-01 --end 2024-01-05 --dry-run

clean:
	$(PYTHON) -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache', '.ruff_cache', 'build', 'dist']]"
