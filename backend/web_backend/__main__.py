"""Start the local game and, optionally, its Gpt2Giga provider."""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from dotenv import dotenv_values, load_dotenv
import uvicorn


BACKEND = Path(__file__).resolve().parents[1]
LOCAL_HOST = "127.0.0.1"
PROXY_ENTRY_POINT = (
    "from importlib.metadata import distribution; "
    "import sys; "
    "entry = next(ep for ep in distribution('gpt2giga').entry_points "
    "if ep.group == 'console_scripts' and ep.name == 'gpt2giga'); "
    "sys.exit(entry.load()())"
)


def listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


@contextmanager
def start_proxy(config: Path):
    if not config.is_file():
        raise ValueError("Создайте backend/gpt2giga.env из файла gpt2giga.env.example.")
    values = dotenv_values(config)
    if not (os.environ.get("GIGACHAT_CREDENTIALS") or values.get("GIGACHAT_CREDENTIALS")):
        raise ValueError("Укажите GIGACHAT_CREDENTIALS в backend/gpt2giga.env.")
    host = os.environ.get("GPT2GIGA_HOST") or values.get("GPT2GIGA_HOST") or LOCAL_HOST
    if host not in {LOCAL_HOST, "localhost", "::1"}:
        raise ValueError("Для локального запуска задайте loopback-адрес в GPT2GIGA_HOST.")
    port = int(os.environ.get("GPT2GIGA_PORT") or values.get("GPT2GIGA_PORT") or 8090)
    if not 1 <= port <= 65535:
        raise ValueError("GPT2GIGA_PORT должен быть в диапазоне 1–65535.")
    if listening(host, port):
        raise ValueError(
            f"Порт Gpt2Giga {port} уже занят. Для подключения к запущенному шлюзу задайте настройки "
            "CITY_N_LLM_* в backend/.env. Затем из папки backend запустите uv run --locked python -m web_backend."
        )

    url_host = f"[{host}]" if ":" in host else host
    if not os.environ.get("CITY_N_LLM_BASE_URL"):
        os.environ["CITY_N_LLM_BASE_URL"] = f"http://{url_host}:{port}/v1"
    for proxy_key, backend_key in (("GIGACHAT_MODEL", "CITY_N_LLM_MODEL"),
                                   ("GPT2GIGA_API_KEY", "CITY_N_LLM_API_KEY")):
        value = os.environ.get(proxy_key) or values.get(proxy_key)
        if value and not os.environ.get(backend_key):
            os.environ[backend_key] = value

    command = [sys.executable, "-c", PROXY_ENTRY_POINT, "--env-path", str(config)]
    process = subprocess.Popen(command, cwd=BACKEND, stdin=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Gpt2Giga завершился при запуске с кодом {process.returncode}.")
            if listening(host, port):
                break
            time.sleep(0.2)
        else:
            raise RuntimeError(f"Gpt2Giga не открыл порт {port} в течение 15 секунд.")
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="Запуск игры «Ситуация в городе N».")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--gigachat", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Порт должен быть в диапазоне 1–65535.")

    load_dotenv(BACKEND / ".env")

    def serve():
        print(f"Город N: http://{LOCAL_HOST}:{args.port}/", flush=True)
        uvicorn.run("web_backend.app:app", host=LOCAL_HOST, port=args.port, workers=1)

    try:
        if args.gigachat:
            with start_proxy(BACKEND / "gpt2giga.env"):
                serve()
        else:
            serve()
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
