"""flow_summary: árvore de decisão validada + ASCII desenhado pelo código."""

from __future__ import annotations

import copy
import json

import pytest

from support_assistant.cli import main
from support_assistant.flow_render import render_flow, strip_ref
from support_assistant.generators import OutputValidationError, parse_output
from support_assistant.llm_client import FAKE_RESPONSES
from support_assistant.models import analyze_flow, load_kb_ids

VALID_TREE = {
    "title": "Wi-Fi cai no quarto — triagem",
    "start": "D1",
    "nodes": [
        {
            "id": "D1",
            "question": "A luz LOS está vermelha?",
            "yes": {"action": "Agendar visita técnica", "ref": "ESC-01"},
            "no": {"next": "D2"},
        },
        {
            "id": "D2",
            "question": "Funciona bem no cabo de rede?",
            "yes": {"action": "Orientar ajustes do Wi-Fi.", "ref": "WIFI-01"},
            "no": {"action": "Encerrar atendimento", "ref": None},
        },
    ],
}

EXPECTED_RENDER = """Wi-Fi cai no quarto — triagem

[D1] A luz LOS está vermelha?
├─ SIM → Agendar visita técnica (ESC-01). FIM
└─ NÃO → [D2] Funciona bem no cabo de rede?
   ├─ SIM → Orientar ajustes do Wi-Fi (WIFI-01). FIM
   └─ NÃO → Encerrar atendimento. FIM"""


@pytest.fixture
def kb_ids(settings):
    return load_kb_ids(settings.domain_path)


def _parse(tree, kb_ids):
    return parse_output(json.dumps(tree, ensure_ascii=False), "flow_summary", kb_ids)


def _mutate(change):
    tree = copy.deepcopy(VALID_TREE)
    change(tree)
    return tree


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------


def test_valid_tree_passes(kb_ids):
    assert _parse(VALID_TREE, kb_ids) == VALID_TREE
    report = analyze_flow(VALID_TREE, kb_ids)
    assert (report.decisions, report.depth, report.leaves, report.leaves_with_ref) == (2, 2, 3, 2)
    assert report.problems() == []


def _set(path, value):
    def change(tree):
        target = tree
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


@pytest.mark.parametrize(
    "change, expected",
    [
        (_set(["nodes", 1, "no"], {"next": "D1"}), "ciclo: D1 → D2 → D1"),
        (_set(["nodes", 1, "no"], {"next": "D9"}), "saídas quebradas"),
        (_set(["nodes", 1, "question"], "Funciona no cabo ou só no Wi-Fi?"), "não são de sim/não"),
        (_set(["nodes", 1, "question"], "Funciona bem no cabo de rede"), "não são de sim/não"),
        (_set(["nodes", 0, "yes", "ref"], "ESC-99"), "ref inexistente"),
        (_set(["start"], "D2"), "inalcançáveis"),
        (_set(["start"], "D7"), "'start' não corresponde"),
        (_set(["nodes", 0, "yes"], {"next": "D2", "action": "Encerrar atendimento"}), "exatamente um"),
        (_set(["nodes", 0, "yes"], {"ref": "ESC-01"}), "exatamente um"),
        (_set(["nodes", 1, "no"], {"action": "Reiniciar ONT e roteador", "ref": "PROC-01"}), r"PROC-\*"),
    ],
)
def test_invalid_trees_fail(change, expected, kb_ids):
    with pytest.raises(OutputValidationError, match=expected):
        _parse(_mutate(change), kb_ids)


def test_depth_above_five_fails(kb_ids):
    nodes = [
        {"id": f"D{i}", "question": f"Pergunta {i}?", "yes": {"next": f"D{i + 1}"},
         "no": {"action": "Encerrar atendimento", "ref": None}}
        for i in range(1, 7)
    ]
    nodes[-1]["yes"] = {"action": "Escalar para N2", "ref": "ESC-04"}
    tree = {"title": "Fundo demais", "start": "D1", "nodes": nodes}
    with pytest.raises(OutputValidationError, match="profundidade 6 excede o máximo de 5"):
        _parse(tree, kb_ids)


def test_invalid_tree_is_retried_once(generator, customer, ticket):
    from test_validation import ScriptedClient

    broken = _mutate(_set(["nodes", 1, "no"], {"next": "D1"}))
    generator.client = ScriptedClient([json.dumps(broken), json.dumps(VALID_TREE)])
    record = generator.generate(customer, ticket, "flow_summary", "v3")
    assert record["attempts"] == 2
    assert record["output"] == VALID_TREE


# ---------------------------------------------------------------------------
# Renderizador
# ---------------------------------------------------------------------------


def test_render_is_deterministic():
    first = render_flow(VALID_TREE)
    assert first == EXPECTED_RENDER
    assert render_flow(copy.deepcopy(VALID_TREE)) == first
    # a ordem dos nós na lista não muda o desenho (a árvore parte de `start`)
    reordered = {**VALID_TREE, "nodes": list(reversed(VALID_TREE["nodes"]))}
    assert render_flow(reordered) == first


@pytest.mark.parametrize(
    "action, ref, expected",
    [
        ("Agendar visita técnica (ESC-01)", "ESC-01", "Agendar visita técnica"),
        ("Agendar visita técnica conforme ESC-01.", "ESC-01", "Agendar visita técnica"),
        ("Escalar para N2 Rede [esc-02] com evidências", "ESC-02", "Escalar para N2 Rede com evidências"),
        ("ESC-04: escalar para N2 Suporte", "ESC-04", "escalar para N2 Suporte"),
        ("Orientar ajustes do Wi-Fi (WIFI-01)", "ESC-01", "Orientar ajustes do Wi-Fi (WIFI-01)"),  # id diferente fica
        ("Encerrar atendimento.", None, "Encerrar atendimento"),
    ],
)
def test_render_removes_id_repeated_from_ref(action, ref, expected):
    assert strip_ref(action, ref) == expected


def test_rendered_leaf_shows_ref_once():
    tree = _mutate(_set(["nodes", 0, "yes"], {"action": "Agendar visita técnica (ESC-01)", "ref": "ESC-01"}))
    assert "├─ SIM → Agendar visita técnica (ESC-01). FIM" in render_flow(tree)


# ---------------------------------------------------------------------------
# Ponta a ponta com o fake
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_flow_summary_end_to_end(version, tmp_path, capsys):
    code = main(["generate", "-c", "c01", "-t", "t02", "-y", "flow_summary", "-p", version])
    out = capsys.readouterr().out
    assert code == 0

    record = json.loads((tmp_path / "outputs" / "history.json").read_text(encoding="utf-8"))[-1]
    assert record["output"] == FAKE_RESPONSES["flow_summary"]  # árvore em `output`
    assert record["rendered"] == render_flow(record["output"])  # texto em campo separado
    assert record["rendered"] in out  # a CLI mostra o texto renderizado
    assert "├─ SIM → Agendar visita técnica (ESC-01). FIM" in out


def test_cache_hit_also_has_rendered(generator, fake_client, customer, ticket):
    first = generator.generate(customer, ticket, "flow_summary", "v3")
    second = generator.generate(customer, ticket, "flow_summary", "v3")
    assert fake_client.call_count == 1 and second["cached"] is True
    assert second["rendered"] == first["rendered"]
