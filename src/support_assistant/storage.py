"""Persistência do histórico de execuções (RN06).

Arquivos gerados em `OUTPUT_DIR` (padrão: `outputs/`):
  history.json        lista de todos os registros (gerações e comparações)
  runs/<id>.json      cada registro também em arquivo próprio, fácil de abrir
  failures.json       respostas inválidas do LLM (após o retry), para depuração
  cache.json          gerenciado por cache.py (usa as funções de escrita daqui)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def atomic_write_json(path: Path, data) -> None:
    """Escreve em arquivo temporário e renomeia: evita JSON corrompido se o processo cair."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class Storage:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.history_path = output_dir / "history.json"
        self.runs_dir = output_dir / "runs"
        self.failures_path = output_dir / "failures.json"

    def load_history(self) -> list[dict]:
        data = read_json(self.history_path, default=[])
        return data if isinstance(data, list) else []

    def _append(self, path: Path, record: dict) -> None:
        records = read_json(path, default=[])
        if not isinstance(records, list):
            records = []
        records.append(record)
        atomic_write_json(path, records)

    def _save_record(self, record: dict, record_id: str) -> Path:
        self._append(self.history_path, record)
        run_path = self.runs_dir / f"{record_id}.json"
        atomic_write_json(run_path, record)
        return run_path

    def save_run(self, record: dict) -> Path:
        return self._save_record(record, record["run_id"])

    def save_comparison(self, comparison: dict) -> Path:
        return self._save_record(comparison, comparison["comparison_id"])

    def log_failure(self, entry: dict) -> None:
        self._append(self.failures_path, entry)
