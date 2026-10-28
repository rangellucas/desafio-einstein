# Checklist de execução

Fonte: [PRD.md](PRD.md), seções 14–16. Os IDs AC remetem aos critérios gerais de aceite da seção 14; sua associação a uma etapa não significa que já foram atendidos. Cada etapa exige solicitação própria.

Estado atual: **Etapa 4 implementada e testada com substitutos; gateway, ingestão, recuperação e respostas reais pendentes**, conforme solicitação de não executar chamadas reais. A compatibilidade real da Etapa 2 e as limitações de extração/revisão visual das Etapas 0–1 permanecem pendentes antes de indexar. Etapas 5–7 não iniciadas. Os critérios gerais seguem parciais, conforme as evidências abaixo.

## Etapa 0 — Preparar as instruções do projeto

- [x] Ler o PRD e registrar inconsistência concreta antes de implementar.
- [x] Criar instruções curtas em [AGENTS.md](AGENTS.md), referenciando o PRD.
- [x] Criar checklist de etapas com os critérios de aceite relacionados.
- [x] Registrar decisões técnicas aprovadas no PRD e verificações pendentes.
- [x] Revisar a coerência documental e manter a entrega restrita a documentos.

Aceite da etapa: documentos coerentes com o escopo, sem implementação, chamadas de modelos, dependências ou infraestrutura adicional. Relaciona-se a AC-14 (registro inicial das decisões); não conclui o critério inteiro.

Evidência: leitura integral do PRD e revisão dos dois documentos criados. Nenhum teste de aplicação executado, pois não há código implementado. O PRD foi preservado.

## Etapa 1 — Estrutura mínima e inspeção dos PDFs

### Implementação

- [x] Criar ambiente, dependências mínimas, exclusões do Git e exemplo de configuração sem segredos.
- [x] Criar FastAPI com `/health` e `/docs`.
- [x] Implementar extração por página, divisão e `--dry-run` sem gateway nem escrita no Qdrant.

### Validação obtida

- [x] Inspecionar textualmente início, meio e fim dos quatro PDFs; registrar páginas problemáticas, ausência de exclusões e limitações no README.
- [x] Verificar inicialização real da API com Uvicorn e testar divisão, preservação do texto e referências com dados sintéticos.
- [x] Executar dry-run real: quatro documentos, 257 páginas, 285 trechos previstos, zero falhas de leitura e nenhuma página completamente sem texto.
- [x] Executar 32 testes sem conexões externas; `pip check` sem incompatibilidades declaradas.
- [x] Verificar exclusões com `git check-ignore` em repositório temporário isolado.

### Limitações e pendências da inspeção

- [ ] Conferir visualmente páginas com pouco texto, imagens e disposição de tabelas/colunas; não há renderizador de PDF instalado neste ambiente. A inspeção realizada foi textual.
- [ ] Resolver ou aceitar explicitamente as perdas de extração antes de indexar: 402 caracteres NUL/U+FFFD e sumários com ordem prejudicada. Alternativa apresentada: avaliar `pdfplumber`; nenhuma troca ou biblioteca adicional aplicada.
- [x] Inicializar repositório Git local por solicitação explícita em 27/10/2026: branch `main`, sem commits nem arquivos adicionados ao índice. `git status`, `git branch --show-current`, `git ls-files` e `git check-ignore` confirmaram o estado inicial e as exclusões de `.env`, `.venv/` e `data/`.
- [ ] Auditar os arquivos selecionados antes do primeiro commit; ainda não há conteúdo versionado nem histórico para auditar.

Evidências de 27/10/2026: Python 3.12.3; FastAPI 0.162.0, Uvicorn 0.54.0, Pydantic 2.14.1, pypdf 6.21.3, pytest 9.1.1 e httpx 0.28.1. `python -m pytest -q`: **32 passed**, com aviso de depreciação de httpx no TestClient. Os 31 testes de processamento/CLI passaram no sandbox; suíte completa e HTTP local exigiram execução fora dele por restrição de sockets. Uvicorn respondeu 200 em `/health`, `/docs` e `/openapi.json` e foi encerrado. Nenhuma chamada de modelos, embedding, gravação vetorial ou publicação. Renderização visual do Swagger não verificada. Totais por documento, amostras e páginas problemáticas estão no [README](README.md).

Aceite: API inicia; dry-run não consome modelos; trechos mantêm documento e página; alternativa de extração é apresentada antes de trocar a biblioteca, se necessário.
Critérios relacionados: AC-01 e AC-02 (preparação parcial), AC-08 (documentação inicial), AC-09, AC-12 e AC-13 (parciais).

## Etapa 2 — Confirmar o contrato do gateway

- [x] Implementar `gateway.py` e `scripts/check_gateway.py`, sem execução automática.
- [x] Planejar até quatro chamadas pequenas: dois embeddings sintéticos (`search_document` e `search_query`) e um streaming por modelo, nessa ordem, com retentativas e redirecionamentos desativados. Execução real somente após autorização conforme seção 15; ainda não executada.
- [x] Testar o SDK instalado com HTTP simulado: payloads, ordenação/validação dos vetores, ambos os modelos, leitura incremental, falhas, timeout, cancelamento, fechamento e proteção dos relatórios.
- [x] Documentar comando opt-in, variáveis obrigatórias/opcionais e contrato candidato no README e em `.env.example`; modo sem `--execute` mostra apenas o plano, sem ler credenciais.
- [ ] Confirmar endereço, autenticação, limite de saída, `search_document`/`search_query`, dimensão, formato de retorno e streaming.
- [ ] Documentar contrato observado; interromper trabalho dependente se houver incompatibilidade não resolvida.

Evidências de 28/10/2026: SDK OpenAI **2.29.0** instalado e fixado, com `httpx 0.28.1` promovido a dependência direta de execução. Assinaturas e recursos assíncronos conferidos no código instalado e documentação oficial. O contrato candidato utiliza Bearer, `max_completion_tokens`, `encoding_format="float"` e `extra_body.input_type`; sua aceitação real não foi confirmada. O adaptador valida o JSON vetorial antes da conversão permissiva do SDK. `python -m scripts.check_gateway` executado somente no modo de plano, sem rede. `python -m pytest -q`: **97 passed** (32 existentes e 65 novos), com o aviso de depreciação do TestClient já conhecido. `pip check` sem incompatibilidades declaradas; `git diff --check` sem problemas. A suíte usa credencial sintética e `httpx.MockTransport`, mantendo a fixture que bloqueia conexões externas; sockets internos de asyncio/TestClient exigiram execução fora do sandbox. Nenhuma chamada real, leitura de credenciais privadas, ingestão, Qdrant, publicação ou commit nesta entrega. Histórico anterior preservado.

O comando real preparado é `python -m scripts.check_gateway --execute`: no máximo **4 requisições**, sem repetição automática; duas gerações solicitam no máximo 600 tokens de saída cada (ou limite configurado menor). Exige `LLM_BASE_URL` e `LLM_API_KEY` exportadas; demais padrões e carregamento manual de `.env` estão no README. `EMBEDDING_DIMENSION` deve permanecer vazia até medição real. Respostas simuladas não concluem o aceite de compatibilidade; a parte dependente da integração permanece pendente.

Aceite: compatibilidade comprovada e parâmetros documentados antes de ingestão completa; sem simular uma integração concluída.
Critérios relacionados: AC-05 e AC-06 (compatibilidade preliminar), AC-09, AC-14 (registro do contrato).

## Etapa 3 — Indexar e recuperar

- [x] Implementar Qdrant local/remoto, validação de coleção/dimensão, IDs determinísticos, retomada e lotes de até 16; sem dimensão presumida e sem apagar/recriar coleções existentes.
- [x] Revisar dry-run e quantidade prevista de chamadas: quatro PDFs, 257 páginas, 285 trechos, teto de 18 chamadas de embeddings de documentos; nenhuma ingestão real executada.
- [x] Conferir relatório e rastreabilidade com quatro PDFs sintéticos e armazenamento temporário; contagens reais de extração reconferidas, sem indexação.
- [ ] Conferir relatório de ingestão e rastreabilidade dos quatro PDFs reais após resolver os pré-requisitos e autorizar execução.
- [x] Verificar com substitutos que repetir a ingestão não duplica pontos nem recalcula embeddings persistidos; retomada após falha, preservação de dados em incompatibilidades e fechamento de clientes verificados.
- [x] Criar oito perguntas respondíveis, duas por documento, em `evals/retrieval.json`; páginas físicas conferidas por leitura textual dos PDFs em 28/10/2026, com elementos esperados e limitações. Sem trechos extraídos versionados; conferência visual geral segue pendente.
- [x] Implementar avaliação opt-in apenas da recuperação e testar sua apuração com vetores sintéticos, sem declarar relevância real.
- [ ] Executar avaliação real e verificar fonte pertinente no top-4 em pelo menos sete das oito perguntas, ou justificar ajustes; requer ingestão completa e autorização.
- [x] Implementar `/ready`, sem consumir modelos: 200 para coleção compatível/completa; 503 público e sem detalhes privados em configuração ausente, coleção ausente/parcial/incompatível ou falha de acesso.

Evidências de 28/10/2026: `qdrant-client==1.19.1` instalado e fixado, sem FastEmbed, servidor local ou outro SDK de modelos. Recursos assíncronos, metadados e persistência conferidos no código instalado, documentação oficial e testes. `python -m pytest -q`: **138 passed** (97 anteriores e 41 novos), com o aviso conhecido de depreciação do TestClient. A suíte usa PDFs/vetores/credenciais sintéticos, `httpx.MockTransport` para gateway e REST do Qdrant e armazenamento local temporário; bloqueio de conexões externas preservado. Execução fora do sandbox necessária para sockets internos de asyncio/TestClient. Persistência após reabertura, IDs/payloads, lotes, retomada parcial, zero embeddings na repetição completa, rejeição de dimensão/modelo/versão/distância/documentos incompatíveis, contagens por documento, proteção dos relatórios, indicação de variáveis inválidas sem valores e ciclo de vida do cliente da API verificados. `pip check` sem incompatibilidades; `git diff --check` sem problemas.

`python -m scripts.ingest --dry-run` executado nos PDFs locais, sem gateway/Qdrant, reconfirmando os totais 71/60/74/80 trechos por documento. `python -m scripts.check_retrieval` executado somente no modo de plano, sem ler credenciais. Comandos reais preparados no README: compatibilidade prévia `python -m scripts.check_gateway --execute` (**até 4 chamadas**, duas de embeddings e duas gerações); após revisão da extração, ingestão `python -m scripts.ingest --execute --gateway-verified --extraction-reviewed --max-embedding-calls 18` (**até 18 embeddings**); avaliação `python -m scripts.check_retrieval --execute --gateway-verified` (**até 8 embeddings de perguntas**, zero geração). Total da Etapa 3: **até 26 chamadas de embeddings**; incluindo a compatibilidade pendente: **até 30 chamadas ao gateway**. Operações Qdrant: até 47 na ingestão inicial e 71 na avaliação (locais ou REST conforme modo); `/ready` acrescenta até sete por requisição, sem modelos. As opções de confirmação atestam revisões já realizadas, sem substituí-las.

Limites: gateway, dimensão medida, servidor Qdrant remoto, ingestão privada e meta semântica **ainda não verificados**. As páginas usadas nos casos foram conferidas textualmente; as perdas de extração e a revisão visual da base continuam pendentes. Nenhuma leitura de credenciais privadas por ferramentas, chamada real de modelo, indexação dos PDFs reais, publicação ou commit nesta entrega. PRD e histórico preservados.

Aceite: quatro documentos processados; retomada verificada; fonte pertinente entre os quatro primeiros resultados em pelo menos sete das oito perguntas, ou ajustes justificados e registrados.
Critérios relacionados: AC-01, AC-02, AC-03, AC-09, AC-10 (falhas da base), AC-14 (resultados de recuperação).

## Etapa 4 — Resposta JSON e escolha do modelo

- [x] Implementar `/models` com lista/padrão da configuração, sem consultar o gateway; `/chat` com contratos e preparação de RAG compartilhável com a futura SSE.
- [x] Implementar contexto de até 8.000 caracteres, deduplicação exata, IDs/fontes por documento e página física, excertos de até 600 caracteres e instruções educacionais com citações e insuficiência de informação.
- [x] Acrescentar Bearer opcional no desenvolvimento e exigido quando configurado, suporte a Authorize no Swagger, validação estrita e erros públicos 401/422/502/503/504 sem detalhes privados.
- [x] Compartilhar e fechar clientes no lifespan; acumular JSON pelo adaptador de geração existente, preservando `stop`/`length`, sem segunda integração ou histórico.
- [x] Testar ambos os modelos e padrão alternativo pelo SDK com HTTP simulado; rejeitar corpo/modelo/autenticação inválidos antes de prontidão, embedding, busca e geração.
- [x] Verificar contratos, esquema OpenAPI, fontes, independência, contexto vazio sem geração, falhas do Qdrant/gateway, timeout por chamada, fechamento e logs sem conteúdo privado com substitutos.
- [x] Documentar configuração, caminho da pergunta e teste JSON no Swagger/terminal no README; preservar a restrição de zero chamadas reais, sem ingestão ou publicação.
- [ ] Conferir visualmente Swagger/Authorize no navegador e resposta/fontes com base/gateway reais após resolver pré-requisitos e autorizar consumo. HTML e esquema foram verificados em memória; não equivalem a essa conferência.

Evidências de 28/10/2026: `python -m pytest -q`: **209 passed** (138 anteriores e 71 novos), com o aviso conhecido de depreciação do TestClient. A suíte completa executou fora do sandbox para permitir sockets internos de asyncio/TestClient, mantendo a fixture que bloqueia conexões externas. As fixtures da API substituem também os carregadores de configuração, sem ler credenciais reais; Qdrant remoto é substituído e o gateway passa pelo SDK real com `httpx.MockTransport`. Foram verificados os dois identificadores, padrão inicial/alternativo, pergunta normalizada de até 1.500 caracteres, tipos/campos inválidos, fontes e deduplicação, limite do contexto/excertos, ausência de geração sem fontes, base indisponível sem consumo, falhas na busca, HTTP/limite/conexão/timeout do provedor, JSON/delta/término malformados, interrupção durante leitura sem resposta parcial e fechamento dos recursos. `length` é preservado e motivos de ferramentas/filtro não viram sucesso. Logs de aplicação foram conferidos sem perguntas, respostas, trechos ou tokens sintéticos. `pip check`: sem incompatibilidades declaradas; `git diff --check`: sem problemas.

Limites: não houve chamada real, ingestão privada, publicação, criação de commit ou alteração de PRD/AGENTS. Não foi realizada avaliação semântica dos prompts ou das respostas reais. O teste manual preparado para Swagger consiste em **três consultas** (dois modelos explícitos e padrão omitido), com teto de **6 chamadas ao gateway** (3 embeddings e 3 gerações de até `MAX_OUTPUT_TOKENS` cada), ainda não executadas. A confirmação prévia do gateway e a base completa continuam necessárias. Timeout **total**, concorrência/429 da aplicação, desconexão do consumidor e rota SSE permanecem na Etapa 5; nesta etapa há timeout separado de embedding/geração e fechamento de seus recursos.

Aceite: resposta JSON e fontes disponíveis; modelos não permitidos rejeitados; falta de conteúdo diferenciada de falha de infraestrutura.
Critérios relacionados: AC-03, AC-04, AC-05, AC-07, AC-08, AC-09 e AC-10 (parcial).

## Etapa 5 — Streaming e controle de execução

- [ ] Esclarecer a inconsistência SSE registrada abaixo antes de implementar o comportamento afetado.
- [ ] Implementar `/chat/stream` reutilizando recuperação e geração de `/chat`.
- [ ] Implementar eventos, timeout total, limite de concorrência, cancelamento e fechamento de recursos.
- [ ] Criar cliente de verificação e exemplos com `curl -N`.
- [ ] Verificar ordem/serialização dos eventos, fontes equivalentes entre rotas, erro terminal sem `done` posterior e liberação de recursos.
- [ ] Comprovar entrega progressiva em conexão HTTP real com Uvicorn e provedor substituto com intervalos controlados.

Aceite: fragmentos chegam antes da conclusão; falhas após o início produzem `error`; desconexões liberam recursos; fluxo de RAG permanece único.
Critérios relacionados: AC-04, AC-06 (local), AC-09, AC-10 e AC-13 (exemplos de consumo).

## Etapa 6 — Avaliar respostas e concluir documentação

- [ ] Completar 12 casos com referências revisadas: oito respondíveis, dois sem suporte, uma tentativa de alterar instruções e uma solicitação clínica individual.
- [ ] Após planejar chamadas e obter autorização, avaliar o conjunto com o modelo padrão e duas perguntas com o alternativo; repetir somente casos afetados por correções.
- [ ] Verificar fundamentação, reconhecimento de falta de suporte, preservação das instruções e ausência de diagnóstico/prescrição individual conforme seção 12.2.
- [ ] Completar testes de erros, autenticação, limites e encerramento de recursos com substitutos.
- [ ] Completar README com instalação, ingestão, configuração, testes, consumo, decisões, limitações, resultados e uso de IA.
- [ ] Conferir segredos e artefatos privados no conteúdo versionado e histórico disponível.

Aceite: metas da seção 12.2 atendidas e registradas; outra pessoa consegue executar o projeto pelas instruções.
Critérios relacionados: AC-04, AC-05, AC-07, AC-08, AC-09, AC-10, AC-12, AC-13 e AC-14.

## Etapa 7 — Publicar e verificar

- [ ] Confirmar condições gratuitas de Qdrant Cloud e Render e documentar limites/inatividade.
- [ ] Preparar coleção remota validada e configuração com credenciais adequadas, sem ingestão no build/startup e com um worker.
- [ ] Publicar somente quando solicitado pelo responsável pelo projeto.
- [ ] Verificar `/health`, `/ready`, `/models`, `/docs`, consulta autenticada e streaming real na URL publicada.
- [ ] Reiniciar e confirmar preservação da base sem nova geração de embeddings.
- [ ] Revisar AC-01 a AC-14 e registrar evidências e limitações no README.

Aceite: API publicada utiliza a base remota previamente preparada após reinicialização; streaming comprovado no ambiente publicado.
Critérios relacionados: todos os critérios AC-01 a AC-14, com verificação específica de AC-06 e AC-11 na publicação.

## Decisões técnicas aprovadas no PRD

Estas são escolhas da especificação, não evidências de compatibilidade já verificada.

| Decisão | Referência e motivo |
| --- | --- |
| Python, FastAPI, Uvicorn e Pydantic; Swagger como interface inicial | Seções 1, 5 e 16: API HTTP sem frontend próprio. |
| RAG com funções e um fluxo compartilhado por JSON/SSE; perguntas independentes | Seções 2, 3, 6, 8 e 16: sequência explícita, sem memória, agentes ou camadas preventivas. |
| SDK da OpenAI para o gateway; adaptações em `gateway.py` | Seções 4.2 e 5: uma integração para `azure/gpt-5-mini` (padrão), `azure/gpt-6-luna` e `cohere/embed-v4.0`. Parâmetros ainda serão confirmados. |
| `pypdf`, limpeza conservadora e trechos dentro de cada página física, a partir de 1 | Seções 4.1, 5 e 7: referências conferíveis; sem reescrita por LLM nem OCR no escopo atual. |
| Ingestão manual separada, dry-run, IDs determinísticos e retomada | Seção 7: evitar geração repetida e duplicação; mudanças incompatíveis exigem nova versão, sem apagar coleções automaticamente. |
| Qdrant local no desenvolvimento e Cloud na publicação; busca por cosseno | Seções 3, 5.1 e 13: único armazenamento, persistência remota fora do disco efêmero do Render; um processo por diretório local. |
| Clientes externos assíncronos compartilhados no ciclo de vida da API | Seção 6: reutilizar recursos e fechá-los no encerramento. |
| SSE com `StreamingResponse` e verificação HTTP real | Seções 9 e 10: entrega progressiva verificável, sem usar Swagger como prova de streaming. |
| Token simples na publicação, limites, logs mínimos e sem retentativas automáticas iniciais | Seção 11: controlar exposição e consumo sem armazenar conteúdo sensível. |
| `venv`/`pip`, `pytest`/`httpx`, fixtures sintéticas e substitutos | Seções 5 e 12: versões verificadas e testes comuns sem credenciais ou gasto de modelos. |
| Avaliação manual com fontes e propósito educacional | Seções 8.1 e 12: conferir suporte factual, sem diagnóstico ou prescrição individual. |
| Render gratuito com um worker, Qdrant remoto e publicação sob solicitação | Seções 11 e 13: preservar a base entre reinicializações sem infraestrutura adicional. |

Os tamanhos e limites das seções 7, 8 e 11 são pontos de partida, não valores otimizados. Não definir limiar de similaridade ou dimensão de embedding por suposição.

## Inconsistência concreta e esclarecimento pendente

- **Seção 9.4 — origem de `delta`:** uma regra restringe `delta` a fragmentos recebidos do gateway; outra exige um `delta` com explicação local quando não há contexto, sem geração externa. As duas regras precisam ser conciliadas antes da implementação afetada na Etapa 5. Possível esclarecimento a confirmar: explicitar que a explicação local de insuficiência de contexto é uma exceção à regra de origem do `delta`. Nenhuma alteração do contrato foi aprovada ou aplicada nesta etapa. Isso não bloqueia a documentação da Etapa 0.

## Verificações técnicas pendentes

- [x] **Inspeção textual dos PDFs — Etapa 1:** quatro arquivos fornecidos em `data/raw/`; 65/53/63/76 páginas e 71/60/74/80 trechos, respectivamente na ordem do PRD. Amostras e limitações registradas no README; nenhuma exclusão aplicada.
- [ ] **Qualidade da extração — antes de indexar:** revisar visualmente páginas de pouco texto e resolver/aceitar os glifos suspeitos e a ordem dos sumários. A leitura textual e o código 0 do dry-run não comprovam completude da base.
- [ ] **Gateway — Etapa 2:** adaptador e comando implementados e verificados com HTTP simulado. Confirmar contrato efetivo, streaming dos dois modelos, parâmetros de saída e encaminhamento dos tipos de entrada Cohere com até quatro chamadas pequenas; execução real ainda não autorizada nem realizada nesta entrega.
- [ ] **Dimensão dos embeddings — Etapa 2:** medir a dimensão retornada para documento e pergunta e registrar compatibilidade; validar lotes e coleção na Etapa 3. Nenhum valor presumido.
- [x] **Versões mínimas — Etapa 1:** dependências diretas fixadas após 32 testes e `pip check`; aviso do TestClient documentado, sem adicionar httpx2.
- [x] **SDK e recursos assíncronos — Etapa 2:** OpenAI 2.29.0 verificado com HTTP simulado, `AsyncOpenAI`, `extra_body`, streaming e fechamento assíncrono. Retentativas desativadas. Compatibilidade com o gateway real continua pendente.
- [x] **Cliente Qdrant — Etapa 3:** versão 1.19.1 instalada e fixada; recursos assíncronos, persistência/metadados locais e REST simulada verificados. A compatibilidade do servidor remoto real (incluindo metadados de coleção) segue pendente.
- [ ] **Serviços gratuitos — Etapa 7:** confirmar limites e políticas vigentes ao preparar a publicação e documentar recuperação/reingestão. Nenhuma infraestrutura criada na Etapa 0.
