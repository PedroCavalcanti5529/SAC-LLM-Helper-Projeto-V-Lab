# samples/

Exemplos de registros JSON gerados pela CLI com `LLM_PROVIDER=fake`. Servem para mostrar o
**formato** do histórico (RN06), não a qualidade do modelo: o provedor fake devolve sempre a mesma
resposta por tipo, marcada com `[FAKE]`.

| Arquivo | O que mostra |
|---|---|
| `fake_resolution_steps_c01_t02_v2.json` | geração normal (`cached: false`, `attempts: 1`) |
| `fake_resolution_steps_c01_t02_v2_cache_hit.json` | mesma entrada repetida: `cached: true`, `attempts: 0`, `cached_from_run_id` |
| `fake_diagnosis_c03_t03_v2.json` | tipo `diagnosis` |
| `fake_clarifying_questions_c03_t03_v2.json` | tipo `clarifying_questions` |
| `fake_flow_summary_c03_t03_v2.json` | tipo `flow_summary` (ASCII + pontos de decisão) |
| `fake_compare_resolution_steps_c02_v1_vs_v2.json` | registro de comparação com rubrica. Como as saídas fake são idênticas, as notas são iguais e o resultado é empate. |

O campo `run_path` aponta para o diretório temporário onde os exemplos foram gerados.

A comparação v1 × v2 com um modelo real fica em `samples/` com o prefixo `gemini_` depois de
rodar `compare` com `LLM_PROVIDER=gemini` (ver `PROMPT_ENGINEERING_NOTES.md`).
