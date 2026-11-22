# support-prompt-assistant

[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

CLI em Python que gera **conteúdo de suporte técnico adaptado ao perfil do cliente** para um
provedor de internet fictício (NetVale Fibra), usando um LLM com **prompts versionados**,
**cache**, **histórico em JSON** e **comparação entre versões de prompt com rubrica manual**.

Dado um perfil de cliente (nível técnico, estilo, canal) e um ticket, gera um de 4 conteúdos:

| Tipo | Para quem | O que entrega |
|---|---|---|
| `diagnosis` | atendente | hipóteses, evidências, informações faltantes, conclusão provável |
| `resolution_steps` | cliente | passos adaptados ao nível, ao estilo e ao canal |
| `clarifying_questions` | cliente | perguntas priorizadas, só as necessárias |
| `flow_summary` | atendente | árvore de decisão estruturada (sim/não), desenhada em texto pelo código |

---

## Sumário

1. [Setup](#1-setup)
2. [Uso](#2-uso)
3. [Arquitetura](#3-arquitetura)
4. [Módulos (código)](#4-módulos-código)
5. [Prompts](#5-prompts)
6. [Dados](#6-dados)
7. [Cache](#7-cache)
8. [Persistência e formato do histórico](#8-persistência-e-formato-do-histórico)
9. [Comparação e rubrica](#9-comparação-e-rubrica)
10. [Tratamento de erros](#10-tratamento-de-erros)
11. [Testes](#11-testes)
12. [Estrutura de pastas](#12-estrutura-de-pastas)
13. [Limitações](#13-limitações)

---

## 1. Setup

Requisitos: **Python 3.11+**.

```bash
# 1. Ambiente virtual
python -m venv .venv
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

# 2. Dependências + instalação do pacote (cria o comando `support_assistant`)
pip install -r requirements.txt
pip install -e .

# 3. Configuração
cp .env.example .env        # Windows: copy .env.example .env
```

**Sem chave de API** o projeto roda inteiro com o provedor `fake` (padrão quando `LLM_PROVIDER`
está vazio). Ele devolve respostas fixas, marcadas com `[FAKE]`, e serve para testar o fluxo.

**Com LLM real (Google Gemini, free tier):**
1. Gere uma chave em <https://aistudio.google.com/apikey>.
2. No `.env`:
   ```env
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=sua-chave
   ```

### Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `fake` | `fake` (offline) ou `gemini` |
| `GEMINI_API_KEY` | — | obrigatória se `LLM_PROVIDER=gemini` |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | modelo do Gemini |
| `LLM_TEMPERATURE` | `0.2` | 0 a 2 |
| `LLM_MAX_OUTPUT_TOKENS` | `4096` | limite de tokens da resposta |
| `LLM_TIMEOUT_SECONDS` | `60` | timeout da requisição |
| `LLM_MAX_RETRIES` | `3` | repetições em falha temporária do provedor (0 a 10; `0` desliga) |
| `LLM_BACKOFF_BASE_SECONDS` | `2` | base do backoff exponencial, em segundos (0 a 60) |
| `OUTPUT_DIR` | `outputs/` | onde ficam `history.json`, `cache.json`, `runs/` |

Variáveis já definidas no ambiente têm prioridade sobre o `.env`.

---

## 2. Uso

Todos os comandos também funcionam como `python -m support_assistant <comando>`.

### `list`: o que está disponível

```bash
support_assistant list
```
```
Perfis (--customer):
  c01    Marta Oliveira         nível=leigo         estilo=didatico  canal=telefone
  c02    Rafael Souza           nível=intermediario estilo=direto    canal=chat
  c03    Juliana Martins        nível=avancado      estilo=detalhado canal=email
  c04    Antônio Ferreira       nível=leigo         estilo=direto    canal=chat

Tickets (--ticket-id):
  t01    [vago    ] minha internet não tá boa, resolve aí por favor
  t02    [comum   ] O Wi-Fi cai várias vezes por dia, principalmente à noite. No quarto...
  t03    [tecnico ] Desde ontem à noite tenho latência alta (80-150 ms, normalmente 8 m...
  t04    [comum   ] A internet ficou fora o dia todo, a luz vermelha da caixinha da fib...

Versões de prompt (--version / --versions), cada uma acrescenta uma camada à anterior:
  v1     camadas: papel mínimo + tarefas v1
         tipos: diagnosis, resolution_steps, clarifying_questions, flow_summary
         Baseline mínimo: papel de uma linha + tarefa simples. Sem camada base e sem domínio.
  v2     camadas: base + domínio + tarefas v1
         ...
  v3     camadas: base + domínio + tarefas v3
         ...
```

### `generate`: gerar um conteúdo

```bash
# ticket do catálogo
support_assistant generate --customer c01 --ticket-id t02 --type resolution_steps --version v3

# ticket em texto livre (forma curta dos argumentos)
support_assistant generate -c c03 --ticket "ping alto desde ontem à noite" -y diagnosis -p v1

# só ver o prompt montado (camadas da versão), sem chamar o LLM nem gravar nada
support_assistant generate -c c04 -t t01 -y clarifying_questions -p v1 --show-prompt
```

| Argumento | Obrigatório | Descrição |
|---|---|---|
| `--customer`, `-c` | sim | id do perfil |
| `--ticket-id`, `-t` / `--ticket` | um dos dois | id do catálogo **ou** texto livre |
| `--type`, `-y` | sim | `diagnosis`, `resolution_steps`, `clarifying_questions`, `flow_summary` |
| `--version`, `-p` | não (`v3`) | versão do prompt: `v1`, `v2` ou `v3` (ver [seção 5](#5-prompts)) |
| `--show-prompt` | não | imprime o prompt e sai |

Saída (com o provedor fake):
```
────────────────────────────────────────────────────────────────────────
resolution_steps | versão v3 | cliente c01 | fake/fake-model-v1
camadas: base + domínio + tarefas v3
cache: não | tentativas: 1 | latência: 0 ms
────────────────────────────────────────────────────────────────────────
[FAKE] Olá! Vamos resolver isso juntos.

1. [FAKE] Desligue o roteador e a ONT da tomada.
   Por quê: Limpa travamentos.
2. [FAKE] Aguarde 30 segundos e ligue primeiro a ONT.
...
[Atendente] Escalonamento: [FAKE] Se o problema continuar, agendar visita técnica (fato POL-03).
────────────────────────────────────────────────────────────────────────
JSON da execução: outputs\runs\20261121-171349-549dfe.json
Histórico:        outputs\history.json
```

Se você rodar o mesmo comando de novo, aparece `cache: sim (nenhuma chamada à API)`.

### `compare`: comparar versões de prompt

```bash
# ablação completa (padrão quando --versions é omitido)
support_assistant compare -c c01 -t t02 -y resolution_steps --versions v1 v2 v3

# só um par de versões vizinhas (ex.: efeito da tarefa estruturada)
support_assistant compare -c c01 -t t02 -y resolution_steps --versions v2 v3
```

1. Gera a mesma entrada em cada versão (**2 ou mais**, todas diferentes; padrão `v1 v2 v3`).
   Perfil, ticket, provedor, modelo e config são os mesmos; só a versão do prompt muda.
2. Mostra as saídas.
3. **Pede, interativamente, as notas de 1 a 5 e uma justificativa** para `clarity`,
   `customer_fit` e `actionability` de cada versão. Nota inválida ou justificativa vazia é
   rejeitada e perguntada de novo.
4. Calcula a média, indica a versão vencedora e grava a comparação em JSON.

`Ctrl+C` cancela sem gravar a comparação. As saídas ficam no cache, então rodar de novo é instantâneo.

---

## 3. Arquitetura

### Fluxo de uma geração

```
perfil + ticket + tipo + versão
        │
        ▼
 validação de entrada (models.py)  ── inválido ──► erro claro com opções válidas (sem chamar LLM)
        │
        ▼
 prompt_builder: lê prompts/<versão>/manifest.json
                 camadas declaradas (base|papel mínimo, domínio, tarefa) + entrada  ──► template_hash
        │
        ▼
 cache_key = sha256(perfil, ticket, tipo, versão, template_hash, provider, model, config)
        │
   hit? ├── sim ──► saída do cache (cached=true, 0 chamadas)
        │
        └── não ──► llm_client.complete()
                         │
                         ▼
                 valida JSON + schema Pydantic
                         │
                inválido?├── sim ──► retry 1x com o erro do validador
                         │              └── inválido de novo ──► failures.json + erro amigável
                         ▼                                       (nada vai p/ cache/histórico)
                     cache.set()
        │
        ▼
 storage.save_run()  ──► history.json + runs/<run_id>.json
        │
        ▼
 CLI mostra a saída formatada + caminho do JSON
```

### Separação de responsabilidades

| Responsabilidade | Único módulo que faz |
|---|---|
| Acesso à rede | `llm_client.py` |
| Leitura de templates de prompt | `prompt_builder.py` |
| Escrita em disco | `storage.py` e `cache.py` (o cache usa as funções de escrita atômica do storage) |
| Interação com o usuário (args, print, input) | `cli.py` |
| Validação da rubrica | `evaluation.py` (não gera notas) |

Com `LLM_PROVIDER=fake`, o projeto inteiro funciona sem chave e sem rede. Os testes usam sempre esse modo.

---

## 4. Módulos (código)

Todos em [src/support_assistant/](src/support_assistant/).

### [config.py](src/support_assistant/config.py): configuração
- Define os caminhos do projeto (`data/`, `prompts/`, `outputs/`).
- `load_settings()` carrega o `.env` com `python-dotenv` (sem sobrescrever variáveis já
  definidas), valida provedor e temperatura e devolve um `Settings` imutável.
- `Settings.generation_config` reúne os parâmetros que afetam a saída (temperatura, max tokens),
  que entram na chave de cache.
- Com o provedor `fake`, o modelo é sempre `fake-model-v1` e nenhuma chave é lida.

### [models.py](src/support_assistant/models.py): entradas e schemas de saída
- **Enums** `TechnicalLevel`, `CommunicationStyle`, `Channel`, `ContentType`, sem acento
  (`intermediario`, `didatico`, `avancado`).
- **`CustomerProfile.from_dict`** valida cada campo de enum e gera erros como
  `Perfil 'x': campo 'technical_level' com valor inválido 'expert'. Valores aceitos: leigo, intermediario, avancado.`
- **`Ticket.from_text`** rejeita texto vazio ou só com espaços. Ticket vago é válido.
- **`load_customers` / `load_tickets`** carregam e validam os arquivos de `data/`.
- **Schemas Pydantic de saída** (`OUTPUT_SCHEMAS`), um por tipo e **iguais em todas as versões**:

  | Tipo | Schema | Regras |
  |---|---|---|
  | `diagnosis` | `hypotheses[{cause, likelihood, rationale}]`, `evidence[]`, `missing_info[]`, `probable_conclusion` | 1–5 hipóteses; `likelihood` ∈ `alta/media/baixa`; ≥1 evidência |
  | `resolution_steps` | `opening`, `steps[{step, instruction, why}]`, `closing`, `escalation` | 1–10 passos, reordenados por `step`; `why` opcional |
  | `clarifying_questions` | `already_known[]`, `questions[{priority, question, purpose}]` | 0–5 perguntas, reordenadas por prioridade |
  | `flow_summary` | `title`, `start`, `nodes[{id, question, yes, no}]`; cada `yes`/`no` é `{"next": id}` ou `{"action", "ref"}` | 1–15 nós; árvore validada por `analyze_flow()` (abaixo) |

  A árvore do `flow_summary` passa por `analyze_flow()` (só regras estruturais): todo `next` aponta para um nó existente,
  todo nó é alcançável a partir de `start`, sem ciclos, profundidade ≤ 5 decisões, toda folha é
  uma ação e `ref` existe na base de conhecimento (`load_kb_ids()`). Problemas viram erro de
  schema → retry 1x com a lista exata.

  As regras de **qualidade** ficam em [metrics.py](src/support_assistant/metrics.py) e não
  rejeitam a árvore: `question_not_yes_no` (pergunta sem "?" ou na forma "X ou Y?") e
  `procedure_leaf` (folha com `ref` `PROC-*`). Vão para o campo `violations` do registro e a CLI as
  mostra como "Avisos de qualidade". A dica de como reestruturar está só no prompt da v3.

  Strings obrigatórias não podem ser vazias. Campos extras são ignorados.

### [prompt_builder.py](src/support_assistant/prompt_builder.py): montagem do prompt
- `load_manifest()` lê e valida `prompts/<versão>/manifest.json` (camadas `base`/`domain` como
  booleanos, pasta `tasks` existente, `role` obrigatório só quando não há base). Erros apontam o
  arquivo e o campo.
- `build_prompt(...)` monta o prompt **só a partir do manifesto** (nenhuma versão está no código):
  - **system** = (`base/system.md` **ou** o arquivo `role`) + (`base/domain.md` com o JSON do
    domínio, se `domain: true`) + `<tasks>/<tipo>.md`
  - **user** = `base/input.md` com perfil (JSON) e ticket delimitados por tags (igual em todas as versões)
  - devolve também `layers`, gravado no histórico como `prompt_layers`
- Usa `string.Template` (`$variavel`) em vez de `str.format`, para que as chaves `{}` dos exemplos
  JSON nos prompts não precisem de escape.
- `template_hash`: SHA-256 de pares (rótulo, texto) de **tudo** o que entra no prompt final (papel
  ou base, domínio, tarefa, entrada, retry). Editar um arquivo ou mudar a composição no manifesto
  muda o hash, invalida o cache e fica registrado no histórico (RN05).
- Sanitiza o ticket para que o texto do cliente não feche as tags `</ticket>` (proteção simples
  contra prompt injection).
- `list_versions()` descobre as versões pelas pastas de `prompts/` que têm `manifest.json`.
  `build_retry_message()` monta a mensagem de correção a partir de `base/retry.md`.

### [flow_render.py](src/support_assistant/flow_render.py): desenho do `flow_summary`
- `render_flow(tree)` desenha a árvore validada como texto, de cima para baixo, uma pergunta por
  nó; folhas como "Ação (REF). FIM". É determinístico: a mesma árvore gera sempre o mesmo texto,
  e a ordem dos nós na lista não importa (parte de `start`).
- O modelo nunca desenha o diagrama; por isso diagrama e decisões não podem se contradizer.
- `strip_ref()` remove do texto da ação o id que já está em `ref` (ex.: "Agendar visita (ESC-01)",
  "… conforme ESC-01"), para o id aparecer uma vez só, em "(REF)".

```
[FAKE] Triagem de internet instável

[D1] [FAKE] A luz LOS da ONT está vermelha?
├─ SIM → Agendar visita técnica (ESC-01). FIM
└─ NÃO → [D2] [FAKE] Reiniciar ONT e roteador resolveu?
   ├─ SIM → Encerrar atendimento. FIM
   └─ NÃO → [D3] [FAKE] O problema também acontece no cabo de rede?
      ├─ SIM → Escalar para N2 Rede com as evidências coletadas (ESC-02). FIM
      └─ NÃO → Orientar ajustes do Wi-Fi (WIFI-01). FIM
```

### [llm_client.py](src/support_assistant/llm_client.py): provedores de LLM
- Interface única: `.provider`, `.model`, `.complete(system, user, content_type) -> str`.
- **`FakeLLMClient`**: devolve um JSON fixo e válido por tipo e conta as chamadas (`call_count`),
  o que permite provar nos testes que o cache evitou uma chamada.
- **`GeminiClient`**: chama a API REST `generateContent` com `urllib` (stdlib). Envia
  `systemInstruction`, `temperature`, `maxOutputTokens` e `responseMimeType: application/json`.
  Traduz falhas em mensagens amigáveis:
  - 429 → rate limit, "aguarde um minuto"
  - 401/403 → chave inválida, "confira o `.env`"
  - 404 → modelo inexistente, "ajuste `LLM_MODEL`"
  - 5xx, timeout, sem conexão, resposta vazia ou bloqueada → `LLMProviderError`
- **Retry do provedor** (separado do retry por schema): só 429, 5xx, timeout e erro de conexão são
  repetidos, até `LLM_MAX_RETRIES` vezes, com espera `base × 2^n + jitter(0..base)`. Se a resposta
  traz `Retry-After`, espera exatamente esse tempo; acima de 60 s (ex.: cota diária) desiste na hora.
  400/401/403/404 nunca são repetidos. Esgotadas as tentativas, a mensagem amigável acima é mostrada e
  nada vai para cache nem histórico. Cada repetição gera um aviso `[WARNING] support_assistant.llm_client: …`.
  O registro grava `provider_retries` (repetições do provedor), separado de `attempts` (tentativas
  por schema); nenhum dos dois entra na chave de cache.
- Transporte HTTP e função de espera são injetáveis (`transport=`, `sleep=`), para os testes
  simularem falhas sem rede e sem esperar.
- **`create_client(settings)`** escolhe o provedor. Sem chave, a mensagem aponta para o `.env`.

### [generators.py](src/support_assistant/generators.py): orquestração
- **`Generator.generate()`** executa o fluxo da seção 3: valida, monta o prompt, calcula a
  chave, consulta o cache, chama o LLM, valida, faz retry, grava cache e histórico.
- **`parse_output()`** remove cercas de código ```` ``` ```` se o modelo as incluir, faz `json.loads`,
  valida com o schema e transforma os erros do Pydantic numa mensagem legível. Essa mensagem é a
  que vai para o retry.
- **Retry 1x**: na segunda tentativa, acrescenta ao prompt o motivo exato da rejeição. Se falhar de
  novo, grava as duas respostas brutas em `failures.json` e lança `GenerationError`, que a CLI
  mostra sem stack trace.
- Falha do provedor ou JSON inválido **nunca** entram no cache nem no histórico.
- Para `flow_summary`, grava a árvore em `output` e o texto de `render_flow()` no campo separado
  `rendered` (também em cache hit). Os outros tipos não têm `rendered`.
- **`Generator.compare()`** valida todas as versões (manifesto e template do tipo) antes de gastar chamadas, gera cada uma com o
  mesmo cliente/config e não persiste nada até a avaliação. **`save_comparison()`** grava o registro final.

### [cache.py](src/support_assistant/cache.py): cache
- `make_cache_key(fields)` faz `json.dumps(sort_keys=True, separators=(",", ":"))` e depois SHA-256.
  A chave é determinística e não depende da ordem dos campos.
- `JsonCache.get/set` sobre `outputs/cache.json`. Detalhes na [seção 7](#7-cache).

### [storage.py](src/support_assistant/storage.py): persistência
- `atomic_write_json()` escreve num arquivo temporário e renomeia (`os.replace`), para não
  corromper o JSON se o processo cair no meio da escrita.
- `Storage.save_run()` / `save_comparison()` acrescentam o registro em `history.json` e também
  gravam `runs/<id>.json`, cujo caminho é mostrado na CLI.
- `Storage.log_failure()` grava respostas inválidas em `failures.json`.

### [evaluation.py](src/support_assistant/evaluation.py): rubrica
- `RUBRIC_CRITERIA`: `clarity`, `customer_fit`, `actionability`, com a descrição de cada um.
- `validate_score()` aceita só inteiros de 1 a 5 (rejeita `0`, `6`, `3.5`, `"abc"`, `True`).
- `validate_justification()` rejeita texto vazio.
- `build_evaluation()` monta `{criterio: {score, justification}, average, evaluated_by: "human"}`.
- `pick_winner()` devolve a versão com maior média, ou `None` em caso de empate.
- O módulo **não gera notas**: quem avalia é a pessoa.

### [cli.py](src/support_assistant/cli.py): interface
- `argparse` com os subcomandos `list`, `generate` e `compare`.
- Resolve perfil e ticket por id (ou texto livre). Ids inexistentes geram erro com as opções válidas.
- `render_output()` formata cada tipo de forma legível no terminal. O JSON completo fica no arquivo.
  O cabeçalho de cada saída mostra as camadas usadas pela versão. Para `flow_summary`, exibe o
  texto de `rendered`.
- `collect_rubric()` faz as perguntas da rubrica e repete a pergunta quando a entrada é inválida.
- `main()` captura os erros conhecidos e imprime `Erro: <mensagem>` com exit code 1, sem stack
  trace. `Ctrl+C` sai com 130. `--verbose` liga logs de depuração.

### [\_\_main\_\_.py](src/support_assistant/__main__.py)
Permite `python -m support_assistant ...`.

---

## 5. Prompts

O prompt tem **4 camadas**. Cada versão declara no seu `manifest.json` quais usa.

| # | Camada | Arquivo | Conteúdo |
|---|---|---|---|
| 1 | Base | [prompts/base/system.md](prompts/base/system.md) | persona (assistente do atendente N1), público de cada tipo, 7 limites obrigatórios, regras de adaptação (nível/estilo/canal) com precedência, formato JSON, proibição de chain-of-thought |
| 2 | Domínio | [prompts/base/domain.md](prompts/base/domain.md) + [data/domains/wifi_isp.json](data/domains/wifi_isp.json) | fatos da empresa com IDs citáveis |
| 3 | Tarefa | `prompts/v1/*.md` (simples), `prompts/v3/*.md` (estruturada) | instrução e formato de cada tipo |
| 4 | Entrada | [prompts/base/input.md](prompts/base/input.md) | `<perfil_cliente>` + `<ticket>` (todas as versões) |
| — | Retry | [prompts/base/retry.md](prompts/base/retry.md) | mensagem de correção com o erro do validador (todas as versões) |

Nenhum prompt está escrito no código Python: todos ficam em arquivos `.md`.

### Versões (ablação: cada uma acrescenta uma camada)

| Versão | Base | Domínio | Tarefas | Mede, em relação à anterior |
|---|---|---|---|---|
| **[v1](prompts/v1/manifest.json)** | não ([papel de uma linha](prompts/v1/role.md)) | não | `v1/` simples | — (baseline) |
| **[v2](prompts/v2/manifest.json)** | sim | sim | `v1/` simples (reutilizadas, sem cópia) | o **contexto** |
| **[v3](prompts/v3/manifest.json)** | sim | sim | `v3/` estruturadas | a **tarefa** |

- **v1**: "assistente de suporte técnico" + "responda apenas com JSON válido, em pt-BR" + uma frase
  de tarefa com o formato JSON. Perfil e ticket entram delimitados, como em todas as versões.
- **v2**: a mesma tarefa da v1 com persona, limites, regras de perfil, formato e base de conhecimento.
- **v3**: estruturada. Objetivo e público, critérios por campo, regras para casos limite (ticket
  vago, cliente que já testou, critério de escalonamento), limites de quantidade por estilo, ordem
  de prioridade, schema com tipos e um checklist de verificação que o modelo não escreve na saída.

O schema de saída de cada tipo é o mesmo nas três versões.

Exemplo de manifesto ([prompts/v2/manifest.json](prompts/v2/manifest.json)):
```json
{
  "description": "Camada base + domínio com a MESMA tarefa simples da v1 ...",
  "layers": { "base": true, "domain": true, "tasks": "v1" },
  "hypothesis": "Persona, limites, regras de adaptação e base de conhecimento melhoram customer_fit ...",
  "changelog": ["2026-11-22: criada como base + domínio + tarefas da v1 ..."]
}
```
Sem base (`"base": false`), o manifesto precisa de `"role": "<arquivo em prompts/>"`.

Estratégias, ablação v1→v2→v3, decisões e limitações estão em
**[PROMPT_ENGINEERING_NOTES.md](PROMPT_ENGINEERING_NOTES.md)**.

### Criar uma nova versão
1. Crie `prompts/v4/manifest.json` declarando as camadas. Se a tarefa mudar, coloque os novos
   arquivos de tarefa em `prompts/v4/` e use `"tasks": "v4"`; senão, aponte para uma pasta existente.
2. Ela aparece automaticamente em `list` e pode ser usada com `--version v4`.
3. Registre a mudança no changelog do manifesto e em `PROMPT_ENGINEERING_NOTES.md`.

Uma versão usada numa comparação registrada **não deve ser editada** (RN05). Crie outra.
Como a v2 reutiliza `prompts/v1/*.md`, editar uma tarefa da v1 muda as duas versões.

---

## 6. Dados

### [data/customers.json](data/customers.json): perfis
4 perfis que cobrem os 3 níveis, os 3 estilos e os 3 canais:

| id | nível | estilo | canal | por que existe |
|---|---|---|---|---|
| c01 | leigo | didatico | telefone | caso mais exigente: sem jargão, explicar o porquê, sem links |
| c02 | intermediario | direto | chat | respostas curtas, sem repetir o que ele já fez |
| c03 | avancado | detalhado | email | aceita termos técnicos e comandos; formato de e-mail |
| c04 | leigo | direto | chat | leigo mas objetivo: simples *e* curto |

Campos: `id`, `name`, `technical_level`, `communication_style`, `channel` (obrigatórios e validados)
e `plan`, `notes` (opcionais, dão contexto ao modelo).

### [data/tickets.json](data/tickets.json): tickets
| id | categoria | exercita |
|---|---|---|
| t01 | vago | `clarifying_questions`, diagnóstico sem hipótese forte |
| t02 | comum | Wi-Fi fraco no quarto e à noite (WIFI-01/02) |
| t03 | técnico | latência e perda via cabo, com traceroute (NET-02, escalonamento N2) |
| t04 | comum | LED LOS vermelho (critério de visita técnica ESC-01) |

### [data/domains/wifi_isp.json](data/domains/wifi_isp.json): base de conhecimento
Empresa fictícia **NetVale Fibra**: planos (`PLAN-xx`), equipamentos e significado dos LEDs
(`EQ-xx`), problemas conhecidos com causas, verificações e ações (`WIFI-xx`, `NET-xx`, `SPEED-xx`),
procedimentos (`PROC-xx`), políticas (`POL-xx`) e critérios de escalonamento (`ESC-xx`). Os IDs
permitem que o modelo cite a fonte e que o avaliador confira se ele inventou algo.

---

## 7. Cache

- **Chave**: SHA-256 de um JSON com chaves ordenadas contendo
  `customer` (perfil completo), `ticket` (texto), `content_type`, `prompt_version`,
  `template_hash`, `provider`, `model` e `config` (temperatura e max tokens).
- **Hit**: não chama a API. O registro vai para o histórico com `cached: true`, `attempts: 0` e
  `cached_from_run_id` apontando para a execução original.
- **Invalidação**: automática. Qualquer mudança em perfil, ticket, template, modelo ou config gera
  outra chave.
- **Arquivo**: `outputs/cache.json` (`{chave: {output, run_id, created_at}}`). Para limpar,
  apague o arquivo.
- O teste [tests/test_cache.py](tests/test_cache.py) prova que duas gerações iguais fazem
  **1 chamada** ao LLM.

---

## 8. Persistência e formato do histórico

Arquivos em `OUTPUT_DIR` (padrão `outputs/`, ignorado pelo git):

| Arquivo | Conteúdo |
|---|---|
| `history.json` | lista de todos os registros (gerações e comparações) |
| `runs/<id>.json` | cada registro em arquivo próprio (é o caminho mostrado na CLI) |
| `cache.json` | cache de respostas |
| `failures.json` | respostas inválidas após o retry, para depuração |

### Registro de geração (`kind: "generation"`)
```json
{
  "kind": "generation",
  "run_id": "20261121-171349-549dfe",
  "timestamp": "2026-11-21T17:13:49-03:00",
  "customer_id": "c01",
  "customer_profile": { "id": "c01", "technical_level": "leigo", "...": "..." },
  "ticket": { "id": "t02", "text": "O Wi-Fi cai várias vezes por dia..." },
  "content_type": "resolution_steps",
  "prompt_version": "v3",
  "prompt_layers": { "base": true, "domain": true, "tasks": "v3", "role": null },
  "template_hash": "3f9a...",
  "provider": "gemini",
  "model": "gemini-3.5-flash-lite",
  "config": { "temperature": 0.2, "max_output_tokens": 4096 },
  "cache_key": "a1b2...",
  "cached": false,
  "attempts": 1,
  "provider_retries": 0,
  "latency_ms": 2140,
  "output": { "opening": "...", "steps": [ ... ], "closing": "...", "escalation": "..." },
  "evaluation": null,
  "run_path": "outputs/runs/20261121-171349-549dfe.json"
}
```

### Registro de comparação (`kind: "comparison"`)
```json
{
  "kind": "comparison",
  "comparison_id": "cmp-20261121-171434-8938d8",
  "timestamp": "...",
  "customer_id": "c02",
  "ticket": { "...": "..." },
  "content_type": "resolution_steps",
  "provider": "gemini", "model": "gemini-3.5-flash-lite", "config": { "...": "..." },
  "versions": ["v1", "v2", "v3"],
  "winner": "v3",
  "runs": [
    { "...registro de geração v1...": "", "evaluation": {
        "clarity": { "score": 3, "justification": "..." },
        "customer_fit": { "score": 2, "justification": "..." },
        "actionability": { "score": 3, "justification": "..." },
        "average": 2.67, "evaluated_by": "human" } },
    { "...registro de geração v2 com evaluation...": "" },
    { "...registro de geração v3 com evaluation...": "" }
  ]
}
```

Exemplos reais estão em [samples/](samples/).

---

## 9. Comparação e rubrica

| Critério | Pergunta |
|---|---|
| `clarity` | O texto é fácil de entender, sem ambiguidade nem ruído? |
| `customer_fit` | Respeita o nível técnico, o estilo e o canal do perfil? |
| `actionability` | Dá para agir imediatamente com base no conteúdo? |

Cada critério recebe uma nota inteira de 1 a 5 e uma justificativa não vazia, dadas por uma pessoa.
Nota fora do intervalo, não inteira ou justificativa vazia é rejeitada. A comparação garante que
só a versão do prompt varia (mesmo perfil, ticket, provedor, modelo e config).

A comparação de referência v1 × v2 × v3 e sua análise estão em
[PROMPT_ENGINEERING_NOTES.md](PROMPT_ENGINEERING_NOTES.md#5-comparação-registrada-rubrica-manual).

---

## 10. Tratamento de erros

| Situação | Comportamento |
|---|---|
| `GEMINI_API_KEY` ausente ou inválida | mensagem apontando o `.env`, sem stack trace |
| `LLM_PROVIDER` ou parâmetro inválido no `.env` | mensagem com as opções válidas |
| Perfil, ticket, tipo ou versão inexistente | erro listando as opções válidas, antes de chamar o LLM |
| Perfil com enum inválido em `customers.json` | erro com o campo e os valores aceitos |
| Ticket vazio ou só espaços | erro antes de chamar o LLM |
| Timeout, rate limit, 5xx, sem conexão | mensagem amigável; **nada** gravado em cache ou histórico |
| JSON inválido ou fora do schema | retry 1x com o erro; se falhar, registra em `failures.json` e mostra erro sem quebrar |
| Nota ou justificativa inválida no `compare` | mostra o erro e pergunta de novo |
| `Ctrl+C` / fim da entrada no `compare` | cancela sem gravar a comparação |

---

## 11. Testes

```bash
pytest -q
```

Todos os testes rodam com o provedor **fake**. Uma fixture força `LLM_PROVIDER=fake` e usa um
diretório temporário, mesmo que exista um `.env` configurado com o Gemini.

| Arquivo | O que prova |
|---|---|
| [tests/test_cache.py](tests/test_cache.py) | **cache hit evita a 2ª chamada** (`call_count == 1`, `cached: true` no histórico); cada uma das 3 versões gera miss com chave própria; a chave independe da ordem dos campos |
| [tests/test_prompt_builder.py](tests/test_prompt_builder.py) | versões descobertas pelos manifestos; **cada versão gera um prompt diferente** (system e hash) com a mesma entrada; **a v1 não contém a base** nem o domínio; v2 = base + domínio + tarefa da v1 (sem arquivos duplicados); v3 = base + domínio + tarefa estruturada; o builder segue um manifesto novo sem mudar código; o hash muda ao editar papel/entrada/retry ou a composição; manifesto inválido gera erro claro |
| [tests/test_flow_summary.py](tests/test_flow_summary.py) | árvore válida passa; ciclo, saída quebrada, pergunta "X ou Y?" ou sem "?", `ref` inexistente, folha com `PROC-*`, nó inalcançável, `start` inexistente, saída com `next` e `action` juntos e profundidade > 5 falham; árvore inválida gera retry 1x; o renderizador gera sempre o mesmo texto (com texto esperado fixo) e remove o id repetido do `ref`; ponta a ponta com o fake nas 3 versões (`output` + `rendered`, CLI mostra o texto); cache hit também tem `rendered` |
| [tests/test_e2e_fake.py](tests/test_e2e_fake.py) | `generate` ponta a ponta pela CLI para os 4 tipos × 3 versões (campos do RN06, `prompt_layers`, mesmo schema de saída, arquivo em `runs/`); versão padrão `v3`; ticket em texto livre; `compare` com 3 versões (padrão) e com 2, incluindo nota e justificativa inválidas rejeitadas; `compare` com menos de 2 versões, repetidas ou inexistentes; `list` com as camadas; erros listando opções; chave ausente apontando o `.env` |
| [tests/test_validation.py](tests/test_validation.py) | enum de perfil inválido; notas inválidas (`0`, `6`, `3.5`, `"abc"`, `True`); justificativa vazia; **retry** após JSON inválido; falha dupla não grava cache nem histórico; erro do provedor não grava nada |

---

## 12. Estrutura de pastas

```
.
├── README.md                    # este arquivo
├── PROMPT_ENGINEERING_NOTES.md  # estratégias, ablação v1→v2→v3, decisões, limitações
├── CLAUDE.md                    # regras do projeto
├── pyproject.toml               # pacote + comando `support_assistant` + config do pytest
├── requirements.txt · .env.example · .gitignore
├── data/
│   ├── customers.json           # 4 perfis
│   ├── tickets.json             # vago, comuns, técnico
│   └── domains/wifi_isp.json    # base de conhecimento com IDs
├── prompts/
│   ├── base/                    # system.md, domain.md (usados conforme o manifesto); input.md, retry.md (todas)
│   ├── v1/                      # manifest.json + role.md (papel mínimo) + 4 tarefas simples
│   ├── v2/                      # só manifest.json: base + domínio + tarefas de v1/
│   └── v3/                      # manifest.json + 4 tarefas estruturadas
├── src/support_assistant/
│   ├── config.py · models.py · prompt_builder.py
│   ├── llm_client.py            # fake + Gemini (única rede)
│   ├── generators.py            # orquestração, retry, compare
│   ├── flow_render.py           # desenha a árvore do flow_summary (determinístico)
│   ├── cache.py · storage.py    # únicos que escrevem em disco
│   ├── evaluation.py            # validação da rubrica
│   ├── cli.py · __main__.py
├── scripts/                     # compare_*.py: métricas objetivas por versão
├── tests/                       # cache hit, e2e fake, validações, prompt builder, flow_summary
├── samples/                     # JSONs de exemplo
└── outputs/                     # gerado em runtime (history, cache, runs) — fora do git
```

---

## 13. Limitações

Resumo; a lista completa está em [PROMPT_ENGINEERING_NOTES.md](PROMPT_ENGINEERING_NOTES.md#6-limitações-conhecidas).

- Um único provedor real (Gemini). Outro provedor exige uma nova classe em `llm_client.py`.
- O provedor fake valida o pipeline, não a qualidade dos prompts.
- A verificação automática de adaptação ao perfil é heurística e parcial: `metrics.py` aponta
  jargão para cliente leigo e URL/IP/comando no canal telefone **só em `resolution_steps`**, por
  lista fixa de termos e expressões regulares (pode haver falso positivo e negativo). Estilo e tom
  continuam dependendo da rubrica humana.
- Histórico e cache em JSON reescritos a cada gravação: adequado para uso local, não para concorrência.
- A base de conhecimento é estática e fictícia; não há integração com sistemas reais (status, cadastro).
- Proteção contra prompt injection é básica (delimitação + instrução + sanitização das tags).
