# Tarefa: resumo do fluxo de decisão (`flow_summary`)

## Objetivo
Dar ao atendente um mapa de decisão para conduzir ESTE atendimento: quais verificações fazer,
em que ordem, e para onde cada resposta leva, até chegar a uma resolução ou a um escalonamento.
Público: atendente (uso interno).

## Regras do fluxo
1. Parta do sintoma do ticket e use apenas verificações, procedimentos e critérios da base de
   conhecimento (`known_issues`, `procedures`, `escalation`).
2. Ordem das verificações: primeiro o que bloqueia tudo ou exige escalonamento imediato
   (ex.: luz LOS vermelha → ESC-01; verificação de falha massiva no painel → ESC-03), depois
   isolamento do problema (cabo × Wi-Fi, um aparelho × todos), por último ajustes finos.
3. Pule verificações que o ticket já respondeu (ex.: se o cliente já testou via cabo, não pergunte
   de novo; use a resposta para decidir o caminho).
4. Cada ponto de decisão é uma pergunta de sim/não. Cada ramo termina em: outro ponto de decisão
   (`Ir para Dx`) ou uma ação final concreta (resolver com PROC-xx, escalar com ESC-xx).
5. Entre 3 e 7 pontos de decisão. Nada de ramos sem saída.
6. As verificações devem ser executáveis pelo cliente deste perfil e canal (ex.: não peça
   traceroute a um cliente `leigo`; no `telefone`, nada de links).

## Como escrever cada campo
- `title`: sintoma + objetivo em poucas palavras (ex.: "Wi-Fi intermitente no quarto — triagem").
- `decision_points`: ids `D1`, `D2`, ... na ordem de execução.
  - `check`: a pergunta de sim/não, curta.
  - `if_yes` / `if_no`: "Ir para Dx" ou a ação final com o id do procedimento/critério.
- `ascii_diagram`: o mesmo fluxo em ASCII, para leitura rápida. Regras:
  - Use apenas caracteres ASCII: `[ ]`, `-`, `|`, `v`, `>`, letras e números.
  - Use `\n` para quebras de linha; no máximo 60 caracteres por linha.
  - Caixas com os ids (`[D1 LOS vermelho?]`) e setas rotuladas com `sim`/`nao`.
  - Deve ser coerente com `decision_points`, sem passos extras.

## Formato de saída (JSON, exatamente estes campos)
{
  "title": "string",
  "ascii_diagram": "string",
  "decision_points": [
    {"id": "D1", "check": "string", "if_yes": "string", "if_no": "string"}
  ]
}

## Verificação antes de responder (não escreva esta verificação na saída)
- Todo ramo termina em ação final ou em outro Dx existente?
- O diagrama corresponde exatamente aos `decision_points`?
- Alguma verificação já foi respondida pelo ticket? Alguma não cabe no perfil do cliente?
- A saída é apenas o JSON?
