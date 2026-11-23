# Arquitetura e referência técnica
 
Referência detalhada do código. A visão geral, os resultados e as decisões estão no [README](../README.md).
 
## Sumário
 
1. [Módulos](#1-módulos)
2. [Cache](#2-cache)
3. [Persistência e formato do histórico](#3-persistência-e-formato-do-histórico)
4. [Tratamento de erros](#4-tratamento-de-erros)
5. [Testes](#5-testes)
---
 
## 1. Módulos

Todos em [src/support_assistant/](../src/support_assistant/).

### [config.py](../src/support_assistant/config.py): configuração
- Define os caminhos do projeto (`data/`, `prompts/`, `outputs/`).
- `load_settings()` carrega o `.env` com `python-dotenv` (sem sobrescrever variáveis já
  definidas), valida provedor e temperatura e devolve um `Settings` imutável.
- `Settings.generation_config` reúne os parâmetros que afetam a saída (temperatura, max tokens),
  que entram na chave de cache.
- Com o provedor `fake`, o modelo é sempre `fake-model-v1` e nenhuma chave é lida.

### [models.py](../src/support_assistant/models.py): entradas e schemas de saída
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

  As regras de **qualidade** ficam em [metrics.py](../src/support_assistant/metrics.py) e não
  rejeitam a árvore: `question_not_yes_no` (pergunta sem "?" ou na forma "X ou Y?") e
  `procedure_leaf` (folha com `ref` `PROC-*`). Vão para o campo `violations` do registro e a CLI as
  mostra como "Avisos de qualidade". A dica de como reestruturar está só no prompt da v3.

  Strings obrigatórias não podem ser vazias. Campos extras são ignorados.

### [prompt_builder.py](../src/support_assistant/prompt_builder.py): montagem do prompt
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

### [flow_render.py](../src/support_assistant/flow_render.py): desenho do `flow_summary`
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

### [llm_client.py](../src/support_assistant/llm_client.py): provedores de LLM
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
  traz `Retry-After`, espera exatamente esse tempo; acima de 15 s (ex.: cota diária) desiste na hora.
  400/401/403/404 nunca são repetidos. Esgotadas as tentativas, a mensagem amigável acima é mostrada e
  nada vai para cache nem histórico. Cada repetição gera um aviso `[WARNING] support_assistant.llm_client: …`.
  O registro grava `provider_retries` (repetições do provedor), separado de `attempts` (tentativas
  por schema); nenhum dos dois entra na chave de cache.
- Transporte HTTP e função de espera são injetáveis (`transport=`, `sleep=`), para os testes
  simularem falhas sem rede e sem esperar.
- **`create_client(settings)`** escolhe o provedor. Sem chave, a mensagem aponta para o `.env`.

### [generators.py](../src/support_assistant/generators.py): orquestração
- **`Generator.generate()`** executa o fluxo descrito no README: valida, monta o prompt, calcula a
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

### [cache.py](../src/support_assistant/cache.py): cache
- `make_cache_key(fields)` faz `json.dumps(sort_keys=True, separators=(",", ":"))` e depois SHA-256.
  A chave é determinística e não depende da ordem dos campos.
- `JsonCache.get/set` sobre `outputs/cache.json`. Detalhes na [seção 2](#2-cache).

### [storage.py](../src/support_assistant/storage.py): persistência
- `atomic_write_json()` escreve num arquivo temporário e renomeia (`os.replace`), para não
  corromper o JSON se o processo cair no meio da escrita.
- `Storage.save_run()` / `save_comparison()` acrescentam o registro em `history.json` e também
  gravam `runs/<id>.json`, cujo caminho é mostrado na CLI.
- `Storage.log_failure()` grava respostas inválidas em `failures.json`.

### [evaluation.py](../src/support_assistant/evaluation.py): rubrica
- `RUBRIC_CRITERIA`: `clarity`, `customer_fit`, `actionability`, com a descrição de cada um.
- `validate_score()` aceita só inteiros de 1 a 5 (rejeita `0`, `6`, `3.5`, `"abc"`, `True`).
- `validate_justification()` rejeita texto vazio.
- `build_evaluation()` monta `{criterio: {score, justification}, average, evaluated_by: "human"}`.
- `pick_winner()` devolve a versão com maior média, ou `None` em caso de empate.
- O módulo **não gera notas**: quem avalia é a pessoa.

### [metrics.py](../src/support_assistant/metrics.py): métricas objetivas
- `compute_metrics(tipo, saída, perfil)` calcula números por tipo (ex.: passos, palavras por passo,
  ids da base citados, perguntas, profundidade da árvore) e uma lista de `violations` que dependem
  do perfil: jargão para `leigo`, URL/IP/comando no `telefone`, passo em forma de pergunta, regras
  de qualidade do `flow_summary`.
- Roda em toda geração (inclusive em cache hit) e vai para o campo `metrics` do registro. É aviso,
  nunca rejeita a saída, e complementa a rubrica humana sem substituí-la.

### [cli.py](../src/support_assistant/cli.py): interface
- `argparse` com os subcomandos `list`, `generate` e `compare`.
- Resolve perfil e ticket por id (ou texto livre). Ids inexistentes geram erro com as opções válidas.
- `render_output()` formata cada tipo de forma legível no terminal. O JSON completo fica no arquivo.
  O cabeçalho de cada saída mostra as camadas usadas pela versão. Para `flow_summary`, exibe o
  texto de `rendered`.
- `collect_rubric()` faz as perguntas da rubrica e repete a pergunta quando a entrada é inválida.
- `main()` captura os erros conhecidos e imprime `Erro: <mensagem>` com exit code 1, sem stack
  trace. `Ctrl+C` sai com 130. `--verbose` liga logs de depuração.

### [\_\_main\_\_.py](../src/support_assistant/__main__.py)
Permite `python -m support_assistant ...`.

 
## 2. Cache

- **Chave**: SHA-256 de um JSON com chaves ordenadas contendo
  `customer` (perfil completo), `ticket` (texto), `content_type`, `prompt_version`,
  `template_hash`, `provider`, `model` e `config` (temperatura e max tokens).
- **Hit**: não chama a API. O registro vai para o histórico com `cached: true`, `attempts: 0` e
  `cached_from_run_id` apontando para a execução original.
- **Invalidação**: automática. Qualquer mudança em perfil, ticket, template, modelo ou config gera
  outra chave.
- **Arquivo**: `outputs/cache.json` (`{chave: {output, run_id, created_at}}`). Para limpar,
  apague o arquivo.
- O teste [tests/test_cache.py](../tests/test_cache.py) prova que duas gerações iguais fazem
  **1 chamada** ao LLM.

---
 
## 3. Persistência e formato do histórico

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

Exemplos reais estão em [samples/](../samples/).

 
## 4. Tratamento de erros

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
 
## 5. Testes

```bash
pytest -q
```

Todos os testes rodam com o provedor **fake**. Uma fixture força `LLM_PROVIDER=fake` e usa um
diretório temporário, mesmo que exista um `.env` configurado com o Gemini.

| Arquivo | O que prova |
|---|---|
| [tests/test_cache.py](../tests/test_cache.py) | **cache hit evita a 2ª chamada** (`call_count == 1`, `cached: true` no histórico); cada uma das 3 versões gera miss com chave própria; a chave independe da ordem dos campos |
| [tests/test_prompt_builder.py](../tests/test_prompt_builder.py) | versões descobertas pelos manifestos; **cada versão gera um prompt diferente** (system e hash) com a mesma entrada; **a v1 não contém a base** nem o domínio; v2 = base + domínio + tarefa da v1 (sem arquivos duplicados); v3 = base + domínio + tarefa estruturada; o builder segue um manifesto novo sem mudar código; o hash muda ao editar papel/entrada/retry ou a composição; manifesto inválido gera erro claro |
| [tests/test_flow_summary.py](../tests/test_flow_summary.py) | árvore válida passa; ciclo, saída quebrada, `ref` inexistente, nó inalcançável, `start` inexistente, saída com `next` e `action` juntos e profundidade > 5 falham; pergunta "X ou Y?" ou sem "?" e folha com `PROC-*` **não** falham, viram violações (`question_not_yes_no`, `procedure_leaf`); árvore inválida gera retry 1x; o renderizador gera sempre o mesmo texto (com texto esperado fixo) e remove o id repetido do `ref`; ponta a ponta com o fake nas 3 versões (`output` + `rendered`, CLI mostra o texto); cache hit também tem `rendered` |
| [tests/test_e2e_fake.py](../tests/test_e2e_fake.py) | `generate` ponta a ponta pela CLI para os 4 tipos × 3 versões (campos do RN06, `prompt_layers`, mesmo schema de saída, arquivo em `runs/`); versão padrão `v3`; ticket em texto livre; `compare` com 3 versões (padrão) e com 2, incluindo nota e justificativa inválidas rejeitadas; `compare` com menos de 2 versões, repetidas ou inexistentes; `list` com as camadas; erros listando opções; chave ausente apontando o `.env` |
| [tests/test_validation.py](../tests/test_validation.py) | enum de perfil inválido; notas inválidas (`0`, `6`, `3.5`, `"abc"`, `True`); justificativa vazia; **retry** após JSON inválido; falha dupla não grava cache nem histórico; erro do provedor não grava nada |
| [tests/test_metrics.py](../tests/test_metrics.py) | métricas objetivas dos 4 tipos; jargão é violação só para `leigo`, URL e comando só no `telefone`; passo terminado em "?" é detectado; a nota de escalonamento (interna) não é checada; regras de qualidade do `flow_summary` viram violações; falha no cálculo das métricas não derruba a geração; o registro de comparação guarda `metrics` e `evaluation` |
| [tests/test_provider_retry.py](../tests/test_provider_retry.py) | 503 duas vezes e depois sucesso; 429 respeita `Retry-After` e desiste se ele for longo demais; 400/401/403/404 não são repetidos (401 aponta o `.env`); timeout e erro de conexão são repetidos; tentativas esgotadas dão erro amigável e não gravam nada; `provider_retries` fica fora da chave de cache; configuração de retry inválida é rejeitada |
| [tests/test_public_mode.py](../tests/test_public_mode.py) | `APP_PUBLIC_MODE=true` força o fake e ignora a chave do ambiente; valor inválido é rejeitado; provedor por sessão com chave colada; a chave nunca aparece no `repr` |
| [tests/test_streamlit_app.py](../tests/test_streamlit_app.py) | interface web (`AppTest`, pulado sem o extra `web`): abre e gera; ticket vazio mostra erro amigável; comparação às cegas só revela as versões depois de gravar; rubrica incompleta é rejeitada; Gemini sem chave não chama nada; **a chave colada é usada mas nunca gravada em disco**; histórico lista os registros |
 