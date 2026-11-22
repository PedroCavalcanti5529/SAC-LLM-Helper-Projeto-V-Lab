# Notas de engenharia de prompt

## 1. Arquitetura do prompt (4 camadas)

| Camada | Arquivo | Muda entre versões? | Papel |
|---|---|---|---|
| 1. Base | `prompts/base/system.md` | não | persona, público de cada tipo, limites, regras de adaptação, formato JSON |
| 2. Domínio | `prompts/base/domain.md` + `data/domains/wifi_isp.json` | não | fatos da empresa com IDs |
| 3. Tarefa | `prompts/<versao>/<tipo>.md` | **sim** | instrução e formato de cada tipo |
| 4. Entrada | `prompts/base/input.md` | não | perfil e ticket entre tags |

As camadas 1–3 vão na instrução de sistema e a camada 4 na mensagem do usuário. Isso separa o que
é regra (sistema) do que é dado (usuário), e numa comparação garante que só a camada 3 varia.

## 2. Estratégias usadas

**Comuns às duas versões (camadas 1, 2 e 4):**
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
- **Delimitação da entrada** com `<perfil_cliente>` e `<ticket>`, a instrução de tratar o conteúdo
  como dado e uma sanitização simples que impede o ticket de fechar a tag (proteção básica
  contra prompt injection).
- **Saída estruturada.** JSON validado por Pydantic, `responseMimeType: application/json` no
  Gemini e um retry com a mensagem de erro do validador (`prompts/base/retry.md`).
- **Sem chain-of-thought na saída.** Os campos de justificativa (`rationale`, `purpose`, `why`)
  são curtos e voltados ao atendente/cliente. Não há raciocínio livre.

**Exclusivas da v2 (camada 3):**
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

## 3. v1 × v2: o que muda e por quê

A v1 é propositalmente o *baseline* ingênuo: uma frase de tarefa + o formato JSON. Ela herda
persona, limites e regras de adaptação da base, então já é razoável. A comparação mede o ganho das
instruções de tarefa estruturadas.

| Aspecto | v1 | v2 | Hipótese de ganho (rubrica) |
|---|---|---|---|
| Rastreabilidade | não pede fontes | evidência com origem e hipóteses citando IDs | clarity, menos alucinação |
| Ticket vago | sem regra | sem hipótese `alta` e coleta de informação como próxima ação | actionability |
| Repetição | pode pedir de novo o que o cliente já disse | `already_known` + "não repita o que já foi feito" | customer_fit |
| Tamanho | livre | limites por estilo | customer_fit |
| Canal | só a regra geral da base | regras concretas por campo (saudação/assinatura no e-mail, tempo de espera no telefone) | customer_fit |
| Escalonamento | opcional | obrigatório citar `ESC-xx` com evidências a coletar | actionability |
| Fluxo | sem garantia de coerência | ramos sempre terminam, diagrama igual aos pontos de decisão | clarity |

## 4. Comparação registrada (rubrica manual)

> **Status: PENDENTE de execução com modelo real.** A rubrica é preenchida por uma pessoa
> (RN08/RN09). O comando abaixo gera as duas saídas e pede as notas interativamente. O JSON resultante
> vai para `outputs/runs/cmp-*.json`. Copie-o para `samples/gemini_compare_*.json` e preencha a
> tabela.

```bash
# .env com LLM_PROVIDER=gemini e GEMINI_API_KEY preenchida
support-assistant compare -c c01 -t t02 -y resolution_steps --versions v1 v2
```

Cenário escolhido: **c01** (leiga, didática, telefone) + **t02** (Wi-Fi cai à noite no quarto).
É o perfil mais exigente em adaptação (sem jargão, explicar o porquê, sem links) e o ticket tem
informação suficiente para passos concretos.

| Critério | v1 nota | v1 justificativa | v2 nota | v2 justificativa |
|---|---|---|---|---|
| clarity | _ | _ | _ | _ |
| customer_fit | _ | _ | _ | _ |
| actionability | _ | _ | _ | _ |
| **média** | _ | | _ | |

Provedor/modelo/config: `gemini` / `gemini-2.5-flash` / `temperature=0.2, max_output_tokens=4096`.
Hash dos templates: ver `template_hash` de cada run no JSON.

**Regra de versionamento (RN05):** depois que esta comparação for registrada, `prompts/v1/` e
`prompts/v2/` **não mudam mais**. Ajustes vão para `prompts/v3/`, com a mudança anotada aqui.

## 5. Decisões e trade-offs

- **Enums sem acento** (`intermediario`, `didatico`, `avancado`): evitam erro de digitação e
  diferenças de normalização Unicode (NFC/NFD) em comparações de string. O texto gerado continua
  acentuado.
- **Schema igual entre versões.** O validador é o mesmo para v1 e v2. Assim a comparação mede
  só a instrução, não a facilidade de passar no parser. Custo: a v1 já recebe o formato JSON, o que
  a deixa melhor que um baseline "puro".
- **`flow_summary` com ASCII *e* descrição estruturada.** `decision_points` é obrigatório (fácil
  de validar e de renderizar). `ascii_diagram` é opcional no schema, porque modelos erram
  alinhamento de ASCII com frequência e não faz sentido rejeitar a resposta inteira por isso.
- **Campos extras ignorados** (`extra="ignore"`), campos obrigatórios exigidos. É uma tolerância
  deliberada a pequenos desvios do modelo sem perder a garantia dos campos usados.
- **`template_hash` cobre todos os arquivos usados** (base, domínio, tarefa, entrada, retry), não
  só a tarefa. Qualquer edição invalida o cache e fica rastreável no histórico.
- **Temperatura 0.2.** Mais reprodutibilidade para comparar versões, com pouca perda de fluência.
- **Gemini via REST (urllib)** em vez do SDK: uma dependência a menos e controle explícito de
  timeout e erros HTTP (429 → rate limit amigável, 401/403 → aponta o `.env`).
- **Retry com o erro do validador** em vez de repetir o mesmo prompt: o modelo recebe o motivo
  exato da rejeição. Só 1 retry, para limitar custo e latência.
- **`compare` não grava nada se cancelado.** As saídas ficam no cache, então rodar de novo é
  instantâneo e não gasta cota.

## 6. Limitações conhecidas

- **A comparação v1×v2 com modelo real ainda não foi executada** (exige chave e avaliação humana).
  Os `samples/` atuais vêm do provedor fake e mostram apenas o formato.
- **Uma comparação com um cenário é uma amostra pequena.** O resultado é indicativo, não
  estatístico. O ideal seria rodar os 4 tickets × 4 perfis e avaliar às cegas (sem saber qual
  versão é qual).
- **O fake não testa qualidade de prompt**, só o pipeline (montagem, cache, validação, persistência).
- **Proteção contra prompt injection é básica** (tags + instrução + sanitização de fechamento de tag).
- **Adaptação ao perfil não é verificada automaticamente.** Não há checagem de jargão ou de links no
  canal telefone; isso depende da rubrica humana.
- **Cache e histórico em JSON** reescrevem o arquivo inteiro a cada gravação. Isso basta para uso local
  de uma pessoa, mas não serve para concorrência nem para grande volume.
- **Base de conhecimento estática e fictícia.** O modelo não consulta status de rede real; o prompt
  instrui a pedir que o atendente verifique.
- **Free tier do Gemini tem limite de requisições por minuto.** O `compare` faz 2 chamadas (até 4
  com retries).
