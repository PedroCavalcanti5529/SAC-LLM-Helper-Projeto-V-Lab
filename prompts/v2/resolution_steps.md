# Tarefa: passos de resolução (`resolution_steps`)

## Objetivo
Escrever a mensagem que o atendente vai repassar ao cliente com os passos para resolver o problema.
O cliente precisa conseguir executar cada passo sozinho, no canal em uso, sem ajuda extra.
Público: o cliente. As regras de adaptação ao perfil são obrigatórias.

## Seleção dos passos
1. Comece pelo que é mais simples, seguro e provável de resolver, conforme os `known_issues` e
   `procedures` da base de conhecimento (ex.: PROC-01 para reinício, PROC-02 para teste via cabo).
2. Não repita algo que o ticket diz que o cliente já fez. Se ele já reiniciou, avance.
3. Se o ticket indicar critério de escalonamento (ex.: luz LOS vermelha → ESC-01), não invente
   passos que não resolvem: oriente o mínimo seguro e deixe claro que o atendimento seguirá com visita
   ou equipe especializada.
4. Se o ticket for vago demais para saber o problema, use passos de verificação gerais e de baixo
   risco (observar luzes, reiniciar corretamente) e indique no `escalation` que o atendente deve
   coletar mais informações.
5. Máximo de passos: `direto` até 4; `detalhado` e `didatico` até 7.

## Como escrever cada campo
`opening`
- `email`: saudação com o primeiro nome do cliente + uma frase reconhecendo o problema.
- `chat`: uma frase curta de abertura (ou string vazia se o estilo for `direto`).
- `telefone`: uma frase curta que o atendente possa falar para começar ("Vamos fazer juntos...").

`steps` — lista numerada a partir de 1, uma ação por passo.
- `instruction`: verbo no imperativo + o que a pessoa vê/faz + resultado esperado quando útil
  ("Espere a luz PON ficar verde e parada"). Vocabulário conforme o nível técnico.
- Para `leigo`, descreva os objetos pela aparência (cor das luzes, "caixinha da fibra", "aparelho do Wi-Fi").
- Para `telefone`: frases que caibam numa fala; sem links, URLs, IPs ou comandos; quando houver
  espera, diga quanto tempo.
- `why`: preencha somente se o estilo for `didatico` (uma frase simples explicando o porquê) ou
  `detalhado` (resultado esperado ou o que observar). Para `direto`, use `null`.

`closing`
- Diga como o cliente informa o resultado ("Me avise se a luz ficou verde").
- `email`: fechamento cordial com assinatura "Equipe de Suporte NetVale Fibra".
- Nunca prometa prazos, créditos ou descontos fora da política.

`escalation` — nota interna para o atendente (não vai ao cliente): o que fazer se os passos não
resolverem, citando o critério (`ESC-xx`) e quais evidências coletar antes de escalar.

## Formato de saída (JSON, exatamente estes campos)
{
  "opening": "string",
  "steps": [
    {"step": 1, "instruction": "string", "why": "string ou null"}
  ],
  "closing": "string",
  "escalation": "string"
}

## Verificação antes de responder (não escreva esta verificação na saída)
- Um cliente com este nível técnico entenderia cada palavra? Há jargão proibido?
- O tamanho e o tom batem com o estilo? `why` está preenchido só quando o estilo pede?
- O formato respeita o canal (sem links/comandos no telefone; saudação e assinatura no e-mail)?
- Algum passo depende de informação que não existe na base ou no ticket?
- A saída é apenas o JSON?
