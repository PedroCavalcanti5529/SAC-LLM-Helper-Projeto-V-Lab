"""Modelos de dados.

- Entradas (perfil e ticket): dataclasses com validação manual, para dar mensagens
  de erro claras ANTES de qualquer chamada ao LLM (RN01, RN02).
- Saídas do LLM: schemas Pydantic, um por tipo de conteúdo (RN03). O schema é o
  mesmo em todas as versões de prompt (não depende da versão, só do tipo), para que a
  comparação entre versões meça a instrução e não a facilidade de passar no validador.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_serializer,
    model_validator,
)


class InputValidationError(ValueError):
    """Entrada inválida (perfil, ticket, tipo ou versão). Detectada antes do LLM."""


# ---------------------------------------------------------------------------
# Enums (sem acento no código: `intermediario`, `didatico`)
# ---------------------------------------------------------------------------


class TechnicalLevel(str, Enum):
    LEIGO = "leigo"
    INTERMEDIARIO = "intermediario"
    AVANCADO = "avancado"


class CommunicationStyle(str, Enum):
    DIRETO = "direto"
    DETALHADO = "detalhado"
    DIDATICO = "didatico"


class Channel(str, Enum):
    CHAT = "chat"
    EMAIL = "email"
    TELEFONE = "telefone"


class ContentType(str, Enum):
    DIAGNOSIS = "diagnosis"
    RESOLUTION_STEPS = "resolution_steps"
    CLARIFYING_QUESTIONS = "clarifying_questions"
    FLOW_SUMMARY = "flow_summary"


CONTENT_TYPES: tuple[str, ...] = tuple(ct.value for ct in ContentType)


def _enum_value(enum_cls: type[Enum], value: object, field_name: str, owner: str) -> str:
    valid = [e.value for e in enum_cls]
    if value not in valid:
        raise InputValidationError(
            f"{owner}: campo '{field_name}' com valor inválido {value!r}. Valores aceitos: {', '.join(valid)}."
        )
    return str(value)


def validate_content_type(content_type: str) -> str:
    if content_type not in CONTENT_TYPES:
        raise InputValidationError(
            f"Tipo de conteúdo inexistente: {content_type!r}. Opções: {', '.join(CONTENT_TYPES)}."
        )
    return content_type


# ---------------------------------------------------------------------------
# Entradas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomerProfile:
    id: str
    name: str
    technical_level: str
    communication_style: str
    channel: str
    plan: str | None = None
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "CustomerProfile":
        if not isinstance(data, dict):
            raise InputValidationError(f"Perfil inválido: esperado objeto JSON, recebido {type(data).__name__}.")
        customer_id = str(data.get("id", "")).strip()
        if not customer_id:
            raise InputValidationError("Perfil sem campo 'id'.")
        owner = f"Perfil '{customer_id}'"
        return cls(
            id=customer_id,
            name=str(data.get("name", customer_id)),
            technical_level=_enum_value(TechnicalLevel, data.get("technical_level"), "technical_level", owner),
            communication_style=_enum_value(
                CommunicationStyle, data.get("communication_style"), "communication_style", owner
            ),
            channel=_enum_value(Channel, data.get("channel"), "channel", owner),
            plan=data.get("plan"),
            notes=data.get("notes"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Ticket:
    id: str | None
    text: str

    @classmethod
    def from_text(cls, text: str | None, ticket_id: str | None = None) -> "Ticket":
        cleaned = (text or "").strip()
        if not cleaned:
            raise InputValidationError("Ticket vazio: descreva o problema do cliente (texto não pode ser só espaços).")
        return cls(id=ticket_id, text=cleaned)

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text}


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InputValidationError(f"Arquivo não encontrado: {path}") from None
    except json.JSONDecodeError as exc:
        raise InputValidationError(f"JSON inválido em {path}: {exc}") from None


def load_customers(path: Path) -> dict[str, CustomerProfile]:
    data = _read_json(path)
    if not isinstance(data, list):
        raise InputValidationError(f"{path}: esperado uma lista de perfis.")
    customers = [CustomerProfile.from_dict(item) for item in data]
    return {c.id: c for c in customers}


def load_tickets(path: Path) -> dict[str, dict]:
    """Retorna {id: {"id", "category", "text"}}. Valida que nenhum texto é vazio."""
    data = _read_json(path)
    if not isinstance(data, list):
        raise InputValidationError(f"{path}: esperado uma lista de tickets.")
    tickets: dict[str, dict] = {}
    for item in data:
        ticket = Ticket.from_text(item.get("text"), item.get("id"))
        tickets[str(ticket.id)] = {"id": ticket.id, "category": item.get("category", ""), "text": ticket.text}
    return tickets


# ---------------------------------------------------------------------------
# Saídas do LLM (Pydantic)
# ---------------------------------------------------------------------------

NonEmptyStr = Annotated[str, Field(min_length=1)]


class _Output(BaseModel):
    # Campos extras são ignorados; campos obrigatórios ausentes geram erro (e retry).
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Hypothesis(_Output):
    cause: NonEmptyStr
    likelihood: Literal["alta", "media", "baixa"]
    rationale: NonEmptyStr


class DiagnosisOutput(_Output):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=5)
    evidence: list[NonEmptyStr] = Field(min_length=1)
    missing_info: list[NonEmptyStr]
    probable_conclusion: NonEmptyStr


class ResolutionStep(_Output):
    step: int = Field(ge=1)
    instruction: NonEmptyStr
    why: str | None = None


class ResolutionStepsOutput(_Output):
    opening: str = ""
    steps: list[ResolutionStep] = Field(min_length=1, max_length=10)
    closing: str = ""
    escalation: NonEmptyStr

    @field_validator("steps")
    @classmethod
    def _sort_steps(cls, steps: list[ResolutionStep]) -> list[ResolutionStep]:
        return sorted(steps, key=lambda s: s.step)


class ClarifyingQuestion(_Output):
    priority: int = Field(ge=1)
    question: NonEmptyStr
    purpose: NonEmptyStr


class ClarifyingQuestionsOutput(_Output):
    already_known: list[NonEmptyStr]
    questions: list[ClarifyingQuestion] = Field(max_length=5)

    @field_validator("questions")
    @classmethod
    def _sort_questions(cls, questions: list[ClarifyingQuestion]) -> list[ClarifyingQuestion]:
        return sorted(questions, key=lambda q: q.priority)


# --- flow_summary: árvore de decisão (o ASCII é desenhado pelo código, em flow_render.py) ---

FLOW_MAX_DEPTH = 5  # máximo de decisões em qualquer caminho a partir de `start`
FLOW_MAX_NODES = 15
PROCEDURE_REF_PREFIX = "PROC-"  # procedimento não é fim de fluxo: folha com PROC-* é inválida
_EITHER_OR_RE = re.compile(r"\bou\b", re.IGNORECASE)  # "X ou Y?" não é pergunta de sim/não


class FlowBranch(_Output):
    """Saída de um nó: vai para outro nó (`next`) OU termina numa ação final (`action` + `ref`)."""

    next: str | None = None
    action: str | None = None
    ref: str | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> "FlowBranch":
        self.next, self.action, self.ref = self.next or None, self.action or None, self.ref or None
        if bool(self.next) == bool(self.action):
            raise ValueError('cada saída precisa de exatamente um: "next" (id de nó) ou "action" (ação final)')
        if self.next and self.ref:
            raise ValueError('"ref" só pode aparecer junto de "action"')
        return self

    @model_serializer
    def _dump(self) -> dict:
        return {"next": self.next} if self.next else {"action": self.action, "ref": self.ref}


class FlowNode(_Output):
    id: NonEmptyStr
    question: NonEmptyStr
    yes: FlowBranch
    no: FlowBranch


@dataclass
class FlowReport:
    """Métricas e problemas de uma árvore. Usado pela validação e pelo script de comparação."""

    decisions: int = 0
    depth: int = 0
    leaves: int = 0
    leaves_with_ref: int = 0
    missing_start: bool = False
    duplicate_ids: list[str] = dc_field(default_factory=list)
    broken_exits: list[str] = dc_field(default_factory=list)
    unreachable: list[str] = dc_field(default_factory=list)
    cycle: list[str] = dc_field(default_factory=list)
    invalid_questions: list[str] = dc_field(default_factory=list)
    unknown_refs: list[str] = dc_field(default_factory=list)
    procedure_refs: list[str] = dc_field(default_factory=list)  # folhas com ref PROC-*: proibido

    def problems(self) -> list[str]:
        found = []
        if self.missing_start:
            found.append("'start' não corresponde a nenhum nó")
        if self.duplicate_ids:
            found.append(f"ids de nó repetidos: {', '.join(self.duplicate_ids)}")
        if self.broken_exits:
            found.append(f"saídas quebradas (next para nó inexistente): {', '.join(self.broken_exits)}")
        if self.unreachable:
            found.append(f"nós inalcançáveis a partir de 'start': {', '.join(self.unreachable)}")
        if self.cycle:
            found.append(f"ciclo: {' → '.join(self.cycle)}")
        elif self.depth > FLOW_MAX_DEPTH:
            found.append(f"profundidade {self.depth} excede o máximo de {FLOW_MAX_DEPTH} decisões")
        if self.invalid_questions:
            found.append(
                "perguntas que não são de sim/não (devem terminar com '?' e não ter a forma 'X ou Y?'): "
                + ", ".join(self.invalid_questions)
            )
        if self.unknown_refs:
            found.append(f"ref inexistente na base de conhecimento: {', '.join(self.unknown_refs)}")
        if self.procedure_refs:
            found.append(
                "folha com ref de procedimento (PROC-*) não é ação final; o procedimento deve virar "
                f"uma decisão ('... resolveu?'): {', '.join(self.procedure_refs)}"
            )
        return found


def is_yes_no_question(question: str) -> bool:
    text = question.strip()
    return text.endswith("?") and not _EITHER_OR_RE.search(text)


def analyze_flow(tree: dict, kb_ids: set[str] | None = None) -> FlowReport:
    """Analisa uma árvore em formato dict (tolerante a campos ausentes).

    `kb_ids=None` pula a checagem de `ref` (usado quando a base não está disponível).
    """
    report = FlowReport()
    by_id: dict[str, dict] = {}
    for node in tree.get("nodes") or []:
        node_id = str(node.get("id"))
        if node_id in by_id:
            report.duplicate_ids.append(node_id)
        by_id[node_id] = node
    report.decisions = len(by_id)

    for node_id, node in by_id.items():
        if not is_yes_no_question(str(node.get("question", ""))):
            report.invalid_questions.append(node_id)
        for side in ("yes", "no"):
            branch = node.get(side) or {}
            if branch.get("next"):
                if branch["next"] not in by_id:
                    report.broken_exits.append(f"{node_id}.{side} → {branch['next']}")
            elif branch.get("action"):
                report.leaves += 1
                if branch.get("ref"):
                    report.leaves_with_ref += 1
                    if str(branch["ref"]).upper().startswith(PROCEDURE_REF_PREFIX):
                        report.procedure_refs.append(f"{node_id}.{side} ({branch['ref']})")
                    if kb_ids is not None and branch["ref"] not in kb_ids:
                        report.unknown_refs.append(branch["ref"])
            else:
                report.broken_exits.append(f"{node_id}.{side} sem next nem action")

    start = tree.get("start")
    if start not in by_id:
        report.missing_start = True
        return report

    reachable: set[str] = set()

    def depth_from(node_id: str, path: list[str]) -> int:
        if node_id in path:  # voltou a um nó do caminho atual: ciclo
            if not report.cycle:
                report.cycle = path[path.index(node_id):] + [node_id]
            return 0
        reachable.add(node_id)
        children = [
            (by_id[node_id].get(side) or {}).get("next") for side in ("yes", "no")
        ]
        deepest = max((depth_from(c, path + [node_id]) for c in children if c in by_id), default=0)
        return 1 + deepest

    report.depth = depth_from(start, [])
    report.unreachable = [node_id for node_id in by_id if node_id not in reachable]
    return report


class FlowSummaryOutput(_Output):
    title: NonEmptyStr
    start: NonEmptyStr
    nodes: list[FlowNode] = Field(min_length=1, max_length=FLOW_MAX_NODES)

    @model_validator(mode="after")
    def _valid_tree(self, info: ValidationInfo) -> "FlowSummaryOutput":
        kb_ids = (info.context or {}).get("kb_ids")
        problems = analyze_flow(self.model_dump(), kb_ids).problems()
        if problems:
            raise ValueError("árvore de decisão inválida: " + "; ".join(problems))
        return self


def load_kb_ids(domain_path: Path) -> set[str]:
    """Todos os `id` da base de conhecimento (EQ-01, PROC-01, ESC-01...)."""
    ids: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("id"), str):
                ids.add(value["id"])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(_read_json(domain_path))
    return ids


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    ContentType.DIAGNOSIS.value: DiagnosisOutput,
    ContentType.RESOLUTION_STEPS.value: ResolutionStepsOutput,
    ContentType.CLARIFYING_QUESTIONS.value: ClarifyingQuestionsOutput,
    ContentType.FLOW_SUMMARY.value: FlowSummaryOutput,
}
