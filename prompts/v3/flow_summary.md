# Tarefa: árvore de decisão do atendimento (`flow_summary`)

## Objetivo
Dar ao atendente uma árvore de decisão para conduzir ESTE atendimento até uma ação final.
Público: atendente (uso interno). O diagrama é desenhado pelo sistema a partir da árvore;
você entrega só a árvore.

## Regras
1. Parta do que já se sabe. Antes de montar a árvore, veja o que o ticket e o perfil já informam.
   Não pergunte de novo o que já foi respondido: use a resposta para escolher o caminho.
2. Só perguntas de sim ou não, uma por nó. Termine com "?" e nunca use a forma "X ou Y?".
   Se a dúvida tem duas alternativas, pergunte por uma delas e deixe a outra no "não":
   em vez de "Funciona no cabo ou só no Wi-Fi?", use "Funciona no cabo de rede?".
3. Comece pela verificação mais barata e mais decisiva que ainda está em aberto (ex.: um sinal de
   escalonamento alto).
4. Cada folha é uma ação final com verbo explícito ("Escalar para outro estado").
   O id da base de conhecimento vai **só** no campo `ref`, nunca no texto de `action`.
   Procedimento (`PROC-xx`) não é folha: vira uma decisão sobre o resultado dele.
   Em vez da folha `{"action": "Reiniciar ONT e roteador", "ref": "PROC-01"}`, crie o nó
   "Reiniciar a ONT e o roteador resolveu?" com `yes` → encerrar e `no` → próxima verificação.
5. "Resolvido" leva a encerrar ("Encerrar atendimento", `ref: null`), nunca a repetir um procedimento.
6. Escalonamento para N2 só depois de esgotar as verificações de N1 para este sintoma
   (as `customer_checks` e os procedimentos da base que ainda não foram feitos).
7. Os testes precisam caber no que o cliente deste perfil consegue fazer pelo canal em uso
   (ex.: nada de traceroute para `leigo`; nada de links no `telefone`).
8. Só as decisões que o ticket ainda não responde, no máximo 5. Inclua só os ramos que mudam a ação.

## Formato de saída (JSON, exatamente estes campos)
{
  "title": "string (sintoma + objetivo, curto)",
  "start": "D1",
  "nodes": [
    {
      "id": "D1",
      "question": "string terminando em ?",
      "yes": {"next": "D2"},
      "no": {"action": "verbo + o que fazer", "ref": "id da base ou null"}
    }
  ]
}
Cada `yes`/`no` é `{"next": "<id de outro nó>"}` ou `{"action": "...", "ref": "..."}`.
