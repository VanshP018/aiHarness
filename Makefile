PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON = $(VENV)/bin/python

.PHONY: setup run test clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e .

run:
	$(VENV_PYTHON) -m aiharness $(ARGS)

test:
	$(VENV_PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf $(VENV) build dist *.egg-info src/*.egg-info __pycache__
