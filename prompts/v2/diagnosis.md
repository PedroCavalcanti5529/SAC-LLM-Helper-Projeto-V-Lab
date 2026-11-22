# Tarefa: diagnóstico (`diagnosis`)

## Objetivo
Dar ao atendente N1 um diagnóstico rastreável do problema: o que provavelmente está acontecendo,
com base em quê, e o que ainda falta saber para confirmar. Público: atendente (uso interno).

## Como construir cada campo

`evidence` — fatos observados, nada de interpretação.
- Cada item é um fato concreto vindo do ticket ou do perfil, com a origem entre colchetes no final:
  `[ticket]` ou `[perfil]`. Ex.: "Wi-Fi normal perto do roteador, ruim no quarto do fundo [ticket]".
- Inclua também o que o cliente já testou (ex.: reiniciou, testou via cabo), pois isso elimina hipóteses.
- Não liste como evidência algo que o cliente não disse.

`hypotheses` — de 1 a 4 causas possíveis, da mais para a menos provável.
- `cause`: a causa em uma frase curta e específica (evite "problema na internet").
- `likelihood`: `alta`, `media` ou `baixa`. No máximo uma hipótese `alta`. Se o ticket for vago,
  nenhuma hipótese deve ser `alta`.
- `rationale`: uma frase ligando a hipótese às evidências e citando o id do fato da base de
  conhecimento que a sustenta (ex.: "Sintoma bate com WIFI-01: piora com a distância.").
- Hipóteses descartadas pelas evidências não entram (ex.: se o teste via cabo deu o mesmo resultado,
  não proponha "interferência no Wi-Fi" como alta).

`missing_info` — o que falta para confirmar ou descartar as hipóteses.
- Liste só itens que mudariam a conclusão. Inclua as verificações em sistemas que só o atendente
  pode fazer (painel de status, financeiro), marcadas com "(atendente verifica)".
- Lista vazia só se o ticket já permitir uma conclusão segura.

`probable_conclusion` — 1 a 2 frases: a causa mais provável E a próxima ação recomendada
(incluindo escalonamento, citando o id `ESC-xx`, quando o critério for atendido).
Se as evidências forem insuficientes, diga isso explicitamente e indique a coleta de informações
como próxima ação, em vez de forçar uma causa.

## Adaptação ao perfil
O texto é interno, mas as ações sugeridas devem caber no perfil: para `leigo` ou canal `telefone`,
não proponha testes que exijam comandos ou acesso ao painel do roteador.

## Formato de saída (JSON, exatamente estes campos)
{
  "hypotheses": [
    {"cause": "string", "likelihood": "alta" | "media" | "baixa", "rationale": "string"}
  ],
  "evidence": ["string"],
  "missing_info": ["string"],
  "probable_conclusion": "string"
}

## Verificação antes de responder (não escreva esta verificação na saída)
- Todo fato em `evidence` está realmente no ticket/perfil?
- Toda hipótese cita um id da base de conhecimento?
- Nada foi inventado (status de rede, valores, prazos)? O que falta está em `missing_info`?
- A saída é apenas o JSON?
