"""Testes ponta a ponta pela CLI, com provedor fake (sem rede, sem chave)."""

from __future__ import annotations

import json

import pytest

from support_assistant.cli import main
from support_assistant.llm_client import FAKE_RESPONSES
from support_assistant.models import CONTENT_TYPES, OUTPUT_SCHEMAS


def _history(tmp_path):
    return json.loads((tmp_path / "outputs" / "history.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_generate_all_types(content_type, version, tmp_path, capsys):
    code = main(["generate", "--customer", "c01", "--ticket-id", "t02", "--type", content_type, "--version", version])
    out = capsys.readouterr().out

    assert code == 0
    assert "JSON da execução:" in out
    record = _history(tmp_path)[-1]
    for field in ("run_id", "timestamp", "customer_id", "ticket", "content_type", "prompt_version",
                  "prompt_layers", "template_hash", "provider", "model", "config", "output", "evaluation",
                  "cached"):
        assert field in record
    assert record["content_type"] == content_type
    assert record["prompt_version"] == version
    assert record["provider"] == "fake"
    # Mesmo schema de saída em todas as versões: a saída validada é idêntica.
    assert record["output"] == OUTPUT_SCHEMAS[content_type].model_validate(FAKE_RESPONSES[content_type]).model_dump()
    assert (tmp_path / "outputs" / "runs" / f"{record['run_id']}.json").exists()


def test_generate_default_version_is_v3(tmp_path, capsys):
    assert main(["generate", "-c", "c01", "-t", "t02", "-y", "diagnosis"]) == 0
    assert _history(tmp_path)[-1]["prompt_version"] == "v3"


def test_generate_free_text_ticket(tmp_path, capsys):
    code = main(["generate", "-c", "c03", "--ticket", "ping alto desde ontem", "-y", "diagnosis", "-p", "v1"])
    assert code == 0
    assert _history(tmp_path)[-1]["ticket"] == {"id": None, "text": "ping alto desde ontem"}


def test_compare_collects_rubric(tmp_path, capsys, monkeypatch):
    answers = iter(
        # v1: nota inválida (7) é rejeitada e pedida de novo; justificativa vazia também.
        ["7", "3", "", "texto ok", "2", "genérico", "3", "acionável"]
        # v2
        + ["4", "claro", "4", "adequado", "3", "genérico ainda"]
        # v3
        + ["5", "muito claro", "5", "linguagem certa", "4", "passos concretos"]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    # Sem --versions: o padrão é a ablação completa v1 v2 v3.
    code = main(["compare", "-c", "c02", "-t", "t02", "-y", "resolution_steps"])
    out = capsys.readouterr().out

    assert code == 0
    assert "fora do intervalo" in out
    assert "não pode ser vazia" in out
    comparison = _history(tmp_path)[-1]
    assert comparison["kind"] == "comparison"
    assert comparison["versions"] == ["v1", "v2", "v3"]
    assert comparison["winner"] == "v3"
    v1, v2, v3 = comparison["runs"]
    assert v1["evaluation"]["clarity"] == {"score": 3, "justification": "texto ok"}
    assert v2["evaluation"]["average"] == pytest.approx(3.67)
    assert v3["evaluation"]["average"] == pytest.approx(4.67)
    assert v1["model"] == v2["model"] == v3["model"] and v1["config"] == v2["config"] == v3["config"]
    assert len({r["template_hash"] for r in comparison["runs"]}) == 3


def test_compare_two_versions(tmp_path, monkeypatch, capsys):
    answers = iter(["3", "ok", "3", "ok", "3", "ok", "4", "ok", "4", "ok", "4", "ok"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert main(["compare", "-c", "c01", "-t", "t02", "-y", "diagnosis", "--versions", "v2", "v3"]) == 0
    comparison = _history(tmp_path)[-1]
    assert comparison["versions"] == ["v2", "v3"] and comparison["winner"] == "v3"


@pytest.mark.parametrize(
    "versions, expected",
    [(["v3"], "pelo menos 2"), (["v1", "v1"], "diferentes entre si"), (["v1", "v9"], "Versão de prompt inexistente")],
)
def test_compare_invalid_versions(versions, expected, capsys):
    assert main(["compare", "-c", "c01", "-t", "t02", "-y", "diagnosis", "--versions", *versions]) == 1
    assert expected in capsys.readouterr().err


def test_list(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "c01" in out and "t01" in out
    assert "v1" in out and "v2" in out and "v3" in out
    assert "papel mínimo + tarefas v1" in out
    assert "base + domínio + tarefas v1" in out
    assert "base + domínio + tarefas v3" in out


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["generate", "-c", "nao-existe", "-t", "t01", "-y", "diagnosis"], "Perfil inexistente"),
        (["generate", "-c", "c01", "-t", "t99", "-y", "diagnosis"], "Ticket inexistente"),
        (["generate", "-c", "c01", "-t", "t01", "-y", "poema"], "Tipo de conteúdo inexistente"),
        (["generate", "-c", "c01", "-t", "t01", "-y", "diagnosis", "-p", "v9"], "Versão de prompt inexistente"),
        (["generate", "-c", "c01", "--ticket", "   ", "-y", "diagnosis"], "Ticket vazio"),
    ],
)
def test_invalid_inputs_show_options(argv, expected, capsys):
    assert main(argv) == 1
    assert expected in capsys.readouterr().err


def test_missing_api_key_points_to_env(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert main(["generate", "-c", "c01", "-t", "t01", "-y", "diagnosis"]) == 1
    assert ".env" in capsys.readouterr().err
