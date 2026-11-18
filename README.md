# ГРУЗСПЕЦСЕРВИС — бэкенд сайта (хакатон)

API сайта грузового автосервиса: заявки со статусом по ссылке, уведомления оператору и клиенту (e-mail,
Telegram с кнопками статусов), калькулятор, зона «выезд за 30 минут» для 2ГИС, отзывы с кейсами «до/после»,
ИИ-ассистент с передачей оператору, операторская админка.

```bash
cp .env.example .env
```

```bash
make dev
```

Это запуск без Docker (SQLite). `make up` поднимает PostgreSQL + API в Docker. После запуска: <http://localhost:8000/docs>.

Документация: [docs/README.md](docs/README.md) (установка на Linux Mint, ключи) ·
[ARCHITECTURE](docs/ARCHITECTURE.md) · [API](docs/API.md) · [FRONTEND_INTEGRATION](docs/FRONTEND_INTEGRATION.md) ·
[DEMO_SCRIPT](docs/DEMO_SCRIPT.md).
