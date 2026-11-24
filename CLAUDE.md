# CLAUDE.md — support-prompt-assistant

Regras e contexto do projeto. Leia antes de alterar código, prompts ou dados.
Prioridade = pesos da avaliação (40% prompt, 30% código, 20% docs, 10% extras).

## Estado

**Núcleo (concluído):** CLI `support-assistant` com `list`, `generate` e `compare`; 4 tipos de
conteúdo; ablação v1 → v2 → v3 por manifesto; cache, histórico e rubrica manual; provedor fake e
Gemini; comparação v1×v2×v3 com Gemini avaliada (`samples/gemini_resolution_steps_*`) e exemplos reais sem rubrica de `clarifying_questions` e `flow_summary` (`samples/gemini_*`).

**Extras (concluídos):** métricas objetivas com violações por perfil (`metrics.py`); retry do
provedor com backoff; CI no GitHub Actions; interface web Streamlit (extra `web`); modo público
para deploy no Streamlit Community Cloud.

**Fora do escopo:** juiz LLM, mais de um provedor real, banco de dados/concorrência, integração
com sistemas reais, recuperação por embeddings, observabilidade além dos logs.

## Stack

- Python 3.11+, `argparse` (stdlib) — sem Click/Typer.
- JSON via stdlib; Pydantic só para schemas de saída.
- LLM: **uma** API gratuita (Gemini, REST via `urllib`). Tudo passa por `llm_client.py`.
- Streamlit só como extra opcional (`pip install -e ".[web]"`). A CLI e os testes do núcleo não
  dependem dele. `app/requirements.txt` existe só para o Streamlit Cloud.
- Segredos só em `.env`. `.env.example` só com nomes.

## Estrutura
```
├── README.md · PROMPT_ENGINEERING_NOTES.md · CLAUDE.md
├── requirements.txt · pyproject.toml · .env.example · .gitignore
├── .github/workflows/ci.yml   # pytest 3.11/3.12, LLM_PROVIDER=fake, sem segredos
├── app/
│ ├── streamlit_app.py         # interface web: Gerar, Comparar (às cegas), Histórico
│ └── requirements.txt         # dependências do deploy (o Cloud não instala o pacote)
├── data/
│ ├── customers.json           # 4 perfis
│ ├── tickets.json             # vago, comuns, técnico
│ └── domains/wifi_isp.json    # fatos da empresa com ids
├── prompts/{base,v1,v2,v3}/   # base compartilhado; cada vN/manifest.json declara as camadas
│                              # v1: role.md + tarefas simples · v2: só manifesto (tarefas de v1/) · v3: tarefas estruturadas
├── src/support_assistant/
│ ├── config.py · models.py · prompt_builder.py
│ ├── llm_client.py            # fake + Gemini (única rede), retry do provedor
│ ├── generators.py · cache.py · storage.py
│ ├── flow_render.py           # desenha a árvore do flow_summary (determinístico)
│ ├── evaluation.py            # rubrica (só validação)
│ ├── metrics.py               # métricas objetivas e violações (avisos, nunca rejeitam)
│ └── cli.py · __main__.py
├── tests/                     # cache hit, e2e fake, prompt builder, flow_summary, validação,
│                              # métricas, retry do provedor, modo público, interface web
├── docs/
│ ├── ARCHITECTURE.md          # módulos, cache, formato do histórico, erros, testes
│ └── DECISIONS.md             # métricas, CI, interface web, deploy
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

Em comparação: camada 4 (entrada) + schema de saída + validação/retry + modelo + config fixos. Só o que o manifesto declara varia. Nada específico de uma versão pode vazar para as outras pela mensagem de retry.

## Fluxo
```
perfil + ticket + tipo + versão
→ prompt_builder (camadas do manifest.json da versão + entrada)
→ cache_key = sha256(campos serializados ordenados)
→ hit? sim → retorna (cached=true)
não → llm_client (retry do provedor em falha temporária) → valida Pydantic → inválido? retry 1x
→ metrics (avisos) → storage + cache → mostra saída + caminho do JSON
```

## Responsabilidades (não misturar)

- Só `llm_client.py` faz rede.
- Só `prompt_builder.py` lê templates.
- Só `storage.py` e `cache.py` escrevem em disco.
- `cli.py` e `app/streamlit_app.py` só interagem: nenhuma regra de negócio, ambos montam o
  `Generator` por `generators.build_generator(settings, client=None)`.
- `metrics.py` só mede; falha no cálculo nunca derruba a geração.
- `LLM_PROVIDER=fake` → projeto inteiro roda sem chave. Testes usam sempre esse modo.

## Regras de negócio

### RN01 — Perfis (`data/customers.json`)
3–5 perfis, cada um com `id`, `technical_level` (`leigo|intermediario|avancado`), `communication_style` (`direto|detalhado|didatico`), `channel` (`chat|email|telefone`).
Valores fora do enum → erro claro **antes** de chamar LLM. **Sem acento no código** (padronize `intermediario`, `didatico`); documentado no NOTES.

### RN02 — Tickets
Texto livre ou de `data/tickets.json`. Vazio/só espaços → inválido. Vago é válido (exercita `clarifying_questions`).

### RN03 — 4 tipos de conteúdo

| Tipo | Saída obrigatória |
|---|---|
| `diagnosis` | `hypotheses`, `evidence`, `missing_info`, `probable_conclusion` |
| `resolution_steps` | passos adaptados ao nível **e** ao estilo |
| `clarifying_questions` | perguntas priorizadas, só as necessárias |
| `flow_summary` | árvore de decisão: `title`, `start`, `nodes[{id, question, yes, no}]`; cada saída é `{"next": id}` ou `{"action", "ref"}`. O modelo **não** desenha ASCII: `flow_render.py` desenha a partir da árvore (campo `rendered` no JSON) |

`flow_summary` tem dois níveis de regra:
- **Estruturais** (`analyze_flow` em `models.py`, retry 1x se falhar): `start` existe, ids únicos, todo `next` existe, todo nó alcançável, sem ciclos, profundidade ≤ 5, toda folha é ação, `ref` existe na base.
- **Qualidade** (`metrics.py`, viram `violations`, nunca rejeitam nem disparam retry): `question` termina com "?" e não é "X ou Y?"; folha não termina em procedimento (`PROC-*`). A dica de como reestruturar fica só no prompt da v3.

Schema igual nas 3 versões. O renderizador remove do texto da ação o id que repete o `ref`.

Sem chain-of-thought. Sem inventar dado — o que faltar vai em `missing_info` (ou vira passo condicional em `resolution_steps`).

### RN04 — Adaptação ao perfil
- **Nível:** leigo (sem jargão) · intermediário · avançado (termos técnicos e comandos OK).
- **Estilo:** direto (curto e objetivo) · detalhado (completo) · didático (explica o porquê).
- **Canal:** chat (mensagens curtas) · email (saudação + passos numerados) · telefone (frases curtas, sem links/código).
- `metrics.py` aponta jargão para `leigo` e URL/IP/comando no `telefone` (só em `resolution_steps`, heurística). O resto depende da rubrica humana.

### RN05 — Versionamento
Cada versão = `prompts/<versao>/manifest.json` (+ arquivos de tarefa próprios, se houver; pode apontar para tarefas de outra versão sem duplicar). Toda execução grava `prompt_version` + `prompt_layers` + `template_hash` (cobre tudo o que entra no prompt final). Versão usada em comparação registrada **não muda** — crie nova. Atenção: a v2 reutiliza `prompts/v1/*.md`, então editar essas tarefas altera v1 **e** v2.
A comparação Gemini registrada (`resolution_steps`, c01 + t02) depende de `base/system.md`, `base/domain.md` + `wifi_isp.json`, `base/input.md`, `base/retry.md`, `v1/role.md`, `v1/resolution_steps.md` e `v3/resolution_steps.md`. Editar qualquer um muda o hash e exige refazer a comparação.

### RN06 — Persistência (`history.json`)
Campos mínimos: `run_id`, `timestamp` (ISO com fuso), `customer_id`, `ticket`, `content_type`, `prompt_version`, `prompt_layers`, `template_hash`, `provider`/`model`/`config`, `cached`, `attempts`, `provider_retries`, `output`, `metrics`, `evaluation` (quando houver); `rendered` no `flow_summary`. Mostrar saída **e** caminho do JSON no CLI.

### RN07 — Cache
Chave = SHA-256 de (perfil, ticket, content_type, prompt_version, hash_template, provider, model, config) serializados deterministicamente (chaves ordenadas). `attempts`, `provider_retries` e a API key **não** entram na chave. Hit não chama API e grava `cached: true`. **Teste comprovando ≥1 chamada evitada é obrigatório.**

### RN08 — Comparação
Mesmo cliente + ticket + provider + model + config, ≥2 versões (padrão `v1 v2 v3`). Só a versão varia. Os resultados + avaliação + métricas vão para o JSON. **O `compare` é interativo**: depois de gerar as saídas, pede as 3 notas (1–5) + justificativas por versão (quem avalia é o candidato, não o LLM). Na interface web, a avaliação é às cegas por padrão (A/B/C embaralhadas; versão revelada só depois de gravar).

### RN09 — Rubrica
`clarity`, `customer_fit`, `actionability` — nota inteira 1–5 + justificativa não vazia. Nota fora do range ou justificativa vazia → rejeitar com erro. `evaluation.py` só valida e persiste; não gera nota.

### RN10 — CLI
Comando `support-assistant` (ou `python -m support_assistant`). `generate` (perfil + ticket + tipo + versão) · `compare` (perfil + ticket + ≥2 versões, coleta rubrica) · `list` (perfis, tickets e versões disponíveis). Cada um mostra a saída e o caminho do JSON.

### RN11 — Deploy público (`APP_PUBLIC_MODE=true`)
- Força o provedor fake e **ignora** `LLM_PROVIDER` e `GEMINI_API_KEY` do ambiente: a chave do dono nunca é usada.
- O Gemini só funciona com a chave que o visitante cola na barra lateral. Ela fica só em memória (`st.session_state`, `Settings` com `repr=False`, cliente) e vai no cabeçalho `x-goog-api-key`; nunca em disco, histórico, cache, JSON baixado ou log.
- Cada sessão grava num diretório temporário próprio: um visitante não vê os tickets de outro.
- Secrets do Streamlit Cloud: só `APP_PUBLIC_MODE = "true"`.

## Erros

- Chave ausente → mensagem apontando `.env`, sem stack trace.
- 429/5xx/timeout/conexão → até `LLM_MAX_RETRIES` repetições com backoff exponencial + jitter (ou `Retry-After`; acima de 15 s desiste). 400/401/403/404 não repetem.
- Falha do provedor após as repetições → mensagem amigável; **não** grava execução nem cache.
- JSON inválido do LLM → valida + retry 1x; se falhar de novo, grava em `failures.json` e não quebra a CLI.
- Perfil/ticket/tipo/versão inexistente → erro listando opções válidas.
- Interface web → os mesmos erros viram `st.error`, sem traceback.

## Entregáveis

- [x] Executa seguindo só o README
- [x] Histórico de commits (mensagens com intenção)
- [x] `README.md` (setup, arquitetura, exemplos)
- [x] `requirements.txt` + `.env.example`
- [x] `samples/` com JSONs de exemplo
- [x] `PROMPT_ENGINEERING_NOTES.md` (estratégias, ablação v1→v2→v3, decisões, trade-offs, limitações)
- [x] 1 comparação v1×v2×v3 com 3 notas + justificativas
- [x] 4 tipos geráveis
- [x] Cache evita ≥1 chamada repetida (com teste)
- [x] Deploy publicado: <https://sac-llm-assistant.streamlit.app> (Streamlit Community Cloud, `APP_PUBLIC_MODE=true`)

## Convenções

- Código simples > abstrações espertas. Você precisa explicar cada parte na entrevista.
- Prompts em arquivo, **nunca** hardcoded no Python.
- Mudança de prompt que afeta comparação → registra no `PROMPT_ENGINEERING_NOTES.md`.
- Decisão de código, CI, interface ou deploy → registra em `docs/DECISIONS.md`.
- Documente limitações; não esconda.
