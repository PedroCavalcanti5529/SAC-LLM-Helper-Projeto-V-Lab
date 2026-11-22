"""Testes ponta a ponta pela CLI, com provedor fake (sem rede, sem chave)."""

from __future__ import annotations

import json

import pytest

from support_assistant.cli import main
from support_assistant.models import CONTENT_TYPES


def _history(tmp_path):
    return json.loads((tmp_path / "outputs" / "history.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_generate_all_types(content_type, tmp_path, capsys):
    code = main(["generate", "--customer", "c01", "--ticket-id", "t02", "--type", content_type, "--version", "v2"])
    out = capsys.readouterr().out

    assert code == 0
    assert "JSON da execução:" in out
    record = _history(tmp_path)[-1]
    for field in ("run_id", "timestamp", "customer_id", "ticket", "content_type", "prompt_version",
                  "template_hash", "provider", "model", "config", "output", "evaluation", "cached"):
        assert field in record
    assert record["content_type"] == content_type
    assert record["provider"] == "fake"
    assert (tmp_path / "outputs" / "runs" / f"{record['run_id']}.json").exists()


def test_generate_free_text_ticket(tmp_path, capsys):
    code = main(["generate", "-c", "c03", "--ticket", "ping alto desde ontem", "-y", "diagnosis", "-p", "v1"])
    assert code == 0
    assert _history(tmp_path)[-1]["ticket"] == {"id": None, "text": "ping alto desde ontem"}


def test_compare_collects_rubric(tmp_path, capsys, monkeypatch):
    answers = iter(
        # v1: nota inválida (7) é rejeitada e pedida de novo; justificativa vazia também.
        ["7", "3", "", "texto ok", "2", "genérico", "3", "acionável"]
        # v2
        + ["5", "muito claro", "5", "linguagem certa", "4", "passos concretos"]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    code = main(["compare", "-c", "c02", "-t", "t02", "-y", "resolution_steps", "--versions", "v1", "v2"])
    out = capsys.readouterr().out

    assert code == 0
    assert "fora do intervalo" in out
    assert "não pode ser vazia" in out
    comparison = _history(tmp_path)[-1]
    assert comparison["kind"] == "comparison"
    assert comparison["versions"] == ["v1", "v2"]
    assert comparison["winner"] == "v2"
    v1, v2 = comparison["runs"]
    assert v1["evaluation"]["clarity"] == {"score": 3, "justification": "texto ok"}
    assert v2["evaluation"]["average"] == pytest.approx(4.67)
    assert v1["model"] == v2["model"] and v1["config"] == v2["config"]


def test_list(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "c01" in out and "t01" in out and "v1" in out and "v2" in out


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
