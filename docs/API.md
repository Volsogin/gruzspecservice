# API

База: `/api/v1`. Живая документация — `/docs` (Swagger) и `/redoc`; файл контракта — [openapi.json](openapi.json)
(`make openapi`). У каждого эндпоинта есть summary/description и примеры.

## Общие правила
- JSON в UTF-8; время — ISO 8601 в UTC (`…+00:00`); деньги — целые рубли.
- Ошибки всегда так:
  ```json
  {"error": {"code": "validation_error", "message": "Проверьте правильность заполнения полей",
             "fields": {"phone": "Укажите телефон в формате +7 XXX XXX XX XX"}}}
  ```
  Коды: `validation_error` (422), `not_found` (404), `conflict` / `invalid_transition` / `idempotency_conflict`
  (409), `rate_limited` / `chat_limit` (429, заголовок `Retry-After`), `payload_too_large` (413),
  `rejected` / `form_token_*` / `form_too_fast` (400), `unauthorized` (401), `not_configured` (501),
  `upstream_error` (502), `internal_error` (500).
- Каждый ответ несёт `X-Request-ID` (можно прислать свой).

## Эндпоинты

| Метод и путь | Назначение |
|---|---|
| `GET /healthz`, `GET /readyz` | liveness; readiness (БД + какие интеграции включены) |
| `GET /bootstrap` | всё для первого экрана: settings, services, stats, топ-отзывы, work_status, зона, марки. ETag/304, br/gzip |
| `GET /settings/public` | контакты, мессенджеры, адрес+координаты, режим и `work_status`, статистика, гарантия, `review_links` |
| `GET /services` | лента услуг; у карточки `form_type` и `prefill` |
| `GET /forms`, `GET /forms/{form_type}` | типы форм; схема полей + `form_token` + текст и версия согласия |
| `POST /leads` | заявка любого типа (multipart с `photos` или JSON); `Idempotency-Key` |
| `GET /orders/{public_token}` | статус, шаги, история, сводка (телефон маскирован, фото-превью) |
| `GET /calculator/options` | марки, типы техники, типы работ, надбавки |
| `POST /calculator/estimate` | `{brand, work_type, vehicle_type?, urgent?, onsite?}` → «от N ₽» + `estimate_id` |
| `GET /dispatch/zone` | центр, радиус, ETA, подпись, GeoJSON круга |
| `POST /dispatch/check` | `{lat, lon}` → `inside` / `region` / `outside` |
| `POST /geo/geocode`, `POST /geo/reverse` | прокси к геокодеру 2ГИС с кэшем (501 без ключа) |
| `GET /reviews` | отзывы, `limit/offset/source/min_rating` |
| `GET /reviews/summary` | средний рейтинг, счётчики по площадкам, ссылки на Яндекс/2ГИС |
| `GET /cases/{id}` | данные заказа и фото «до/после» для раскрытия отзыва |
| `GET /legal/privacy` | политика ПДн (заглушка), версия согласия |
| `POST /chat/sessions` | начать диалог (`consent`) |
| `POST /chat/sessions/{id}/messages` | сообщение → SSE-поток (`?stream=false` → JSON) |
| `GET /chat/sessions/{id}/messages` | история (`after_id`) |
| `POST /chat/sessions/{id}/handoff` | кнопка «Позвать оператора» |
| `GET /chat/sessions/{id}/events` | SSE: ответы живого оператора |
| `POST /chat/sessions/{id}/close` | завершить диалог |
| `GET /admin/leads`, `GET /admin/leads/{id}` | заявки (Bearer `ADMIN_TOKEN`) |
| `POST /admin/leads/{id}/status` | смена статуса `{status, comment?}` |
| `GET /admin/outbox` | очередь уведомлений |
| `GET /admin/settings`, `PUT /admin/settings/{key}` | настройки сайта |
| `POST /telegram/webhook` | для режима webhook (скрыт из схемы, проверяет секрет) |

Статусы: `new` «Заявка получена» → `accepted` «Принята мастером» → `on_the_way` «Мастер выехал к вам»
(только `onsite`/`tow`) → `in_progress` «Работы выполняются» → `completed` «Готово»; `cancelled` «Отменена».

Типы заявок: `repair`, `onsite`, `tow`, `parts`, `corporate`, `callback` (публичные формы) и `chat_handoff`
(создаёт ассистент). Источник (`source`): `form`, `calculator` (если передан `estimate_id`), `chatbot`.

## Журнал изменений контракта
| Версия | Дата | Изменение |
|---|---|---|
| 1.0.0 | 2026-11-18 | Первая версия контракта (до получения макетов фронта) |
| 1.2.0 | 2026-11-19 | Фронт подключён. `settings/public`: `maps` `{provider, mapgl_key, style}` (ключ MapGL из `DGIS_MAPGL_KEY`), `company.requisites` `{inn, kpp, ogrn, vat}` (пустые не показываются), 9 преимуществ. `orders/{token}`: `summary.vehicle_type_label`, `summary.estimate` теперь полный `{price_from, price_label, breakdown, input}`. `legal/privacy`: `sections[]`. Корпоративная форма: `fleet_size` — выбор из `1-5`, `6-20`, `21-50`, `50+` (было число). Сайт раздаётся тем же сервером: неизвестные пути под `/api`, `/media`, `/admin` — JSON 404, остальные — `index.html` |
| 1.3.0 | 2026-11-20 | `POST /leads`: `telegram_bound` — клиент уже нажимал «Start» в боте (тот же @ник из формы или телефон, подтверждённый кнопкой «Контакт»): заявка сразу привязана к его чату и бот прислал «Заявка принята». Иначе, как раньше, — кнопка `telegram_bind_url` |
| 1.1.0 | 2026-11-18 | `settings/public` и `bootstrap.settings`: новое поле `telegram_bot` `{username, url}` (или `null`) — ссылка «Написать в Telegram»; подсказка у поля формы `telegram_username` |
| 1.0.1 | 2026-11-18 | `review_links`: общий флаг `is_placeholder` заменён списком `placeholders` (сейчас `["yandex"]`); ссылка `2gis` ведёт на реальную карточку |
