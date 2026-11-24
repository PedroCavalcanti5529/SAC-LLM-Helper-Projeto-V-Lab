# samples/

Exemplos de registros JSON gerados pela aplicação.

- **`gemini_*`**: saídas reais do `gemini-3.5-flash-lite` (temperatura 0.2), mesmo perfil e ticket
  nas três versões do prompt. Mostram a **qualidade** e o efeito de cada camada.
- **`fake_*`**: provedor fake (`LLM_PROVIDER=fake`). Mostram o **formato** do histórico (RN06), não a
  qualidade: o fake devolve sempre a mesma resposta por tipo, marcada com `[FAKE]`.

## Modelo real (Gemini)

| Arquivo | Cenário | O que mostra |
|---|---|---|
| `gemini_resolution_steps_c01_t02_v1_v2_v3.json` | c01 (leiga, didática, telefone) + t02 (Wi-Fi cai no quarto) | **comparação com rubrica**: registro `kind: "comparison"` com as 3 notas e justificativas por versão. Médias 3.33 / 4.33 / 4.33. Análise na seção 5 de `PROMPT_ENGINEERING_NOTES.md`. |
| `gemini_clarifying_questions_c04_t01_v1_v2_v3.json` | c04 (leigo, direto, chat) + t01 (ticket vago) | perguntas de esclarecimento para um ticket sem detalhe nenhum |
| `gemini_flow_summary_c04_t01_v1_v2_v3.json` | c04 + t01 (ticket vago) | árvore de decisão quando quase nada é conhecido |
| `gemini_flow_summary_c02_t04_v1_v2_v3.json` | c02 (intermediário, direto, chat) + t04 (luz vermelha, já reiniciou) | árvore de decisão quando o ticket já responde quase tudo (exemplo abaixo) |

Os três arquivos sem rubrica são **exemplos de funcionamento**: uma lista com os 3 registros de
geração (v1, v2, v3), cada um no formato do `generate` (`prompt_layers`, `template_hash`,
`attempts`, `provider_retries`, `output`, `metrics` e, no `flow_summary`, `rendered`). Não têm
`evaluation`, porque não passaram pela rubrica.

### Exemplo: `flow_summary` para c02 + t04, v1 × v2 × v3

> **Ticket t04:** "A internet ficou fora o dia todo, a luz vermelha da caixinha da fibra está acesa e
> piscando. Já tirei da tomada e nada."
> **Perfil c02:** Rafael, intermediário, direto, chat.
> Pela base, LOS vermelho é critério de visita técnica (`ESC-01`), e reiniciar não resolve.

**v1** (papel mínimo + tarefa simples): precisou de **2 tentativas**. Na primeira, inventou ids que não
existem na base (`KB-FIBRA-001`, `KB-MANUTENCAO-005`…), a validação rejeitou e o retry corrigiu.
```
Fluxo de Atendimento - Luz vermelha piscando na ONT

[D1] A luz vermelha LOS da caixinha da fibra está acesa e piscando
├─ SIM → Abrir chamado técnico externo por rompimento ou perda de sinal de fibra. FIM
└─ NÃO → [D2] O cliente já reiniciou o equipamento da tomada
   ├─ SIM → Encaminhar para suporte avançado. FIM
   └─ NÃO → Orientar o cliente a reiniciar o roteador e aguardar 5 minutos. FIM
```

**v2** (base + domínio + tarefa simples):
```
Fluxo de Atendimento - Sem Internet com LED LOS Vermelho

[D1] O LED LOS da ONT está vermelho (fixo ou piscando)?
├─ SIM → [D2] O LED LOS vermelho indica sem sinal óptico, que não se resolve reiniciando. Há falha massiva registrada no painel de status interno?
│  ├─ SIM → Informar a ocorrência da falha massiva ao cliente e aguardar normalização (ESC-03). FIM
│  └─ NÃO → Agendar visita técnica no sistema com prazo de até 48 horas úteis, sem custo (POL-03) (ESC-01). FIM
└─ NÃO → Seguir para fluxos de roteador travado, Wi-Fi ou velocidade (NET-01). FIM
```

**v3** (base + domínio + tarefa estruturada):
```
Diagnóstico de perda de sinal óptico

[D1] A luz LOS da caixinha da fibra continua vermelha?
├─ SIM → Escalar para visita técnica (ESC-01). FIM
└─ NÃO → Verificar painel de status e cadastrar chamado (NET-01). FIM
```

Métricas objetivas (`metrics` de cada registro):

| | v1 | v2 | v3 |
|---|---|---|---|
| tentativas por schema | 2 (ids inventados) | 1 | 1 |
| decisões / profundidade | 2 / 2 | 2 / 2 | 1 / 1 |
| folhas com `ref` da base | 0 de 3 | 3 de 3 | 2 de 2 |
| ids citados | nenhum | `ESC-01`, `ESC-03`, `NET-01`, `POL-03` | `ESC-01`, `NET-01` |
| violações de qualidade | 2: perguntas sem "?" | 1: "X ou Y?" no D1 | 0 |

O que a ablação mostra neste caso:
- **v1 → v2 (contexto):** sem a base, a v1 inventa referências, pergunta de novo o que o ticket já
  disse ("já reiniciou?") e escala sem critério. Com a base, a v2 aplica `ESC-01` e `POL-03` (prazo
  de 48 horas úteis, que está na base) e lembra de checar falha massiva (`ESC-03`). Por outro lado,
  ela tira a condição do "sem custo", que na `POL-03` vale só quando a falha é da rede ou do
  equipamento.
- **v2 → v3 (tarefa):** a regra "parta do que o ticket já responde" da v3 corta o que já se sabe e
  deixa uma decisão só, a que ainda está em aberto. A v2 mantém uma pergunta "X ou Y?" e põe uma
  explicação dentro da pergunta do D2. Por outro lado, a v3 não lembra de checar falha massiva antes de
  agendar a visita: a árvore enxuta perdeu um passo que a v2 tinha.

Nos outros dois arquivos aparece o mesmo padrão. A v1 não cita a base. A v2 cita a base, mas
mantém perguntas "X ou Y?" (2 violações no `flow_summary` c04 + t01). A v3 abre pela verificação
mais decisiva (luz vermelha, `ESC-01`) e não tem violações.

## Provedor fake (formato)

| Arquivo | O que mostra |
|---|---|
| `fake_resolution_steps_c01_t02_v3.json` | geração normal (`cached: false`, `attempts: 1`, `prompt_layers`) |
| `fake_resolution_steps_c01_t02_v3_cache_hit.json` | mesma entrada repetida: `cached: true`, `attempts: 0`, `cached_from_run_id` |
| `fake_diagnosis_c03_t03_v3.json` | tipo `diagnosis` |
| `fake_clarifying_questions_c03_t03_v3.json` | tipo `clarifying_questions` |
| `fake_flow_summary_c03_t03_v3.json` | tipo `flow_summary`: árvore em `output` e diagrama desenhado pelo código em `rendered`, com `metrics` e `provider_retries` (formato atual) |
| `fake_compare_resolution_steps_c02_v1_v2_v3.json` | registro de comparação da ablação v1 × v2 × v3 com rubrica. Cada run mostra suas camadas (`prompt_layers`) e um `template_hash` diferente. Como as saídas fake são idênticas, as notas são iguais e o resultado é empate. |

Os samples `fake_*` de `resolution_steps`, `diagnosis`, `clarifying_questions` e da comparação, e
a comparação Gemini de `resolution_steps`, foram gerados antes das métricas e do retry do provedor,
então não têm os campos `metrics` e `provider_retries`. As métricas dessas saídas podem ser
recalculadas com `support_assistant.metrics.compute_metrics`.
