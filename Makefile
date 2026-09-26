# `make env data test`. On Windows without make, run the same lines by hand;
# each target is a single command.
PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY = .venv/Scripts/python
endif

.PHONY: all env data test

all: data test

env:
	uv venv --python 3.12 .venv && uv pip install --python $(PY) -r requirements.txt

data:
	$(PY) scripts/fetch.py all

test:
	$(PY) -m pytest -q tests
