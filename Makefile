PYTHON ?= python3.11
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYTHON_BIN := $(VENV)/bin/python

.PHONY: venv test run format lint

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

test:
	$(PYTHON_BIN) -m pytest

run:
	$(VENV)/bin/csv-clean --input examples/customers_small.csv --output-dir out

format:
	$(VENV)/bin/ruff check src tests --fix
	$(VENV)/bin/black src tests

lint:
	$(VENV)/bin/ruff check src tests
