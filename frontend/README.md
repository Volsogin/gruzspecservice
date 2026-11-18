# Фронтенд (будет добавлен)

Здесь будет сайт: тёмная тема, лента услуг, формы заявок, карта 2ГИС, калькулятор, отзывы, чат-виджет,
страница заказа `/order/{token}`.

Контракт с бэкендом уже готов — см. [docs/FRONTEND_INTEGRATION.md](../docs/FRONTEND_INTEGRATION.md) и
[docs/openapi.json](../docs/openapi.json). Договорённости для этого каталога:

- свой `package.json` и lock-файл здесь, в `frontend/`; сборка — в `frontend/dist/` (в `.gitignore`);
- адрес API — переменная окружения сборки (например, `VITE_API_URL=http://localhost:8000/api/v1`);
- ключ 2ГИС MapGL — только через окружение и с ограничением по домену в кабинете 2ГИС, не в коде;
- отдельный workflow `.github/workflows/frontend.yml` с фильтром `paths: ["frontend/**"]`;
- в `docker-compose.yml` — сервис `web` (заготовка там закомментирована), либо раздача `dist/` самим
  бэкендом через `FRONTEND_DIST_DIR`.
