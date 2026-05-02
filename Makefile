.PHONY: setup run-cli run-server test clean

setup:
	python -m venv .venv
	.\.venv\Scripts\activate && pip install -r requirements.txt
	copy .env.sample .env

run-cli:
	python main.py --mode cli

run-server:
	python main.py --mode server

test:
	pytest tests/

clean:
	rm -rf __pycache__ .pytest_cache memories.db
