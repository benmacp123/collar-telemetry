install:
	python -m pip install --upgrade pip &&\
		python -m pip install -r requirements.txt


setup: install


test:
	PYTHONPATH=src python -m pytest -vv --cov=telemetry tests/


format:
	black src/ tests/ scripts/

format-check:
	black --check src/ tests/ scripts/


lint:
	PYTHONPATH=src python -m pylint --disable=R,C src/telemetry


all: install format lint test
