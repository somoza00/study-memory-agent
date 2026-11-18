.PHONY: up down logs build config venv lint test frontend-build frontend-test docker-build scan audit ci

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

# Espelha o job `dependency-audit` do CI: pip-audit quebra o build quando há
# CVE conhecida nas deps resolvidas. O pip-audit não é dev-dependency (o CI
# instala na hora), então o alvo faz o mesmo. `--skip-editable`: o próprio
# pacote local não existe no PyPI para ser auditado.
audit:
	cd backend && .venv/bin/pip install --upgrade pip \
		&& .venv/bin/pip install "pip-audit>=2.7.0" && .venv/bin/pip-audit --skip-editable

# Espelha o job `docker-build` do CI: as DUAS imagens, com as mesmas tags de
# lá. Antes, um Dockerfile quebrado (COPY de arquivo renomeado, dependência
# faltando no pyproject, `[local-embeddings]` sem as libs de sistema do
# onnxruntime) passava por ruff/mypy/pytest e só aparecia em `docker compose
# up` — `make build` builda via compose, não valida o build isolado de cada
# imagem como o CI faz.
docker-build:
	docker build -t sma-backend:ci ./backend
	docker build -t sma-frontend:ci ./frontend

# Espelha os passos de Trivy do job `docker-build` do CI: as imagens eram
# construídas mas nunca varridas, então uma CVE CRITICAL/HIGH na base
# (python-slim, node-alpine) ou numa wheel do `[local-embeddings]`
# (fastembed/onnxruntime) só aparecia se alguém rodasse o scanner na mão.
# Os repos irmãos (myown-llm-gateway, evaluation-framework) já têm este alvo.
# O Trivy é ferramenta externa (não é dev-dependency): o alvo falha com a
# instrução de instalação em vez de fingir que varreu. Informativo
# (exit-code 0), como no CI.
scan: docker-build
	@command -v trivy >/dev/null 2>&1 || { \
		echo "trivy nao encontrado: instale (ex.: 'pacman -S trivy', 'brew install trivy')"; \
		echo "ou rode: docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy image --severity CRITICAL,HIGH sma-backend:ci"; \
		exit 1; }
	trivy image --severity CRITICAL,HIGH --exit-code 0 sma-backend:ci
	trivy image --severity CRITICAL,HIGH --exit-code 0 sma-frontend:ci

# Roda o CI inteiro, na mesma ordem do .github/workflows/ci.yml: validação do
# compose, backend (ruff + mypy + pytest), auditoria de CVE das deps, frontend
# (npm ci + build + test) e as imagens Docker. O `config` entrou na lista quando
# o CI passou a ter o job `compose-config` — antes o compose só era validado se
# alguém lembrasse de rodar `make config` na mão.
ci: config test audit frontend-build frontend-test docker-build
