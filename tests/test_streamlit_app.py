"""Fumaça da interface web (Streamlit AppTest), sempre no modo fake.

Pulado quando o extra `web` não está instalado (`pip install -e ".[web]"`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture
def app(settings):
    """App com as configurações injetadas pela sessão (o app não lê o .env quando já há settings)."""
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["settings"] = settings
    return at.run()


def _texts(at) -> str:
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [c.value for c in at.code]
    return "\n".join(map(str, parts))


def test_app_loads_and_generates(app, settings):
    assert not app.exception
    assert "fake" in _texts(app)  # barra lateral mostra o provedor

    app.selectbox(key="gen_type").set_value("flow_summary")
    app.button(key="gen_button").click().run()

    assert not app.exception
    assert not app.error
    assert "├─ SIM →" in _texts(app)  # flow_summary renderizado em st.code
    history = json.loads((settings.output_dir / "history.json").read_text(encoding="utf-8"))
    assert history[-1]["content_type"] == "flow_summary"
    assert history[-1]["metrics"] is not None


def test_empty_free_text_ticket_shows_friendly_error(app):
    app.radio(key="gen_source").set_value("Texto livre").run()
    app.button(key="gen_button").click().run()
    assert not app.exception
    assert app.error and "vazio" in app.error[0].value.lower()


def test_blind_compare_reveals_versions_only_after_saving(app, settings):
    app.radio(key="screen").set_value("Comparar").run()
    app.button(key="cmp_button").click().run()
    assert not app.exception
    headers = [s.value for s in app.subheader]
    assert {"Resposta A", "Resposta B", "Resposta C"} <= set(headers)
    assert not any("v1" in h or "v2" in h or "v3" in h for h in headers)  # versões escondidas
    client = app.session_state["_generator"].client
    assert client.call_count == 3

    # Reexecutar o script (interação fora do formulário) não chama o LLM de novo nem perde as saídas.
    app.checkbox(key="cmp_blind").uncheck().run()
    assert client.call_count == 3
    assert {"Resposta A", "Resposta B", "Resposta C"} <= {s.value for s in app.subheader}

    # Preencher e enviar a rubrica também não gera nada: só grava.
    for pos in range(3):
        for criterion in ("clarity", "customer_fit", "actionability"):
            app.selectbox(key=f"rub_{pos}_{criterion}_score").set_value(4)
            app.text_input(key=f"rub_{pos}_{criterion}_just").input("ok")
    app.button(key="FormSubmitter:cmp_rubric-Gravar avaliação").click().run()
    assert not app.exception
    assert not app.error
    assert client.call_count == 3
    headers = [s.value for s in app.subheader]
    assert any("= v1" in h for h in headers)  # revelado depois de gravar
    comparison = json.loads((settings.output_dir / "history.json").read_text(encoding="utf-8"))[-1]
    assert comparison["kind"] == "comparison"
    assert [r["prompt_version"] for r in comparison["runs"]] == ["v1", "v2", "v3"]
    for run in comparison["runs"]:
        assert run["evaluation"]["average"] == 4 and run["metrics"] is not None


def test_rubric_with_missing_fields_is_rejected(app, settings):
    app.radio(key="screen").set_value("Comparar").run()
    app.button(key="cmp_button").click().run()
    app.button(key="FormSubmitter:cmp_rubric-Gravar avaliação").click().run()  # nada preenchido
    assert not app.exception
    assert app.error and "Justificativa não pode ser vazia" in app.error[0].value
    assert not (settings.output_dir / "history.json").exists()  # nada gravado


def test_gemini_without_key_asks_for_it_and_calls_nothing(app):
    app.radio(key="session_provider").set_value("gemini").run()
    assert not app.exception
    assert app.warning and "cole a sua chave" in app.warning[0].value.lower()
    assert not app.button  # telas não aparecem: nada pode chamar o LLM sem chave


def test_pasted_gemini_key_is_used_but_never_written(settings, monkeypatch):
    from dataclasses import replace

    from support_assistant.llm_client import FAKE_RESPONSES, GeminiClient

    seen_keys = []

    def fake_complete(self, system, user, content_type):  # sem rede: só registra a chave usada
        seen_keys.append(self.api_key)
        return json.dumps(FAKE_RESPONSES[content_type], ensure_ascii=False)

    monkeypatch.setattr(GeminiClient, "complete", fake_complete)
    at = AppTest.from_file(APP, default_timeout=30)
    at.session_state["settings"] = replace(settings, public_mode=True)
    at.run()

    at.radio(key="session_provider").set_value("gemini").run()
    at.text_input(key="session_api_key").input("CHAVE-DA-SESSAO-123").run()
    at.button(key="gen_button").click().run()

    assert not at.exception and not at.error
    assert seen_keys == ["CHAVE-DA-SESSAO-123"]
    record = at.session_state["gen_record"]
    assert record["provider"] == "gemini"

    # Modo público: a sessão grava num diretório temporário próprio, não no OUTPUT_DIR comum.
    session_dir = at.session_state["base_settings"].output_dir
    assert session_dir != settings.output_dir
    assert not (settings.output_dir / "history.json").exists()
    written = [p for p in session_dir.rglob("*") if p.is_file()]
    assert written  # histórico, run e cache foram gravados...
    for path in written:  # ...e nenhum deles contém a chave
        assert "CHAVE-DA-SESSAO-123" not in path.read_text(encoding="utf-8")


def test_history_lists_records(app):
    app.button(key="gen_button").click().run()
    app.radio(key="screen").set_value("Histórico").run()
    assert not app.exception
    assert app.selectbox(key="hist_selected").value  # algum registro selecionável
