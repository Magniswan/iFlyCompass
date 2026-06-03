# iFlyCompass — Agent Notes

**Stack:** Flask 3.x + Vue 2 + Element UI + SQLite (SQLAlchemy) + Flask-SocketIO (threading)
**Version:** REL3.1.1

## Run

```bash
pip install -r requirements.txt
python app.py          # Main app http://127.0.0.1:5002
```

Proxy service auto-starts on port 5003 in the background.
Windows helpers: `start_app.bat` (background via `pythonw`), `git_update.bat`.

## Architecture

- **Entry:** `app.py` creates app, registers Blueprints, runs `run_migrations()`, starts proxy server.
- **Modules:** `modules/<name>/` — each has `__init__.py` (Blueprint), `routes.py`, `api.py`, and often `websocket.py`.
- **Models:** `models/` — SQLAlchemy ORM. Import from `models` package (`from models.user import User`).
- **Utils:** `utils/` — shared helpers (settings, validators, file, chapter parser, NCM API, ffmpeg).
- **Extensions:** `extensions.py` — `db`, `login_manager`, `socketio`.
- **Templates/Assets:** `templates/` (HTML with Vue 2), `assets/js/` (client-side logic), `assets/css/`.
- **Config:** `instance/config.yml` (YAML); auto-created with defaults if missing. Secrets auto-generated and persisted there.
- **Data dirs:** `instance/`, `temp/`, `stickers/` — auto-created at startup in `app.py`.

## Game Modules Pattern

Each game (doudizhu, chess, gomoku, uno, uno_nomer) is an independent Blueprint + Socket.IO namespace:
- Shared in-memory room state lives in the module `__init__.py`.
- `api.py`: REST for room create/join/leave.
- `websocket.py`: Socket.IO game events.
- Game stats are written to `GameRecord` / `UserGameStats` in `models/game_stats.py`.

## Critical Conventions

- **Datetime:** Always use `datetime.now(timezone.utc)` (aware). Do NOT use `datetime.utcnow()` — it was deprecated and mixing naive/aware datetimes causes `TypeError`.
- **Session invalidation:** `User.session_version` is checked in `login_manager.user_loader` (`extensions.py`). Bumping it kicks the user out on next request. Used for "logout all devices" and password changes.
- **Time zone:** Server stores UTC; UI converts to China time (UTC+8) where needed.
- **Migration style:** New DB tables/columns are added via raw SQLite `ALTER`/`CREATE TABLE` in `app.py::run_migrations()`, not Alembic.
- **Proxy process:** `modules/proxy/proxy_server.py` spawns `mitmdump` with `CREATE_NO_WINDOW` and kills old processes via `taskkill`/`pkill` on start/stop.

## Adding a New Module

1. Create `modules/<name>/` with `__init__.py`, `routes.py`, `api.py`.
2. Import and register Blueprint in `app.py`.
3. If using Socket.IO, add `websocket.py` with `register_socketio_events(socketio)` and call it in `app.py`.
4. Add models in `models/<name>.py` and export in `models/__init__.py`.
5. Add table creation in `app.py::run_migrations()` if the table is new.
6. Add nav/tool entries in `templates/tools.html` `builtInApps` and/or `instance/nav.yml`.

## Frontend Notes

- Vue 2 + Element UI. Templates are server-rendered Jinja2 HTML with inline Vue components.
- CSS uses custom themes and variables (e.g., `--imm-text`, `--primary-color`).
- Touch/gesture handling: many pages intercept `touchmove` to prevent browser pull-to-refresh and rubber-band effects. Be careful adding global touch listeners.
- Android virtual keyboard: `Visual Viewport API` is used to detect keyboard open and hide UI chrome.

## Gotchas

- **No test suite exists** currently. Verify by running the app and exercising the feature manually.
- **No lint/typecheck config** in repo. Follow existing style (4-space indent, Chinese comments OK).
- **FFmpeg** is required for Bilibili video caching. Path resolution is in `utils/ffmpeg.py`; it looks in `tools/` and system PATH.
- **SQLite only.** No migrations framework — hand-write `run_migrations()` additions.
- **Windows-oriented scripts** assume `taskkill`, `pythonw.exe`, etc.
