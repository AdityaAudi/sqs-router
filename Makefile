.PHONY: install test lint build publish clean

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check src/ tests/

build:
	python -m build

publish:
	twine upload dist/*

clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .pytest_cache __pycache__
