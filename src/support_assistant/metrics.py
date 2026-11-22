"""Métricas objetivas por execução (não bloqueiam a geração).

`compute_metrics(content_type, output, profile)` despacha para uma função por tipo e devolve
contagens + uma lista `violations` que **depende do perfil do cliente**:

| regra                  | quando conta                                   |
|------------------------|------------------------------------------------|
| `jargon_for_leigo`     | jargão técnico em texto ao cliente, só p/ leigo |
| `link_or_command_phone`| URL, IP ou comando, só no canal telefone (POL-05) |
| `step_is_question`     | passo que termina em "?" (sempre)              |
| `too_many_questions`   | mais de 5 perguntas (sempre)                   |
| `question_not_yes_no`  | nó do fluxo sem "?" ou na forma "X ou Y?" (sempre) |
| `procedure_leaf`       | folha do fluxo com ref `PROC-*` (sempre)       |

Separação deliberada em relação à validação:
- `models.py` (schemas + `analyze_flow`) = regras **estruturais**: falhou → retry 1x → erro.
- Este módulo = regras de **qualidade**: medidas e gravadas no registro, nunca rejeitam. São
  heurísticas (falso positivo possível) e é a ablação que deve mostrá-las, não um retry que
  ensinaria a correção a todas as versões.

Os campos lidos são os dos schemas de `models.py`, acessados como dict (sem revalidar), para que
as métricas também funcionem em registros antigos e mostrem violações que o schema atual barraria.
Quem chama (generators.py) captura qualquer exceção e grava `metrics_error`: métrica nunca derruba
uma execução.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from support_assistant.models import analyze_flow

# --- regras -----------------------------------------------------------------

VIOLATION_RULES = {
    "jargon_for_leigo": "jargão técnico em texto para cliente leigo",
    "link_or_command_phone": "URL, IP ou comando no canal telefone (POL-05)",
    "step_is_question": "passo é uma pergunta, não uma instrução",
    "too_many_questions": "mais perguntas que o limite",
    "question_not_yes_no": "pergunta não é de sim/não (não termina com '?' ou tem a forma 'X ou Y?')",
    "procedure_leaf": "folha termina num procedimento (ref PROC-*), não numa ação final",
}

MAX_QUESTIONS = 5  # igual ao max_length de ClarifyingQuestionsOutput.questions (conferido em teste)
PROCEDURE_REF_PREFIX = "PROC-"
ESCALATION_PREFIX = "ESC-"

KB_ID_RE = re.compile(r"\b[A-Z]{2,6}-\d{2}\b")  # EQ-01, PROC-01, ESC-02...
# Siglas comparadas com maiúsculas exatas: em minúsculas colidem com português
# ("desligá-los" contém "los"). Palavras comuns, sem diferenciar maiúsculas.
# Mesma lista que o script de comparação já usava (termos que a base proíbe para `leigo`).
JARGON_ACRONYMS = ("ONT", "PON", "LOS", "DNS", "IP", "LAN", "GHz")
JARGON_WORDS = ("ping", "traceroute", "firmware")
_JARGON_ACRONYM_RE = re.compile(r"\b(" + "|".join(map(re.escape, JARGON_ACRONYMS)) + r")\b")
_JARGON_WORD_RE = re.compile(r"\b(" + "|".join(map(re.escape, JARGON_WORDS)) + r")\b", re.IGNORECASE)
URL_IP_RE = re.compile(r"https?://\S+|www\.\S+|\b\d{1,3}(?:\.\d{1,3}){3}\b")
COMMAND_RE = re.compile(r"\b(ping|traceroute|tracert|ipconfig|ifconfig|nslookup|netsh)\s+\S+", re.IGNORECASE)
_EITHER_OR_RE = re.compile(r"\bou\b", re.IGNORECASE)


# --- helpers ----------------------------------------------------------------


def _violation(rule: str, where: str, detail: str) -> dict:
    return {"rule": rule, "where": where, "detail": detail}


def _profile_fields(profile) -> tuple[str, str]:
    """(technical_level, channel) de um CustomerProfile ou do dict gravado no registro."""
    data = profile.to_dict() if hasattr(profile, "to_dict") else dict(profile or {})
    return str(data.get("technical_level", "")), str(data.get("channel", ""))


def kb_ids_cited(value) -> list[str]:
    """Ids da base citados em qualquer lugar de um valor JSON."""
    return sorted(set(KB_ID_RE.findall(json.dumps(value, ensure_ascii=False))))


def find_jargon(text: str) -> list[str]:
    acronyms = _JARGON_ACRONYM_RE.findall(text)
    words = [w.lower() for w in _JARGON_WORD_RE.findall(text)]
    return sorted(set(acronyms + words))


def find_links_and_commands(text: str) -> tuple[list[str], list[str]]:
    return URL_IP_RE.findall(text), [m.group(0) for m in COMMAND_RE.finditer(text)]


def is_yes_no_question(question: str) -> bool:
    text = question.strip()
    return text.endswith("?") and not _EITHER_OR_RE.search(text)


def _escalation(ids: list[str]) -> bool:
    return any(i.startswith(ESCALATION_PREFIX) for i in ids)


# --- por tipo -----------------------------------------------------------------


def diagnosis_metrics(output: dict, level: str, channel: str) -> dict:
    hypotheses = output.get("hypotheses") or []
    distribution = {"alta": 0, "media": 0, "baixa": 0}
    for h in hypotheses:
        key = str(h.get("likelihood", ""))
        distribution[key] = distribution.get(key, 0) + 1
    ids = kb_ids_cited(output)
    return {
        "n_hypotheses": len(hypotheses),
        "n_evidence": len(output.get("evidence") or []),
        "n_missing_info": len(output.get("missing_info") or []),
        "likelihood": distribution,
        "kb_ids": ids,
        "escalation": _escalation(ids),
        # texto interno (para o atendente): jargão e links não são violação aqui
        "violations": [],
    }


def resolution_steps_metrics(output: dict, level: str, channel: str) -> dict:
    steps = output.get("steps") or []
    violations: list[dict] = []
    words = [len(str(s.get("instruction", "")).split()) for s in steps]
    question_steps = [s for s in steps if str(s.get("instruction", "")).strip().endswith("?")]

    # Texto que chega ao cliente: abertura, passos (instrução + porquê) e fechamento.
    # `escalation` é nota para o atendente e fica fora da checagem de jargão/links.
    customer_texts = [("opening", str(output.get("opening") or ""))]
    for s in steps:
        label = f"steps[{s.get('step')}]"
        customer_texts.append((label, f"{s.get('instruction') or ''} {s.get('why') or ''}"))
    customer_texts.append(("closing", str(output.get("closing") or "")))

    jargon_all: set[str] = set()
    links_all: list[str] = []
    commands_all: list[str] = []
    for where, text in customer_texts:
        jargon = find_jargon(text)
        links, commands = find_links_and_commands(text)
        jargon_all.update(jargon)
        links_all += links
        commands_all += commands
        if jargon and level == "leigo":
            violations.append(_violation("jargon_for_leigo", where, ", ".join(jargon)))
        if (links or commands) and channel == "telefone":
            violations.append(_violation("link_or_command_phone", where, ", ".join(links + commands)))

    for s in question_steps:
        violations.append(_violation("step_is_question", f"steps[{s.get('step')}]", str(s.get("instruction"))))

    ids = kb_ids_cited(output)
    return {
        "n_steps": len(steps),
        "avg_words_per_step": round(sum(words) / len(words), 1) if words else 0,
        "max_words_per_step": max(words, default=0),
        "question_steps": len(question_steps),
        "jargon": sorted(jargon_all),
        "urls_ips": len(links_all),
        "commands": len(commands_all),
        "kb_ids": ids,
        "escalation": _escalation(ids),
        "violations": violations,
    }


def clarifying_questions_metrics(output: dict, level: str, channel: str) -> dict:
    questions = output.get("questions") or []
    priorities = sorted(q.get("priority") for q in questions if isinstance(q.get("priority"), int))
    violations = []
    if len(questions) > MAX_QUESTIONS:
        violations.append(_violation("too_many_questions", "questions", f"{len(questions)} > {MAX_QUESTIONS}"))
    return {
        "n_questions": len(questions),
        "n_already_known": len(output.get("already_known") or []),
        # mais de um "?" num item = duas perguntas juntas
        "double_questions": sum(str(q.get("question", "")).count("?") > 1 for q in questions),
        "over_limit": len(questions) > MAX_QUESTIONS,
        "priorities_sequential": priorities == list(range(1, len(questions) + 1)),
        "kb_ids": kb_ids_cited(output),
        "violations": violations,
    }


def flow_violations(tree: dict) -> list[dict]:
    """Regras de qualidade do fluxo (independem do perfil), em ordem dos nós."""
    found: list[dict] = []
    for node in tree.get("nodes") or []:
        node_id = str(node.get("id"))
        question = str(node.get("question", ""))
        if not is_yes_no_question(question):
            found.append(_violation("question_not_yes_no", node_id, question))
        for side in ("yes", "no"):
            branch = node.get(side) or {}
            ref = branch.get("ref")
            if branch.get("action") and ref and str(ref).upper().startswith(PROCEDURE_REF_PREFIX):
                found.append(_violation("procedure_leaf", f"{node_id}.{side}", str(ref)))
    return found


def flow_summary_metrics(output: dict, level: str, channel: str) -> dict:
    report = analyze_flow(output)  # mesma função da validação; kb_ids=None pula a checagem de ref
    ids = kb_ids_cited(output)
    return {
        "decisions": report.decisions,
        "depth": report.depth,
        "leaves": report.leaves,
        "leaves_with_ref": report.leaves_with_ref,
        "kb_ids": ids,
        "escalation": _escalation(ids),
        "violations": flow_violations(output),
    }


METRICS_BY_TYPE: dict[str, Callable[[dict, str, str], dict]] = {
    "diagnosis": diagnosis_metrics,
    "resolution_steps": resolution_steps_metrics,
    "clarifying_questions": clarifying_questions_metrics,
    "flow_summary": flow_summary_metrics,
}


def compute_metrics(content_type: str, output: dict, profile) -> dict:
    """Métricas de uma saída para um perfil. Levanta exceção se não conseguir calcular."""
    if content_type not in METRICS_BY_TYPE:
        raise ValueError(f"sem métricas para o tipo {content_type!r}")
    if not isinstance(output, dict):
        raise ValueError("a saída precisa ser um objeto JSON")
    level, channel = _profile_fields(profile)
    metrics = METRICS_BY_TYPE[content_type](output, level, channel)
    metrics["n_violations"] = len(metrics["violations"])
    return metrics


def count_by_rule(violations: list[dict]) -> dict[str, int]:
    """Contagem por regra, com zero para as regras sem violação (colunas estáveis)."""
    counts = {rule: 0 for rule in VIOLATION_RULES}
    for violation in violations:
        counts[violation["rule"]] = counts.get(violation["rule"], 0) + 1
    return counts
