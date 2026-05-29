.PHONY: install dev test fmt lint samples api worker web docker compose-up clean

install:
	uv sync || true
	uv pip install -e packages/common -e packages/ocr -e packages/classify -e packages/extract \
	               -e packages/route -e packages/store -e cli

dev: install
	cp -n .env.example .env || true
	python3 scripts/make_samples.py

test:
	pytest -q

fmt:
	ruff format .

lint:
	ruff check .

samples:
	python3 scripts/make_samples.py

api:
	uv run uvicorn services.api.app.main:app --reload --port 7441

worker:
	uv run python -m services.worker.app.main

web:
	cd web && npm install && npm run dev

docker:
	docker build -f infra/docker/Dockerfile -t shotclassify-api:dev .
	docker build -f infra/docker/Dockerfile.worker -t shotclassify-worker:dev .
	docker build -f infra/docker/Dockerfile.web -t shotclassify-web:dev .

compose-up:
	docker compose -f infra/docker/docker-compose.dev.yml up --build

clean:
	rm -rf .venv .pytest_cache .ruff_cache **/__pycache__ shotclassify.db storage
