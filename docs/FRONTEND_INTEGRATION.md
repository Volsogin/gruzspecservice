# Подключение фронтенда

Бэкенд — contract-first: всё ниже есть в `/docs` и `docs/openapi.json` (можно сгенерировать типы, например
`npx openapi-typescript docs/openapi.json -o src/api.d.ts`). База API: `VITE_API_URL=http://localhost:8000/api/v1`.

**Что нужно от фронта/команды:**
- Ключ **2ГИС MapGL** для карты — на фронте. Этот ключ виден в браузере: **не коммитьте его в репозиторий фронта
  без ограничения по домену** (в кабинете 2ГИС ограничьте ключ доменами сайта). Ключ геокодера бэкенда
  (`DGIS_API_KEY`) — отдельно, только в `.env` бэкенда.
- Страница **`/order/{token}`** (статус заявки по ссылке) — **должна быть в макете**: на неё ведут ссылки из
  экрана подтверждения, писем и Telegram. Если её в макете нет — скажите, обсудим.
- Origin фронта — в `CORS_ORIGINS` бэкенда; его адрес — в `PUBLIC_BASE_URL` (из него строятся ссылки).

## 1. Первый экран
`GET /bootstrap` — одним запросом: `settings` (контакты, адрес+координаты, мессенджеры, статистика, гарантия,
преимущества, ссылки на отзывы, согласие), `work_status` (`is_open`, `label`), `services`, `stats`,
`reviews.summary` + `reviews.top` (6 шт.), `brands` (лента «Мы ремонтируем»), `dispatch_zone`, `forms`.
Отвечает с `ETag` — браузер сам пришлёт `If-None-Match` и получит 304. Статистика помечена `is_demo: true`.

## 2. Лента услуг → предзаполненная форма
```
GET /services → [{slug, title, short_description, items[], badge, is_24_7, form_type, prefill}, …]
```
Клик по карточке: прокрутить к форме и загрузить её схему:
```
GET /forms/{form_type}   (form_type из карточки)
→ {form_type, title, submit_label, location_mode: "sto"|"onsite", callback_eta_minutes,
   fields: [{name, type, label, required, placeholder?, help?, options?, mask?, required_if?, max_files?,
             options_source?, wire_fields?}],
   hidden_fields: ["service_slug","estimate_id","source","form_token","website"],
   form_token, consent: {version, text, privacy_url}}
```
Значения из `prefill` (`lead_type`, `service_slug`, …) подставьте в форму/скрытые поля. Смена карточки =
новая схема, без перезагрузки страницы.

Типы полей и как рисовать:
| `type` | UI | что отправлять |
|---|---|---|
| `text`, `textarea` | поле ввода | строка (`max_length`) |
| `phone` | маска `+7 (999) 999-99-99` | любая запись, сервер нормализует к `+7XXXXXXXXXX` |
| `email`, `telegram_username` | поле | строка (`@` необязателен) |
| `select` | список/кнопки из `options` | `value` |
| `multiselect` | чекбоксы | повторяющиеся ключи в multipart или массив в JSON |
| `integer` | число (`min`/`max`) | число |
| `datetime` | дата и время | `2026-11-20T10:00` (время по Саратову) |
| `geo_point` | **карта 2ГИС** + геолокация + адрес | три поля: `lat`, `lon`, `address` |
| `inn`, `vin` | поле | строка |
| `files` | загрузка фото | `photos` (до `max_files`), см. ниже |
| `consent` | **обязательный чекбокс** + `consent.text` + ссылка на политику | `true` |

`required_if: {"destination": "other_address"}` — поле обязательно, только если выбрано это значение.
`options_source: "calculator.brands"` — подсказки марок из `GET /calculator/options` (свободный ввод тоже можно).
Honeypot: скрытое (CSS, не `type=hidden`) поле `website` — должно остаться пустым.
`form_token` из схемы верните в поле `form_token` (сервер отсечёт ботов, отправивших форму быстрее 3 с).

## 3. Отправка заявки → экран подтверждения
```
POST /leads   multipart/form-data (с фото)  или  application/json (без фото)
Idempotency-Key: <uuid, генерируйте один раз на попытку отправки формы>
```
```bash
curl -X POST http://localhost:8000/api/v1/leads -H 'Idempotency-Key: 2f8a…' \
  -F lead_type=onsite -F service_slug=onsite-repair -F name=Иван -F 'phone=+7 (927) 123-45-67' \
  -F vehicle_brand=MAN -F is_drivable=no -F 'description=Не заводится' \
  -F lat=51.55 -F lon=46.02 -F 'address=Сокурский тракт' -F consent=true -F photos=@breakdown.jpg
```
Ответ `201`:
```json
{"id": "…", "number": "GS-1001", "public_token": "5vS7kp…", "tracking_url": "https://site/order/5vS7kp…",
 "status": "new", "status_label": "Заявка получена",
 "summary": {"type": "onsite", "type_label": "Выезд мастера", "name": "Иван", "phone_masked": "+7 *** *** 45 67",
             "vehicle_brand": "MAN", "address": "Сокурский тракт", "photos_count": 1, "created_at": "…"},
 "callback_eta_minutes": 3, "message": "Заявка принята. Диспетчер перезвонит в течение нескольких минут.",
 "telegram_bind_url": "https://t.me/<bot>?start=5vS7kp…", "max_bind_url": null}
```
Экран подтверждения: номер, статус, `message`, «перезвоним в течение `callback_eta_minutes` минут», ссылка
`tracking_url` и кнопка **«Получать статус в Telegram»** (`telegram_bind_url`, если не `null`).
Ошибка 422 → `error.fields` — показать под полями. Повтор с тем же `Idempotency-Key` вернёт ту же заявку.

Фото: до 5 файлов, ≤5 МБ, JPG/PNG/WebP/HEIC (проверяется содержимое, не расширение). Геометки и EXIF
удаляются, HEIC конвертируется в JPEG. Общий лимит запроса — 27 МБ (413).

## 4. Страница заказа `/order/{token}`
```
GET /orders/{token} → {number, status, status_label, is_cancelled,
  steps: [{status, label, done, current}],              ← прогресс-бар (шаг «выехал» только для выезда/эвакуатора)
  history: [{status, label, at, comment}],
  summary: {type_label, phone_masked, vehicle_brand, address, description, details: [{label, value}],
            photos: [{preview_url, url}], estimate}, callback_eta_minutes,
  telegram_bind_url, telegram_bound, email_notifications, created_at, updated_at}
```
404 — «заявка не найдена» (одинаково для неверной и чужой ссылки). Добавьте `<meta name="robots" content="noindex">`.
Статус можно обновлять опросом раз в 30–60 с.

## 5. Кнопка «Выезд за 30 минут» и карта
- `GET /dispatch/zone` → `{center:{lat,lon}, radius_km, eta_minutes, note, geojson}` — нарисовать круг на MapGL
  (`geojson` — готовый Polygon) и мелким шрифтом `note` («в пределах 15 км — около 30 минут»).
- Маркер СТО — `settings.address.lat/lon`.
- При выборе точки: `POST /dispatch/check {lat, lon}` → `{zone: inside|region|outside, distance_km, eta_minutes, message}` —
  показать `message`. `region` — без обещания 30 минут.
- Кнопка ведёт на форму `onsite` (`GET /forms/onsite`), контакты — из `settings.contacts`.
- Адрес ↔ точка: `POST /geo/geocode {query}` и `POST /geo/reverse {lat, lon}`; если ответ 501 — работайте
  только с точкой на карте.

## 6. Калькулятор
`GET /calculator/options` → списки; `POST /calculator/estimate {brand, work_type, vehicle_type?, urgent?, onsite?}` →
`{estimate_id, price_from, price_label: "от 6 000 ₽", breakdown[], disclaimer, lead_prefill}`.
Кнопка «Оставить заявку» — открыть форму `lead_prefill.lead_type` и передать `estimate_id` в скрытом поле
(оператор увидит расчёт). Всегда показывайте `disclaimer`.

## 7. Отзывы и «до/после»
`GET /reviews/summary` → средний рейтинг и `review_links.yandex` / `review_links["2gis"]` для кнопок
«Отзывы на Яндексе» / «Отзывы на 2ГИС» (открывать в новой вкладке). Ключи из `review_links.placeholders` — ещё заглушки: такую кнопку лучше не показывать. `GET /reviews?limit=10` — лента.
Если у отзыва `has_case: true` → при раскрытии `GET /cases/{case_id}` → `photos.before[] / photos.after[]`
(`preview_url` в карточке, `url` — полноразмерное), `work_done[]`, `duration_hours`, `vehicle`.
Все seed-отзывы — `is_demo: true`.

## 8. Чат (ИИ-помощник + оператор)
```
POST /chat/sessions {consent}                → {session_id, status, messages:[приветствие], llm_enabled, live_chat_available}
POST /chat/sessions/{id}/messages {text, consent?}  → text/event-stream
```
Читать поток через `fetch` + `ReadableStream` (это POST, `EventSource` не подходит):
```js
const res = await fetch(`${API}/chat/sessions/${id}/messages`, {method: "POST",
  headers: {"Content-Type": "application/json"}, body: JSON.stringify({text, consent})});
const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
let buf = "";
for (;;) { const {value, done} = await reader.read(); if (done) break; buf += value;
  let i; while ((i = buf.indexOf("\n\n")) >= 0) { const block = buf.slice(0, i); buf = buf.slice(i + 2);
    const event = /^event: (.*)$/m.exec(block)?.[1]; const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] ?? "{}");
    handle(event, data); } }
```
События: `meta`; `delta` {text} — дописывать к ответу; `reset` — стереть дописанное (дальше FAQ-ответ);
`estimate` — карточка расчёта; `action` {type}: `open_form` (+`form_type`, `prefill` — прокрутить к форме),
`show_map`, `open_calculator`, `show_services`, `phone_required` (показать поле телефона),
`consent_required` (показать чекбокс согласия и отправить `consent: true`), `lead_created` (+`lead` — как ответ
`POST /leads`, показать номер и ссылку); `handoff` {status, live_chat}; `done` {text, topic, suggested_replies[],
mode, session_status} — показать `suggested_replies` кнопками-подсказками; `error`.
«Темы»: `topic` ∈ services | pricing | dispatch | parts | corporate | warranty | other — можно подсвечивать.

Кнопка «Позвать оператора» → `POST /chat/sessions/{id}/handoff {phone?, name?, consent?}`.
Живой чат (если `live_chat_available`): после handoff откройте `new EventSource(`${API}/chat/sessions/${id}/events`)` —
приходят `operator_message` {text, operator_name}; сообщения пользователя отправляйте как обычно.

## 9. Прочее
- Ошибки — `{error: {code, message, fields?}}`; на 429 есть `Retry-After`.
- Фото и медиа: абсолютные URL от `API_BASE_URL`, кэш на год.
- Опционально бэкенд раздаёт собранный фронт: `FRONTEND_DIST_DIR=/path/to/dist` → `/` и SPA-fallback на
  `index.html`, `/assets/*` с долгим кэшем; тогда CORS не нужен.
