"""Cache de respostas do LLM em arquivo JSON (RN07).

Chave = SHA-256 de (perfil, ticket, content_type, prompt_version, template_hash,
provider, model, config) serializados com chaves ordenadas. Mesma entrada -> mesma
chave -> nenhuma chamada à API.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from support_assistant.storage import atomic_write_json, read_json


def make_cache_key(fields: dict) -> str:
    serialized = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class JsonCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict:
        data = read_json(self.path, default={})
        return data if isinstance(data, dict) else {}

    def get(self, key: str) -> dict | None:
        return self._load().get(key)

    def set(self, key: str, value: dict) -> None:
        data = self._load()
        data[key] = value
        atomic_write_json(self.path, data)
