# Установка, запуск, интеграции

Сайт (React, [`frontend/`](../frontend)) и REST API сайта грузового автосервиса ООО «ГРУЗСПЕЦСЕРВИС»: заявки всех типов со статусом по ссылке,
уведомления оператору (e-mail и Telegram с кнопками статусов) и клиенту, калькулятор «от N ₽»,
зона «выезд за 30 минут» для карты 2ГИС, отзывы с кейсами «до/после», ИИ-ассистент (OpenRouter)
с FAQ-режимом и передачей оператору, операторская админка.

| Документ | О чём |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | слои, потоки данных, решения, допущения, заглушки |
| [API.md](API.md) | обзор эндпоинтов, форматы, журнал изменений контракта |
| [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md) | как фронту подключиться: блоки сайта → эндпоинты, примеры |
| [DEMO_SCRIPT.md](DEMO_SCRIPT.md) | сценарий демонстрации жюри |
| [DEPLOY.md](DEPLOY.md) | тестовый запуск на ноутбуке и сервер Ubuntu 24.04 + домен + HTTPS |
| [EMAIL_AND_DOMAIN.md](EMAIL_AND_DOMAIN.md) | почта (Resend/Gmail), домен на Cloudflare |
| [openapi.json](openapi.json) | контракт (генерируется `make openapi`), живой — `/docs` |

Стек: Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async) + Alembic, PostgreSQL (SQLite для локального
запуска), SQLAdmin, httpx, Pillow. Качество: ruff, mypy `--strict`, pytest (120 тестов), pre-commit, GitHub Actions.
Фронт: React 18 + TypeScript + Vite, карта 2ГИС MapGL.

## Быстрый старт (Linux Mint / Ubuntu)

### Путь 1 — без Docker: `make dev` (SQLite, автоперезагрузка)

Нужен только [uv](https://docs.astral.sh/uv/) — он сам скачает Python 3.12 (версия зафиксирована в
`backend/.python-version` и `pyproject.toml`), системный Python Mint не используется.

```bash
sudo apt install -y make curl
```

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

(или `pipx install uv`). После установки откройте новый терминал, чтобы `~/.local/bin` попал в `PATH`.

```bash
cp .env.example .env
```

```bash
make dev
```

`make dev` = `uv sync` → `alembic upgrade head` → seed → uvicorn на <http://127.0.0.1:8000>.
Swagger: <http://127.0.0.1:8000/docs>, админка: <http://127.0.0.1:8000/admin> (пароль — `ADMIN_TOKEN` из `.env`;
пустой токен = админка выключена). Данные: `backend/var/` (SQLite, загрузки, письма dev-режима) — в `.gitignore`.

Сайт в режиме разработки (нужен Node.js 18.18+: `sudo apt install -y nodejs npm`) — во втором терминале:

```bash
make web
```

→ <http://localhost:5173> (Vite проксирует `/api` и `/media` на :8000, правки видны сразу).
Собрать сайт и запустить всё одним процессом, как на сервере, — `make preview` (см. [DEPLOY.md](DEPLOY.md)).

### Путь 2 — `docker compose up` (PostgreSQL + сайт + API, как на сервере)

```bash
cp .env.example .env
```

```bash
make up
```

`make up` — это `docker compose up --build` с вашими `UID/GID` (контейнер работает не от root). При старте
контейнер сам применяет миграции и подгружает недостающие seed-данные. Загрузки и письма лежат в именованном
volume `appdata`, а не в каталоге проекта, поэтому root-файлов в исходниках не появится. Порт: `API_PORT`
(по умолчанию 8000), сайт открывается там же: <http://localhost:8000>. Без `make`: `docker compose up --build`.

### Установка Docker Engine на Linux Mint

Официально Docker поддерживает Ubuntu, а не Mint («may work»). Репозиторий Ubuntu подходит, но в строке
репозитория нужен **`UBUNTU_CODENAME`** (например, `noble`), а не `VERSION_CODENAME` (у Mint своё имя, например
`zena`, которого в репозитории Docker нет). Команды сверены с <https://docs.docker.com/engine/install/ubuntu/>;
отличие одно — подставляем только `UBUNTU_CODENAME`:

```bash
sudo apt update && sudo apt install -y ca-certificates curl
```

```bash
sudo install -m 0755 -d /etc/apt/keyrings && sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "$UBUNTU_CODENAME")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
```

```bash
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

```bash
sudo usermod -aG docker $USER
```

После `usermod` **выйдите из сеанса и войдите снова** (или перезагрузитесь), затем проверьте:

```bash
docker run --rm hello-world
```

## Команды

`make help` выводит список. Основное:

| Команда | Что делает |
|---|---|
| `make dev` | API без Docker (SQLite) на :8000 |
| `make web` | сайт в режиме разработки на :5173 |
| `make preview` | собрать сайт и запустить сайт + API одним процессом на :8000 (виден в Wi-Fi) |
| `make up` / `make down` / `make logs` | Docker Compose (сайт + API + PostgreSQL) |
| `make prod-up` / `make prod-logs` / `make prod-backup` | сервер: + Caddy с HTTPS ([DEPLOY.md](DEPLOY.md)) |
| `make migrate` | `alembic upgrade head` |
| `make seed` | демо-данные; `make seed ARGS=--force` перезаписывает seed-контент (заявки не трогает) |
| `make test` | pytest (SQLite, все внешние интеграции — фейки) |
| `make check` | ruff + mypy --strict + pytest + tsc фронта — как в CI |
| `make openapi` | экспорт `docs/openapi.json` |
| `make geocode-sto` | координаты СТО через геокодер 2ГИС (см. ниже) |
| `make import-reviews FILE=…` | ручной импорт отзывов JSON/CSV |
| `make pre-commit` | установить git-хуки |

## Что нужно получить (ключи и адресаты)

Все параметры — только через окружение (`.env`, шаблон — `.env.example`). Секретов в репозитории нет.
Без каждого ключа система работает в dev-режиме:

| Переменная | Без неё |
|---|---|
| `OPENROUTER_API_KEY`, `LLM_MODEL` | ассистент работает в FAQ-режиме (правила + база знаний) |
| `TELEGRAM_BOT_TOKEN`, `BOT_USERNAME` | уведомления «в Telegram» пишутся в лог; кнопки привязки нет |
| `OPERATOR_INVITE_CODE` | операторы не могут зарегистрироваться в боте (`/operator <код>`) |
| `OPERATOR_TG_CHAT_ID` | нет запасного общего чата: если ни один оператор не на смене, заявки в Telegram не уходят |
| `SMTP_*` | письма сохраняются в `backend/var/mail/*.eml` (откройте любым почтовым клиентом) |
| `OPERATOR_EMAIL` | при SMTP — письма оператору не отправляются; без SMTP — пишутся в файл на `operator@localhost` |
| `ADMIN_TOKEN` | админка и `/api/v1/admin/*` выключены |
| `DGIS_API_KEY` | `/geo/*` отвечает 501, фронт ставит точку на карте вручную |
| `DGIS_MAPGL_KEY` | вместо карты 2ГИС — схема (клик по ней всё равно ставит точку). Ключ публичный, ограничьте его доменом в кабинете 2ГИС; можно тот же, что `DGIS_API_KEY` |
| `LLM_PROXY_URL` | OpenRouter отвечает `403` на российские IP: на ноутбуке в РФ укажите прокси v2rayN (`http://127.0.0.1:10809`), иначе чат работает в режиме FAQ. На сервере за рубежом — пусто |
| `PUBLIC_BASE_URL` | ссылки `/order/{token}` в письмах ведут на `localhost:5173` |
| `SECRET_KEY` | генерируется при старте (сессии админки и form_token сбросятся при перезапуске) |

Адресаты уведомлений (`OPERATOR_EMAIL`, `OPERATOR_TG_CHAT_ID`) **не имеют значений по умолчанию** — тестовые
заявки не уйдут по реквизитам с сайта-примера.

### Telegram: бот для клиентов и операторов
1. @BotFather → `/newbot` → токен в `TELEGRAM_BOT_TOKEN`, юзернейм (без @) в `BOT_USERNAME`.
   Там же `/setprivacy` → Disable (чтобы бот видел ответы операторов в группе).
2. Придумайте `OPERATOR_INVITE_CODE` и перезапустите API. Каждый оператор пишет боту `/operator <код>` —
   новые заявки будут приходить ему в личку. `/smena` — включить/выключить приём заявок, `/moi` — мои заявки.
3. По желанию — запасная группа: добавьте бота в группу, отправьте там `/chatid` → `OPERATOR_TG_CHAT_ID`.
   Туда идут заявки, когда ни один оператор не на смене.
4. Бот работает через long polling (`TELEGRAM_MODE=polling`), публичный URL не нужен.

Как это работает — в [ARCHITECTURE.md](ARCHITECTURE.md#telegram).

**Если Telegram недоступен с сервера** — задайте `TELEGRAM_PROXY_URL`: прокси используется только для
Telegram (2ГИС, OpenRouter и почта идут напрямую). Для v2rayN/xray на той же машине:
`http://127.0.0.1:10809` (HTTP) или `socks5://127.0.0.1:10808` (SOCKS5). В Docker `127.0.0.1` — это сам
контейнер: укажите `http://host.docker.internal:10809`, добавьте в сервис `api` строку
`extra_hosts: ["host.docker.internal:host-gateway"]` и включите в v2rayN «разрешить подключения из локальной сети».
Проверка: `curl -x http://127.0.0.1:10809 -s -o /dev/null -w "%{http_code}\n" https://api.telegram.org` → `302`.

### Координаты СТО: `make geocode-sto`
В seed координаты взяты из карточки организации в 2ГИС (`address.coordinates_source`). Если адрес сменится — с ключом 2ГИС:

```bash
make geocode-sto
```

Скрипт берёт адрес из `seeds/settings.json` (или `ARGS='--address "…"'`), обращается к Catalog API
(`GET https://catalog.api.2gis.com/3.0/items/geocode?q=…&fields=items.point`), **показывает найденные объекты
с координатами и расстоянием до центра Саратова** и записывает lat/lon в seed только после подтверждения.
`ARGS='--db'` — обновить ещё и уже заполненную БД. Ключ не печатается и не попадает в логи и тесты
(в тестах — мок геокодера).

## SPF/DKIM — чтобы письма не попадали в спам
Отправляйте с домена компании через его SMTP (Яндекс 360, Mail.ru для бизнеса, Unisender Go и т. п.) и
настройте DNS: **SPF** (`v=spf1 include:<провайдер> ~all`), **DKIM** (TXT-ключ из кабинета провайдера),
**DMARC** (`v=DMARC1; p=none; rua=mailto:…` для начала). `SMTP_FROM` должен быть на том же домене.
Не отправляйте с `@gmail.com`/`@yandex.ru` через чужой SMTP.

## Тесты

```bash
make test
```

Тесты используют реальные Alembic-миграции и seed (шаблонная SQLite-база копируется на каждый тест),
SMTP/Telegram/LLM/2ГИС заменены фейками. Покрыто: телефон, ИНН, согласие; заявка каждого типа; multipart и фото
(подмена расширения, большой файл, удаление EXIF/GPS, обход путей); идемпотентность; honeypot, form_token,
rate limit; конвейер статусов и уведомления; ссылка на заказ (чужой/неверный токен — одинаковый 404);
калькулятор; зона (внутри/по области/вне); Telegram-кнопки и привязка по deep-link; живой чат;
FAQ-режим без ключа; LLM tool calling, фолбэк при сбое и исчерпании бюджета; передача оператору только по просьбе.
Путь `docker compose up` (PostgreSQL + API) проверяется в CI на каждый пуш: подъём, смоук-тест
(заявка → страница заказа, bootstrap, калькулятор) и перезапуск без потери данных.
