.PHONY: install dev test lint format typecheck check docker-up docker-down

install:            ## install backend with dev deps into current venv
	pip install -e "backend[dev]"

dev:                ## run API with hot reload
	cd backend && uvicorn app.main:app --reload --port 8000

test:               ## run test suite
	cd backend && pytest

lint:               ## ruff checks
	cd backend && ruff check .

format:             ## auto-format
	cd backend && ruff format . && ruff check --fix .

typecheck:          ## mypy strict
	cd backend && mypy app

check: lint typecheck test   ## everything CI would run

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
