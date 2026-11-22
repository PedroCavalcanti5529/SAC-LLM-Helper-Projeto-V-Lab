"""Desenho da árvore de decisão do `flow_summary` em texto.

O modelo devolve só a árvore estruturada (validada em models.py); o diagrama é feito aqui,
de forma determinística: a mesma árvore gera sempre o mesmo texto. Assim o diagrama nunca
contradiz a lista de decisões, porque os dois vêm da mesma fonte.

Formato (de cima para baixo, uma pergunta por nó):

    Título

    [D1] Pergunta?
    ├─ SIM → Ação (REF). FIM
    └─ NÃO → [D2] Outra pergunta?
       ├─ SIM → ...
       └─ NÃO → ...

Se o texto da ação repete o id que está em `ref`, o id é removido do texto (aparece só em "(REF)").

Pré-condição: a árvore já passou pela validação (sem ciclos, todo `next` existe).
Um nó apontado por dois ramos é desenhado nos dois lugares.
"""

from __future__ import annotations

import re

# (rótulo, chave, conector, prefixo dos filhos)
_BRANCHES = (
    ("SIM", "yes", "├─", "│  "),
    ("NÃO", "no", "└─", "   "),
)


def _node_label(node: dict) -> str:
    return f"[{node['id']}] {node['question']}"


def strip_ref(action: str, ref: str | None) -> str:
    """Remove do texto da ação o id que já está em `ref` (ex.: "Agendar visita (ESC-01)").

    Tira o id com parênteses/colchetes e um conector solto antes dele ("conforme ESC-01"),
    para o id aparecer uma vez só, no lugar padrão "(REF)".
    """
    text = action
    if ref:
        connector = r"(?:\s*[,;:\-–]?\s*\b(?:conforme|segundo|via|ver|com base em|de acordo com|por)\b)?"
        text = re.sub(connector + r"\s*[\(\[]?\s*" + re.escape(ref) + r"\s*[\)\]]?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" .,;:-–")


def _action_label(branch: dict) -> str:
    action = strip_ref(branch["action"], branch.get("ref"))
    ref = f" ({branch['ref']})" if branch.get("ref") else ""
    return f"{action}{ref}. FIM"


def _render_children(node: dict, nodes: dict[str, dict], prefix: str, lines: list[str]) -> None:
    for label, key, connector, child_prefix in _BRANCHES:
        branch = node[key]
        head = f"{prefix}{connector} {label} → "
        if branch.get("next"):
            child = nodes[branch["next"]]
            lines.append(head + _node_label(child))
            _render_children(child, nodes, prefix + child_prefix, lines)
        else:
            lines.append(head + _action_label(branch))


def render_flow(tree: dict) -> str:
    nodes = {node["id"]: node for node in tree["nodes"]}
    root = nodes[tree["start"]]
    lines = [tree["title"], "", _node_label(root)]
    _render_children(root, nodes, "", lines)
    return "\n".join(lines)
