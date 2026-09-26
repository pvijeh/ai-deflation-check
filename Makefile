all: fetch analyze

fetch:
	uv run python scripts/fetch_incidents.py
	uv run python scripts/fetch_prices.py
	uv run python scripts/fetch_sec.py
	uv run python scripts/fetch_ai_spend.py
	uv run python scripts/fetch_productivity.py

analyze:
	uv run python scripts/analyze.py

lint:
	uvx ruff check scripts

.PHONY: all fetch analyze lint
