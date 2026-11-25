# Город N

Город N — учебная игра о переговорах после экологической аварии. Река загрязнена, и пяти сторонам нужно договориться, кто оплатит реконструкцию очистных и на каких условиях.

Перед запуском партии можно задать стратегии администрации, холдинга, региона, жителей и экологической организации. Дальше ИИ играет за все пять сторон. Они предлагают взносы, обсуждают условия и голосуют за протокол. В конце игра показывает итоги переговоров и выпуск городской газеты о том, что произошло за следующие десять лет.

## Запуск бекенда

Понадобятся Python 3.12, `uv` и доступ к языковой модели.
Для GigaChat сначала запустите локальный прокси Gpt2Giga.
Если у вас уже есть OpenAI-совместимый провайдер, переходите к разделу прямого подключения.

### Вариант 1. GigaChat через Gpt2Giga

1. В первом терминале из корня репозитория установите зависимости бекенда и прокси.

   ```bash
   cd backend
   uv sync --locked --extra gigachat
   ```

2. Создайте файл `backend/gpt2giga.env`. В `GIGACHAT_CREDENTIALS` вставьте
   **Authorization Key** из личного кабинета GigaChat. `GIGACHAT_API_PERS` подходит
   для личного доступа. Для аккаунта организации укажите scope своего аккаунта.

   ```dotenv
   GIGACHAT_CREDENTIALS=ваш_ключ_авторизации_GigaChat
   GIGACHAT_SCOPE=GIGACHAT_API_PERS
   GIGACHAT_MODEL=GigaChat-3-Lightning
   GPT2GIGA_MODE=DEV
   GPT2GIGA_HOST=127.0.0.1
   GPT2GIGA_PORT=8090
   GPT2GIGA_ENABLE_API_KEY_AUTH=True
   GPT2GIGA_API_KEY=city-n-local
   ```

3. Из папки `backend/` запустите Gpt2Giga и оставьте терминал открытым.

   ```bash
   uv run --locked --extra gigachat gpt2giga --env-path gpt2giga.env
   ```

   Прокси принимает OpenAI-совместимые запросы по базовому адресу
   `http://127.0.0.1:8090/v1`. Подробнее о переменных и режимах прокси см. в
   [документации Gpt2Giga](https://github.com/ai-forever/gpt2giga/blob/main/docs/configuration.md).

4. Создайте `backend/.env`. Значение `CITY_N_LLM_API_KEY` должно совпадать с
   `GPT2GIGA_API_KEY` из файла прокси. Здесь это локальный ключ `city-n-local`.
   Ключ авторизации GigaChat используется в `gpt2giga.env`.

   ```dotenv
   CITY_N_LLM_BASE_URL=http://127.0.0.1:8090/v1
   CITY_N_LLM_MODEL=GigaChat-3-Lightning
   CITY_N_LLM_API_KEY=city-n-local
   CITY_N_IMAGES=1
   ```

5. Откройте второй терминал. Из корня репозитория запустите FastAPI.

   ```bash
   cd backend
   uv run --locked --extra gigachat uvicorn web_backend.app:app --env-file .env --host 127.0.0.1 --port 8000
   ```

### Вариант 2. Прямое подключение OpenAI-совместимого провайдера

Провайдер должен поддерживать Chat Completions и function calling.
В `backend/.env` укажите базовый URL из документации провайдера, ID модели и
API-ключ, если требуется авторизация. Здесь можно подключиться и к уже
работающему OpenAI-совместимому прокси.

```dotenv
CITY_N_LLM_BASE_URL=https://provider.example/v1
CITY_N_LLM_MODEL=model-id
CITY_N_LLM_API_KEY=ключ_провайдера
CITY_N_IMAGES=1
```

Из корня репозитория запустите бекенд. `--env-file .env` загружает настройки для FastAPI.

```bash
cd backend
uv sync --locked
uv run --locked uvicorn web_backend.app:app --env-file .env --host 127.0.0.1 --port 8000
```

### Как запустить партию

Откройте Swagger UI. `GET /api/v1/scenario` покажет сценарий и ID пяти ролей.
Отправьте `POST /api/v1/games` с телом `{}` для стандартных стратегий или
передайте тексты в объекте `strategies` с ID ролей в качестве ключей.

В ответе на запуск будет `status_url`. Отправляйте по нему `GET`, чтобы читать
прогресс и итог. Для остановки отправьте `POST {status_url}/cancel`.
При `CITY_N_IMAGES=1` итог включает ссылку на иллюстрацию газеты.
[Swagger UI](http://127.0.0.1:8000/docs) · [Контракт API](backend/web_backend/openapi.json)

### Если возникла ошибка запуска

- При `Connection refused` проверьте, что процесс провайдера запущен и адрес в
  `CITY_N_LLM_BASE_URL` совпадает с его базовым URL. Для Gpt2Giga в примере
  используется `http://127.0.0.1:8090/v1`.
- При `401 Invalid API key` от локального прокси сверяйте `CITY_N_LLM_API_KEY`
  с `GPT2GIGA_API_KEY` и проверьте, что FastAPI запущен с `--env-file .env`.
  Если авторизацию отклоняет сам GigaChat, проверьте `GIGACHAT_CREDENTIALS` и `GIGACHAT_SCOPE`.
- При статусе партии `failed` подробность ошибки можно посмотреть в поле
  `error` файла `backend/games/web/<game_id>/result.json`.

## Запуск демофронта

В папке `frontend/` находится демонстрационный интерфейс с заготовленными репликами и итогами. Интерфейс предстоит подключить к API.

Из корня репозитория запустите статический сервер и откройте [демо](http://127.0.0.1:5173/).

```bash
python3 -m http.server 5173 --bind 127.0.0.1 --directory frontend
```

## Проверки

Автоматические тесты запускаются из папки `backend/`. Ответы модели в них подменены.

```bash
uv run --locked python -m unittest discover -s tests
```

## Зависимости Python

`backend/pyproject.toml` содержит прямые зависимости и опциональный набор `gigachat`.
`backend/uv.lock` фиксирует точные версии пакетов. Для установки используйте
`uv sync --locked`, для добавления нового пакета — `uv add <пакет>` из папки
`backend/`. После изменения зависимостей обновлённые `pyproject.toml` и
`uv.lock` идут в один коммит.
