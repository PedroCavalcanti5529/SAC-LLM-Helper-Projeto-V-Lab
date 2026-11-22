"""Modelos de dados.

- Entradas (perfil e ticket): dataclasses com validação manual, para dar mensagens
  de erro claras ANTES de qualquer chamada ao LLM (RN01, RN02).
- Saídas do LLM: schemas Pydantic, um por tipo de conteúdo (RN03). O schema é o
  mesmo em todas as versões de prompt, para que a comparação v1 x v2 seja justa.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class DecisionPoint(_Output):
    id: NonEmptyStr
    check: NonEmptyStr
    if_yes: NonEmptyStr
    if_no: NonEmptyStr


class FlowSummaryOutput(_Output):
    title: NonEmptyStr
    ascii_diagram: str | None = None
    decision_points: list[DecisionPoint] = Field(min_length=1, max_length=10)


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    ContentType.DIAGNOSIS.value: DiagnosisOutput,
    ContentType.RESOLUTION_STEPS.value: ResolutionStepsOutput,
    ContentType.CLARIFYING_QUESTIONS.value: ClarifyingQuestionsOutput,
    ContentType.FLOW_SUMMARY.value: FlowSummaryOutput,
}
