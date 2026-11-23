"""Métricas objetivas (metrics.py): uma função por tipo, violações dependentes do perfil,
falha no cálculo não derruba a geração, comparação grava metrics + evaluation."""

from __future__ import annotations

import copy
import json

import pytest

from support_assistant.cli import main
from support_assistant.llm_client import FAKE_RESPONSES
from support_assistant.metrics import MAX_QUESTIONS, compute_metrics
from support_assistant.models import ClarifyingQuestionsOutput, analyze_flow

LEIGO_CHAT = {"technical_level": "leigo", "channel": "chat"}
AVANCADO_EMAIL = {"technical_level": "avancado", "channel": "email"}
INTERMEDIARIO_TELEFONE = {"technical_level": "intermediario", "channel": "telefone"}
INTERMEDIARIO_EMAIL = {"technical_level": "intermediario", "channel": "email"}


def rules(metrics: dict) -> list[str]:
    return [v["rule"] for v in metrics["violations"]]


def steps_output(*instructions: str) -> dict:
    return {
        "opening": "Olá!",
        "steps": [{"step": i, "instruction": text, "why": None} for i, text in enumerate(instructions, 1)],
        "closing": "Até logo.",
        "escalation": "Se persistir, agendar visita (ESC-01).",
    }


# ---------------------------------------------------------------------------
# Um caso por tipo
# ---------------------------------------------------------------------------


def test_diagnosis_metrics():
    m = compute_metrics("diagnosis", FAKE_RESPONSES["diagnosis"], LEIGO_CHAT)
    assert (m["n_hypotheses"], m["n_evidence"], m["n_missing_info"]) == (2, 1, 2)
    assert m["likelihood"] == {"alta": 1, "media": 1, "baixa": 0}
    assert m["kb_ids"] == ["PROC-01", "WIFI-01"]
    assert m["escalation"] is False
    assert m["violations"] == [] and m["n_violations"] == 0  # texto interno: sem regra de perfil


def test_resolution_steps_metrics():
    output = steps_output("Desligue o roteador da tomada.", "Espere trinta segundos e ligue de novo.")
    m = compute_metrics("resolution_steps", output, INTERMEDIARIO_EMAIL)
    assert m["n_steps"] == 2
    assert m["avg_words_per_step"] == 6.0  # 5 e 7 palavras
    assert m["max_words_per_step"] == 7
    assert m["question_steps"] == 0
    assert (m["jargon"], m["urls_ips"], m["commands"]) == ([], 0, 0)
    assert m["kb_ids"] == ["ESC-01"] and m["escalation"] is True
    assert m["violations"] == []


def test_clarifying_questions_metrics():
    output = {
        "already_known": ["Internet lenta", "Desde ontem"],
        "questions": [
            {"priority": 1, "question": "A luz LOS está vermelha?", "purpose": "Descartar fibra (ESC-01)."},
            {"priority": 3, "question": "Acontece no cabo? E no Wi-Fi?", "purpose": "Isolar."},
        ],
    }
    m = compute_metrics("clarifying_questions", output, AVANCADO_EMAIL)
    assert (m["n_questions"], m["n_already_known"]) == (2, 2)
    assert m["double_questions"] == 1
    assert m["over_limit"] is False
    assert m["priorities_sequential"] is False  # 1, 3: pulou o 2
    assert m["kb_ids"] == ["ESC-01"]
    assert m["violations"] == []


def test_more_than_five_questions_is_always_a_violation():
    output = {
        "already_known": [],
        "questions": [{"priority": i, "question": f"Pergunta {i}?", "purpose": "x"} for i in range(1, 7)],
    }
    for profile in (LEIGO_CHAT, AVANCADO_EMAIL):
        m = compute_metrics("clarifying_questions", output, profile)
        assert m["over_limit"] is True and m["priorities_sequential"] is True
        assert rules(m) == ["too_many_questions"]


def test_question_limit_matches_schema():
    max_len = next(c.max_length for c in ClarifyingQuestionsOutput.model_fields["questions"].metadata
                   if hasattr(c, "max_length"))
    assert MAX_QUESTIONS == max_len


def test_flow_summary_metrics_reuse_analyze_flow():
    tree = FAKE_RESPONSES["flow_summary"]
    m = compute_metrics("flow_summary", tree, LEIGO_CHAT)
    report = analyze_flow(tree)
    assert (m["decisions"], m["depth"], m["leaves_with_ref"]) == (report.decisions, report.depth, report.leaves_with_ref)
    assert (m["decisions"], m["depth"], m["leaves_with_ref"]) == (3, 3, 3)
    assert m["kb_ids"] == ["ESC-01", "ESC-02", "WIFI-01"]
    assert m["escalation"] is True
    assert m["violations"] == []


def test_flow_quality_rules_are_violations():
    tree = copy.deepcopy(FAKE_RESPONSES["flow_summary"])
    tree["nodes"][2]["question"] = "Funciona no cabo ou só no Wi-Fi?"
    tree["nodes"][2]["no"] = {"action": "Reiniciar", "ref": "PROC-01"}
    m = compute_metrics("flow_summary", tree, AVANCADO_EMAIL)
    assert rules(m) == ["question_not_yes_no", "procedure_leaf"]


# ---------------------------------------------------------------------------
# Violações dependentes do perfil
# ---------------------------------------------------------------------------


def test_jargon_is_violation_only_for_leigo():
    output = steps_output("Conecte o celular na rede de 5 GHz.")
    leigo = compute_metrics("resolution_steps", output, LEIGO_CHAT)
    avancado = compute_metrics("resolution_steps", output, AVANCADO_EMAIL)

    assert leigo["jargon"] == avancado["jargon"] == ["GHz"]  # a métrica é igual...
    assert rules(leigo) == ["jargon_for_leigo"]  # ...mas só é violação para leigo
    assert leigo["violations"][0]["where"] == "steps[1]"
    assert rules(avancado) == []


def test_portuguese_pronoun_is_not_jargon():
    output = steps_output("Desligue os aparelhos e espere para religá-los.")
    assert compute_metrics("resolution_steps", output, LEIGO_CHAT)["jargon"] == []


def test_url_is_violation_only_on_phone():
    output = steps_output("Acesse http://192.168.0.1 e confira o sinal.")
    phone = compute_metrics("resolution_steps", output, INTERMEDIARIO_TELEFONE)
    email = compute_metrics("resolution_steps", output, INTERMEDIARIO_EMAIL)

    assert phone["urls_ips"] == email["urls_ips"] >= 1
    assert rules(phone) == ["link_or_command_phone"]
    assert rules(email) == []


def test_command_is_violation_on_phone():
    output = steps_output("Rode ping 8.8.8.8 no computador.")
    m = compute_metrics("resolution_steps", output, INTERMEDIARIO_TELEFONE)
    assert m["commands"] == 1
    assert "link_or_command_phone" in rules(m)


def test_step_ending_with_question_mark_is_detected():
    output = steps_output("Desligue o roteador.", "A luz ficou verde?")
    for profile in (LEIGO_CHAT, AVANCADO_EMAIL):  # conta sempre
        m = compute_metrics("resolution_steps", output, profile)
        assert m["question_steps"] == 1
        assert {"rule": "step_is_question", "where": "steps[2]", "detail": "A luz ficou verde?"} in m["violations"]


def test_escalation_note_is_not_checked_for_jargon():
    """`escalation` é nota para o atendente: jargão ali não é violação para o cliente leigo."""
    output = steps_output("Desligue o roteador.")
    output["escalation"] = "Se a ONT ficar com LOS vermelho, agendar visita (ESC-01)."
    assert compute_metrics("resolution_steps", output, LEIGO_CHAT)["violations"] == []


def test_accepts_customer_profile_object(settings):
    from support_assistant.models import load_customers

    c01 = load_customers(settings.customers_path)["c01"]  # leigo + telefone
    m = compute_metrics("resolution_steps", FAKE_RESPONSES["resolution_steps"], c01)
    assert "jargon_for_leigo" in rules(m)  # o fake fala em ONT/PON


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        compute_metrics("poema", {}, LEIGO_CHAT)


# ---------------------------------------------------------------------------
# Integração
# ---------------------------------------------------------------------------


def test_generate_records_metrics(generator, customer, ticket):
    record = generator.generate(customer, ticket, "resolution_steps", "v3")
    assert record["metrics"]["n_steps"] == 3
    assert "metrics_error" not in record
    saved = json.loads((generator.storage.output_dir / "history.json").read_text(encoding="utf-8"))[-1]
    assert saved["metrics"] == record["metrics"]


def test_metrics_failure_does_not_break_generation(generator, customer, ticket, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("métrica quebrou")

    monkeypatch.setattr("support_assistant.generators.compute_metrics", boom)
    record = generator.generate(customer, ticket, "diagnosis", "v3")

    assert record["output"] == FAKE_RESPONSES["diagnosis"]
    assert record["metrics"] is None
    assert record["metrics_error"] == "RuntimeError: métrica quebrou"
    saved = json.loads((generator.storage.output_dir / "history.json").read_text(encoding="utf-8"))[-1]
    assert saved["metrics_error"] == "RuntimeError: métrica quebrou"
    assert (generator.storage.output_dir / "cache.json").exists()  # a saída válida foi cacheada


def test_comparison_record_has_metrics_and_evaluation(tmp_path, monkeypatch, capsys):
    answers = iter(["3", "ok", "3", "ok", "3", "ok", "4", "ok", "4", "ok", "4", "ok"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    code = main(["compare", "-c", "c01", "-t", "t02", "-y", "resolution_steps", "--versions", "v2", "v3"])
    out = capsys.readouterr().out

    assert code == 0
    # tabela impressa depois das saídas e antes das notas
    assert out.index("Métricas objetivas") < out.index("Agora avalie")
    assert "jargon_for_leigo" in out  # c01 é leigo e o fake usa ONT/PON

    history = json.loads((tmp_path / "outputs" / "history.json").read_text(encoding="utf-8"))
    comparison = history[-1]
    assert comparison["kind"] == "comparison"
    for run in comparison["runs"]:
        assert run["evaluation"]["average"] in (3, 4)
        assert run["metrics"]["n_steps"] == 3
        assert "jargon_for_leigo" in rules(run["metrics"])
