"""Interface web (Streamlit) sobre o núcleo do support_assistant.

Executar:  streamlit run app/streamlit_app.py   (depois de `pip install -e ".[web]"`)

Regras desta camada:
- Não duplica lógica: gerar/comparar = generators.py; rubrica = evaluation.py; métricas =
  metrics.py (já vêm no registro); diagrama = flow_render.py (já vem em `rendered`);
  histórico = storage.py. Aqui só há widgets e formatação.
- Configuração injetável: as telas recebem um `AppContext`; nenhuma tela lê o .env. A base vem
  de `st.session_state["settings"]` quando injetada (testes) e, só na falta, de `load_settings()`.
  O provedor efetivo é escolhido por sessão na barra lateral (`config.with_session_provider`).
- Deploy público (APP_PUBLIC_MODE=true): provedor fake por padrão; o Gemini só com a chave que a
  pessoa cola na sessão (em memória, nunca gravada); histórico e cache num diretório temporário
  por sessão, para um visitante não ver os tickets de outro.
- O Streamlit reexecuta o script a cada interação: o LLM só é chamado dentro do `if` do botão,
  e os resultados ficam em `st.session_state`. Mexer na rubrica não gera nada de novo.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import streamlit as st

try:
    import support_assistant  # noqa: F401  (instalado com `pip install -e ".[web]"`)
except ImportError:  # Streamlit Community Cloud instala só app/requirements.txt, não o pacote
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from support_assistant.config import (
    DEFAULT_GEMINI_MODEL,
    ConfigError,
    Settings,
    load_settings,
    with_session_provider,
)
from support_assistant.evaluation import (
    RUBRIC_CRITERIA,
    SCORE_MAX,
    SCORE_MIN,
    EvaluationError,
    build_evaluation,
    pick_winner,
    validate_justification,
    validate_score,
)
from support_assistant.generators import GenerationError, Generator, build_generator
from support_assistant.llm_client import LLMError
from support_assistant.metrics import VIOLATION_RULES
from support_assistant.models import (
    CONTENT_TYPES,
    CustomerProfile,
    InputValidationError,
    Ticket,
    load_customers,
    load_tickets,
)
from support_assistant.prompt_builder import list_versions

# Mesmos erros que a CLI trata com mensagem amigável (sem traceback).
KNOWN_ERRORS = (ConfigError, InputValidationError, LLMError, GenerationError, EvaluationError)

CONTENT_LABELS = {
    "diagnosis": "Diagnóstico (atendente)",
    "resolution_steps": "Passos de resolução (cliente)",
    "clarifying_questions": "Perguntas de esclarecimento (cliente)",
    "flow_summary": "Fluxo de decisão (atendente)",
}
NO_SCORE = "—"


# ---------------------------------------------------------------------------
# Contexto (configuração injetável)
# ---------------------------------------------------------------------------


@dataclass
class AppContext:
    settings: Settings
    generator: Generator
    customers: dict[str, CustomerProfile]
    tickets: dict[str, dict]
    versions: list[str]


def base_settings() -> Settings:
    """Configurações de partida da sessão, montadas uma vez só.

    Vêm de `st.session_state["settings"]` quando injetadas (testes) ou de `load_settings()`.
    No modo público (deploy), cada sessão grava num diretório temporário próprio: histórico e
    cache de um visitante nunca aparecem para outro.
    """
    if "base_settings" not in st.session_state:
        try:
            settings = st.session_state.get("settings") or load_settings()
        except ConfigError as exc:
            st.error(f"Não foi possível iniciar: {exc}")
            st.stop()
        if settings.public_mode:
            settings = replace(settings, output_dir=Path(tempfile.mkdtemp(prefix="support-assistant-session-")))
        st.session_state["base_settings"] = settings
    return st.session_state["base_settings"]


def get_context(settings: Settings) -> AppContext:
    """Monta o contexto com as configurações efetivas da sessão (provedor escolhido na barra lateral)."""
    try:
        st.session_state["settings"] = settings
        # Reaproveita o Generator enquanto as configurações forem as mesmas (comparação por valor).
        if st.session_state.get("_generator_settings") != settings:
            st.session_state["_generator"] = build_generator(settings)
            st.session_state["_generator_settings"] = settings
        return AppContext(
            settings=settings,
            generator=st.session_state["_generator"],
            customers=load_customers(settings.customers_path),
            tickets=load_tickets(settings.tickets_path),
            versions=list_versions(settings.prompts_dir),
        )
    except KNOWN_ERRORS as exc:
        st.error(f"Não foi possível iniciar: {exc}")
        st.stop()


# ---------------------------------------------------------------------------
# Formatação (só apresentação)
# ---------------------------------------------------------------------------


def customer_label(customer: CustomerProfile) -> str:
    return (
        f"{customer.id} · {customer.name} ({customer.technical_level}, "
        f"{customer.communication_style}, {customer.channel})"
    )


def describe_layers(layers: dict) -> str:
    parts = ["base" if layers.get("base") else "papel mínimo"]
    if layers.get("domain"):
        parts.append("domínio")
    parts.append(f"tarefas {layers.get('tasks')}")
    return " + ".join(parts)


def fmt_value(value) -> str:
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, dict):
        return " · ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "—"
    return str(value)


def render_output(record: dict) -> None:
    """Saída formatada por tipo. flow_summary usa o texto desenhado pelo código (`rendered`)."""
    content_type, out = record["content_type"], record["output"]
    if content_type == "flow_summary":
        st.code(record.get("rendered") or "", language=None)
    elif content_type == "diagnosis":
        st.markdown("**Hipóteses**")
        for h in out["hypotheses"]:
            st.markdown(f"- **[{h['likelihood']}]** {h['cause']}  \n  _{h['rationale']}_")
        st.markdown("**Evidências**")
        st.markdown("\n".join(f"- {e}" for e in out["evidence"]))
        st.markdown("**Informações faltantes**")
        st.markdown("\n".join(f"- {m}" for m in out["missing_info"]) or "_(nenhuma)_")
        st.markdown(f"**Conclusão provável:** {out['probable_conclusion']}")
    elif content_type == "resolution_steps":
        if out.get("opening"):
            st.markdown(out["opening"])
        for s in out["steps"]:
            line = f"{s['step']}. {s['instruction']}"
            if s.get("why"):
                line += f"  \n   _Por quê: {s['why']}_"
            st.markdown(line)
        if out.get("closing"):
            st.markdown(out["closing"])
        st.info(f"Para o atendente (escalonamento): {out['escalation']}")
    elif content_type == "clarifying_questions":
        st.markdown("**Já sabemos**")
        st.markdown("\n".join(f"- {k}" for k in out["already_known"]) or "_(nada)_")
        st.markdown("**Perguntas (por prioridade)**")
        if not out["questions"]:
            st.markdown("_(nenhuma: o ticket já tem o necessário)_")
        for q in out["questions"]:
            st.markdown(f"{q['priority']}. {q['question']}  \n   _objetivo: {q['purpose']}_")
    else:
        st.json(out)


def violation_lines(record: dict) -> list[str]:
    violations = (record.get("metrics") or {}).get("violations") or []
    return [
        f"[{v['rule']}] {v['where']}: {VIOLATION_RULES.get(v['rule'], v['rule'])} ({v['detail']})"
        for v in violations
    ]


def render_run_header(record: dict, show_layers: bool = True) -> None:
    cols = st.columns(5)
    cols[0].metric("Cache", "sim" if record["cached"] else "não")
    cols[1].metric("Tentativas", record["attempts"])
    cols[2].metric("Repetições do provedor", record.get("provider_retries", 0))
    cols[3].metric("Latência", f"{record['latency_ms']} ms")
    cols[4].metric("Violações", (record.get("metrics") or {}).get("n_violations", "—"))
    if show_layers:
        st.caption(
            f"Versão {record['prompt_version']} · camadas: {describe_layers(record['prompt_layers'])} · "
            f"{record['provider']}/{record['model']}"
        )
    render_warnings(record)


def render_warnings(record: dict) -> None:
    if record.get("metrics_error"):
        st.warning(f"Métricas indisponíveis: {record['metrics_error']}")
    for line in violation_lines(record):
        st.warning(line)


def metrics_rows(record: dict) -> list[dict]:
    metrics = record.get("metrics") or {}
    return [{"métrica": k, "valor": fmt_value(v)} for k, v in metrics.items() if k != "violations"]


def metrics_table(labeled_records: list[tuple[str, dict]]) -> list[dict]:
    """Uma linha por métrica, uma coluna por resposta (rótulo)."""
    keys: list[str] = []
    for _, record in labeled_records:
        for key in record.get("metrics") or {}:
            if key not in keys and key != "violations":
                keys.append(key)
    return [
        {"métrica": key, **{label: fmt_value((r.get("metrics") or {}).get(key, "—")) for label, r in labeled_records}}
        for key in keys
    ]


def record_json(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entradas comuns
# ---------------------------------------------------------------------------


def input_widgets(ctx: AppContext, prefix: str) -> tuple[CustomerProfile, str | None, str | None, str]:
    """Perfil, ticket (catálogo ou texto livre) e tipo. Devolve (perfil, ticket_id, texto, tipo)."""
    customer_id = st.selectbox(
        "Perfil do cliente",
        list(ctx.customers),
        format_func=lambda cid: customer_label(ctx.customers[cid]),
        key=f"{prefix}_customer",
    )
    source = st.radio("Ticket", ["Do catálogo", "Texto livre"], horizontal=True, key=f"{prefix}_source")
    ticket_id = ticket_text = None
    if source == "Do catálogo":
        ticket_id = st.selectbox(
            "Ticket do catálogo",
            list(ctx.tickets),
            format_func=lambda tid: f"{tid} [{ctx.tickets[tid]['category']}] {ctx.tickets[tid]['text'][:80]}",
            key=f"{prefix}_ticket_id",
        )
    else:
        ticket_text = st.text_area("Texto do ticket", key=f"{prefix}_ticket_text", height=100)
    content_type = st.selectbox(
        "Tipo de conteúdo", CONTENT_TYPES, format_func=lambda t: CONTENT_LABELS.get(t, t), key=f"{prefix}_type"
    )
    return ctx.customers[customer_id], ticket_id, ticket_text, content_type


def resolve_ticket(ctx: AppContext, ticket_id: str | None, ticket_text: str | None) -> Ticket:
    if ticket_id is not None:
        return Ticket.from_text(ctx.tickets[ticket_id]["text"], ticket_id)
    return Ticket.from_text(ticket_text or "")  # vazio -> InputValidationError (RN02)


# ---------------------------------------------------------------------------
# Tela: Gerar
# ---------------------------------------------------------------------------


def screen_generate(ctx: AppContext) -> None:
    st.header("Gerar conteúdo")
    customer, ticket_id, ticket_text, content_type = input_widgets(ctx, "gen")
    default_version = ctx.versions.index("v3") if "v3" in ctx.versions else len(ctx.versions) - 1
    version = st.selectbox("Versão do prompt", ctx.versions, index=default_version, key="gen_version")

    if st.button("Gerar", type="primary", key="gen_button"):  # única chamada ao LLM desta tela
        st.session_state.pop("gen_error", None)
        try:
            ticket = resolve_ticket(ctx, ticket_id, ticket_text)
            with st.spinner("Gerando..."):
                st.session_state["gen_record"] = ctx.generator.generate(customer, ticket, content_type, version)
        except KNOWN_ERRORS as exc:
            st.session_state["gen_error"] = str(exc)

    if st.session_state.get("gen_error"):
        st.error(st.session_state["gen_error"])
        return
    record = st.session_state.get("gen_record")
    if not record:
        st.info("Escolha as opções e clique em **Gerar**.")
        return

    st.divider()
    st.subheader(f"{CONTENT_LABELS.get(record['content_type'])} · cliente {record['customer_id']}")
    render_run_header(record)
    render_output(record)

    st.markdown("**Métricas objetivas**")
    if record.get("metrics"):
        st.dataframe(metrics_rows(record), hide_index=True)
    st.caption(f"JSON salvo em: `{record.get('run_path')}`")
    st.download_button(
        "Baixar JSON da execução",
        data=record_json(record),
        file_name=f"{record['run_id']}.json",
        mime="application/json",
        key="gen_download",
    )


# ---------------------------------------------------------------------------
# Tela: Comparar
# ---------------------------------------------------------------------------


def screen_compare(ctx: AppContext) -> None:
    st.header("Comparar versões de prompt")
    customer, ticket_id, ticket_text, content_type = input_widgets(ctx, "cmp")
    versions = st.multiselect(
        "Versões (2 ou mais)", ctx.versions, default=[v for v in ("v1", "v2", "v3") if v in ctx.versions], key="cmp_versions"
    )
    blind = st.checkbox(
        "Avaliação às cegas (versões aparecem como Resposta A/B/C, em ordem embaralhada)",
        value=True,
        key="cmp_blind",
    )

    if st.button("Gerar comparação", type="primary", key="cmp_button"):  # única chamada ao LLM desta tela
        st.session_state.pop("cmp_error", None)
        st.session_state.pop("cmp", None)
        try:
            ticket = resolve_ticket(ctx, ticket_id, ticket_text)
            with st.spinner("Gerando as versões..."):
                runs = ctx.generator.compare(customer, ticket, content_type, versions)
            order = list(range(len(runs)))
            if blind:
                random.shuffle(order)
            st.session_state["cmp"] = {"runs": runs, "order": order, "blind": blind, "saved": None}
        except KNOWN_ERRORS as exc:
            st.session_state["cmp_error"] = str(exc)

    if st.session_state.get("cmp_error"):
        st.error(st.session_state["cmp_error"])
        return
    state = st.session_state.get("cmp")
    if not state:
        st.info("Escolha as opções e clique em **Gerar comparação**.")
        return

    runs, order, saved = state["runs"], state["order"], state["saved"]
    hidden = state["blind"] and saved is None  # a versão real só aparece depois de gravar
    labels = [
        f"Resposta {chr(ord('A') + pos)}" if state["blind"] else runs[idx]["prompt_version"]
        for pos, idx in enumerate(order)
    ]
    labeled = [(label, runs[idx]) for label, idx in zip(labels, order)]

    st.divider()
    for col, (label, run) in zip(st.columns(len(labeled)), labeled):
        with col:
            title = label if hidden or not state["blind"] else f"{label} = {run['prompt_version']}"
            st.subheader(title)
            render_run_header(run, show_layers=not hidden)
            render_output(run)

    st.markdown("**Métricas e violações por resposta**")
    st.dataframe(metrics_table(labeled), hide_index=True)
    for label, run in labeled:
        lines = violation_lines(run)
        if run.get("metrics_error"):
            lines = [f"métricas indisponíveis: {run['metrics_error']}"]
        st.markdown(f"- **{label}:** " + ("; ".join(lines) if lines else "nenhuma violação"))

    if saved is None:
        rubric_form(ctx, state, labeled)
    else:
        render_saved_comparison(state, labeled)


def rubric_form(ctx: AppContext, state: dict, labeled: list[tuple[str, dict]]) -> None:
    st.divider()
    st.subheader("Avaliação (rubrica manual)")
    options = [NO_SCORE, *range(SCORE_MIN, SCORE_MAX + 1)]
    # st.form: mexer nas notas não reexecuta nada até o envio, e nunca chama o LLM.
    with st.form("cmp_rubric"):
        for pos, (label, _run) in enumerate(labeled):
            st.markdown(f"**{label}**")
            for criterion, description in RUBRIC_CRITERIA.items():
                c1, c2 = st.columns([1, 3])
                c1.selectbox(criterion, options, key=f"rub_{pos}_{criterion}_score", help=description)
                c2.text_input(f"Justificativa ({criterion})", key=f"rub_{pos}_{criterion}_just")
        submitted = st.form_submit_button("Gravar avaliação", type="primary")

    if not submitted:
        return
    evaluations, errors = {}, []
    for pos, (label, run) in enumerate(labeled):
        scores = {
            criterion: {
                "score": st.session_state.get(f"rub_{pos}_{criterion}_score"),
                "justification": st.session_state.get(f"rub_{pos}_{criterion}_just"),
            }
            for criterion in RUBRIC_CRITERIA
        }
        run_errors = []
        for criterion, item in scores.items():  # mensagem por campo, com as regras de evaluation.py
            if item["score"] == NO_SCORE:
                run_errors.append(f"{label} · {criterion}: escolha uma nota de {SCORE_MIN} a {SCORE_MAX}.")
            else:
                try:
                    validate_score(item["score"])
                except EvaluationError as exc:
                    run_errors.append(f"{label} · {criterion}: {exc}")
            try:
                validate_justification(item["justification"])
            except EvaluationError as exc:
                run_errors.append(f"{label} · {criterion}: {exc}")
        errors += run_errors
        if not run_errors:
            evaluations[id(run)] = build_evaluation(scores)
    if errors:
        st.error("Avaliação não gravada:\n\n" + "\n".join(f"- {e}" for e in errors))
        return

    runs = [dict(run, evaluation=evaluations[id(run)]) for run in state["runs"]]  # ordem original das versões
    try:
        winner = pick_winner(runs)
        comparison, path = ctx.generator.save_comparison(runs, winner)
    except KNOWN_ERRORS as exc:
        st.error(str(exc))
        return
    state["runs"] = runs
    state["saved"] = {"comparison_id": comparison["comparison_id"], "winner": winner, "path": path}
    st.rerun()  # redesenha já revelado


def render_saved_comparison(state: dict, labeled: list[tuple[str, dict]]) -> None:
    saved = state["saved"]
    st.divider()
    st.success("Avaliação gravada.")
    by_version = {r["prompt_version"]: r for r in state["runs"]}
    rows = []
    for label, run in labeled:
        ev = by_version[run["prompt_version"]]["evaluation"]
        rows.append(
            {
                "resposta": label,
                "versão": run["prompt_version"],
                **{c: ev[c]["score"] for c in RUBRIC_CRITERIA},
                "média": ev["average"],
            }
        )
    st.dataframe(rows, hide_index=True)
    winner = saved["winner"]
    st.markdown(f"**Vencedora:** {winner if winner else 'empate'}")
    st.caption(f"JSON da comparação: `{saved['path']}`")


# ---------------------------------------------------------------------------
# Tela: Histórico
# ---------------------------------------------------------------------------


def record_versions(record: dict) -> list[str]:
    return record.get("versions") or [record.get("prompt_version")]


def screen_history(ctx: AppContext) -> None:
    st.header("Histórico")
    records = list(reversed(ctx.generator.storage.load_history()))  # mais recentes primeiro
    if not records:
        st.info("Nenhuma execução gravada ainda.")
        return

    c1, c2, c3, c4 = st.columns(4)
    kind = c1.selectbox("Registro", ["todos", "generation", "comparison"], key="hist_kind")
    customers = sorted({r.get("customer_id") for r in records if r.get("customer_id")})
    customer = c2.selectbox("Cliente", ["todos", *customers], key="hist_customer")
    content_type = c3.selectbox("Tipo de conteúdo", ["todos", *CONTENT_TYPES], key="hist_type")
    version = c4.selectbox("Versão", ["todos", *ctx.versions], key="hist_version")

    filtered = [
        r
        for r in records
        if (kind == "todos" or r.get("kind") == kind)
        and (customer == "todos" or r.get("customer_id") == customer)
        and (content_type == "todos" or r.get("content_type") == content_type)
        and (version == "todos" or version in record_versions(r))
    ]
    st.caption(f"{len(filtered)} de {len(records)} registros")
    if not filtered:
        return

    def record_id(r: dict) -> str:
        return r.get("run_id") or r.get("comparison_id") or "?"

    summary = [
        {
            "id": record_id(r),
            "data": r.get("timestamp"),
            "registro": r.get("kind"),
            "cliente": r.get("customer_id"),
            "tipo": r.get("content_type"),
            "versão": ", ".join(map(str, record_versions(r))),
            "cache/vencedora": (
                fmt_value(r.get("cached")) if r.get("kind") == "generation" else (r.get("winner") or "empate")
            ),
        }
        for r in filtered
    ]
    st.dataframe(summary, hide_index=True)

    by_id = {record_id(r): r for r in filtered}
    selected = st.selectbox("Ver detalhes de", list(by_id), key="hist_selected")
    record = by_id[selected]
    if record.get("kind") == "comparison":
        st.markdown(f"**Comparação** · vencedora: {record.get('winner') or 'empate'}")
        for col, run in zip(st.columns(len(record["runs"])), record["runs"]):
            with col:
                st.subheader(run["prompt_version"])
                ev = run.get("evaluation") or {}
                if ev:
                    st.caption(" · ".join(f"{c}: {ev[c]['score']}" for c in RUBRIC_CRITERIA) + f" · média {ev['average']}")
                render_output(run)
    elif record.get("output") is not None:
        render_run_header(record)
        render_output(record)
    with st.expander("JSON completo"):
        st.json(record)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

SCREENS = {"Gerar": screen_generate, "Comparar": screen_compare, "Histórico": screen_history}


def sidebar(base: Settings) -> tuple[str, Settings | None]:
    """Tela escolhida e configurações efetivas da sessão (None = Gemini escolhido sem chave)."""
    with st.sidebar:
        st.title("Assistente de Suporte")
        screen = st.radio("Tela", list(SCREENS), key="screen")
        st.divider()

        st.subheader("Provedor desta sessão")
        providers = ["fake", "gemini"]
        provider = st.radio(
            "Provedor",
            providers,
            index=providers.index(base.provider) if base.provider in providers else 0,
            horizontal=True,
            key="session_provider",
            label_visibility="collapsed",
        )
        settings: Settings | None
        if provider == "fake":
            settings = with_session_provider(base, "fake")
            st.info("Modo fake: respostas fixas, sem chave e sem rede.")
        else:
            pasted = st.text_input(
                "Sua chave do Gemini",
                type="password",
                key="session_api_key",
                help="Fica só na memória desta sessão: não é gravada em disco, histórico, cache nem log.",
            )
            model = st.text_input(
                "Modelo", value=base.model if base.provider == "gemini" else DEFAULT_GEMINI_MODEL, key="session_model"
            )
            # Local: sem chave colada, usa a do .env. Público: só a chave colada (a do dono nunca).
            fallback = None if base.public_mode or base.provider != "gemini" else base.api_key
            key = (pasted or "").strip() or fallback
            settings = with_session_provider(base, "gemini", key, model) if key else None
            st.caption("Gere uma chave gratuita em aistudio.google.com/apikey. As chamadas usam a sua cota.")

        if settings is not None:
            st.markdown(f"**Provedor:** `{settings.provider}`  \n**Modelo:** `{settings.model}`")
        if base.public_mode:
            st.caption("Modo público: o histórico é só desta sessão e some quando ela termina.")
        else:
            st.caption(f"Saída: `{base.output_dir}`")
    return screen, settings


def main() -> None:
    st.set_page_config(page_title="Assistente de Suporte", page_icon="🛠️", layout="wide")
    base = base_settings()
    screen, settings = sidebar(base)
    if settings is None:
        st.warning(
            "Para usar o Gemini, cole a sua chave na barra lateral. Ela fica só nesta sessão e não é "
            "gravada. Sem chave, volte ao provedor **fake**."
        )
        st.stop()
    ctx = get_context(settings)
    SCREENS[screen](ctx)


main()
