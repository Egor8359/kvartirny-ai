# Квартирный AI — персональный менеджер

Учебное приложение FastAPI для вымышленного ЖК «Северный парк». SQLite используется локально, PostgreSQL — для облачной среды. AI работает через RouterAI; интерфейс, собственные сессии и роли сохранены.

## Локальный запуск

Python 3.11+ и PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m app.setup init
.\.venv\Scripts\python.exe -m app.setup create-user --username demo --name Клиент --role client
.\.venv\Scripts\python.exe -m app.setup create-user --username manager --name Администратор --role admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Пароль вводится скрыто в интерактивной консоли и не передаётся аргументом команды. При существующем `.env` его не перезаписывайте. `init` создаёт отсутствующие таблицы и квартиры; существующих пользователей, пароли, роли, факты и диалоги не сбрасывает. Таблицы не создаются автоматически при запуске сервера. Если база существовала до этого этапа, выполните `init` один раз для добавления служебных таблиц.

Для AI добавьте личный `ROUTERAI_API_KEY` в локальный `.env`; без ключа AI-ответы недоступны, но введённое сообщение сохраняется. Откройте http://127.0.0.1:8000. Используйте только учебные данные.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Обычные тесты используют временную SQLite и подмену AI. Тест PostgreSQL пропускается без отдельного `TEST_POSTGRES_URL`; его разрешено запускать только с `ALLOW_TEST_DATABASE=1`, `APP_ENV=test` и базой с именем `apartment_test`. Для локального тестового контейнера без TLS задайте `DB_SSL_MODE=disable`. Нельзя направлять тесты на рабочую базу. CI создаёт отдельный PostgreSQL-сервис и запускает весь набор.

Для облака, Supabase, GitHub Actions и Vercel см. [инструкцию](docs/deployment.md). Публикация и создание внешних проектов выполняются отдельно по согласованию.

## Основные файлы

- `app/main.py` — маршруты, авторизация, роли, cookie и CSRF.
- `app/database.py`, `app/setup.py` — модели, настройки подключения и отдельная инициализация.
- `app/coordination.py` — общие лимиты и блокировка изменений памяти в SQL.
- `app/services.py`, `app/prompts.py` — AI, память и подбор.
- `app/templates/`, `app/static/` — существующий интерфейс.
- `tests/`, `.github/workflows/ci.yml` — автоматические проверки.

Учебные квоты: до 15 попыток входа на логин за 5 минут, 200 глобально за 5 минут; до 20 сообщений в час на пользователя и 300 глобально. Это защита от неконтролируемых запросов, а не полноценная защита от распределённых атак. Блокировка данных одного пользователя автоматически истекает через 10 минут после аварии. При использовании PostgreSQL SQLAlchemy подключается через `NullPool`; prepared statements отключены для transaction pooler.
