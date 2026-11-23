"""Orquestração de uma geração (e de uma comparação).

Fluxo de `generate`:
  perfil + ticket + tipo + versão
  -> prompt_builder (camadas declaradas no manifesto da versão + entrada)
  -> cache_key = sha256(campos ordenados)
  -> hit?  sim -> retorna saída do cache (cached=true, nenhuma chamada)
           não -> llm_client -> valida Pydantic -> inválido? retry 1x
  -> grava cache + histórico -> devolve o registro
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime

from pydantic import ValidationError

from support_assistant.cache import JsonCache, make_cache_key
from support_assistant.config import Settings
from support_assistant.flow_render import render_flow
from support_assistant.llm_client import create_client
from support_assistant.metrics import compute_metrics
from support_assistant.models import (
    OUTPUT_SCHEMAS,
    CustomerProfile,
    InputValidationError,
    Ticket,
    load_kb_ids,
    validate_content_type,
)
from support_assistant.prompt_builder import build_prompt, build_retry_message, list_content_types
from support_assistant.storage import Storage

logger = logging.getLogger(__name__)

# Tipos cuja saída também é desenhada pelo código. O texto vai no campo `rendered` do registro.
RENDERERS = {"flow_summary": render_flow}


class OutputValidationError(ValueError):
    """Resposta do LLM não é JSON válido ou não segue o schema."""


class GenerationError(Exception):
    """Resposta inválida mesmo após o retry. A CLI mostra a mensagem e segue sem quebrar."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_output(raw: str, content_type: str, kb_ids: set[str] | None = None) -> dict:
    """Converte o texto do LLM em dict validado pelo schema do tipo.

    `kb_ids` (ids da base de conhecimento) permite checar as `ref` do flow_summary.
    """
    try:
        data = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError as exc:
        raise OutputValidationError(f"A resposta não é um JSON válido ({exc.msg}, posição {exc.pos}).") from None
    if not isinstance(data, dict):
        raise OutputValidationError("A resposta deve ser um objeto JSON (chaves e valores), não uma lista/valor.")
    try:
        model = OUTPUT_SCHEMAS[content_type].model_validate(data, context={"kb_ids": kb_ids})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(raiz)'}: {err['msg']}" for err in exc.errors()
        )
        raise OutputValidationError(f"JSON fora do schema de {content_type}: {problems}") from None
    return model.model_dump()


def build_generator(settings: Settings, client=None) -> "Generator":
    """Monta o Generator a partir das configurações. Usado pela CLI e pela interface web.

    `client` permite injetar outro cliente de LLM (ex.: um provedor escolhido por sessão no
    deploy); sem ele, o provedor vem de `settings`.
    """
    return Generator(
        settings=settings,
        client=client if client is not None else create_client(settings),
        cache=JsonCache(settings.output_dir / "cache.json"),
        storage=Storage(settings.output_dir),
    )


class Generator:
    """Junta as dependências (settings, cliente, cache, storage) para gerar conteúdo."""

    def __init__(self, settings: Settings, client, cache: JsonCache, storage: Storage) -> None:
        self.settings = settings
        self.client = client
        self.cache = cache
        self.storage = storage
        self.kb_ids = load_kb_ids(settings.domain_path)  # para validar as `ref` do flow_summary

    def generate(
        self,
        customer: CustomerProfile,
        ticket: Ticket,
        content_type: str,
        version: str,
        persist: bool = True,
    ) -> dict:
        validate_content_type(content_type)
        prompt = build_prompt(
            customer, ticket, content_type, version, self.settings.prompts_dir, self.settings.domain_path
        )
        config = self.settings.generation_config
        cache_key = make_cache_key(
            {
                "customer": customer.to_dict(),
                "ticket": ticket.text,
                "content_type": content_type,
                "prompt_version": version,
                "template_hash": prompt.template_hash,
                "provider": self.client.provider,
                "model": self.client.model,
                "config": config,
            }
        )

        record = {
            "kind": "generation",
            "run_id": new_id(),
            "timestamp": now_iso(),
            "customer_id": customer.id,
            "customer_profile": customer.to_dict(),
            "ticket": ticket.to_dict(),
            "content_type": content_type,
            "prompt_version": version,
            "prompt_layers": prompt.layers,
            "template_hash": prompt.template_hash,
            "provider": self.client.provider,
            "model": self.client.model,
            "config": config,
            "cache_key": cache_key,
            "cached": False,
            "attempts": 0,  # tentativas por schema (1 ou 2)
            "provider_retries": 0,  # repetições por falha temporária do provedor (fora da chave de cache)
            "latency_ms": 0,
            "output": None,
            "metrics": None,  # objetivas, calculadas pelo código (metrics.py)
            "evaluation": None,  # rubrica humana (só em comparação)
        }

        hit = self.cache.get(cache_key)
        if hit is not None:
            record["cached"] = True
            record["output"] = hit["output"]
            record["cached_from_run_id"] = hit.get("run_id")
        else:
            started = time.perf_counter()
            output, attempts = self._call_with_retry(prompt.system, prompt.user, content_type, record)
            record["latency_ms"] = int((time.perf_counter() - started) * 1000)
            record["attempts"] = attempts
            record["output"] = output
            # Só chega aqui com saída válida: falhas nunca entram no cache.
            self.cache.set(
                cache_key,
                {"output": output, "run_id": record["run_id"], "created_at": record["timestamp"]},
            )

        if content_type in RENDERERS:  # texto desenhado pelo código, separado da árvore em `output`
            record["rendered"] = RENDERERS[content_type](record["output"])
        self._attach_metrics(record, content_type, customer)

        if persist:
            record["run_path"] = str(self.storage.save_run(record))
        return record

    @staticmethod
    def _attach_metrics(record: dict, content_type: str, customer: CustomerProfile) -> None:
        """Métricas + violações dependentes do perfil. Recalculadas também em cache hit
        (dependem só da saída e do perfil). Falha no cálculo nunca derruba a execução."""
        try:
            record["metrics"] = compute_metrics(content_type, record["output"], customer)
        except Exception as exc:  # noqa: BLE001 - métrica é acessória: registra e segue
            logger.warning("Falha ao calcular métricas (%s): %s", content_type, exc)
            record["metrics"] = None
            record["metrics_error"] = f"{type(exc).__name__}: {exc}"

    def _complete(self, system: str, user: str, content_type: str, record: dict) -> str:
        """Chama o LLM e soma as repetições por falha do provedor (retry de transporte, no llm_client)."""
        raw = self.client.complete(system, user, content_type)
        record["provider_retries"] += getattr(self.client, "last_provider_retries", 0)
        return raw

    def _call_with_retry(self, system: str, user: str, content_type: str, record: dict) -> tuple[dict, int]:
        raw = self._complete(system, user, content_type, record)
        try:
            return parse_output(raw, content_type, self.kb_ids), 1
        except OutputValidationError as first_error:
            logger.warning("Resposta fora do schema na 1ª tentativa (retry por schema): %s", first_error)
            retry_user = user + "\n\n" + build_retry_message(self.settings.prompts_dir, str(first_error))
            raw_retry = self._complete(system, retry_user, content_type, record)
            try:
                return parse_output(raw_retry, content_type, self.kb_ids), 2
            except OutputValidationError as second_error:
                self.storage.log_failure(
                    {
                        "timestamp": now_iso(),
                        "run_id": record["run_id"],
                        "content_type": content_type,
                        "prompt_version": record["prompt_version"],
                        "provider": record["provider"],
                        "model": record["model"],
                        "errors": [str(first_error), str(second_error)],
                        "raw_responses": [raw, raw_retry],
                    }
                )
                raise GenerationError(
                    f"O modelo devolveu JSON inválido duas vezes ({second_error}). "
                    f"Detalhes em {self.storage.failures_path}. Nada foi gravado no histórico nem no cache."
                ) from None

    def compare(
        self,
        customer: CustomerProfile,
        ticket: Ticket,
        content_type: str,
        versions: list[str],
    ) -> list[dict]:
        """Gera a mesma entrada em ≥2 versões. Só a versão varia (perfil/ticket/provider/model/config fixos)."""
        if len(versions) < 2:
            raise InputValidationError("A comparação precisa de pelo menos 2 versões de prompt.")
        if len(set(versions)) != len(versions):
            raise InputValidationError("As versões comparadas devem ser diferentes entre si.")
        validate_content_type(content_type)
        for version in versions:  # valida tudo (versão, manifesto, template do tipo) antes de gastar chamadas
            available = list_content_types(self.settings.prompts_dir, version)
            if content_type not in available:
                raise InputValidationError(
                    f"A versão {version!r} não tem template para {content_type!r}. "
                    f"Disponíveis: {', '.join(available)}."
                )
        return [self.generate(customer, ticket, content_type, v, persist=False) for v in versions]

    def save_comparison(self, runs: list[dict], winner: str | None) -> tuple[dict, str]:
        first = runs[0]
        comparison = {
            "kind": "comparison",
            "comparison_id": "cmp-" + new_id(),
            "timestamp": now_iso(),
            "customer_id": first["customer_id"],
            "ticket": first["ticket"],
            "content_type": first["content_type"],
            "provider": first["provider"],
            "model": first["model"],
            "config": first["config"],
            "versions": [r["prompt_version"] for r in runs],
            "winner": winner,
            "runs": runs,
        }
        path = self.storage.save_comparison(comparison)
        return comparison, str(path)
