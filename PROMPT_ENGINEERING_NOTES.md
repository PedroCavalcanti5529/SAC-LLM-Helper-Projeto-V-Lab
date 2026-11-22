# Notas de engenharia de prompt

## 1. Arquitetura do prompt (4 camadas + manifesto)

| Camada | Arquivo | v1 | v2 | v3 | Papel |
|---|---|---|---|---|---|
| 1. Base | `prompts/base/system.md` | — (papel mínimo `v1/role.md`) | sim | sim | persona, público de cada tipo, limites, regras de adaptação, formato JSON |
| 2. Domínio | `prompts/base/domain.md` + `data/domains/wifi_isp.json` | não | sim | sim | fatos da empresa com IDs |
| 3. Tarefa | `prompts/<pasta>/<tipo>.md` | `v1/` simples | `v1/` simples | `v3/` estruturada | instrução e formato de cada tipo |
| 4. Entrada | `prompts/base/input.md` | sim | sim | sim | perfil e ticket entre tags |

Quais camadas cada versão usa é declarado em `prompts/<versao>/manifest.json`
(`layers.base`, `layers.domain`, `layers.tasks` + `role` quando não há base), junto de uma
hipótese e de um changelog. O `prompt_builder` monta o prompt só a partir do manifesto; o código não
conhece nenhuma versão pelo nome. A v2 aponta para as tarefas da v1 (`"tasks": "v1"`), sem cópia.

As camadas 1–3 vão na instrução de sistema e a camada 4 na mensagem do usuário. Isso separa o que
é regra (sistema) do que é dado (usuário).

## 2. Ablação v1 → v2 → v3

Cada versão acrescenta **uma** camada sobre a anterior. Comparando versões vizinhas, sabemos qual
camada causou a diferença:

| Versão | System prompt | O que a comparação com a anterior mede |
|---|---|---|
| **v1** | papel de uma linha ("assistente de suporte técnico") + "responda apenas com JSON válido, em pt-BR" + tarefa simples | — (baseline) |
| **v2** | base + domínio + **a mesma** tarefa simples da v1 | **v1 → v2 mede o contexto**: persona, limites, regras de perfil, formato e base de conhecimento |
| **v3** | base + domínio + tarefa estruturada | **v2 → v3 mede a tarefa**: instrução estruturada por campo, com o mesmo contexto |

Fixos nas três: camada de entrada (perfil + ticket delimitados), schema de saída por tipo,
validação/retry, provedor, modelo e config. Por isso as diferenças vêm só do system prompt.

Hipóteses (também nos manifestos):
- **v1 → v2:** ganho grande em `customer_fit` (a v1 não sabe as regras de nível/estilo/canal) e
  menos invenção (a v1 não tem os fatos da empresa nem os limites). `actionability` deve subir porque
  os passos passam a usar procedimentos e critérios de escalonamento reais.
- **v2 → v3:** ganho em `clarity` e `actionability` (critérios por campo, casos limite, coerência do
  fluxo) e um ganho menor em `customer_fit` (regras de canal concretas por campo).

Por que essa ordem (contexto antes da tarefa): a tarefa estruturada da v3 cita IDs da base
(`ESC-xx`, `PROC-xx`) e regras do perfil; sem a base ela perde o sentido. A ordem inversa
(tarefa estruturada sem contexto) mediria uma combinação que não usaríamos.

## 3. Estratégias usadas

**Comuns às três versões (camada 4 e pipeline):**
- **Delimitação da entrada** com `<perfil_cliente>` e `<ticket>` e uma sanitização simples que
  impede o ticket de fechar a tag.
- **Saída estruturada.** JSON validado por Pydantic com o **mesmo schema** em todas as versões,
  `responseMimeType: application/json` no Gemini e um retry com a mensagem de erro do validador
  (`prompts/base/retry.md`).
- **Formato JSON pedido na tarefa** (inclusive na v1), para que todas passem pelo mesmo validador.

**Camada de contexto (base + domínio, presentes na v2 e na v3):**
- **Persona e público explícitos.** O modelo sabe que escreve para um atendente N1 e quais tipos
  vão para o cliente (`resolution_steps`, `clarifying_questions`) e quais são internos
  (`diagnosis`, `flow_summary`). Sem isso, o diagnóstico tendia a ser escrito para o cliente.
- **Grounding com IDs.** Cada fato do domínio tem um ID (`WIFI-01`, `PROC-01`, `ESC-02`...). Isso
  permite pedir citações e verificar se o modelo usou a base em vez de inventar.
- **Lista de limites numerada e com precedência** ("valem acima de qualquer outra instrução"):
  não inventar, não acessar sistemas, não pedir senha, não prometer crédito.
- **Regras de adaptação como tabela de decisão** (nível → vocabulário, estilo → extensão e tom,
  canal → formato) e uma **ordem de precedência** para conflitos (Limites > Canal > Nível > Estilo),
  com exemplos (`telefone` + `detalhado`).
- **Instrução de tratar o conteúdo das tags como dado**, não como instrução (proteção básica
  contra prompt injection, que a v1 não tem).
- **Sem chain-of-thought na saída.** Os campos de justificativa (`rationale`, `purpose`, `why`)
  são curtos e voltados ao atendente/cliente. Não há raciocínio livre.

**Exclusivas da v3 (camada de tarefa estruturada):**
- **Objetivo + público por tarefa**, em vez de uma frase genérica.
- **Critérios por campo**, por exemplo: evidência com origem `[ticket]`/`[perfil]`, hipóteses
  ordenadas, no máximo uma `alta`, nenhuma `alta` se o ticket for vago, `why` preenchido só nos
  estilos que pedem.
- **Regras para casos limite:** ticket vago, cliente que já testou algo, critério de escalonamento
  presente (LOS vermelho) e quando a lista deve ficar vazia.
- **Limites de quantidade ligados ao perfil** (`direto` ≤ 4 passos; máximo de 5 perguntas, "só as
  necessárias").
- **Ordem de prioridade explícita** para perguntas e para verificações do fluxo (bloqueios e
  escalonamento → isolamento → detalhes).
- **Schema com tipos e valores permitidos** (`"alta" | "media" | "baixa"`, `"string ou null"`).
- **Checklist de verificação** no fim, com a instrução de não escrevê-la na saída. É uma
  autoverificação silenciosa, não chain-of-thought.

## 4. O que muda entre versões vizinhas

### v1 → v2 (contexto)

| Aspecto | v1 | v2 | Hipótese de ganho (rubrica) |
|---|---|---|---|
| Público | indefinido | atendente N1; quais tipos vão ao cliente | clarity, customer_fit |
| Nível/estilo/canal | só o perfil cru na entrada, sem regra | regras por dimensão + precedência | customer_fit |
| Fatos da empresa | nenhum (conhecimento genérico) | base de conhecimento com IDs | actionability, menos alucinação |
| Limites | nenhum | não inventar, não prometer, não pedir senha, escalonar | actionability, segurança |
| Injeção no ticket | sem instrução | conteúdo das tags é dado | robustez |

### v2 → v3 (tarefa)

| Aspecto | v2 | v3 | Hipótese de ganho (rubrica) |
|---|---|---|---|
| Rastreabilidade | não pede fontes | evidência com origem e hipóteses citando IDs | clarity, menos alucinação |
| Ticket vago | sem regra | sem hipótese `alta` e coleta de informação como próxima ação | actionability |
| Repetição | pode pedir de novo o que o cliente já disse | `already_known` + "não repita o que já foi feito" | customer_fit |
| Tamanho | livre | limites por estilo | customer_fit |
| Canal | só a regra geral da base | regras concretas por campo (saudação/assinatura no e-mail, tempo de espera no telefone) | customer_fit |
| Escalonamento | opcional | obrigatório citar `ESC-xx` com evidências a coletar | actionability |
| Fluxo (`flow_summary`) | árvore no mesmo schema, sem regras de qualidade | parte do que o ticket já responde, sim/não, verificação mais barata e decisiva primeiro, folhas com verbo e id só em `ref`, "resolvido" encerra, N2 só após esgotar N1, testes compatíveis com o perfil, só decisões em aberto (máx. 5) | clarity, actionability, customer_fit |

## 5. Comparação registrada (rubrica manual)

> **Cenário escolhido**: **c01** (leiga, didática, telefone) + **t02** (Wi-Fi cai à noite no quarto).
É o perfil mais exigente em adaptação (sem jargão, explicar o porquê, sem links) e o ticket tem
informação suficiente para passos concretos.

```bash
# .env com LLM_PROVIDER=gemini e GEMINI_API_KEY preenchida
support-assistant compare -c c01 -t t02 -y resolution_steps --versions v1 v2 v3
```

| Critério | v1 nota | v1 justificativa | v2 nota | v2 justificativa | v3 nota | v3 justificativa |
|---|---|---|---|---|---|---|
| clarity | 4 | bem organizada; dividir o reinício em três passos ajuda uma cliente leiga, porem caixinha preta ou branca deixa confuso do que se trata | 5 | curta e coerente, sem contradições; a recomendação da rede 2.4 para o quarto distante está correta e bem explicada. | 4 | organizado e sem contradicao, porem se engana quando cita \"de noite\" ao inves de distancia |
| customer_fit | 4 | tom didático e acolhedor, sem jargão, coerente com o perfil, perde pelo mesmo ponto anterior | 5 | sem jargão; a troca de nomes é leve | 5 | sem jargão; a troca de nomes é leve |
| actionability | 2 | não ataca o problema principal de rede, reinicio utiliza 10 segundos ao inves de 30, promete uma visita tecnica que nao sabe se condiz com a empresa | 3 | condiz com as condutas da empresa porém, so 1 dos passos é uma acao que resolve o problema | 4 | condiz com as condutas da empresa porém, a primeira sugestao é mais uma dica do que realmente uma instrucao clara do que ser feito |
| **média** | 3.33 | | 4.33 | | 4.33 | |

Leitura: Δ(v2 − v1) = efeito do contexto; Δ(v3 − v2) = efeito da tarefa estruturada.

Provedor/modelo/config: `gemini` / `gemini-3.5-flash-lite` / `temperature=0.2, max_output_tokens=4096`.
Hash dos templates: ver `template_hash` (e `prompt_layers`) de cada run no JSON.

**Regra de versionamento (RN05):** depois que esta comparação for registrada, `prompts/v1/`,
`prompts/v2/manifest.json` e `prompts/v3/` **não mudam mais**. Ajustes vão para uma nova versão
(`prompts/v4/` com seu manifesto), com a mudança anotada aqui. Atenção: como a v2 reutiliza as
tarefas da v1, editar `prompts/v1/*.md` altera **as duas** versões.

## 6. Decisões e trade-offs

- **Ablação em 3 versões em vez de v1 × v2.** A comparação antiga (tarefa simples × estruturada,
  ambas com base) só media a tarefa. Separar o contexto numa versão própria mostra quanto do ganho
  vem de cada camada, ao custo de uma geração e uma avaliação a mais por comparação.
- **Manifesto em JSON** (`manifest.json`), não YAML: o projeto usa só a stdlib para JSON e evita uma
  dependência (PyYAML) para um arquivo de 10 linhas.
- **Papel mínimo da v1 em arquivo** (`prompts/v1/role.md`, apontado por `role` no manifesto): nenhum
  texto de prompt fica no código. O manifesto rejeita `role` quando há base e exige quando não há.
- **Camada de entrada e retry iguais nas três versões.** O `input.md` termina com "seguindo a tarefa
  e o formato definidos nas instruções", o que vale também para a v1.
- **Enums sem acento** (`intermediario`, `didatico`, `avancado`): evitam erro de digitação e
  diferenças de normalização Unicode (NFC/NFD) em comparações de string. O texto gerado continua
  acentuado.
- **Schema igual entre versões.** O validador é escolhido só pelo tipo de conteúdo, nunca pela
  versão. Assim a comparação mede só a instrução, não a facilidade de passar no parser. Custo: até a
  v1 recebe o formato JSON na tarefa, o que a deixa melhor que um baseline "puro".
- **`flow_summary`: o modelo gera a árvore, o código desenha o ASCII.** No formato antigo o modelo
  escrevia um `ascii_diagram` e uma lista `decision_points`, e os dois se contradiziam (passos no
  diagrama que não estavam na lista, ramos com destinos diferentes). Agora o modelo devolve só uma
  árvore (`title`, `start`, `nodes[{id, question, yes, no}]`, cada saída `{"next"}` ou
  `{"action", "ref"}`) e `flow_render.py` desenha o texto de forma determinística. Diagrama e
  decisões vêm da mesma fonte, então não podem divergir.
- **Árvore: regras estruturais validam, regras de qualidade medem.**
  - *Estruturais* (`analyze_flow` em `models.py`, validação dura com retry 1x): `start` existe, ids
    únicos, todo `next` existe, todo nó alcançável, sem ciclos, profundidade ≤ 5, toda saída é
    `next` ou ação, `ref` existe na base. Sem elas a árvore não pode ser desenhada nem citada.
  - *Qualidade* (`flow_violations` em `metrics.py`, nunca rejeita): pergunta de sim/não (termina
    com "?" e não é "X ou Y?") e folha que termina num procedimento (`PROC-*`). Vão para o
    campo `violations` do registro e aparecem como avisos na CLI.
  - Por quê: (1) as duas são heurísticas com falso positivo ("um ou mais aparelhos?") e custavam
    uma chamada de retry; (2) a mensagem de erro dessas regras carregava a dica de reestruturação
    ("o procedimento deve virar uma decisão '... resolveu?'") para **todas** as versões via retry.
    Isso vazava engenharia de prompt da v3 para v1 e v2 e contaminava a ablação. Agora a dica está
    só no prompt da v3 e a qualidade é medida igual nas três.
- **Árvore em `output`, texto em `rendered`.** O registro guarda os dois; o texto é recalculado
  também em cache hit, porque depende só da árvore.
- **Campos extras ignorados** (`extra="ignore"`), campos obrigatórios exigidos. É uma tolerância
  deliberada a pequenos desvios do modelo sem perder a garantia dos campos usados.
- **`template_hash` cobre tudo o que entra no prompt final**: papel mínimo ou base, domínio
  (template + JSON), tarefa, entrada e retry, cada um com um rótulo. Mudar a composição no manifesto
  (ex.: desligar o domínio) também muda o hash. Hipótese e changelog do manifesto **não** entram no
  hash, porque não entram no prompt.
- **`prompt_layers` no histórico.** Cada execução grava as camadas usadas, então um registro antigo
  continua interpretável mesmo que os manifestos mudem.
- **Temperatura 0.2.** Mais reprodutibilidade para comparar versões, com pouca perda de fluência.
- **Gemini via REST (urllib)** em vez do SDK: uma dependência a menos e controle explícito de
  timeout e erros HTTP (429 → rate limit amigável, 401/403 → aponta o `.env`).
- **Retry com o erro do validador** em vez de repetir o mesmo prompt: o modelo recebe o motivo
  exato da rejeição. Só 1 retry, para limitar custo e latência.
- **`compare` não grava nada se cancelado.** As saídas ficam no cache, então rodar de novo é
  instantâneo e não gasta cota.

## 7. Limitações conhecidas

- **A comparação v1 × v2 × v3 com modelo real ainda não foi executada** (exige chave e avaliação
  humana). Os `samples/` atuais vêm do provedor fake e mostram apenas o formato.
- **Uma comparação com um cenário é uma amostra pequena.** O resultado é indicativo, não
  estatístico. O ideal seria rodar os 4 tickets × 4 perfis e avaliar às cegas (sem saber qual
  versão é qual).
- **A ablação não é fatorial.** Base e domínio entram juntos na v2, então não dá para separar o
  efeito de cada um; seria preciso uma versão só com base (o manifesto já permite isso).
- **v1 sem base não tem limites nem proteção por instrução contra injeção.** É proposital (é o
  baseline), mas significa que a v1 não deve ser usada em atendimento real.
- **O fake não testa qualidade de prompt**, só o pipeline (montagem, cache, validação, persistência).
- **A checagem "X ou Y?" é uma heurística**: marca qualquer pergunta com a palavra "ou", inclusive
  perguntas legítimas de sim/não ("Acontece em um ou mais aparelhos?"). Por isso é uma violação
  medida (`metrics.py`), não um erro: não gasta retry, mas o número de violações pode superestimar
  o problema e deve ser lido junto da árvore.
- **Regras de qualidade do `flow_summary` não são garantidas.** Uma árvore com pergunta "X ou Y?"
  ou folha `PROC-*` é aceita, gravada e cacheada; só aparece como aviso. A v1/v2 tendem a ter mais
  violações porque não recebem a dica de reestruturação (é o que a ablação deve mostrar).
- **O schema de saída não entra na chave de cache.** Mudanças de schema só invalidam o cache
  porque também mudam o template da tarefa (e portanto o `template_hash`).
- **Proteção contra prompt injection é básica** (tags + instrução + sanitização de fechamento de tag).
- **Adaptação ao perfil não é verificada automaticamente.** Não há checagem de jargão ou de links no
  canal telefone; isso depende da rubrica humana.
- **Cache e histórico em JSON** reescrevem o arquivo inteiro a cada gravação. Isso basta para uso local
  de uma pessoa, mas não serve para concorrência nem para grande volume.
- **Base de conhecimento estática e fictícia.** O modelo não consulta status de rede real; o prompt
  instrui a pedir que o atendente verifique.
- **Free tier do Gemini tem limite de requisições por minuto.** O `compare` padrão faz 3 chamadas
  (até 6 com retries).

## 8. Changelog do versionamento

- **2026-11-22 — reorganização em ablação.** A antiga `v2` (tarefas estruturadas) foi movida para
  `v3` sem edição de texto. A nova `v2` = base + domínio + tarefas da v1 (mesma composição da antiga
  `v1`). A nova `v1` não tem base nem domínio. Como `template_hash` passou a ser calculado com
  rótulos por camada, entradas antigas do cache não são reaproveitadas por nenhuma versão nova.
  As execuções antigas com a numeração anterior (1 execução Gemini no histórico local e os 6
  samples fake) foram descartadas, não reclassificadas. Os samples foram regenerados com o fake
  nas versões novas.
- **2026-11-22 — `flow_summary` como árvore de decisão.** Motivo: no formato antigo o diagrama
  ASCII e a lista de decisões, ambos escritos pelo modelo, se contradiziam. Duas mudanças de
  natureza diferente, sem criar v4:
  - **Formato (vale para v1, v2 e v3):** schema novo de árvore, validação estrutural com retry e
    ASCII desenhado pelo código. Na v1 (reutilizada pela v2) só a seção de formato do
    `prompts/v1/flow_summary.md` mudou, sem regras de qualidade novas. Como o schema é o mesmo
    nas três, a comparação continua medindo só as camadas.
  - **Engenharia de prompt (só v3):** as instruções de `prompts/v3/flow_summary.md` foram trocadas
    por 6 regras enxutas (só sim/não, uma pergunta por nó; começar pela verificação mais barata e
    decisiva; folhas com verbo de ação e o id da base só em `ref`; "resolvido" encerra, nunca
    repete procedimento; testes compatíveis com o perfil; 3 a 5 decisões, só ramos que mudam a
    ação). O checklist de verificação desse tipo saiu: as regras que ele conferia agora são
    garantidas pela validação.
  - Os outros 3 tipos não mudaram. Execuções antigas de `flow_summary` ficaram incompatíveis com
    o schema novo.
- **2026-11-22 — correções do `flow_summary` após revisar as saídas.**
  - **Validação (todas as versões):** folha com `ref` de procedimento (`PROC-*`) é inválida e entra
    no retry. Procedimento é algo a tentar antes de decidir ("Reiniciar resolveu?"), não fim de
    fluxo; uma folha "Reiniciar (PROC-01)" deixava o atendimento sem saída.
  - **Renderização (todas as versões):** o renderizador remove do texto da ação o id que repete o
    `ref`, para não aparecer "Agendar visita (ESC-01) (ESC-01)".
  - **Prompt da v3 (engenharia de prompt):** (a) o fluxo parte do que o ticket já informa e só
    inclui decisões ainda em aberto, a mesma lógica do `already_known` em `clarifying_questions`;
    (b) a regra fixa "de 3 a 5 decisões" virou "só as decisões que o ticket ainda não responde, no
    máximo 5": o mínimo fixo obrigava o modelo a repetir perguntas já respondidas quando o ticket
    era detalhado (cenário em que o fixo conflitava com a regra de não repetir); (c) escalonamento
    para N2 só depois de esgotar as verificações de N1 do sintoma; (d) o id vai só em `ref`, nunca
    no texto da ação, e procedimento não é folha.
  - O prompt da v1 (e portanto da v2) não mudou: as correções de validação e renderização valem
    para as três versões por serem de formato; as regras novas são só da v3.
  - Correção na tarefa de passos: informação faltante vira um passo condicional 
    ("Se o aparelho estiver no chão, coloque-o num lugar alto"), nunca uma pergunta.
  - Correção no domínio: acrescente à WIFI-01 que, em cômodo distante, a preferência é a rede 2.4 GHz. 
    Como a correção está no domínio, vale igualmente para v2 e v3 e não desequilibra a comparação.
- **2026-11-22 — regras de qualidade do `flow_summary` saem da validação.**
  - **Validação (todas as versões):** "pergunta de sim/não" e "folha `PROC-*`" deixam de rejeitar a
    árvore e de disparar retry; viram violações em `metrics.py` (campo `violations`). Continuam
    como validação dura só as regras estruturais. Efeito: a mensagem de retry, que todas as versões
    recebem, não carrega mais a dica de reestruturação.
  - **Prompt da v3 (engenharia de prompt):** a dica foi para `prompts/v3/flow_summary.md` com
    exemplos: alternativa "X ou Y?" vira pergunta sobre uma delas ("Funciona no cabo de rede?");
    folha de procedimento vira o nó "Reiniciar a ONT e o roteador resolveu?" (sim → encerrar,
    não → próxima verificação). Muda o `template_hash` da v3 **só** para `flow_summary`; a
    comparação Gemini registrada (`resolution_steps`) não é afetada.
  - v1 e v2 não mudaram de prompt. Execuções antigas de `flow_summary` que foram rejeitadas por
    essas regras hoje seriam aceitas com avisos.
