# GRUZSPECSERVICE backend — run `make help`.
SHELL := /bin/bash
UV ?= uv
BE := cd backend &&
COMPOSE := UID=$$(id -u) GID=$$(id -g) docker compose

.DEFAULT_GOAL := help
.PHONY: help install dev migrate seed test lint format typecheck check openapi geocode-sto import-reviews test-email \
        up down logs pre-commit

help: ## Показать команды
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Установить зависимости (uv sync, Python 3.12 uv скачает сам)
	$(BE) $(UV) sync

dev: install migrate seed ## Запуск без Docker: SQLite + автоперезагрузка на :8000
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

check: lint typecheck test ## Всё сразу (как в CI)

test-email: ## Пробное письмо по настройкам SMTP_* из .env: make test-email TO=you@example.com
	$(BE) $(UV) run python -m scripts.send_test_email $(TO)

openapi: ## Экспорт контракта в docs/openapi.json
	$(BE) $(UV) run python -m scripts.export_openapi

geocode-sto: ## Координаты СТО через геокодер 2ГИС (нужен DGIS_API_KEY в .env)
	$(BE) $(UV) run python -m scripts.geocode_sto $(ARGS)

import-reviews: ## Импорт отзывов из JSON/CSV: make import-reviews FILE=reviews.csv
	$(BE) $(UV) run python -m scripts.import_reviews $(abspath $(FILE))

up: ## docker compose up (Postgres + API)
	$(COMPOSE) up --build

down: ## Остановить контейнеры
	$(COMPOSE) down

logs: ## Логи API
	$(COMPOSE) logs -f api

pre-commit: ## Установить git-хуки
	$(BE) $(UV) run pre-commit install --config ../.pre-commit-config.yaml
