# Деплой: тест на ноутбуке (Linux Mint) и сервер (Ubuntu 24.04)

Сайт и API живут **на одном адресе**: бэкенд сам отдаёт собранный фронт (`/`), API (`/api/v1`),
админку (`/admin`) и фото (`/media`). Поэтому CORS не нужен, а ссылки из писем и Telegram
(`/order/{token}`) сразу открывают нужную страницу.

```
Браузер ──► Caddy (HTTPS, только на сервере) ──► контейнер api: FastAPI + собранный фронт ──► PostgreSQL
                                                         └──► Telegram, SMTP, OpenRouter, 2ГИС
```

| Где | Команда | База | HTTPS |
|---|---|---|---|
| Разработка | `make dev` + `make web` → <http://localhost:5173> | SQLite | — |
| Тест на ноутбуке без Docker | `make preview` → <http://localhost:8000> | SQLite | — |
| Тест на ноутбуке с Docker | `make up` → <http://localhost:8000> | PostgreSQL | — |
| Сервер Ubuntu 24.04 | `make prod-up` → `https://ваш-домен.ru` | PostgreSQL | Caddy, Let's Encrypt |

## 0. Быстрый путь: сервер одной командой

Нужно: VPS с Ubuntu 24.04 (2 vCPU, 2 ГБ RAM), его IP и root-пароль/SSH-ключ, домен в Cloudflare.
**Где VPS.** OpenRouter отвечает `403` на российские IP, а Telegram API из РФ работает нестабильно. Поэтому:
- **VPS за рубежом** (Нидерланды, Германия, Финляндия…) — проще всего: всё работает напрямую, прокси не нужен;
- **VPS в России** — передайте скрипту свою ссылку `vless://…` (VLESS + XHTTP/WS/gRPC/TCP, TLS или REALITY):
  рядом с сайтом поднимется контейнер `proxy` (Xray), и **только** Telegram и OpenRouter пойдут через него.
  2ГИС, почта и посетители сайта ходят напрямую. Ссылку берите в своём клиенте (v2rayN → сервер → «Поделиться»
  / «Экспорт ссылки»). Hysteria не нужна — достаточно VLESS.

1. **Cloudflare → DNS → Add record:** тип `A`, имя `@`, IPv4 = IP сервера, прокси **DNS only** (серое облако).
2. **На ноутбуке**, из папки проекта — отправить свой `.env` (ключи Telegram, 2ГИС, OpenRouter) на сервер:

   ```bash
   scp .env root@IP_СЕРВЕРА:/root/gruzspec.env
   ```

3. **Зайти на сервер:**

   ```bash
   ssh root@IP_СЕРВЕРА
   ```

4. **На сервере** — всё остальное делает [deploy/setup-ubuntu.sh](../deploy/setup-ubuntu.sh):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Volsogin/gruzspecservice/main/deploy/setup-ubuntu.sh -o setup.sh && bash setup.sh ваш-домен.ru
   ```

   **VPS в России** — сначала положите ссылку VLESS в файл (так она не останется в истории команд):

   ```bash
   nano /root/vless.txt
   ```

   вставьте `vless://…`, сохраните (`Ctrl+O`, `Enter`, `Ctrl+X`) и запустите ту же команду `bash setup.sh ваш-домен.ru` —
   скрипт сам найдёт файл, соберёт конфиг Xray и включит прокси. В конце он проверит, что Telegram и OpenRouter
   отвечают (✅/❌).

   Ставит Docker, firewall (SSH/80/443) и автообновления; кладёт код в `/opt/gruzspecservice`; делает из вашего
   `.env` продовый (`APP_ENV=prod`, адреса `https://домен`, новые `SECRET_KEY`/пароль БД, без прокси v2rayN);
   запускает `make prod-up`; включает ночной бэкап; ждёт, пока заработает HTTPS.

5. **Остановить бот на ноутбуке** (`Ctrl+C` в окне `make dev`/`make preview`): один Telegram-бот может работать
   только в одном месте, иначе сервер получит `409 Conflict`.
6. В кабинете 2ГИС добавьте домен в ограничения ключа MapGL.

Обновление после новых коммитов — на сервере:

```bash
cd /opt/gruzspecservice && git pull && make prod-up
```

Ниже — то же самое по шагам, с объяснениями.

---

## 1. Тестовый деплой на ноутбуке (Linux Mint 22 / Ubuntu 24)

### 1.1. Один раз: инструменты
- **uv** (Python 3.12 он скачает сам):

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

- **Node.js 18.18+** (для сборки фронта). На Mint 22 из коробки подходит пакет `nodejs` (18.19):

  ```bash
  sudo apt install -y nodejs npm
  ```

  Проверка: `node -v` → `v18.19` или новее.

### 1.2. Запуск «как на сервере», одним процессом
```bash
cp .env.example .env
```

Заполните в `.env` то, что уже есть (Telegram, 2ГИС, OpenRouter, SMTP — всё необязательно, см.
[README.md](README.md#что-нужно-получить-ключи-и-адресаты)). Затем:

```bash
make preview
```

Команда соберёт фронт, применит миграции, загрузит демо-данные и запустит всё на порту 8000:
- сайт — <http://localhost:8000>, админка — `/admin` (вход по `ADMIN_TOKEN`), Swagger — `/docs`;
- **с телефона в той же Wi-Fi** — `http://<IP ноутбука>:8000` (адрес команда печатает при старте).
  Если не открывается — разрешите порт: `sudo ufw allow 8000/tcp`.

Ссылки в письмах и Telegram строятся из `PUBLIC_URL` (по умолчанию `http://localhost:8000`). Чтобы
кнопка «Открыть заявку» в Telegram вела на ноутбук с телефона:

```bash
make preview PUBLIC_URL=http://192.168.1.50:8000
```

> ⚠️ Telegram-бот (long polling) может работать **только в одном процессе**. Не запускайте одновременно
> `make dev` и `make preview` с одним `TELEGRAM_BOT_TOKEN` — второй получит ошибку 409 от Telegram.

### 1.3. Показать сайт снаружи без сервера (по желанию)
Временный публичный HTTPS-адрес через Cloudflare Tunnel — без аккаунта и без sudo. Скачайте
`cloudflared` с [официальной страницы релизов](https://github.com/cloudflare/cloudflared/releases)
(файл `cloudflared-linux-amd64`), сделайте исполняемым и запустите рядом с `make preview`:

```bash
chmod +x cloudflared-linux-amd64 && ./cloudflared-linux-amd64 tunnel --url http://localhost:8000
```

Он напечатает адрес вида `https://случайные-слова.trycloudflare.com`. Перезапустите preview с ним, чтобы
ссылки в Telegram и письмах вели туда:

```bash
make preview PUBLIC_URL=https://случайные-слова.trycloudflare.com
```

Адрес меняется при каждом запуске туннеля — для демо этого хватает. Ключ MapGL 2ГИС ограничен по
доменам: добавьте `*.trycloudflare.com` в кабинете 2ГИС, иначе вместо карты будет схема.

### 1.4. То же в Docker (PostgreSQL, как на сервере)
Нужен Docker Engine — установка на Mint в [README.md](README.md#установка-docker-engine-на-linux-mint).

```bash
make up
```

Сайт и API — <http://localhost:8000>. В `.env` поставьте `PUBLIC_BASE_URL=http://localhost:8000`.

---

## 2. Сервер: Ubuntu 24.04 + домен + HTTPS

### 2.1. VPS
- Ubuntu 24.04 LTS, 2 vCPU, 2 ГБ RAM, 20–30 ГБ диска. Сборка образа (Node + Python) — 2–4 минуты.
- Проверьте доступ к внешним сервисам **с самого сервера**:

  ```bash
  curl -s -o /dev/null -w "telegram %{http_code}\n" https://api.telegram.org
  ```

  ```bash
  curl -s -o /dev/null -w "openrouter %{http_code}\n" https://openrouter.ai/api/v1/models
  ```

  `200`/`302` — хорошо. Таймаут до Telegram — нужен `TELEGRAM_PROXY_URL`
  (см. [README.md](README.md#telegram-бот-для-клиентов-и-операторов)).

### 2.2. Пользователь, firewall, обновления
Под root один раз создайте пользователя (дальше работаем под ним):

```bash
adduser deploy && usermod -aG sudo deploy
```

Наружу — только SSH и HTTP(S):

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443 && sudo ufw enable
```

Автоматические обновления безопасности:

```bash
sudo apt update && sudo apt install -y unattended-upgrades git make && sudo dpkg-reconfigure -plow unattended-upgrades
```

### 2.3. Docker Engine (официальный репозиторий)
```bash
sudo install -m 0755 -d /etc/apt/keyrings && sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

```bash
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

```bash
sudo usermod -aG docker $USER
```

Перезайдите по SSH, проверьте: `docker compose version` (нужна 2.24+).

### 2.4. DNS
Cloudflare → DNS → **Add record**: тип `A`, имя `@` (сам домен), IPv4 сервера, прокси **DNS only**
(серое облако — сертификат выпускает Caddy на сервере). По желанию — такая же запись `www`.

```bash
dig +short ваш-домен.ru
```

Должен вернуться IP сервера. Подробнее про домен и почту — [EMAIL_AND_DOMAIN.md](EMAIL_AND_DOMAIN.md).

### 2.5. Код и `.env`
```bash
git clone https://github.com/Volsogin/gruzspecservice.git && cd gruzspecservice && cp .env.example .env && chmod 600 .env
```

Случайные строки для секретов (запустите три раза):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Главное в `.env` на сервере:

```dotenv
APP_ENV=prod
DOMAIN=ваш-домен.ru
PUBLIC_BASE_URL=https://ваш-домен.ru
API_BASE_URL=https://ваш-домен.ru
CORS_ORIGINS=https://ваш-домен.ru

SECRET_KEY=случайная_строка_1
ADMIN_TOKEN=случайная_строка_2
POSTGRES_PASSWORD=случайная_строка_3

# Карта: ключ MapGL; в кабинете 2ГИС ограничьте его доменом ваш-домен.ru
DGIS_MAPGL_KEY=...
DGIS_API_KEY=...
# + TELEGRAM_*, OPERATOR_*, OPENROUTER_API_KEY, SMTP_* — как на ноутбуке
```

> `POSTGRES_PASSWORD` задайте **до первого запуска**: база создаётся с ним один раз.

### 2.6. Запуск
```bash
make prod-up
```

Поднимутся три контейнера: `db` (PostgreSQL), `api` (сайт + API, миграции и демо-данные применяются при
старте), `caddy` (HTTPS). Наружу открыт только Caddy (80/443); порт API не публикуется
([docker-compose.prod.yml](../docker-compose.prod.yml), [deploy/Caddyfile](../deploy/Caddyfile)).

Проверка через минуту:

```bash
curl -s https://ваш-домен.ru/healthz
```

→ `{"status":"ok"}`. Сайт — `https://ваш-домен.ru`, админка — `https://ваш-домен.ru/admin`.

Первый сертификат Caddy получает за 10–60 секунд. Логи:

```bash
make prod-logs
```

### 2.7. Обновление после новых коммитов
```bash
git pull && make prod-up
```

Образ пересоберётся (фронт тоже), миграции применятся при старте. Простой — несколько секунд.

### 2.8. Резервные копии
Дамп базы в `backups/`:

```bash
make prod-backup
```

Каждую ночь в 03:30 (`crontab -e`, путь замените на свой):

```cron
30 3 * * * cd /home/deploy/gruzspecservice && make prod-backup >/dev/null 2>&1 && find backups -name '*.sql.gz' -mtime +14 -delete
```

Фото заявок лежат в Docker-томе `appdata` (`docker volume inspect gruzspecservice_appdata`). Восстановление
базы из дампа:

```bash
gunzip -c backups/ФАЙЛ.sql.gz | docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U gruzspec gruzspec
```

### 2.9. Чек-лист после запуска
- [ ] `https://ваш-домен.ru` открывается, на карте — 2ГИС, а не схема (иначе проверьте `DGIS_MAPGL_KEY` и
      ограничение домена в кабинете 2ГИС).
- [ ] Тестовая заявка → карточка оператору в Telegram, кнопка «Открыть заявку» ведёт на `https://…/order/…`.
- [ ] `make test-email TO=ваш@ящик` — письмо дошло (SPF/DKIM — [EMAIL_AND_DOMAIN.md](EMAIL_AND_DOMAIN.md)).
- [ ] Чат отвечает потоком (если ответ появляется целиком — проверьте, что перед Caddy нет другого прокси с буферизацией).
- [ ] `ADMIN_TOKEN`, `SECRET_KEY`, `POSTGRES_PASSWORD` — случайные, `.env` с правами `600`.
- [ ] Заменены демо-данные: отзывы, статистика, ссылка на Яндекс, текст политики ПДн (админка → «Настройки»).

## Прокси для Telegram и OpenRouter (VPS в России)

Как устроено: [deploy/proxy-config.py](../deploy/proxy-config.py) превращает ссылку `vless://…` в конфиг Xray
(`deploy/xray/config.json`, в git не попадает — там ваш UUID), а [docker-compose.prod.yml](../docker-compose.prod.yml)
запускает контейнер `proxy` (официальный образ `ghcr.io/xtls/xray-core`) при `COMPOSE_PROFILES=proxy` в `.env`.
API ходит в него по `http://proxy:10809` — это `TELEGRAM_PROXY_URL` и `LLM_PROXY_URL`. Порт наружу не открыт.

Сменить сервер VLESS:

```bash
cd /opt/gruzspecservice && python3 deploy/proxy-config.py 'vless://новая-ссылка' && make prod-up
```

Логи прокси: `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f proxy`.
Выключить прокси: в `.env` очистите `COMPOSE_PROFILES`, `TELEGRAM_PROXY_URL`, `LLM_PROXY_URL` и выполните `make prod-up`.

## Если что-то не работает

| Симптом | Причина и решение |
|---|---|
| Caddy не получил сертификат | DNS ещё не обновился (`dig`), закрыты 80/443 (ufw или панель хостера), включено оранжевое облако Cloudflare |
| `502` от Caddy | контейнер api не поднялся: `make prod-logs`, часто — ошибка в `.env` |
| Вместо карты схема «карта 2ГИС появится после настройки ключа» | пустой `DGIS_MAPGL_KEY` или домен не добавлен в ограничения ключа |
| Поиск адреса «недоступен» | пустой `DGIS_API_KEY` (серверный ключ геокодера) |
| Чат отвечает шаблонами (режим FAQ) | OpenRouter недоступен: с российского IP он отвечает `403` — нужен `LLM_PROXY_URL` (на ноутбуке — v2rayN, на сервере — раздел про прокси) |
| Бот молчит, в логах `409 Conflict` | бот запущен ещё где-то (ноутбук) с тем же токеном — остановите второй процесс |
| После смены настроек сайт показывает старое | `/bootstrap` кэшируется до минуты в браузере — обновите страницу через минуту |
