# Tarefa: perguntas de esclarecimento (`clarifying_questions`)

## Objetivo
Gerar o menor conjunto de perguntas que o atendente deve fazer ao cliente para conseguir
diagnosticar o problema. Cada pergunta precisa ter um motivo: se a resposta não muda o próximo
passo, a pergunta não entra. Público: o cliente (as perguntas serão repassadas como estão).

## Processo
1. Em `already_known`, liste o que o ticket e o perfil já informam (sintoma, onde ocorre, desde
   quando, o que já foi testado, plano). Isso evita perguntar o que o cliente já disse.
2. Identifique as hipóteses possíveis com base nos `known_issues` da base de conhecimento.
3. Escolha as perguntas que mais separam essas hipóteses. Priorize nesta ordem:
   a) sinais de critério de escalonamento ou de segurança (ex.: luz LOS vermelha → ESC-01);
   b) escopo do problema (todos os aparelhos? só no Wi-Fi ou também no cabo? só em um cômodo?);
   c) quando começou e se é constante ou intermitente;
   d) detalhes finos (velocidade medida, mensagens de erro).
4. Quantidade: só as necessárias, no máximo 5. Ticket detalhado pode ter 1–2 perguntas; ticket
   claro e completo pode ter lista vazia. Ticket vago normalmente pede 3–5.

## Como escrever cada pergunta
- `priority`: inteiro começando em 1 (mais importante), sem repetir.
- `question`: uma única pergunta por item (não junte duas perguntas com "e"), fácil de responder
  (sim/não, escolha entre opções ou um dado simples).
  - `leigo`: refira-se ao que a pessoa vê ("a luzinha vermelha da caixinha da fibra está acesa?"). Sem siglas.
  - `avancado`: pode pedir dados técnicos (resultado de ping, traceroute, teste via cabo).
  - `telefone`: frases curtas faladas, sem pedir para acessar links ou digitar comandos.
  - `chat`: curtas, informais-cordiais. `email`: completas e educadas.
  - Nunca peça senha, dados de cartão ou documento (POL-01).
- `purpose`: nota interna curta dizendo qual hipótese a resposta confirma/descarta, citando o id
  da base quando aplicável (ex.: "Se sim, ESC-01: visita técnica").

## Formato de saída (JSON, exatamente estes campos)
{
  "already_known": ["string"],
  "questions": [
    {"priority": 1, "question": "string", "purpose": "string"}
  ]
}

## Verificação antes de responder (não escreva esta verificação na saída)
- Alguma pergunta pede algo que já está em `already_known`? Remova.
- Toda pergunta muda o próximo passo? As que não mudam saíram?
- Linguagem adequada ao nível técnico e ao canal?
- A saída é apenas o JSON?
