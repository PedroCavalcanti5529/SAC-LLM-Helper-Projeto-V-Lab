# samples/

Exemplos de registros JSON gerados pela CLI. Os arquivos `fake_*` vêm de `LLM_PROVIDER=fake` e
mostram o **formato** do histórico (RN06), não a qualidade do modelo: o provedor fake devolve sempre
a mesma resposta por tipo, marcada com `[FAKE]`. O arquivo `gemini_*` é uma comparação com modelo real.

| Arquivo | O que mostra |
|---|---|
| `gemini_resolution_steps_c01_t02_v1_v2_v3.json` | **comparação com modelo real** (`gemini-3.5-flash-lite`): ablação v1 × v2 × v3 de `resolution_steps` para c01 (leiga, telefone) + t02, com as 3 notas e justificativas por versão. Médias 3.33 / 4.33 / 4.33, empate entre v2 e v3. Análise na seção 5 de `PROMPT_ENGINEERING_NOTES.md`. |
| `fake_resolution_steps_c01_t02_v3.json` | geração normal (`cached: false`, `attempts: 1`, `prompt_layers`) |
| `fake_resolution_steps_c01_t02_v3_cache_hit.json` | mesma entrada repetida: `cached: true`, `attempts: 0`, `cached_from_run_id` |
| `fake_diagnosis_c03_t03_v3.json` | tipo `diagnosis` |
| `fake_clarifying_questions_c03_t03_v3.json` | tipo `clarifying_questions` |
| `fake_flow_summary_c03_t03_v3.json` | tipo `flow_summary`: árvore em `output` e diagrama desenhado pelo código em `rendered`, com `metrics` e `provider_retries` (formato atual) |
| `fake_compare_resolution_steps_c02_v1_v2_v3.json` | registro de comparação da ablação v1 × v2 × v3 com rubrica. Cada run mostra suas camadas (`prompt_layers`) e um `template_hash` diferente. Como as saídas fake são idênticas, as notas são iguais e o resultado é empate. |

Os samples `fake_*` de `resolution_steps`, `diagnosis`, `clarifying_questions` e da comparação
foram gerados antes das métricas e do retry do provedor, então não têm os campos `metrics` e
`provider_retries`. A comparação Gemini também é anterior e não tem `metrics`; as métricas dessas
saídas podem ser recalculadas com `support_assistant.metrics.compute_metrics`.
