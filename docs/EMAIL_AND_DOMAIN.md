# Почта, домен и HTTPS: пошаговый гайд

Что получится в итоге:

```
ваш-домен.ru            → фронт (позже: Cloudflare Pages или тот же VPS)
api.ваш-домен.ru        → VPS: Caddy (HTTPS) → API в Docker (127.0.0.1:8000) + PostgreSQL
no-reply@mail.ваш-домен.ru → письма клиентам и операторам (Resend, бесплатно)
info@ваш-домен.ru       → входящие письма пересылаются в ваш личный ящик (Cloudflare Email Routing)
```

Везде ниже `ваш-домен.ru` замените на свой домен, `203.0.113.10` — на IP вашего VPS.

Порядок: **1 → 2 → 3** можно сделать уже сейчас, без сервера. **4** — когда арендуете VPS.

---

## 1. Домен в Cloudflare: что проверить

1. Cloudflare → ваш домен → **Overview**: статус должен быть **Active**. Если `Pending` — у регистратора домена
   (где покупали) должны стоять NS-серверы Cloudflare, указанные на этой же странице.
2. **DNS → Records** — сюда будем добавлять записи. Итоговый набор (подробности в разделах ниже):

| Тип | Имя | Значение | Прокси | Зачем |
|---|---|---|---|---|
| A | `api` | `203.0.113.10` | **DNS only** (серое облако) | бэкенд на VPS (раздел 4) |
| MX | `send.mail` | из Resend | DNS only | отправка писем (раздел 2) |
| TXT | `send.mail` | `v=spf1 include:amazonses.com ~all` (из Resend) | — | SPF |
| TXT | `resend._domainkey.mail` | `p=…` (из Resend) | DNS only | DKIM |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:info@ваш-домен.ru` | — | DMARC |
| MX/TXT | `@` | добавит Cloudflare сам | — | приём почты (раздел 3) |

**Почему серое облако, а не оранжевое.** Оранжевое облако — это прокси Cloudflare: трафик идёт через их
серверы. Российские провайдеры периодически замедляли такой трафик, а наши клиенты — в России. Поэтому для
`api` оставляем **DNS only**, а HTTPS выпускает Caddy на сервере сам (бесплатно, Let's Encrypt).

---

## 2. Отправка писем

### Вариант A — Resend + ваш домен (рекомендуется)

Бесплатно: **3000 писем в месяц, 100 в день, до 3 доменов** (на момент написания; лимиты см. resend.com/pricing).
Письма уходят от `no-reply@mail.ваш-домен.ru` с подписью DKIM — не падают в спам.

1. **Регистрация.** Зайдите на <https://resend.com>, создайте аккаунт.
2. **Домен.** Resend → **Domains** → **Add Domain** → введите **поддомен** `mail.ваш-домен.ru`.
   Resend советует поддомен, а не корень домена: репутация рассылки не смешивается с основным доменом,
   а приём почты на `info@ваш-домен.ru` (раздел 3) ничему не мешает.
3. **DNS-записи — автоматически.** На странице домена нажмите **Sign in to Cloudflare** и разрешите доступ —
   Resend сам добавит записи в Cloudflare (Domain Connect).
   **Или вручную:** Cloudflare → DNS → **Add record**, по одной строке из таблицы, которую показывает Resend:
   - `MX`, имя `send.mail`, значение — из Resend, приоритет `10`;
   - `TXT`, имя `send.mail`, значение `v=spf1 include:amazonses.com ~all`;
   - `TXT`, имя `resend._domainkey.mail`, значение `p=…` (длинный ключ из Resend), прокси **DNS only**.

   В поле «Name» в Cloudflare пишите **только поддоменную часть**: `send.mail`, а не `send.mail.ваш-домен.ru`.
4. **Проверка.** В Resend нажмите **Verify DNS Records**. Обычно проходит за несколько минут, в худшем случае —
   до 72 часов. Ошибка `Code: 1004` в Cloudflare — переключите запись в **DNS only**.
5. **DMARC** (желательно, 1 минута). Cloudflare → DNS → `TXT`, имя `_dmarc`,
   значение `v=DMARC1; p=none; rua=mailto:info@ваш-домен.ru`. Это говорит почтовикам «домен настоящий,
   отчёты слать сюда» и заметно улучшает доставляемость. Gmail и Яндекс без DMARC режут письма чаще.
6. **API-ключ.** Resend → **API Keys** → **Create API Key**, права **Sending access**, домен `mail.ваш-домен.ru`.
   Ключ показывается **один раз** — сразу вставьте в `.env`.
7. **`.env`** (локально или на сервере):

   ```dotenv
   SMTP_HOST=smtp.resend.com
   SMTP_PORT=465
   SMTP_SSL=true
   SMTP_STARTTLS=false
   SMTP_USER=resend
   SMTP_PASSWORD=re_ваш_API_ключ
   SMTP_FROM=ГРУЗСПЕЦСЕРВИС <no-reply@mail.ваш-домен.ru>
   OPERATOR_EMAIL=куда-слать-заявки@example.com
   ```

   Если на хостинге закрыт порт 465 — `SMTP_PORT=587`, `SMTP_SSL=false`, `SMTP_STARTTLS=true`
   (Resend также принимает 2465 с SSL и 2587 со STARTTLS).
8. **Проверка отправки:**

   ```bash
   make test-email TO=ваш-личный@ящик.ru
   ```

   Скрипт покажет, через какой сервер отправляет, и либо «Готово», либо понятную ошибку. Письмо проверьте
   во «Входящих» и в «Спаме». Если пришло в спам — почти всегда не хватает DKIM или DMARC (шаги 3 и 5).

### Вариант B — Gmail (5 минут, если домена ещё нет)

Письма будут от вашего `@gmail.com`. Для демо нормально, для продакшена — вариант A.

1. В Google-аккаунте включите **двухэтапную аутентификацию** (Security → 2-Step Verification).
2. Откройте <https://myaccount.google.com/apppasswords>, создайте пароль приложения (например, «gruzspec»).
   Google покажет 16 символов — это и есть пароль для SMTP (пробелы можно убрать).
3. `.env`:

   ```dotenv
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_SSL=false
   SMTP_STARTTLS=true
   SMTP_USER=ваш@gmail.com
   SMTP_PASSWORD=пароль_приложения
   SMTP_FROM=ГРУЗСПЕЦСЕРВИС <ваш@gmail.com>
   OPERATOR_EMAIL=куда-слать-заявки@example.com
   ```

4. `make test-email TO=…`.

`SMTP_FROM` должен совпадать с ящиком, через который отправляете. Чужой адрес в «От кого» = спам.

### Что будет приходить

- **Оператору** (`OPERATOR_EMAIL`) — каждая новая заявка с телефоном, точкой в 2ГИС, фото и расчётом.
- **Клиенту** (если указал e-mail в форме) — подтверждение со ссылкой на заказ и каждая смена статуса.
- Всё отправляется из очереди с повторами: если SMTP упал, заявка всё равно принята, письмо уйдёт позже.
  Ошибки видны в админке → «Очередь уведомлений».

---

## 3. Приём почты на `info@ваш-домен.ru` (Cloudflare Email Routing, бесплатно)

Нужно, чтобы клиенты могли ответить на письмо, и чтобы на сайте был красивый адрес вместо gmail.

1. Cloudflare → ваш домен → **Email** → **Email Routing** (в новом интерфейсе: **Compute → Email Service →
   Email Routing**) → **Onboard Domain** / **Get started**. Проверьте предложенные DNS-записи → **Done**.
   Cloudflare сам добавит MX-, SPF- и DKIM-записи на корень домена.
   Если у домена уже есть почта (другие MX-записи) — сначала посмотрите, что там, иначе она перестанет работать.
2. **Destination Addresses** → добавьте свой личный ящик → откройте письмо от Cloudflare → **Verify email address**.
3. **Routing Rules** → **Create routing rule**: адрес `info` (и, например, `zayavki`) → действие
   «Send to an email» → ваш ящик → **Save**.
4. Проверка: напишите на `info@ваш-домен.ru` с другого ящика — письмо должно прийти (возможно, в «Спам»
   первый раз — отметьте «Не спам»).
5. В админке сайта → «Настройки сайта» → `contacts` → замените e-mail на `info@ваш-домен.ru`.

Отправка (Resend, поддомен `mail`) и приём (Cloudflare, корень домена) друг другу не мешают.

---

## 4. Сервер: домен `api.ваш-домен.ru` с HTTPS

### 4.1. VPS
- Ubuntu 24.04, 2 vCPU, 2 ГБ RAM, 20–30 ГБ диска — с запасом.
- Сразу проверьте доступность внешних сервисов **с самого VPS**:

  ```bash
  curl -s -o /dev/null -w "telegram %{http_code}\n" https://api.telegram.org
  ```

  ```bash
  curl -s -o /dev/null -w "openrouter %{http_code}\n" https://openrouter.ai/api/v1/models
  ```

  Ответы `302`/`200` — всё хорошо. Таймаут к Telegram — настроим `TELEGRAM_PROXY_URL`
  (см. [README.md](README.md)); к OpenRouter — скажите, добавлю такой же прокси для LLM.

### 4.2. Firewall
Наружу открыты только SSH и HTTP(S):

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw enable
```

### 4.3. Docker и проект
1. Docker Engine — по инструкции из [README.md](README.md#установка-docker-engine-на-linux-mint)
   (на Ubuntu там же, только `UBUNTU_CODENAME` совпадёт с обычным именем версии).
2. Код:

   ```bash
   git clone https://github.com/Volsogin/gruzspecservice.git && cd gruzspecservice && cp .env.example .env
   ```

3. `.env` на сервере — главное:

   ```dotenv
   APP_ENV=prod
   SECRET_KEY=длинная_случайная_строка
   ADMIN_TOKEN=длинный_случайный_пароль_админки
   POSTGRES_PASSWORD=длинный_случайный_пароль_БД

   PUBLIC_BASE_URL=https://ваш-домен.ru
   API_BASE_URL=https://api.ваш-домен.ru
   CORS_ORIGINS=https://ваш-домен.ru

   # API слушает только localhost — снаружи доступен лишь Caddy (HTTPS)
   API_BIND=127.0.0.1
   # доверять заголовкам X-Forwarded-* (реальный IP клиента для лимитов): безопасно, т.к. порт закрыт снаружи
   FORWARDED_ALLOW_IPS=*

   # + SMTP_* (раздел 2), TELEGRAM_*, OPERATOR_*, DGIS_API_KEY, OPENROUTER_API_KEY — как локально
   ```

   Случайные строки:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

4. Запуск в фоне (миграции и демо-данные применятся сами):

   ```bash
   docker compose up -d --build
   ```

   ```bash
   curl -s http://127.0.0.1:8000/readyz
   ```

   Должно быть `"database":true`.

### 4.4. DNS
Cloudflare → DNS → **Add record**: `A`, имя `api`, IPv4 `203.0.113.10`, прокси **DNS only** (серое облако).
Проверка (через пару минут):

```bash
dig +short api.ваш-домен.ru
```

Должен вернуться IP вашего VPS.

### 4.5. Caddy (HTTPS автоматически)
Установка — официальный репозиторий (команды с caddyserver.com/docs/install):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
```

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
```

```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
```

```bash
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list && sudo apt update && sudo apt install -y caddy
```

Конфиг `/etc/caddy/Caddyfile` (замените домен):

```caddy
api.ваш-домен.ru {
    # без `encode`: API сам сжимает ответы, а сжатие на прокси может задерживать поток чата (SSE)
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1   # чат (SSE): отдавать ответ ИИ по мере генерации, без буферизации
    }
}
```

Применить:

```bash
sudo systemctl reload caddy
```

Caddy сам получит сертификат Let's Encrypt (нужны открытые 80/443 и DNS из 4.4). Проверка:

```bash
curl -s https://api.ваш-домен.ru/healthz
```

→ `{"status":"ok"}`. Swagger: `https://api.ваш-домен.ru/docs`, админка: `https://api.ваш-домен.ru/admin`.

### 4.6. Что заработает после этого
- Ссылки на фото и на заказ в письмах и Telegram станут нормальными `https://…`.
- В Telegram вместо текстовой ссылки появится **кнопка «Открыть заявку»** (Telegram не принимает
  кнопки на localhost). Страница `/order/{token}` при этом должна быть на фронте — до его появления
  ссылка будет вести на `ваш-домен.ru`, где пока ничего нет.
- CORS: фронт с `https://ваш-домен.ru` сможет ходить в API.

### 4.7. Обновление сервера после новых коммитов

```bash
git pull && docker compose up -d --build
```

Миграции применяются при старте контейнера автоматически.

---

## Если что-то не работает

| Симптом | Причина и решение |
|---|---|
| `make test-email`: `smtp error: SMTPAuthenticationError` | неверный пароль: для Resend — API-ключ, логин `resend`; для Gmail — пароль приложения, не обычный |
| `smtp error: … timeout` | хостинг закрыл порт — попробуйте 587/STARTTLS или 2587/2465 (Resend) |
| письма в «Спаме» | нет DKIM/DMARC или `SMTP_FROM` не на подтверждённом домене |
| Resend не подтверждает домен | лишняя часть домена в поле Name (`send.mail.ваш-домен.ru` вместо `send.mail`), запись в оранжевом облаке |
| Caddy не получил сертификат | DNS ещё не обновился (`dig`), закрыт порт 80/443 в ufw или у хостера, включено оранжевое облако |
| `502 Bad Gateway` от Caddy | контейнер API не запущен: `docker compose ps`, `docker compose logs api` |
| в логах у всех клиентов один IP, лимиты срабатывают на всех | не задан `FORWARDED_ALLOW_IPS=*` |
