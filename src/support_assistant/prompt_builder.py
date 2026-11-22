"""Montagem do prompt em camadas, guiada pelo manifesto da versão. Único módulo que lê `prompts/`.

Camadas:
  1. Base     (prompts/base/system.md)   persona, limites, regras de adaptação, formato.
  2. Domínio  (prompts/base/domain.md + data/domains/wifi_isp.json)   fatos da empresa.
  3. Tarefa   (prompts/<pasta>/<tipo>.md)   instrução + formato de cada tipo.
  4. Entrada  (prompts/base/input.md)   perfil + ticket delimitados por tags. Sempre presente.

Cada versão tem `prompts/<versao>/manifest.json`, que declara quais camadas usa:

  {"layers": {"base": true|false, "domain": true|false, "tasks": "<pasta>"},
   "role": "<arquivo>"   # obrigatório quando base=false: papel mínimo que substitui a base
   "description": "...", "hypothesis": "...", "changelog": [...]}

Caminhos (`tasks`, `role`) são relativos a `prompts/`.

O código não conhece nenhuma versão pelo nome: tudo sai do manifesto. Camadas 1-3 (ou o
papel mínimo) vão na instrução de sistema; a camada 4 vai na mensagem do usuário.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from support_assistant.models import CONTENT_TYPES, CustomerProfile, InputValidationError, Ticket

BASE_DIR = "base"
MANIFEST_FILE = "manifest.json"
SYSTEM_FILE = "system.md"
DOMAIN_FILE = "domain.md"
INPUT_FILE = "input.md"
RETRY_FILE = "retry.md"


@dataclass(frozen=True)
class Manifest:
    version: str
    base: bool
    domain: bool
    tasks: str
    role: str | None
    description: str
    hypothesis: str
    changelog: list[str] = field(default_factory=list)

    def layers(self) -> dict:
        """Resumo das camadas usadas, gravado no histórico junto de cada execução."""
        return {"base": self.base, "domain": self.domain, "tasks": self.tasks, "role": self.role}


@dataclass(frozen=True)
class BuiltPrompt:
    system: str
    user: str
    prompt_version: str
    content_type: str
    template_hash: str
    layers: dict


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise InputValidationError(f"Template de prompt não encontrado: {path}") from None


# ---------------------------------------------------------------------------
# Versões e manifestos
# ---------------------------------------------------------------------------


def list_versions(prompts_dir: Path) -> list[str]:
    """Versões = subpastas de prompts/ que têm um manifest.json."""
    if not prompts_dir.is_dir():
        return []
    return sorted(p.name for p in prompts_dir.iterdir() if p.is_dir() and (p / MANIFEST_FILE).is_file())


def validate_version(prompts_dir: Path, version: str) -> str:
    versions = list_versions(prompts_dir)
    if version not in versions:
        raise InputValidationError(
            f"Versão de prompt inexistente: {version!r}. Opções: {', '.join(versions) or '(nenhuma)'}."
        )
    return version


def load_manifest(prompts_dir: Path, version: str) -> Manifest:
    """Lê e valida o manifesto. Erros apontam o arquivo e o campo com problema."""
    validate_version(prompts_dir, version)
    path = prompts_dir / version / MANIFEST_FILE
    try:
        data = json.loads(_read(path))
    except json.JSONDecodeError as exc:
        raise InputValidationError(f"Manifesto inválido em {path}: {exc}") from None

    def fail(message: str) -> InputValidationError:
        return InputValidationError(f"Manifesto {path}: {message}")

    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, dict):
        raise fail("campo 'layers' ausente ou não é um objeto.")
    for flag in ("base", "domain"):
        if not isinstance(layers.get(flag), bool):
            raise fail(f"'layers.{flag}' deve ser true ou false.")
    tasks = layers.get("tasks")
    if not isinstance(tasks, str) or not tasks.strip():
        raise fail("'layers.tasks' deve ser o nome de uma pasta em prompts/.")
    if not (prompts_dir / tasks).is_dir():
        raise fail(f"pasta de tarefas 'prompts/{tasks}' não existe.")

    role = data.get("role")
    if not layers["base"]:
        if not isinstance(role, str) or not role.strip():
            raise fail("sem camada base ('layers.base': false) é obrigatório informar 'role'.")
        if not (prompts_dir / role).is_file():
            raise fail(f"arquivo de papel 'prompts/{role}' não existe.")
    elif role is not None:
        raise fail("'role' só é usado quando 'layers.base' é false; remova o campo.")

    changelog = data.get("changelog", [])
    return Manifest(
        version=version,
        base=layers["base"],
        domain=layers["domain"],
        tasks=tasks,
        role=role,
        description=str(data.get("description", "")),
        hypothesis=str(data.get("hypothesis", "")),
        changelog=list(changelog) if isinstance(changelog, list) else [],
    )


def list_content_types(prompts_dir: Path, version: str) -> list[str]:
    folder = prompts_dir / load_manifest(prompts_dir, version).tasks
    return [ct for ct in CONTENT_TYPES if (folder / f"{ct}.md").is_file()]


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------


def _hash_parts(parts: list[tuple[str, str]]) -> str:
    """SHA-256 de pares (rótulo, texto). O rótulo distingue, por exemplo, 'role' de 'base'."""
    digest = hashlib.sha256()
    for label, text in parts:
        for chunk in (label, text):
            digest.update(chunk.encode("utf-8"))
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
    manifest = load_manifest(prompts_dir, version)
    available = list_content_types(prompts_dir, version)
    if content_type not in available:
        raise InputValidationError(
            f"A versão {version!r} não tem template para {content_type!r}. Disponíveis: {', '.join(available)}."
        )

    base_dir = prompts_dir / BASE_DIR
    # Pares (rótulo, texto bruto) de TUDO que entra no prompt final, na ordem de montagem.
    hashed: list[tuple[str, str]] = []
    system_parts: list[str] = []

    # Camada 1: base completa, ou o papel mínimo declarado no manifesto.
    if manifest.base:
        base_raw = _read(base_dir / SYSTEM_FILE)
        hashed.append(("base", base_raw))
    else:
        base_raw = _read(prompts_dir / manifest.role)
        hashed.append(("role", base_raw))
    system_parts.append(base_raw)

    # Camada 2: domínio (opcional).
    if manifest.domain:
        domain_tpl = _read(base_dir / DOMAIN_FILE)
        domain_raw = _read(domain_path)
        try:
            domain_facts = json.dumps(json.loads(domain_raw), ensure_ascii=False, indent=2)
        except json.JSONDecodeError as exc:
            raise InputValidationError(f"JSON de domínio inválido em {domain_path}: {exc}") from None
        hashed += [("domain_template", domain_tpl), ("domain_data", domain_raw)]
        system_parts.append(Template(domain_tpl).substitute(domain_facts=domain_facts))

    # Camada 3: tarefa, da pasta indicada no manifesto.
    task_raw = _read(prompts_dir / manifest.tasks / f"{content_type}.md")
    hashed.append(("task", task_raw))
    system_parts.append(task_raw)

    system = "\n\n".join(part.strip() for part in system_parts)

    # Camada 4: entrada (igual em todas as versões).
    input_tpl = _read(base_dir / INPUT_FILE)
    user = Template(input_tpl).substitute(
        customer_profile=_sanitize_tag_content(json.dumps(customer.to_dict(), ensure_ascii=False, indent=2)),
        ticket_id=ticket.id or "texto_livre",
        ticket_text=_sanitize_tag_content(ticket.text),
        content_type=content_type,
    ).strip()
    hashed.append(("input", input_tpl))

    # O retry também pode entrar no prompt (2ª tentativa), então entra no hash.
    hashed.append(("retry", _read(base_dir / RETRY_FILE)))

    # Qualquer edição em um arquivo usado, ou mudança de composição no manifesto,
    # muda o hash, invalida o cache e fica registrada no histórico (RN05).
    template_hash = _hash_parts(hashed)

    return BuiltPrompt(
        system=system,
        user=user,
        prompt_version=version,
        content_type=content_type,
        template_hash=template_hash,
        layers=manifest.layers(),
    )


def build_retry_message(prompts_dir: Path, errors: str) -> str:
    """Mensagem de correção enviada na 2ª tentativa quando o JSON veio inválido."""
    template = _read(prompts_dir / BASE_DIR / RETRY_FILE)
    return Template(template).substitute(errors=errors).strip()
