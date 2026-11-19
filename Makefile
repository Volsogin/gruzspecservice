# GRUZSPECSERVICE — run `make help`.
SHELL := /bin/bash
UV ?= uv
BE := cd backend &&
FE := cd frontend &&
COMPOSE := UID=$$(id -u) GID=$$(id -g) docker compose
PROD := $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml
# `make preview`: адрес, по которому сайт откроют другие (телефон в той же Wi-Fi, туннель)
PUBLIC_URL ?= http://localhost:$(PORT)
HOST ?= 0.0.0.0
PORT ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install dev migrate seed test lint format typecheck check openapi geocode-sto import-reviews test-email \
        web-install web web-build web-check preview up down logs prod-up prod-down prod-logs prod-backup pre-commit

help: ## Показать команды
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- бэкенд -----------------------------------------------------------------------------------------
install: ## Зависимости бэкенда (uv sync, Python 3.12 uv скачает сам)
	$(BE) $(UV) sync

dev: install migrate seed ## API без Docker: SQLite + автоперезагрузка на :8000
	$(BE) $(UV) run uvicorn app.main:app_factory --factory --reload --host 127.0.0.1 --port 8000

migrate: ## Применить миграции Alembic
	$(BE) mkdir -p var && $(UV) run alembic upgrade head

seed: ## Загрузить демо-данные (ARGS=--force — перезаписать seed-контент)
	$(BE) $(UV) run python -m scripts.seed $(ARGS)

test: ## Тесты (pytest), ARGS — доп. аргументы
	$(BE) $(UV) run pytest $(ARGS)

lint: ## ruff check + format --check
	$(BE) $(UV) run ruff check . && $(UV) run ruff format --check .

format: ## Автоисправление и форматирование
	$(BE) $(UV) run ruff check --fix . && $(UV) run ruff format .

typecheck: ## mypy --strict
	$(BE) $(UV) run mypy app scripts

check: lint typecheck test web-check ## Всё сразу (как в CI)

test-email: ## Пробное письмо по настройкам SMTP_* из .env: make test-email TO=you@example.com
	$(BE) $(UV) run python -m scripts.send_test_email $(TO)

openapi: ## Экспорт контракта в docs/openapi.json
	$(BE) $(UV) run python -m scripts.export_openapi

geocode-sto: ## Координаты СТО через геокодер 2ГИС (нужен DGIS_API_KEY в .env)
	$(BE) $(UV) run python -m scripts.geocode_sto $(ARGS)

import-reviews: ## Импорт отзывов из JSON/CSV: make import-reviews FILE=reviews.csv
	$(BE) $(UV) run python -m scripts.import_reviews $(abspath $(FILE))

# --- фронтенд ---------------------------------------------------------------------------------------
web-install: ## Зависимости фронта (npm ci)
	$(FE) npm ci --no-audit --no-fund

web: ## Фронт в режиме разработки на :5173 (нужен запущенный `make dev`)
	@test -d frontend/node_modules || $(MAKE) web-install
	$(FE) npm run dev

web-build: ## Собрать фронт в frontend/dist
	@test -d frontend/node_modules || $(MAKE) web-install
	$(FE) npm run build

web-check: ## Проверка типов фронта (tsc)
	@test -d frontend/node_modules || $(MAKE) web-install
	$(FE) npm run typecheck

# --- тестовый запуск на ноутбуке (без Docker) -------------------------------------------------------
preview: install web-build migrate seed ## Сайт + API одним процессом на :8000, виден в локальной сети
	@echo ""
	@echo "  Сайт:     http://localhost:$(PORT)   (с телефона: http://$$(hostname -I | awk '{print $$1}'):$(PORT))"
	@echo "  Админка:  http://localhost:$(PORT)/admin   Swagger: http://localhost:$(PORT)/docs"
	@echo "  Ссылки в письмах/Telegram ведут на PUBLIC_URL=$(PUBLIC_URL)"
	@echo ""
	$(BE) FRONTEND_DIST_DIR=$(abspath frontend/dist) PUBLIC_BASE_URL=$(PUBLIC_URL) API_BASE_URL=$(PUBLIC_URL) \
	    $(UV) run uvicorn app.main:app_factory --factory --host $(HOST) --port $(PORT) --proxy-headers

# --- Docker -----------------------------------------------------------------------------------------
up: ## docker compose up (PostgreSQL + сайт + API на :8000)
	$(COMPOSE) up --build

down: ## Остановить контейнеры
	$(COMPOSE) down

logs: ## Логи API
	$(COMPOSE) logs -f api

prod-up: ## Сервер: PostgreSQL + сайт/API + Caddy (HTTPS для DOMAIN из .env), в фоне
	@grep -q '^DOMAIN=.' .env || { echo "Укажите DOMAIN=ваш-домен.ru в .env (см. docs/DEPLOY.md)"; exit 1; }
	$(PROD) up -d --build
	$(PROD) ps

prod-down: ## Сервер: остановить
	$(PROD) down

prod-logs: ## Сервер: логи API и Caddy
	$(PROD) logs -f --tail=200 api caddy

prod-backup: ## Сервер: дамп БД в backups/ (gzip)
	mkdir -p backups
	$(PROD) exec -T db pg_dump -U gruzspec gruzspec | gzip > backups/gruzspec-$$(date +%Y%m%d-%H%M).sql.gz
	@ls -lh backups | tail -3

pre-commit: ## Установить git-хуки
	$(BE) $(UV) run pre-commit install --config ../.pre-commit-config.yaml
