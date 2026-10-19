install:
	python -m pip install --upgrade pip &&\
		python -m pip install -r requirements.txt


setup: install


test:
	PYTHONPATH=src python -m pytest -vv --cov=telemetry tests/


profile:
	PYTHONPATH=src python scripts/profile_studies.py


replay:
	PYTHONPATH=src python scripts/replay.py


evaluate:
	PYTHONPATH=src python scripts/evaluate.py


sweep:
	PYTHONPATH=src python scripts/sweep.py


results: replay evaluate


cloud-sizing:
	PYTHONPATH=src python scripts/cloud_sizing.py


format:
	black src/ tests/ scripts/

format-check:
	black --check src/ tests/ scripts/


lint:
	PYTHONPATH=src python -m pylint --disable=R,C src/telemetry
	# Every module, class and function needs a docstring, tests included.
	PYTHONPATH=src python -m pylint --disable=all \
		--enable=missing-module-docstring,missing-class-docstring,missing-function-docstring \
		src scripts tests


all: install format lint test
