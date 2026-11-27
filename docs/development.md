# Разработка

Обычный запуск описан в [README](../README.md). Здесь собраны сценарии для разработки и интеграции.

## Другой OpenAI-совместимый провайдер

В корневом `.env` задайте `CITY_N_LLM_BASE_URL`, `CITY_N_LLM_MODEL` и, если нужна авторизация, `CITY_N_LLM_API_KEY`. Адрес должен быть доступен из контейнера. Провайдер должен поддерживать Chat Completions и function calling.

```bash
docker compose -f compose.yaml -f compose.openai.yaml up --build
```

Остановить этот вариант можно командой `docker compose -f compose.yaml -f compose.openai.yaml down`. У обоих вариантов один том для партий. Переопределение требует Compose с поддержкой `!reset`. [Справка Docker](https://docs.docker.com/reference/compose-file/merge/#reset-value)

## Запуск без контейнеров

Понадобятся Python 3.12 и `uv`. Для GigaChat скопируйте [шаблон для локального шлюза](../backend/gpt2giga.env.example) в `backend/gpt2giga.env` и укажите там Authorization Key и scope. Команды для Windows, Linux и macOS одинаковые.

```bash
cd backend
uv run --locked --extra gigachat python -m web_backend --gigachat
```

Для прямого подключения вне Docker задайте `CITY_N_LLM_BASE_URL`, `CITY_N_LLM_MODEL` и, если нужна авторизация, `CITY_N_LLM_API_KEY` в `backend/.env`. Из папки `backend/` выполните `uv run --locked python -m web_backend`.

## API и состояние партии

- `POST /api/v1/games` с пустым телом и `Idempotency-Key` создаёт черновик. Сохраните cookie владельца из ответа.
- `PUT /api/v1/games/{game_id}/settings` принимает `{"mode":"automatic"}` или `{"mode":"manual","answers":{...}}`. Метаданные вопросов и границы ползунков приходят в snapshot.
- `POST /api/v1/games/{game_id}/start` запускает игру. Для каждого изменяющего `POST` нужен новый ключ. При сетевом повторе того же запроса используйте исходный ключ.
- `GET /api/v1/games/{game_id}` возвращает snapshot. `GET /api/v1/games/{game_id}/events?after=<last_event_id>` отдаёт новые события. При `EVENT_CURSOR_EXPIRED` загрузите snapshot заново.
- `POST /api/v1/games/{game_id}/analysis` разбирает указанную в `role_id` сторону. `message_ids` ограничивает запрос выбранными репликами. `complete_from_journal` разрешает дополнить неудавшиеся оценки наблюдениями из журнала.
- `GET /api/v1/games/{game_id}/analysis/questionnaire/{role_id}` сопоставляет сохранённые ответы анкеты с итоговым протоколом и предлагает варианты на следующую партию.
- `POST /api/v1/games/{game_id}/retry-result` пересчитывает последствия по сохранённым голосам.

Сессии доступны семь суток и привязаны к cookie браузера. Сервер запускается с одним worker. После перезапуска доступны черновики и завершённые партии. Прерванные дебаты получают `GAME_INTERRUPTED`. Если голоса сохранены, расчёт последствий можно повторить.

[Swagger UI](http://127.0.0.1:8000/docs) · [Контракт OpenAPI](../backend/web_backend/openapi.json)

## Настройки и диагностика

- При ошибке авторизации GigaChat проверьте `GIGACHAT_CREDENTIALS` и `GIGACHAT_SCOPE`. При ошибке подключения к другому провайдеру проверьте URL и доступность API из среды игры.
- `CITY_N_IMAGES=0` включает текстовый режим газеты. Для HTTPS за обратным прокси можно задать `CITY_N_SECURE_COOKIE=1`.

## Проверки

Запустите из `backend/`. Ответы модели в тестах подменяются.

```bash
uv run --locked python -X utf8 -m unittest discover -s tests
```

Прямые зависимости описаны в `backend/pyproject.toml`, версии зафиксированы в `backend/uv.lock`. Для установки используйте `uv sync --locked`, для добавления пакета — `uv add <пакет>` из `backend/`.
