# `make env data test`. On Windows without make, run the same lines by hand;
# each target is a single command.
PY ?= .venv/bin/python
ifeq ($(OS),Windows_NT)
PY = .venv/Scripts/python
endif

.PHONY: all env data test rain_check terrain figures

all: data test rain_check terrain figures

env:
	uv venv --python 3.12 .venv && uv pip install --python $(PY) -r requirements.txt

data:
	$(PY) scripts/fetch.py all

test:
	$(PY) -m pytest -q tests

rain_check:
	$(PY) scripts/rain_check.py

terrain:
	$(PY) -m studies.ahmedabad.terrain all

figures:
	$(PY) -m studies.ahmedabad.figures_terrain all
