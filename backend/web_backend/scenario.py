"""Trusted server configuration for the City N scenario."""

import base64
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import zlib

from negotiation_game.engine import search_enabled


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((Path(__file__).with_name("scenario.json")).read_text(encoding="utf-8"))
ROLES = CONFIG["roles"]
ROLE_IDS = {role["player_id"] for role in ROLES}
logger = logging.getLogger(__name__)


def game_settings() -> dict:
    raw = CONFIG["settings"]
    return {"max_rounds": raw["max_rounds"], "components": [
        {"id": "water_supply", "name": "Вода и заморозка тарифов", "cost": raw["water_cost"] * 1_000_000},
        {"id": "independent_monitoring", "name": "Независимый мониторинг",
         "cost": raw["monitoring_cost"] * 1_000_000},
        {"id": "reconstruction", "name": "Реконструкция очистных",
         "cost": raw["reconstruction_cost"] * 1_000_000},
    ]}


def public_scenario() -> dict:
    settings = game_settings()
    return {
        "title": "Ситуация в городе N",
        "briefing": ("После аварии на предприятии холдинга река загрязнена. Пять сторон обсуждают "
                     "восстановление очистных и безопасную воду для жителей."),
        "roles": [{"id": row["player_id"], "name": row["player_name"], "interest": row["motivation"]}
                  for row in ROLES],
        "total_cost_rub": sum(item["cost"] for item in settings["components"]),
        "max_bargaining_turns": settings["max_rounds"],
    }


def game_profiles(strategies, model_factory, *, human_roles=()) -> list[dict]:
    profiles = []
    for role in ROLES:
        role_id, name = role["player_id"], role["player_name"]
        prompt = strategies.get(role_id, role["prompt"]).strip()
        context = role["personal_context"].strip()
        if not context:
            context = prompt or f"Вы представляете {name} в переговорах."
        elif prompt and context != prompt:
            context = f"{context}\n\n### Стратегия и инструкции:\n{prompt}"
        profiles.append({
            "id": role_id, "name": name, "budget": role["budget_millions"] * 1_000_000,
            "expected_own_share": role["expected_own_share"], "desired_responsible": role["desired_responsible"],
            "personal_context": context, "motivation": role["motivation"],
            "personal_history": role["personal_history"], "prompt": prompt,
            **({"control_mode": "human"} if role_id in human_roles else {}),
            "llm": None if role_id in human_roles else model_factory(role_id, role["temperature"]),
        })
    return profiles


@lru_cache(maxsize=1)
def rag_corpus() -> tuple[str, bytes]:
    raw = (ROOT / "full_embeddings.jsonl").read_bytes()
    return base64.b64encode(zlib.compress(raw)).decode("ascii"), raw


def build_rag(runs_dir: Path, embedding_base_url: str, embedding_api_key: str) -> dict:
    corpus, raw = rag_corpus()
    config = CONFIG["rag"]
    result = {"corpus_b64": corpus, "embedding_base_url": embedding_base_url,
              "embedding_api_key": embedding_api_key, "embedding_model": config["MODEL"],
              "dimension": config["DIMENSION"], "top_k": config["top_k"]}
    if not embedding_base_url:
        return result

    try:
        path, collection_name = build_search_index(runs_dir, raw)
    except Exception as exc:
        logger.warning("Дополнительный поиск RAG недоступен: %s. Используем обязательный контекст.",
                       type(exc).__name__)
        return {**result, "embedding_base_url": ""}
    return {**result, "chroma_path": str(path), "collection_name": collection_name}


def build_search_index(runs_dir: Path, raw: bytes) -> tuple[Path, str]:
    import chromadb
    from chromadb.config import Settings

    config = CONFIG["rag"]

    digest = hashlib.sha256(raw).hexdigest()[:16]
    collection_name = f"city_n_{digest}_{config['INDEX_SCHEMA_VERSION']}"
    path = runs_dir / ".rag" / digest
    client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
    collection = client.get_or_create_collection(name=collection_name, embedding_function=None,
                                                  configuration={"hnsw": {"space": "cosine"}})
    records = [json.loads(row) for row in raw.splitlines() if row.strip()]
    if collection.count() != len(records):
        for start in range(0, len(records), 50):
            batch = records[start:start + 50]
            metadata = [{**{f"visible_{role}": role in record["audience"] for role in config["ROLES"]},
                         "area": record["area"], "search_enabled": search_enabled(record)} for record in batch]
            collection.upsert(ids=[r["chunk_id"] for r in batch], documents=[r["text"] for r in batch],
                              embeddings=[r["embedding"] for r in batch], metadatas=metadata)
    return path, collection_name
