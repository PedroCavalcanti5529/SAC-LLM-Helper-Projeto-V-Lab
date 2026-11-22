"""Montagem do prompt em 4 camadas. Único módulo que lê templates de `prompts/`.

Camadas:
  1. Base     (prompts/base/system.md)   persona, limites, regras de adaptação. Fixa.
  2. Domínio  (prompts/base/domain.md + data/domains/wifi_isp.json)   fatos da empresa. Fixa.
  3. Tarefa   (prompts/<versao>/<tipo>.md)   instrução + formato. ÚNICA que muda entre versões.
  4. Entrada  (prompts/base/input.md)   perfil + ticket delimitados por tags.

Camadas 1-3 vão na instrução de sistema; a camada 4 vai na mensagem do usuário.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from string import Template

from support_assistant.models import CONTENT_TYPES, CustomerProfile, InputValidationError, Ticket

BASE_DIR = "base"
SYSTEM_FILE = "system.md"
DOMAIN_FILE = "domain.md"
INPUT_FILE = "input.md"
RETRY_FILE = "retry.md"


@dataclass(frozen=True)
class BuiltPrompt:
    system: str
    user: str
    prompt_version: str
    content_type: str
    template_hash: str


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InputValidationError(f"Template de prompt não encontrado: {path}") from None


def list_versions(prompts_dir: Path) -> list[str]:
    """Versões = subpastas de prompts/ (exceto base) com ao menos um template .md."""
    if not prompts_dir.is_dir():
        return []
    return sorted(
        p.name for p in prompts_dir.iterdir() if p.is_dir() and p.name != BASE_DIR and any(p.glob("*.md"))
    )


def list_content_types(prompts_dir: Path, version: str) -> list[str]:
    folder = prompts_dir / version
    return [ct for ct in CONTENT_TYPES if (folder / f"{ct}.md").is_file()]


def validate_version(prompts_dir: Path, version: str) -> str:
    versions = list_versions(prompts_dir)
    if version not in versions:
        raise InputValidationError(
            f"Versão de prompt inexistente: {version!r}. Opções: {', '.join(versions) or '(nenhuma)'}."
        )
    return version


def _hash_texts(*texts: str) -> str:
    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
        digest.update(b"\x00")  # separador: evita colisão por concatenação
    return digest.hexdigest()


def _sanitize_tag_content(text: str) -> str:
    """Impede que o texto do cliente feche as tags de delimitação (injeção simples)."""
    return text.replace("</ticket>", "</ ticket>").replace("</perfil_cliente>", "</ perfil_cliente>")


def build_prompt(
    customer: CustomerProfile,
    ticket: Ticket,
    content_type: str,
    version: str,
    prompts_dir: Path,
    domain_path: Path,
) -> BuiltPrompt:
    validate_version(prompts_dir, version)
    if content_type not in list_content_types(prompts_dir, version):
        raise InputValidationError(
            f"A versão {version!r} não tem template para {content_type!r}. "
            f"Disponíveis: {', '.join(list_content_types(prompts_dir, version))}."
        )

    base_dir = prompts_dir / BASE_DIR
    system_raw = _read(base_dir / SYSTEM_FILE)
    domain_tpl = _read(base_dir / DOMAIN_FILE)
    input_tpl = _read(base_dir / INPUT_FILE)
    retry_tpl = _read(base_dir / RETRY_FILE)
    task_raw = _read(prompts_dir / version / f"{content_type}.md")
    domain_raw = _read(domain_path)

    try:
        domain_facts = json.dumps(json.loads(domain_raw), ensure_ascii=False, indent=2)
    except json.JSONDecodeError as exc:
        raise InputValidationError(f"JSON de domínio inválido em {domain_path}: {exc}") from None

    domain_layer = Template(domain_tpl).substitute(domain_facts=domain_facts)
    system = "\n\n".join(part.strip() for part in (system_raw, domain_layer, task_raw))

    user = Template(input_tpl).substitute(
        customer_profile=_sanitize_tag_content(json.dumps(customer.to_dict(), ensure_ascii=False, indent=2)),
        ticket_id=ticket.id or "texto_livre",
        ticket_text=_sanitize_tag_content(ticket.text),
        content_type=content_type,
    ).strip()

    # Hash de TODOS os templates usados (inclui domínio e retry): qualquer edição
    # muda o hash, invalida o cache e fica registrada no histórico (RN05).
    template_hash = _hash_texts(system_raw, domain_tpl, domain_raw, task_raw, input_tpl, retry_tpl)

    return BuiltPrompt(
        system=system,
        user=user,
        prompt_version=version,
        content_type=content_type,
        template_hash=template_hash,
    )


def build_retry_message(prompts_dir: Path, errors: str) -> str:
    """Mensagem de correção enviada na 2ª tentativa quando o JSON veio inválido."""
    template = _read(prompts_dir / BASE_DIR / RETRY_FILE)
    return Template(template).substitute(errors=errors).strip()
