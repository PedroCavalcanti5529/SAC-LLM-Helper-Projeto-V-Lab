# Notas de decisão

Registro das decisões de cada fase e do porquê de cada uma. Nenhuma das fases mudou prompts, schemas
de saída ou rubrica.

- Fase 1, métricas no pacote + CI: seções 1 a 4.
- Fase 2, interface web (Streamlit): seção 5.
- Fase 3, deploy (Streamlit Community Cloud): seção 6.

## 1. Métricas dentro do pacote (`src/support_assistant/metrics.py`)

**Decisão.** As métricas objetivas ficam no pacote, não em scripts avulsos (os antigos
`scripts/compare_*.py` foram removidos).
`compute_metrics(content_type, output, profile)` despacha para uma função por tipo e é chamada pelo
`Generator` em toda execução (inclusive cache hit). O resultado vai no campo `metrics` do registro,
ao lado de `evaluation`.

**Por quê.**
- O `compare` grava rubrica humana e métricas **no mesmo registro**, para a mesma saída. Com as
  métricas num resumo separado, cruzar "nota de customer_fit" com "jargão para leigo" exigia juntar
  arquivos à mão.
- Uma só implementação: CLI e interface web mostram os mesmos números, lidos do campo `metrics`
  do registro. Execuções antigas, sem o campo, podem ser recalculadas com `compute_metrics`.
- `flow_summary` reaproveita `models.analyze_flow` (a mesma função da validação) para decisões,
  profundidade e folhas, sem duplicar a lógica.
- Os campos lidos são os dos schemas de `models.py`, acessados como dict (sem revalidar). Assim
  as métricas funcionam em registros antigos e conseguem apontar violações que o schema atual barraria
  (ex.: mais de 5 perguntas). Um teste confere que o limite de 5 em `metrics.py` é o mesmo do schema.

**Métrica nunca derruba execução.** Se o cálculo falhar, o registro fica com `metrics: null` e
`metrics_error: "<Tipo>: <mensagem>"`, a CLI avisa e a saída válida segue para cache e histórico.
Métrica é acessória; perder uma geração (e uma chamada paga) por causa dela seria pior.

| Tipo | Métricas |
|---|---|
| `diagnosis` | `n_hypotheses`, `n_evidence`, `n_missing_info`, `likelihood` (alta/media/baixa), `kb_ids`, `escalation` |
| `resolution_steps` | `n_steps`, `avg_words_per_step`, `max_words_per_step`, `question_steps`, `jargon`, `urls_ips`, `commands`, `kb_ids`, `escalation` |
| `clarifying_questions` | `n_questions`, `n_already_known`, `double_questions`, `over_limit`, `priorities_sequential`, `kb_ids` |
| `flow_summary` | `decisions`, `depth`, `leaves`, `leaves_with_ref`, `kb_ids`, `escalation` |
| todos | `violations` (lista `{rule, where, detail}`) e `n_violations` |

`escalation` = algum id `ESC-*` citado. `kb_ids` = ids no formato da base (`XX-00`) citados na saída.

## 2. Violações dependentes do perfil

**Decisão.** A métrica é a mesma para qualquer cliente; o que muda é se ela vira **violação**:

| Regra | Conta quando | Tipo |
|---|---|---|
| `jargon_for_leigo` | jargão em texto ao cliente e `technical_level = leigo` | `resolution_steps` |
| `link_or_command_phone` | URL, IP ou comando e `channel = telefone` (POL-05) | `resolution_steps` |
| `step_is_question` | instrução termina em "?" (sempre) | `resolution_steps` |
| `too_many_questions` | mais de 5 perguntas (sempre) | `clarifying_questions` |
| `question_not_yes_no` | nó sem "?" ou na forma "X ou Y?" (sempre) | `flow_summary` |
| `procedure_leaf` | folha com ref `PROC-*` (sempre) | `flow_summary` |

**Por quê.**
- "GHz" é jargão para a Marta (leiga), mas é a palavra certa para a Juliana (avançada). Contar
  jargão como erro para todo mundo puniria a v3 justamente quando ela adapta bem ao perfil.
- Link no e-mail é útil; no telefone é impossível de seguir (POL-05). Mesma lógica.
- Passo em forma de pergunta e excesso de perguntas são problemas para qualquer perfil.

**Escopo e limites conscientes.**
- Jargão e links só são checados em `resolution_steps`, o tipo cujo texto vai inteiro ao cliente.
  `diagnosis` e `flow_summary` são para o atendente; `clarifying_questions` fica para depois.
- Dentro de `resolution_steps`, só o texto ao cliente é checado (`opening`, `instruction`, `why`,
  `closing`). `escalation` é nota para o atendente e fica de fora.
- Siglas (`ONT`, `PON`, `LOS`, `DNS`, `IP`, `LAN`, `GHz`) são comparadas com maiúsculas exatas:
  em minúsculas colidiriam com o português ("religá-**los**"). Palavras (`ping`, `traceroute`,
  `firmware`) ignoram maiúsculas. A lista é a mesma que o script já usava.
- São heurísticas: indicam onde olhar, não substituem a rubrica humana.

**Onde aparecem.** No `generate`, como "Avisos de qualidade" depois da saída. No `compare`, numa
tabela compacta (métricas por versão + violações) impressa **depois das saídas e antes das notas**,
para o avaliador ver os números antes de pontuar.

## 3. CI sem segredos (`.github/workflows/ci.yml`)

**Decisão.** GitHub Actions em push na `main` e em todo pull request; matriz Python 3.11 e 3.12;
`pip install -r requirements.txt` + `pip install -e .`; `pytest -q`; cache do pip pelo
`actions/setup-python`. `LLM_PROVIDER=fake`, permissões só de leitura, sem linter por enquanto.

**Por quê.**
- O projeto foi desenhado para rodar inteiro com o provedor fake. O CI não precisa de chave, então
  não há segredo para vazar, e PRs de forks rodam sem configuração.
- Os testes já forçam o fake (fixture `force_fake_provider`); a variável no workflow é uma segunda
  garantia explícita.
- 3.11 é o mínimo do `pyproject.toml`; 3.12 cobre a versão estável seguinte.
- Linter fica de fora para não misturar mudança de estilo com mudança de comportamento agora.

## 4. Exemplo de métricas (modo fake)

Gerado com `LLM_PROVIDER=fake`:

```bash
support-assistant compare -c c01 -t t02 -y resolution_steps
```

Perfil `c01` = leiga, canal telefone. Como o fake devolve a mesma resposta nas três versões, os
números são iguais por versão; o exemplo mostra o formato, não uma diferença entre prompts.

```
Métricas objetivas (calculadas pelo código; não substituem a sua avaliação):
  métrica             v1       v2       v3
  n_steps             3        3        3
  avg_words_per_step  9.7      9.7      9.7
  max_words_per_step  11       11       11
  question_steps      0        0        0
  jargon              ONT,PON  ONT,PON  ONT,PON
  urls_ips            0        0        0
  commands            0        0        0
  kb_ids              POL-03   POL-03   POL-03
  escalation          não      não      não
  n_violations        3        3        3
Violações:
  v1: [jargon_for_leigo] steps[1]: ONT
  v1: [jargon_for_leigo] steps[2]: ONT
  v1: [jargon_for_leigo] steps[3]: PON
  v2: [jargon_for_leigo] steps[1]: ONT
  ...
```

Com o mesmo fake e `c03` (avançada, e-mail), `jargon` continua `ONT,PON`, mas `n_violations` é 0.
Esse é o efeito da regra dependente do perfil.

`escalation` é "não" porque o fake cita só `POL-03` (política de visita), não um id `ESC-*`.

Trecho do registro de comparação (`history.json`), com `metrics` ao lado de `evaluation`:

```json
{
  "prompt_version": "v3",
  "metrics": {
    "n_steps": 3, "avg_words_per_step": 9.7, "max_words_per_step": 11, "question_steps": 0,
    "jargon": ["ONT", "PON"], "urls_ips": 0, "commands": 0, "kb_ids": ["POL-03"], "escalation": false,
    "violations": [{"rule": "jargon_for_leigo", "where": "steps[1]", "detail": "ONT"}, "..."],
    "n_violations": 3
  },
  "evaluation": {"clarity": {"score": 3, "justification": "..."}, "...": "...", "average": 3.0, "evaluated_by": "human"}
}
```

## 5. Interface web (Streamlit)

Arquivo único: `app/streamlit_app.py`. Instalação: `pip install -e ".[web]"`. Execução:
`streamlit run app/streamlit_app.py`. A interface **não tem regra de negócio**:

| Precisa de | Chama |
|---|---|
| gerar / comparar / gravar comparação | `generators.py` (`generate`, `compare`, `save_comparison`) |
| validar a rubrica e escolher a vencedora | `evaluation.py` (`validate_score`, `validate_justification`, `build_evaluation`, `pick_winner`) |
| métricas e violações | já vêm no registro (`metrics.py`, via generator); a tela só exibe |
| diagrama do `flow_summary` | já vem em `rendered` (`flow_render.py`); a tela mostra em `st.code` |
| histórico | `storage.py` (`load_history`) |

**Extra opcional `web` em vez de dependência obrigatória.** O Streamlit traz dezenas de pacotes
(pandas, pyarrow, tornado...). Quem só usa a CLI, o avaliador que roda os testes e o próprio núcleo
continuam com `pydantic` + `python-dotenv`. Os testes da interface usam
`pytest.importorskip("streamlit")`: sem o extra são pulados, não quebram. O CI instala o extra para
que eles rodem.

**Avaliação às cegas ligada por padrão.** Quem escreveu os prompts sabe que a v3 "deveria" ganhar.
Ver o rótulo da versão enviesa a nota (viés de confirmação), e a ordem fixa v1 → v2 → v3 soma
efeito de ordem. Por isso as respostas aparecem como "Resposta A/B/C", em ordem embaralhada. As
camadas, que denunciariam a versão (v1 = "papel mínimo"), também ficam escondidas até a avaliação ser
gravada. A métrica objetiva continua visível, porque não identifica a versão. Depois de gravar, a
tela revela qual resposta era qual versão. O JSON da comparação guarda os runs na ordem original
das versões, igual à CLI. Dá para desligar a opção quando o objetivo é inspecionar, não avaliar.

**`st.session_state` para não repetir chamadas.** O Streamlit reexecuta o script inteiro a cada
clique. O LLM só é chamado dentro do `if st.button(...)`, e o resultado vai para
`st.session_state` (`gen_record` e `cmp`). Qualquer outra interação só redesenha a partir do
estado. A rubrica fica num `st.form`, então mexer nas notas não reexecuta nada até "Gravar
avaliação", e gravar não chama o LLM. Um teste conta as chamadas do cliente para provar isso
(3 versões = 3 chamadas, antes e depois de interagir e gravar).

**Configuração injetável, pensando no deploy.** Nenhuma tela lê o `.env`. `get_context()` usa
`st.session_state["settings"]` se alguém o colocou lá e só na falta chama `load_settings()`. O
`Generator` é montado por `generators.build_generator(settings, client=None)`, a mesma fábrica que a
CLI passou a usar, e é refeito quando as configurações da sessão mudam. Na Fase 3, trocar o
provedor por sessão é colocar outro `Settings` (ou outro `client`) na sessão, sem tocar no núcleo.
Os testes já usam esse caminho para injetar um `Settings` com diretório temporário.

**Erros amigáveis.** As telas capturam os mesmos erros que a CLI trata (`ConfigError`,
`InputValidationError`, `LLMError`, `GenerationError`, `EvaluationError`) e mostram `st.error` com a
mensagem, sem traceback. Exemplo: sem `GEMINI_API_KEY`, o app abre com "Não foi possível iniciar:
GEMINI_API_KEY ausente…". Com ticket vazio, aparece o erro de validação do RN02.

**Decisões menores.**
- Navegação por `st.radio` na barra lateral em vez de multipage: um arquivo só, fácil de testar com
  `AppTest`.
- Nota da rubrica num seletor com "—" (sem nota) em vez de um campo numérico com padrão 3. Assim
  esquecer uma nota é um erro visível, não um 3 silencioso.
- Cada clique em "Gerar" grava a execução no histórico, como a CLI (inclusive em cache hit).
- "Comparar" grava só ao enviar a rubrica, como o `compare` da CLI: abandonar a tela não grava nada,
  mas as saídas ficam no cache.

### Prints a tirar (`docs/screenshots/`)

| Arquivo sugerido | O que mostrar |
|---|---|
| `docs/screenshots/01-gerar.png` | tela Gerar com `resolution_steps` para c01 (leiga, telefone): cabeçalho (cache, tentativas, repetições, latência, violações), avisos de jargão, saída, tabela de métricas e botão de baixar o JSON |
| `docs/screenshots/02-gerar-flow.png` | tela Gerar com `flow_summary`: árvore desenhada em `st.code` |
| `docs/screenshots/03-comparar-cegas.png` | tela Comparar às cegas: Resposta A/B/C lado a lado, tabela de métricas por resposta e o formulário da rubrica |
| `docs/screenshots/04-comparacao-revelada.png` | depois de gravar: cabeçalhos "Resposta X = vN", tabela de notas por versão, vencedora e caminho do JSON |
| `docs/screenshots/05-historico.png` | tela Histórico com filtros aplicados, a tabela de registros e o detalhe de uma comparação com o JSON aberto |

## 6. Deploy (Streamlit Community Cloud)

**Plataforma.** Streamlit Community Cloud: gratuita, publica direto do GitHub e redeploya a cada
push na branch escolhida. É a mesma tecnologia da interface, então não há código de servidor
para escrever.

### Segurança da chave

**A versão pública não tem chave do projeto.** O deploy liga `APP_PUBLIC_MODE=true`, e com isso
`load_settings()` força o provedor fake e **ignora** `LLM_PROVIDER` e `GEMINI_API_KEY` do ambiente.
Mesmo que alguém coloque uma chave nos Secrets por engano, ela não é usada. Quem quiser o Gemini
cola a própria chave na barra lateral. Assim a chave do dono nunca fica exposta e a cota dele
nunca é consumida por estranhos.

**A chave colada não é gravada.** Ela só existe:
- no campo de senha (`type="password"`), em `st.session_state`, ou seja, na memória da sessão no
  servidor;
- no `Settings` montado por `config.with_session_provider()` e no `GeminiClient`.

Ela não entra em nada que vai para disco ou para a tela:
- `history.json`, `runs/*.json`, `cache.json`, `failures.json` e o JSON baixado guardam só
  `provider`, `model` e `config`;
- a chave de cache não inclui a API key;
- a requisição envia a chave no cabeçalho `x-goog-api-key`, não na URL (URLs costumam ir para logs);
- `Settings` declara `api_key` com `repr=False`, então nem um log ou traceback com o objeto mostra
  a chave.

Um teste cola uma chave, gera uma resposta (com o cliente simulado, sem rede) e confere que nenhum
arquivo gravado contém a chave.

**Histórico isolado por sessão.** No Cloud, todas as sessões rodam no mesmo processo e no mesmo
disco. Com um `outputs/` comum, a tela Histórico mostraria os tickets em texto livre de um
visitante para outro, e o cache serviria a resposta de um para outro. No modo público, cada
sessão grava num diretório temporário próprio (`tempfile.mkdtemp`), que some com o container.
Isso é deliberado: a versão pública é uma demonstração, não um lugar para guardar dados. Quem
quiser guardar uma execução usa "Baixar JSON".

**Erros e limites.** Rate limit ou chave inválida do Gemini aparecem como mensagem amigável
(`st.error`), com o retry do provedor da Fase "robustez" valendo também aqui. O modo fake não tem
custo nem limite.

### Como o app roda no Cloud sem instalar o pacote

O Cloud instala as dependências do `requirements.txt` que está **na pasta do arquivo de entrada**
(`app/requirements.txt`) e não roda `pip install -e .`. Por isso:
- `app/requirements.txt` lista só `streamlit`, `pydantic` e `python-dotenv`. O `requirements.txt`
  da raiz continua sendo o da CLI e dos testes.
- `app/streamlit_app.py` tenta `import support_assistant` e, se falhar, acrescenta `src/` ao
  `sys.path`. Localmente, com o pacote instalado, nada muda.

Conferido localmente numa venv limpa só com `app/requirements.txt` (sem o pacote), em modo público
e com uma "chave do dono" no ambiente. O app abriu no fake, sem chave, e gerou uma resposta.

### Passo a passo para publicar (dono do repositório)

1. Faça merge na branch que vai ao ar (ex.: `main`) e envie para o GitHub.
2. Em <https://share.streamlit.io>, entre com o GitHub e clique em **Create app** → **Deploy a public
   app from GitHub**.
3. Preencha:
   - **Repository:** `PedroCavalcanti5529/SAC-LLM-Helper-Projeto-V-Lab-`
   - **Branch:** `main`
   - **Main file path:** `app/streamlit_app.py`
   - **App URL:** escolha o subdomínio (ex.: `sac-llm-helper.streamlit.app`)
4. Em **Advanced settings**:
   - **Python version:** 3.11 ou 3.12 (o projeto exige ≥ 3.11).
   - **Secrets:** cole exatamente o bloco abaixo. **Não** coloque `GEMINI_API_KEY`.
     ```toml
     APP_PUBLIC_MODE = "true"
     ```
     O Cloud expõe os secrets de primeiro nível como variáveis de ambiente, que é como o
     `config.py` lê.
5. Clique em **Deploy**. Ao abrir, confira na barra lateral: "Provedor: fake" e "Modo público: o
   histórico é só desta sessão…". Se essa frase não aparecer, o secret não foi aplicado.
6. Troque `https://SEU-APP.streamlit.app` no README pelo link real.

Cada push na branch publicada redeploya o app sozinho.

### Limitações do deploy

- O plano gratuito hiberna o app sem uso: o primeiro acesso depois disso leva alguns segundos.
- Diretórios temporários de sessão ficam no disco do container até ele reiniciar (são pequenos e
  somem no redeploy ou na hibernação).
- A chave colada passa pelo servidor do Streamlit Cloud (memória do processo) para chegar ao
  Gemini. Não fica gravada, mas quem não confia na plataforma deve rodar o app localmente.
- Uma chave colada vale para a aba. Recarregar a página cria uma sessão nova e pede a chave de novo.
