# Decisões das fases extras
 
Métricas, CI, interface web e deploy: o que foi decidido e por quê. Nenhuma dessas fases mudou
prompts, schemas de saída ou a rubrica. As decisões de prompt estão em
[PROMPT_ENGINEERING_NOTES.md](../PROMPT_ENGINEERING_NOTES.md).
 
1. [Métricas objetivas](#1-métricas-objetivas)
2. [CI sem segredos](#2-ci-sem-segredos)
3. [Interface web](#3-interface-web)
4. [Deploy](#4-deploy)
---
 
## 1. Métricas objetivas
 
**As métricas ficam dentro do pacote** (`src/support_assistant/metrics.py`), não em scripts avulsos.
`compute_metrics(content_type, output, profile)` roda em toda geração, inclusive em cache hit, e o
resultado vai para o campo `metrics` do registro, ao lado de `evaluation`.
 
- **A rubrica e as métricas ficam no mesmo registro,** para a mesma saída. Assim dá para cruzar "nota
  de adequação" com "jargão para leigo" sem juntar arquivos à mão.
- **Há uma única implementação:** a CLI e a interface web mostram os mesmos números.
- **O `flow_summary` reaproveita a `analyze_flow`,** a mesma função da validação.
- **Uma falha nas métricas nunca derruba a execução.** O registro fica com `metrics: null` e
  `metrics_error`, e a saída válida segue normalmente. Perder uma chamada paga por causa de uma
  métrica acessória seria pior.
| Tipo | Métricas |
|---|---|
| `diagnosis` | hipóteses, evidências, informações faltantes, distribuição de `likelihood`, ids citados, escalonamento |
| `resolution_steps` | passos, palavras por passo (média e máximo), passos-pergunta, jargão, URLs/IPs, comandos, ids, escalonamento |
| `clarifying_questions` | perguntas, `already_known`, perguntas duplas, acima do limite, prioridades em sequência, ids |
| `flow_summary` | decisões, profundidade, folhas, folhas com ref, ids, escalonamento |
 
### Violações dependentes do perfil
 
A métrica é a mesma para qualquer cliente. O que muda é se ela conta como **violação**:
 
| Regra | Conta quando |
|---|---|
| `jargon_for_leigo` | há jargão no texto ao cliente **e** o cliente é `leigo` |
| `link_or_command_phone` | há URL, IP ou comando **e** o canal é `telefone` (POL-05) |
| `step_is_question` | uma instrução termina em "?" (sempre) |
| `too_many_questions` | há mais de 5 perguntas (sempre) |
| `question_not_yes_no` | um nó do fluxo não é uma pergunta de sim ou não (sempre) |
| `procedure_leaf` | o fluxo termina num procedimento `PROC-*` (sempre) |
 
"GHz" é jargão para a Marta, que é leiga, e a palavra certa para a Juliana, que é avançada. Punir o
jargão para todo mundo puniria justamente a versão que se adapta bem ao perfil.
 
**Escopo consciente:**
- Jargão e links só são checados em `resolution_steps`, o único tipo cujo texto vai inteiro ao
  cliente, e a nota de escalonamento, que é interna, fica de fora.
- As siglas (`ONT`, `LOS`, `IP`, `GHz`…) são comparadas com as maiúsculas exatas, porque em
  minúsculas colidiriam com o português ("religá-**los**").
- São heurísticas: apontam onde olhar e não dão a nota.
**Onde aparecem:** no `generate`, como "Avisos de qualidade". No `compare`, numa tabela impressa
**antes** das notas, para o avaliador ver os números antes de pontuar.
 
## 2. CI sem segredos
 
**O workflow** (`.github/workflows/ci.yml`) roda em push na `main` e em todo pull request, com
Python 3.11 e 3.12, cache do pip, `pytest -q`, `LLM_PROVIDER=fake` e permissões só de leitura.
 
- **O CI não usa chave nenhuma.** O projeto roda inteiro com o provedor fake, então não há segredo
  para vazar, e PRs de forks rodam sem configuração.
- **O CI instala o extra `web`,** para que os testes da interface também rodem.
- **Ainda não há linter,** para não misturar mudança de estilo com mudança de comportamento.
## 3. Interface web
 
Um único arquivo, `app/streamlit_app.py`, **sem regra de negócio**: gerar, comparar e gravar ficam
no `generators.py`, a rubrica no `evaluation.py`, as métricas e o diagrama já vêm no registro, e o
histórico vem do `storage.py`.
 
- **O Streamlit é um extra opcional** (`pip install -e ".[web]"`). Ele traz dezenas de pacotes, e
  quem só usa a CLI ou roda os testes continua apenas com `pydantic` + `python-dotenv`. Sem o
  extra, os testes da interface são pulados (`pytest.importorskip`), não quebram.
- **A avaliação às cegas vem ligada por padrão.** Quem escreveu os prompts sabe que a v3 "deveria"
  ganhar. As respostas aparecem como A, B e C, em ordem embaralhada, e as camadas, que entregariam
  a versão, só são reveladas depois de gravar. As métricas continuam visíveis, porque não
  identificam a versão.
- **O `st.session_state` evita chamadas repetidas.** O Streamlit reexecuta o script a cada clique,
  então o LLM só é chamado dentro do botão e a rubrica fica num `st.form`. Um teste conta as
  chamadas: três versões geram três chamadas, antes e depois de interagir e gravar.
- **A configuração é injetável.** Nenhuma tela lê o `.env`: o `Generator` vem de
  `build_generator(settings)`, a mesma fábrica da CLI. Trocar o provedor por sessão, como o deploy
  faz, não toca no núcleo.
- **Os erros aparecem como mensagens amigáveis** (`st.error`), os mesmos que a CLI trata, sem traceback.
- **A nota da rubrica começa vazia ("—").** Esquecer uma nota vira um erro visível, não um 3 silencioso.
## 4. Deploy
 
**Plataforma:** Streamlit Community Cloud, gratuita. Publica direto do GitHub e redeploya a cada push.
 
### Segurança da chave
 
- **A versão pública não tem chave do projeto.** Com `APP_PUBLIC_MODE=true`, o `load_settings()`
  força o fake e **ignora** o `LLM_PROVIDER` e a `GEMINI_API_KEY` do ambiente. Mesmo uma chave
  colocada nos Secrets por engano não é usada.
- **Quem quiser o Gemini cola a própria chave.** Ela fica só na memória da sessão, no campo de
  senha, no `Settings` e no cliente, e não vai para histórico, runs, cache, failures, o JSON
  baixado nem a chave do cache.
- **A chave vai no cabeçalho `x-goog-api-key`, não na URL,** porque URLs costumam parar em logs. O
  `Settings` declara `api_key` com `repr=False`.
- **Um teste comprova isso:** cola uma chave, gera uma resposta com o cliente simulado e confere que
  nenhum arquivo gravado contém a chave.
- **O histórico é isolado por sessão.** No Cloud, todas as sessões dividem processo e disco. Um
  `outputs/` comum mostraria os tickets de um visitante para outro, e o cache serviria a resposta
  de um para outro. No modo público, cada sessão grava num diretório temporário próprio. Para
  guardar uma execução, use "Baixar JSON".
### Como o app roda no Cloud sem instalar o pacote
 
O Cloud instala o `requirements.txt` da pasta do arquivo de entrada e não roda `pip install -e .`.
Por isso existe um `app/requirements.txt` com `streamlit`, `pydantic` e `python-dotenv`, e o app
acrescenta `src/` ao `sys.path` quando o pacote não está instalado.
 
### Publicar
 
1. Faça o merge na `main` e envie para o GitHub.
2. Em <https://share.streamlit.io>, clique em **Create app** → **Deploy a public app from GitHub**.
3. Preencha: repositório `PedroCavalcanti5529/SAC-LLM-Helper-Projeto-V-Lab-`, branch `main`, arquivo
   `app/streamlit_app.py`, e escolha o subdomínio.
4. Em **Advanced settings**, escolha o Python 3.11 ou 3.12 e cole nos **Secrets** só a linha abaixo,
   **sem** a `GEMINI_API_KEY`:
```toml
APP_PUBLIC_MODE = "true"
```
5. Clique em **Deploy** e confira na barra lateral se aparece "Provedor: fake" e o aviso de modo
   público. Se o aviso não aparecer, o secret não foi aplicado.
### Limitações do deploy
 
- O plano gratuito hiberna sem uso, e o primeiro acesso depois disso leva alguns segundos.
- A chave colada passa pela memória do servidor do Streamlit Cloud até chegar ao Gemini. Ela não é
  gravada, mas quem não confia na plataforma deve rodar o app localmente.
- Recarregar a página cria uma sessão nova e pede a chave de novo.
 