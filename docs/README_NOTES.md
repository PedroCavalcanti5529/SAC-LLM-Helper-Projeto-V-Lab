# Notas de decisão: métricas no pacote + CI

Registro das decisões da fase "métricas no pacote + CI" e do porquê de cada uma. Prompts, schemas
de saída e rubrica **não** mudaram nesta fase.

## 1. Métricas dentro do pacote (`src/support_assistant/metrics.py`)

**Decisão.** As métricas objetivas saíram dos `scripts/compare_*.py` e foram para o pacote.
`compute_metrics(content_type, output, profile)` despacha para uma função por tipo e é chamada pelo
`Generator` em toda execução (inclusive cache hit). O resultado vai no campo `metrics` do registro,
ao lado de `evaluation`.

**Por quê.**
- O `compare` grava rubrica humana e métricas **no mesmo registro**, para a mesma saída. Antes, as
  métricas só existiam num resumo separado do script, e cruzar "nota de customer_fit" com "jargão
  para leigo" exigia juntar arquivos à mão.
- Uma só implementação: o `compare` da CLI e os scripts mostram os mesmos números. Os scripts agora
  **leem** `metrics` do JSON da execução; só recalculam (importando `support_assistant.metrics`)
  quando o campo não existe, em execuções antigas. A coluna `metrics_source` do resumo diz
  qual caminho foi usado.
- `flow_summary` reaproveita `models.analyze_flow` (a mesma função da validação) para decisões,
  profundidade e folhas, sem duplicar a lógica.
- Os campos lidos são os dos schemas de `models.py`, acessados como dict (sem revalidar). Assim
  as métricas funcionam em registros antigos e conseguem apontar violações que o schema atual barraria
  (ex.: mais de 5 perguntas). Um teste confere que o limite de 5 em `metrics.py` é o mesmo do schema.

**Métrica nunca derruba execução.** Se o cálculo falhar, o registro fica com `metrics: null` e
`metrics_error: "<Tipo>: <mensagem>"`, a CLI avisa e a saída válida segue para cache e histórico.
Métrica é acessória; perder uma geração (e uma chamada paga) por causa dela seria pior.

| Tipo | Métricas |
|---|---|
| `diagnosis` | `n_hypotheses`, `n_evidence`, `n_missing_info`, `likelihood` (alta/media/baixa), `kb_ids`, `escalation` |
| `resolution_steps` | `n_steps`, `avg_words_per_step`, `max_words_per_step`, `question_steps`, `jargon`, `urls_ips`, `commands`, `kb_ids`, `escalation` |
| `clarifying_questions` | `n_questions`, `n_already_known`, `double_questions`, `over_limit`, `priorities_sequential`, `kb_ids` |
| `flow_summary` | `decisions`, `depth`, `leaves`, `leaves_with_ref`, `kb_ids`, `escalation` |
| todos | `violations` (lista `{rule, where, detail}`) e `n_violations` |

`escalation` = algum id `ESC-*` citado. `kb_ids` = ids no formato da base (`XX-00`) citados na saída.

## 2. Violações dependentes do perfil

**Decisão.** A métrica é a mesma para qualquer cliente; o que muda é se ela vira **violação**:

| Regra | Conta quando | Tipo |
|---|---|---|
| `jargon_for_leigo` | jargão em texto ao cliente e `technical_level = leigo` | `resolution_steps` |
| `link_or_command_phone` | URL, IP ou comando e `channel = telefone` (POL-05) | `resolution_steps` |
| `step_is_question` | instrução termina em "?" (sempre) | `resolution_steps` |
| `too_many_questions` | mais de 5 perguntas (sempre) | `clarifying_questions` |
| `question_not_yes_no` | nó sem "?" ou na forma "X ou Y?" (sempre) | `flow_summary` |
| `procedure_leaf` | folha com ref `PROC-*` (sempre) | `flow_summary` |

**Por quê.**
- "GHz" é jargão para a Marta (leiga), mas é a palavra certa para a Juliana (avançada). Contar
  jargão como erro para todo mundo puniria a v3 justamente quando ela adapta bem ao perfil.
- Link no e-mail é útil; no telefone é impossível de seguir (POL-05). Mesma lógica.
- Passo em forma de pergunta e excesso de perguntas são problemas para qualquer perfil.

**Escopo e limites conscientes.**
- Jargão e links só são checados em `resolution_steps`, o tipo cujo texto vai inteiro ao cliente.
  `diagnosis` e `flow_summary` são para o atendente; `clarifying_questions` fica para depois.
- Dentro de `resolution_steps`, só o texto ao cliente é checado (`opening`, `instruction`, `why`,
  `closing`). `escalation` é nota para o atendente e fica de fora.
- Siglas (`ONT`, `PON`, `LOS`, `DNS`, `IP`, `LAN`, `GHz`) são comparadas com maiúsculas exatas:
  em minúsculas colidiriam com o português ("religá-**los**"). Palavras (`ping`, `traceroute`,
  `firmware`) ignoram maiúsculas. A lista é a mesma que o script já usava.
- São heurísticas: indicam onde olhar, não substituem a rubrica humana.

**Onde aparecem.** No `generate`, como "Avisos de qualidade" depois da saída. No `compare`, numa
tabela compacta (métricas por versão + violações) impressa **depois das saídas e antes das notas**,
para o avaliador ver os números antes de pontuar.

## 3. CI sem segredos (`.github/workflows/ci.yml`)

**Decisão.** GitHub Actions em push na `main` e em todo pull request; matriz Python 3.11 e 3.12;
`pip install -r requirements.txt` + `pip install -e .`; `pytest -q`; cache do pip pelo
`actions/setup-python`. `LLM_PROVIDER=fake`, permissões só de leitura, sem linter por enquanto.

**Por quê.**
- O projeto foi desenhado para rodar inteiro com o provedor fake. O CI não precisa de chave, então
  não há segredo para vazar, e PRs de forks rodam sem configuração.
- Os testes já forçam o fake (fixture `force_fake_provider`); a variável no workflow é uma segunda
  garantia explícita.
- 3.11 é o mínimo do `pyproject.toml`; 3.12 cobre a versão estável seguinte.
- Linter fica de fora para não misturar mudança de estilo com mudança de comportamento agora.

## 4. Exemplo de métricas (modo fake)

Gerado com `LLM_PROVIDER=fake`:

```bash
support_assistant compare -c c01 -t t02 -y resolution_steps
```

Perfil `c01` = leiga, canal telefone. Como o fake devolve a mesma resposta nas três versões, os
números são iguais por versão; o exemplo mostra o formato, não uma diferença entre prompts.

```
Métricas objetivas (calculadas pelo código; não substituem a sua avaliação):
  métrica             v1       v2       v3
  n_steps             3        3        3
  avg_words_per_step  9.7      9.7      9.7
  max_words_per_step  11       11       11
  question_steps      0        0        0
  jargon              ONT,PON  ONT,PON  ONT,PON
  urls_ips            0        0        0
  commands            0        0        0
  kb_ids              POL-03   POL-03   POL-03
  escalation          não      não      não
  n_violations        3        3        3
Violações:
  v1: [jargon_for_leigo] steps[1]: ONT
  v1: [jargon_for_leigo] steps[2]: ONT
  v1: [jargon_for_leigo] steps[3]: PON
  v2: [jargon_for_leigo] steps[1]: ONT
  ...
```

Com o mesmo fake e `c03` (avançada, e-mail), `jargon` continua `ONT,PON`, mas `n_violations` é 0.
Esse é o efeito da regra dependente do perfil.

`escalation` é "não" porque o fake cita só `POL-03` (política de visita), não um id `ESC-*`.

Trecho do registro de comparação (`history.json`), com `metrics` ao lado de `evaluation`:

```json
{
  "prompt_version": "v3",
  "metrics": {
    "n_steps": 3, "avg_words_per_step": 9.7, "max_words_per_step": 11, "question_steps": 0,
    "jargon": ["ONT", "PON"], "urls_ips": 0, "commands": 0, "kb_ids": ["POL-03"], "escalation": false,
    "violations": [{"rule": "jargon_for_leigo", "where": "steps[1]", "detail": "ONT"}, "..."],
    "n_violations": 3
  },
  "evaluation": {"clarity": {"score": 3, "justification": "..."}, "...": "...", "average": 3.0, "evaluated_by": "human"}
}
```
