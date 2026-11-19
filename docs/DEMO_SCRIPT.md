# Сценарий демонстрации (≈7 минут)

Подготовка: `.env` с `ADMIN_TOKEN`, `TELEGRAM_BOT_TOKEN`, `BOT_USERNAME`, `OPERATOR_INVITE_CODE`; два оператора
заранее написали боту `/operator <код>` (два телефона/аккаунта на втором экране); по возможности `OPENROUTER_API_KEY`. Запуск — `make up` (или `make dev`).
Без ключей всё тоже работает: письма — в `backend/var/mail` (в Docker — volume), Telegram — в лог, чат — FAQ.

Переменные для примеров:

```bash
export B=http://localhost:8000/api/v1 ADMIN='Authorization: Bearer <ваш ADMIN_TOKEN>'
```

## 1. Контракт и здоровье (30 с)
Открыть <http://localhost:8000/docs> — все эндпоинты с описаниями и примерами, теги по блокам сайта.

```bash
curl -s http://localhost:8000/readyz
```

## 2. Первый экран одним запросом (30 с)

```bash
curl -s -D - -o /dev/null -H 'Accept-Encoding: br' $B/bootstrap
```

Показать `content-encoding: br`, `etag`; повтор с `If-None-Match` → 304.

## 3. Услуга → форма по схеме → заявка с фото (1,5 мин)

```bash
curl -s $B/services | python3 -m json.tool | head -30
```

Карточка «Выездной ремонт 24/7» → `prefill: {lead_type: onsite, …}` → схема формы:

```bash
curl -s $B/forms/onsite | python3 -m json.tool | head -40
```

Отправка (точка на карте, фото, кривой формат телефона — сервер нормализует):

```bash
curl -s -X POST $B/leads -H "Idempotency-Key: demo-$(date +%s)" -F lead_type=onsite -F service_slug=onsite-repair -F name=Иван -F 'phone=8 (927) 123-45-67' -F vehicle_brand=MAN -F is_drivable=no -F 'description=Не заводится на трассе' -F lat=51.55 -F lon=46.02 -F 'address=Сокурский тракт' -F consent=true -F photos=@photo.jpg | python3 -m json.tool
```

Показать: номер `GS-…`, статус, `tracking_url`, `telegram_bind_url`. В группе операторов — карточка
с телефоном, ссылкой «открыть в 2ГИС», «в зоне 30 минут», фото и кнопками «Принять / Отменить».
Валидация: тот же запрос без `consent` и с `phone=123` → 422 с ошибками по полям.

## 4. Статус по ссылке и уведомления (1,5 мин)
1. Открыть `telegram_bind_url` с «телефона клиента» → бот: «Будем присылать сюда статус заявки GS-…».
2. Оба оператора получили карточку с «✋ Беру». Первый жмёт «Беру» — у второго карточка меняется на
   «👷 Ответственный: …» без кнопок, его попытка нажать отклоняется.
3. Ответственный: «🚚 Выехали» → «🔧 В работе» → «🏁 Готово» — клиенту в Telegram (и на e-mail) приходит каждый статус.
4. Клиент пишет боту «Сколько ждать?» → вопрос приходит ответственному → он отвечает реплаем → ответ у клиента.
   Отмена заявки клиентом — кнопкой в «📋 Мои заявки» (пока мастер не выехал).
5. Страница заказа:

```bash
curl -s $B/orders/<public_token> | python3 -m json.tool
```

Телефон замаскирован, есть шаги и история. Неверный токен → тот же 404.
6. Альтернатива кнопкам — админка <http://localhost:8000/admin> (пароль = `ADMIN_TOKEN`): «Заявки» → действия
   статусов, «История статусов», «Очередь уведомлений».

## 5. Калькулятор и зона выезда (1 мин)

```bash
curl -s -X POST $B/calculator/estimate -H 'Content-Type: application/json' -d '{"brand":"КамАЗ","work_type":"brakes","urgent":true}' | python3 -m json.tool
```

```bash
curl -s -X POST $B/dispatch/check -H 'Content-Type: application/json' -d '{"lat":51.03,"lon":45.70}'
```

`region` — «приедем, время уточнит диспетчер» (без обещания 30 минут); точка в Москве — `outside`.

## 6. ИИ-ассистент (1,5 мин)

```bash
S=$(curl -s -X POST $B/chat/sessions -H 'Content-Type: application/json' -d '{"consent":true}' | python3 -c "import json,sys;print(json.load(sys.stdin)['session_id'])")
```

```bash
curl -sN -X POST $B/chat/sessions/$S/messages -H 'Content-Type: application/json' -d '{"text":"Сколько стоит диагностика MAN?"}'
```

Поток SSE: `delta` (текст), `estimate` (карточка цены через tool `calculate_price`), `done` с подсказками.
Затем «Позовите оператора» → ассистент без уговоров просит телефон → отправить номер → заявка `chat_handoff`
с расшифровкой диалога в группе операторов. Ответ оператора reply'ем в группе приходит в чат на сайте
(`GET /chat/sessions/$S/events`). Без ключа OpenRouter (или при его недоступности) — те же сценарии в FAQ-режиме.

## 7. Качество (30 с)

```bash
make check
```

ruff, mypy --strict и 115 тестов за ~6 секунд; CI в `.github/workflows/backend.yml`.
