# CLAUDE.md — support-prompt-assistant

Regras e contexto do projeto. Leia antes de alterar código, prompts ou dados.
**Prazo: 3 dias.** Prioridade = pesos da avaliação (40% prompt, 30% código, 20% docs, 10% extras).

## Escopo por dia

**Dia 1 — Walking skeleton (e2e fake)**
- `config.py`, `models.py`, `prompt_builder.py`, `llm_client.py` (fake), `generators.py` (1 tipo), `cli.py` (generate), `data/` inicial.
- `README` mínimo (setup + 1 comando).

**Dia 2 — Completar o MVP**
- 4 tipos de conteúdo; `cache.py`, `storage.py`; `cli.py` com `generate` + `compare` + `list`.
- Integrar 1 provedor real (Gemini free tier ou Groq) — smoke test manual.
- `prompts/v1/` (baseline) para os 4 tipos.

**Dia 3 — Qualidade e entrega**
- Ablação de 3 versões via manifesto: `v1` (papel mínimo + tarefa simples), `v2` (base + domínio + tarefa da v1), `v3` (base + domínio + tarefa estruturada) para os 4 tipos.
- 1 comparação v1×v2×v3 completa com rubrica manual (3 notas + justificativas por versão).
- 2 testes: cache hit + e2e fake. `samples/`. `PROMPT_ENGINEERING_NOTES.md`. README final.

**Fora do escopo:** web UI, deploy, CI, observabilidade, juiz LLM, múltiplos provedores.
`flow_summary`: o modelo gera só a árvore estruturada; o ASCII é desenhado pelo código (ver RN03).

## Stack

- Python 3.11+, `argparse` (stdlib) — sem Click/Typer.
- JSON via stdlib; Pydantic só para schemas de saída.
- LLM: **uma** API gratuita (Gemini free tier recomendada; Groq alternativa). Tudo passa por `llm_client.py`.
- Segredos só em `.env`. `.env.example` só com nomes.

```
## Estrutura
support-prompt-assistant/
├── README.md · PROMPT_ENGINEERING_NOTES.md · CLAUDE.md
├── requirements.txt · .env.example · .gitignore
├── data/
│ ├── customers.json # 3–5 perfis
│ ├── tickets.json # vago, comum, técnico
│ └── domains/wifi_isp.json # fatos da empresa
├── prompts/{base,v1,v2,v3}/ # base compartilhado; cada vN/manifest.json declara as camadas
│                            # v1: role.md + tarefas simples · v2: só manifesto (tarefas de v1/) · v3: tarefas estruturadas
├── src/support_assistant/
│ ├── config.py · models.py · prompt_builder.py
│ ├── llm_client.py # fake + provedor real
│ ├── generators.py · cache.py · storage.py
│ ├── flow_render.py # desenha a árvore do flow_summary (determinístico)
│ ├── evaluation.py # rubrica (validação + I/O)
│ └── cli.py
├── tests/ # cache hit, e2e fake, prompt builder, flow_summary
├── scripts/ # compare_*.py: métricas objetivas por versão (flow reaproveita a validação)
└── samples/
```

## Camadas do prompt

1. **Base** — persona, limites, regras de adaptação, formato. Presente na v2 e v3; a v1 usa só um papel mínimo (`prompts/v1/role.md`).
2. **Domínio** — fatos da empresa. Modelo diagnostica a partir deles, não inventa. Presente na v2 e v3.
3. **Tarefa** — instrução + formato de saída de cada tipo. Simples (`prompts/v1/`, usada por v1 e v2) ou estruturada (`prompts/v3/`). O schema de saída é o mesmo em todas.
4. **Entrada** — perfil + ticket delimitados. Igual em todas as versões.

Cada versão declara em `prompts/<versao>/manifest.json` quais camadas usa (`base`, `domain`, pasta de `tasks`; `role` quando não há base), com hipótese e changelog. O `prompt_builder` monta só a partir do manifesto.

Ablação: cada versão acrescenta **uma** camada à anterior.
- `v1` = papel de uma linha + tarefa simples (sem base, sem domínio).
- `v2` = base + domínio + a mesma tarefa da v1 → **v1→v2 mede o contexto**.
- `v3` = base + domínio + tarefa estruturada → **v2→v3 mede a tarefa**.

Em comparação: camada 4 (entrada) + schema de saída + modelo + config fixos. Só o que o manifesto declara varia.

## Fluxo
```
perfil + ticket + tipo + versão
→ prompt_builder (camadas do manifest.json da versão + entrada)
→ cache_key = sha256(campos serializados ordenados)
→ hit? sim → retorna (cached=true)
não → llm_client → valida Pydantic → inválido? retry 1x
→ storage + cache → mostra saída + caminho do JSON
```

## Responsabilidades (não misturar)

- Só `llm_client.py` faz rede.
- Só `prompt_builder.py` lê templates.
- Só `storage.py` e `cache.py` escrevem em disco.
- `cli.py` só interage.
- `LLM_PROVIDER=fake` → projeto inteiro roda sem chave. Testes usam sempre esse modo.

## Regras de negócio

### RN01 — Perfis (`data/customers.json`)
3–5 perfis, cada um com `id`, `technical_level` (`leigo|intermediario|avancado`), `communication_style` (`direto|detalhado|didatico`), `channel` (`chat|email|telefone`).
Valores fora do enum → erro claro **antes** de chamar LLM. **Sem acento no código** (padronize `intermediario`, `didatico`); documente no NOTES.

### RN02 — Tickets
Texto livre ou de `data/tickets.json`. Vazio/só espaços → inválido. Vago é válido (exercita `clarifying_questions`).

### RN03 — 4 tipos de conteúdo

| Tipo | Saída obrigatória |
|---|---|
| `diagnosis` | `hypotheses`, `evidence`, `missing_info`, `probable_conclusion` |
| `resolution_steps` | passos adaptados ao nível **e** ao estilo |
| `clarifying_questions` | perguntas priorizadas, só as necessárias |
| `flow_summary` | árvore de decisão: `title`, `start`, `nodes[{id, question, yes, no}]`; cada saída é `{"next": id}` ou `{"action", "ref"}`. O modelo **não** desenha ASCII: `flow_render.py` desenha a partir da árvore (campo `rendered` no JSON) |

Validação do `flow_summary` (retry 1x se falhar): todo `next` existe, todo nó alcançável a partir de `start`, sem ciclos, profundidade ≤ 5, toda folha é ação, `ref` existe na base e **não** é procedimento (`PROC-*`), `question` termina com "?" e não é "X ou Y?". Schema igual nas 3 versões. O renderizador remove do texto da ação o id que repete o `ref`.

Sem chain-of-thought. Sem inventar dado — o que faltar vai em `missing_info`.

### RN04 — Adaptação ao perfil
- **Nível:** leigo (sem jargão) · intermediário · avançado (termos técnicos e comandos OK).
- **Estilo:** direto (curto e objetivo) · detalhado (completo) · didático (explica o porquê).
- **Canal:** chat (mensagens curtas) · email (saudação + passos numerados) · telefone (frases curtas, sem links/código).

### RN05 — Versionamento
Cada versão = `prompts/<versao>/manifest.json` (+ arquivos de tarefa próprios, se houver; pode apontar para tarefas de outra versão sem duplicar). Toda execução grava `prompt_version` + `prompt_layers` + `template_hash` (cobre tudo o que entra no prompt final). Versão usada em comparação registrada **não muda** — crie nova. Atenção: a v2 reutiliza `prompts/v1/*.md`, então editar essas tarefas altera v1 **e** v2.

### RN06 — Persistência (`history.json`)
Campos mínimos: `run_id`, `timestamp` (ISO com fuso), `customer_id`, `ticket`, `content_type`, `prompt_version`, `provider`/`model`/`config`, `output`, `evaluation` (quando houver). Mostrar saída **e** caminho do JSON no CLI.

### RN07 — Cache
Chave = SHA-256 de (perfil, ticket, content_type, prompt_version, hash_template, provider, model, config) serializados deterministicamente (chaves ordenadas). Hit não chama API e grava `cached: true`. **Teste comprovando ≥1 chamada evitada é obrigatório.**

### RN08 — Comparação
Mesmo cliente + ticket + provider + model + config, ≥2 versões. Só a versão varia. Os 2 resultados + avaliação vão para o JSON. **Comando `compare` é interativo**: após gerar as 2 saídas, pede ao usuário as 3 notas (1–5) + justificativas por versão (é o candidato que avalia, não o LLM).

### RN09 — Rubrica
`clarity`, `customer_fit`, `actionability` — nota inteira 1–5 + justificativa não vazia. Nota fora do range ou justificativa vazia → rejeitar com erro. `evaluation.py` só valida e persiste; não gera nota.

### RN10 — CLI
`generate` (perfil + ticket + tipo + versão) · `compare` (perfil + ticket + 2 versões, coleta rubrica) · `list` (perfis, tickets e versões disponíveis). Cada um mostra a saída e o caminho do JSON.

## Erros

- Chave ausente → mensagem apontando `.env`, sem stack trace.
- Timeout/rate limit do provedor → mensagem amigável; **não** grava execução nem cache com falha.
- JSON inválido do LLM → valida + retry 1x; se falhar de novo, loga e não quebra CLI.
- Perfil/ticket/tipo/versão inexistente → erro listando opções válidas.

## Entregáveis

- [ ] Executa seguindo só o README
- [ ] Histórico de commits (mensagens com intenção)
- [ ] `README.md` (setup, arquitetura, exemplos)
- [ ] `requirements.txt` + `.env.example`
- [ ] `samples/` com JSONs de exemplo
- [ ] `PROMPT_ENGINEERING_NOTES.md` (estratégias, ablação v1→v2→v3, decisões, trade-offs, limitações)
- [ ] 1 comparação v1×v2×v3 com 3 notas + justificativas
- [ ] 4 tipos geráveis
- [ ] Cache evita ≥1 chamada repetida (com teste)

## Convenções

- Código simples > abstrações espertas. Você precisa explicar cada parte na entrevista.
- Prompts em arquivo, **nunca** hardcoded no Python.
- Mudança de prompt que afeta comparação → registra no `PROMPT_ENGINEERING_NOTES.md`.
- Documente limitações; não esconda.