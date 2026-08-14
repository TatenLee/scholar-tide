PYTHON ?= python3
VENV = .venv
BIN = $(VENV)/bin

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -e ".[all]"

.PHONY: setup
setup: $(BIN)/python
	@echo "venv ready. activate with: source $(VENV)/bin/activate"

.PHONY: build
build: $(BIN)/python
	$(BIN)/python -m engine build --use-embed

.PHONY: build-plain
build-plain: $(BIN)/python
	$(BIN)/python -m engine build

.PHONY: serve
serve: $(BIN)/python
	$(BIN)/python -m engine serve

.PHONY: spiders
spiders: $(BIN)/python
	$(BIN)/python -m engine spiders

.PHONY: clean
clean:
	rm -rf $(VENV) output.md output.json
