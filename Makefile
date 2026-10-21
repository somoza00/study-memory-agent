.PHONY: up down logs build config venv lint test frontend-build frontend-test

up:
	docker compose up -d --build
down:
	docker compose down
logs:
	docker compose logs -f
build:
	docker compose build
config:
	docker compose config -q

# --- Dev helpers ---
venv:
	cd backend && (test -d .venv || python3 -m venv .venv)
	cd backend && .venv/bin/pip install -e ".[dev]"
lint:
	cd backend && .venv/bin/ruff check app && .venv/bin/mypy app
test:
	cd backend && .venv/bin/ruff check app && .venv/bin/mypy app && .venv/bin/pytest
# O CI usa `npm ci` (o package-lock.json está commitado): `npm install` podia
# reescrever o lockfile localmente e mascarar um lock dessincronizado do
# package.json — a divergência só aparecia no CI, depois do push.
frontend-build:
	cd frontend && npm ci && npm run build
frontend-test:
	cd frontend && npm test