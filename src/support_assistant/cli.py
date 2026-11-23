"""Interface de linha de comando (argparse). Só interage: lê argumentos, chama os
módulos de domínio e imprime resultados/erros. Não faz rede nem escreve em disco.

Comandos:
  list      perfis, tickets, versões e tipos disponíveis
  generate  gera um conteúdo (perfil + ticket + tipo + versão)
  compare   gera o mesmo conteúdo em ≥2 versões e coleta a rubrica manual
"""

from __future__ import annotations

import argparse
import logging
import sys

from support_assistant.config import ConfigError, Settings, load_settings
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
from support_assistant.llm_client import LLMError, create_client
from support_assistant.metrics import VIOLATION_RULES
from support_assistant.models import (
    CONTENT_TYPES,
    CustomerProfile,
    InputValidationError,
    Ticket,
    load_customers,
    load_tickets,
    validate_content_type,
)
from support_assistant.prompt_builder import build_prompt, list_content_types, list_versions, load_manifest

LINE = "─" * 72


# ---------------------------------------------------------------------------
# Resolução de entradas
# ---------------------------------------------------------------------------


def resolve_customer(settings: Settings, customer_id: str) -> CustomerProfile:
    customers = load_customers(settings.customers_path)
    if customer_id not in customers:
        raise InputValidationError(
            f"Perfil inexistente: {customer_id!r}. Opções: {', '.join(customers)}."
        )
    return customers[customer_id]


def resolve_ticket(settings: Settings, ticket_id: str | None, ticket_text: str | None) -> Ticket:
    if ticket_text is not None:
        return Ticket.from_text(ticket_text)
    tickets = load_tickets(settings.tickets_path)
    if ticket_id not in tickets:
        raise InputValidationError(f"Ticket inexistente: {ticket_id!r}. Opções: {', '.join(tickets)}.")
    return Ticket.from_text(tickets[ticket_id]["text"], ticket_id)


def make_generator(settings: Settings) -> Generator:
    # `create_client` passado explicitamente: os testes trocam `cli.create_client` por um cliente simulado.
    return build_generator(settings, client=create_client(settings))


# ---------------------------------------------------------------------------
# Renderização legível das saídas
# ---------------------------------------------------------------------------


def render_output(content_type: str, output: dict) -> str:
    lines: list[str] = []
    if content_type == "diagnosis":
        lines.append("Hipóteses:")
        for h in output["hypotheses"]:
            lines.append(f"  • [{h['likelihood']}] {h['cause']}")
            lines.append(f"      {h['rationale']}")
        lines.append("Evidências:")
        lines += [f"  • {e}" for e in output["evidence"]]
        lines.append("Informações faltantes:")
        lines += [f"  • {m}" for m in output["missing_info"]] or ["  (nenhuma)"]
        lines.append(f"Conclusão provável: {output['probable_conclusion']}")
    elif content_type == "resolution_steps":
        if output.get("opening"):
            lines += [output["opening"], ""]
        for s in output["steps"]:
            lines.append(f"{s['step']}. {s['instruction']}")
            if s.get("why"):
                lines.append(f"   Por quê: {s['why']}")
        if output.get("closing"):
            lines += ["", output["closing"]]
        lines += ["", f"[Atendente] Escalonamento: {output['escalation']}"]
    elif content_type == "clarifying_questions":
        lines.append("Já sabemos:")
        lines += [f"  • {k}" for k in output["already_known"]] or ["  (nada)"]
        lines.append("Perguntas (por prioridade):")
        for q in output["questions"]:
            lines.append(f"  {q['priority']}. {q['question']}")
            lines.append(f"     objetivo: {q['purpose']}")
        if not output["questions"]:
            lines.append("  (nenhuma: o ticket já tem o necessário)")
    else:  # pragma: no cover  (flow_summary usa o texto de `rendered`, ver print_run)
        lines.append(str(output))
    return "\n".join(lines)


def describe_layers(layers: dict) -> str:
    """Ex.: 'base + domínio + tarefas v1' ou 'papel mínimo + tarefas v1'."""
    parts = ["base" if layers["base"] else "papel mínimo"]
    if layers["domain"]:
        parts.append("domínio")
    parts.append(f"tarefas {layers['tasks']}")
    return " + ".join(parts)


def print_run(record: dict) -> None:
    cache_flag = "sim (nenhuma chamada à API)" if record["cached"] else "não"
    print(LINE)
    print(
        f"{record['content_type']} | versão {record['prompt_version']} | cliente {record['customer_id']} | "
        f"{record['provider']}/{record['model']}"
    )
    print(f"camadas: {describe_layers(record['prompt_layers'])}")
    retries = record.get("provider_retries", 0)
    retries_info = f" | repetições do provedor: {retries}" if retries else ""
    print(
        f"cache: {cache_flag} | tentativas: {record['attempts']}{retries_info} | "
        f"latência: {record['latency_ms']} ms"
    )
    print(LINE)
    # flow_summary: mostra a árvore desenhada pelo código (flow_render.py), guardada em `rendered`.
    print(record.get("rendered") or render_output(record["content_type"], record["output"]))
    print_violations(record)
    print(LINE)


def print_violations(record: dict) -> None:
    """Regras de qualidade dependentes do perfil (metrics.py): avisam, não bloqueiam."""
    if record.get("metrics_error"):
        print(LINE)
        print(f"Métricas indisponíveis: {record['metrics_error']}")
        return
    violations = (record.get("metrics") or {}).get("violations") or []
    if violations:
        print(LINE)
        print(f"Avisos de qualidade ({len(violations)}):")
        for v in violations:
            print(f"  - [{v['rule']}] {v['where']}: {VIOLATION_RULES.get(v['rule'], v['rule'])} ({v['detail']})")


def _fmt_metric(value) -> str:
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, dict):
        return " ".join(f"{k}:{v}" for k, v in value.items())
    if isinstance(value, list):
        return ",".join(map(str, value)) or "-"
    return str(value)


def print_metrics_table(runs: list[dict]) -> None:
    """Tabela compacta: uma linha por métrica, uma coluna por versão, depois as violações."""
    print(LINE)
    print("Métricas objetivas (calculadas pelo código; não substituem a sua avaliação):")
    keys: list[str] = []
    for run in runs:
        for key in run.get("metrics") or {}:
            if key not in keys and key not in ("violations", "n_violations"):
                keys.append(key)
    keys.append("n_violations")
    headers = ["métrica", *(run["prompt_version"] for run in runs)]
    rows = [
        [key, *(_fmt_metric((run.get("metrics") or {}).get(key, "erro")) for run in runs)]
        for key in keys
    ]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  " + "  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for row in rows:
        print("  " + "  ".join(c.ljust(w) for c, w in zip(row, widths)))
    print("Violações:")
    for run in runs:
        if run.get("metrics_error"):
            print(f"  {run['prompt_version']}: métricas indisponíveis ({run['metrics_error']})")
            continue
        violations = (run.get("metrics") or {}).get("violations") or []
        if not violations:
            print(f"  {run['prompt_version']}: nenhuma")
        for v in violations:
            print(f"  {run['prompt_version']}: [{v['rule']}] {v['where']}: {v['detail']}")


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace, settings: Settings) -> int:
    customers = load_customers(settings.customers_path)
    tickets = load_tickets(settings.tickets_path)
    print("Perfis (--customer):")
    for c in customers.values():
        print(f"  {c.id:<6} {c.name:<22} nível={c.technical_level:<13} estilo={c.communication_style:<9} canal={c.channel}")
    print("\nTickets (--ticket-id):")
    for t in tickets.values():
        preview = t["text"] if len(t["text"]) <= 70 else t["text"][:67] + "..."
        print(f"  {t['id']:<6} [{t['category']:<8}] {preview}")
    print("\nVersões de prompt (--version / --versions), cada uma acrescenta uma camada à anterior:")
    for v in list_versions(settings.prompts_dir):
        manifest = load_manifest(settings.prompts_dir, v)
        print(f"  {v:<6} camadas: {describe_layers(manifest.layers())}")
        print(f"         tipos: {', '.join(list_content_types(settings.prompts_dir, v))}")
        if manifest.description:
            print(f"         {manifest.description}")
    print(f"\nTipos de conteúdo (--type): {', '.join(CONTENT_TYPES)}")
    print(f"Provedor atual: {settings.provider} ({settings.model})")
    return 0


def cmd_generate(args: argparse.Namespace, settings: Settings) -> int:
    customer = resolve_customer(settings, args.customer)
    ticket = resolve_ticket(settings, args.ticket_id, args.ticket)
    if args.show_prompt:  # só monta e mostra o prompt; não chama o LLM nem grava nada
        validate_content_type(args.type)
        prompt = build_prompt(customer, ticket, args.type, args.version, settings.prompts_dir, settings.domain_path)
        print(
            f"===== SYSTEM ({describe_layers(prompt.layers)}) | versão {prompt.prompt_version} "
            f"| template_hash={prompt.template_hash[:12]} ====="
        )
        print(prompt.system)
        print("\n===== USER (camada 4) =====")
        print(prompt.user)
        return 0
    generator = make_generator(settings)
    record = generator.generate(customer, ticket, args.type, args.version)
    print_run(record)
    print(f"JSON da execução: {record['run_path']}")
    print(f"Histórico:        {generator.storage.history_path}")
    return 0


def _ask(prompt: str) -> str:
    try:
        # PowerShell insere BOM ao canalizar texto para o stdin; removemos para não invalidar a nota.
        return input(prompt).replace("﻿", "")
    except EOFError:
        raise KeyboardInterrupt from None


def collect_rubric(version: str) -> dict:
    """Pede as 3 notas + justificativas. Rejeita entradas inválidas e pergunta de novo."""
    print(f"\nAvaliação da versão {version} (notas inteiras {SCORE_MIN}–{SCORE_MAX}):")
    scores: dict[str, dict] = {}
    for criterion, description in RUBRIC_CRITERIA.items():
        print(f"  {criterion} — {description}")
        while True:
            try:
                score = validate_score(_ask(f"    nota {criterion}: "))
                break
            except EvaluationError as exc:
                print(f"    Erro: {exc}")
        while True:
            try:
                justification = validate_justification(_ask(f"    justificativa {criterion}: "))
                break
            except EvaluationError as exc:
                print(f"    Erro: {exc}")
        scores[criterion] = {"score": score, "justification": justification}
    return build_evaluation(scores)


def cmd_compare(args: argparse.Namespace, settings: Settings) -> int:
    customer = resolve_customer(settings, args.customer)
    ticket = resolve_ticket(settings, args.ticket_id, args.ticket)
    generator = make_generator(settings)
    runs = generator.compare(customer, ticket, args.type, args.versions)

    for run in runs:
        print_run(run)
    print_metrics_table(runs)  # antes das notas: métricas ao lado da rubrica, gravadas juntas

    print("\nAgora avalie cada versão. (Ctrl+C cancela sem gravar a comparação; as saídas ficam no cache.)")
    for run in runs:
        run["evaluation"] = collect_rubric(run["prompt_version"])

    winner = pick_winner(runs)
    comparison, path = generator.save_comparison(runs, winner)
    print(LINE)
    print("Resumo da comparação:")
    for run in runs:
        ev = run["evaluation"]
        print(
            f"  {run['prompt_version']}: clarity={ev['clarity']['score']} customer_fit={ev['customer_fit']['score']} "
            f"actionability={ev['actionability']['score']} média={ev['average']}"
        )
    print(f"  Vencedora: {winner or 'empate'}")
    print(f"JSON da comparação: {path}")
    print(f"Histórico:          {generator.storage.history_path}")
    return 0


# ---------------------------------------------------------------------------
# Parser e main
# ---------------------------------------------------------------------------


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--customer", "-c", required=True, help="id do perfil (ver `list`)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticket-id", "-t", help="id de um ticket de data/tickets.json")
    group.add_argument("--ticket", help="texto livre do ticket")
    parser.add_argument("--type", "-y", required=True, help=f"tipo de conteúdo: {', '.join(CONTENT_TYPES)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="support-assistant",
        description="Gera conteúdo de suporte técnico adaptado ao perfil do cliente.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="mostra logs de depuração")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="lista perfis, tickets, versões e tipos")
    p_list.set_defaults(func=cmd_list)

    p_gen = sub.add_parser("generate", help="gera um conteúdo")
    _add_input_args(p_gen)
    p_gen.add_argument("--version", "-p", default="v3", help="versão do prompt (padrão: v3; opções em `list`)")
    p_gen.add_argument("--show-prompt", action="store_true", help="mostra o prompt montado e sai, sem chamar o LLM")
    p_gen.set_defaults(func=cmd_generate)

    p_cmp = sub.add_parser("compare", help="compara ≥2 versões de prompt e coleta a rubrica")
    _add_input_args(p_cmp)
    p_cmp.add_argument(
        "--versions",
        nargs="+",
        default=["v1", "v2", "v3"],
        help="2 ou mais versões a comparar (padrão: v1 v2 v3, a ablação completa)",
    )
    p_cmp.set_defaults(func=cmd_compare)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # evita UnicodeEncodeError em consoles antigos
        except AttributeError:  # pragma: no cover
            pass

    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        # nome do módulo no aviso: distingue retry do provedor (llm_client) de retry por schema (generators)
        format="[%(levelname)s] %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
        return args.func(args, settings)
    except (ConfigError, InputValidationError, LLMError, GenerationError, EvaluationError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelado. Nada foi gravado no histórico.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
