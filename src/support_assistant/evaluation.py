"""Rubrica de avaliação manual (RN09).

Este módulo só VALIDA as notas dadas por uma pessoa e monta o objeto que será
persistido junto da execução. Ele não gera notas (não há juiz LLM).
"""

from __future__ import annotations

RUBRIC_CRITERIA: dict[str, str] = {
    "clarity": "Clareza: o texto é fácil de entender, sem ambiguidade nem ruído?",
    "customer_fit": "Adequação ao cliente: respeita nível técnico, estilo e canal do perfil?",
    "actionability": "Acionabilidade: dá para agir imediatamente com base no conteúdo?",
}
SCORE_MIN = 1
SCORE_MAX = 5


class EvaluationError(ValueError):
    """Nota fora do intervalo, não inteira, ou justificativa vazia."""


def validate_score(value: object) -> int:
    if isinstance(value, bool):
        raise EvaluationError("Nota deve ser um número inteiro de 1 a 5.")
    if isinstance(value, str):
        value = value.strip()
        if not value.lstrip("-").isdigit():
            raise EvaluationError(f"Nota inválida {value!r}: use um inteiro de {SCORE_MIN} a {SCORE_MAX}.")
        value = int(value)
    if not isinstance(value, int):
        raise EvaluationError(f"Nota inválida {value!r}: use um inteiro de {SCORE_MIN} a {SCORE_MAX}.")
    if not SCORE_MIN <= value <= SCORE_MAX:
        raise EvaluationError(f"Nota {value} fora do intervalo {SCORE_MIN}–{SCORE_MAX}.")
    return value


def validate_justification(text: object) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise EvaluationError("Justificativa não pode ser vazia.")
    return cleaned


def build_evaluation(scores: dict[str, dict]) -> dict:
    """Recebe {criterio: {"score": ..., "justification": ...}} e devolve a avaliação validada."""
    missing = [c for c in RUBRIC_CRITERIA if c not in scores]
    if missing:
        raise EvaluationError(f"Critérios sem nota: {', '.join(missing)}.")
    evaluation: dict = {}
    for criterion in RUBRIC_CRITERIA:
        item = scores[criterion]
        evaluation[criterion] = {
            "score": validate_score(item.get("score")),
            "justification": validate_justification(item.get("justification")),
        }
    total = sum(evaluation[c]["score"] for c in RUBRIC_CRITERIA)
    evaluation["average"] = round(total / len(RUBRIC_CRITERIA), 2)
    evaluation["evaluated_by"] = "human"
    return evaluation


def pick_winner(runs: list[dict]) -> str | None:
    """Versão com maior média; None em caso de empate ou sem avaliação."""
    scored = [(r["evaluation"]["average"], r["prompt_version"]) for r in runs if r.get("evaluation")]
    if len(scored) < 2:
        return None
    scored.sort(reverse=True)
    if scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]
