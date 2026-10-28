# Checklist de execução

Fonte: [PRD.md](PRD.md), seções 14–16. Os IDs AC remetem aos critérios gerais de aceite da seção 14; sua associação a uma etapa não significa que já foram atendidos. Cada etapa exige solicitação própria.

Estado atual: **Etapa 6 preparada, documentada e validada com substitutos; avaliação real pendente, sem autorização de consumo**. Etapas 1–5 implementadas, incluindo streaming por HTTP real local com provedor substituto. Gateway/dimensão, revisão da extração, ingestão, recuperação e respostas reais continuam pendentes; esses pré-requisitos não foram presumidos como concluídos. Etapa 7 não iniciada. Os critérios gerais seguem parciais, conforme as evidências abaixo.

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
- [ ] Auditar os arquivos selecionados antes do primeiro commit; esta era uma pendência histórica da Etapa 1. A auditoria posterior da Etapa 6 foi executada sobre os cinco commits já existentes e não constitui evidência retroativa de revisão anterior ao primeiro commit.

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

- [x] Revisar a implementação da Etapa 4: preparação de contexto e adaptador reutilizáveis; 209 testes anteriores passaram antes das alterações. Sem bloqueio para implementação/validação com substitutos. Gateway/base reais permanecem pendentes, sem evidência inventada.
- [x] Esclarecer a inconsistência SSE: o item 3 do escopo solicitado nesta etapa exige explicitamente a explicação local em `delta`, sem geração, e resolve a exceção à regra de origem no gateway. PRD preservado; decisão registrada abaixo.
- [x] Implementar `/chat/stream` reutilizando admissão, preparação, recuperação, contexto, seleção e abertura/validação da geração de `/chat`; JSON mantém contrato e acumula somente seus próprios fragmentos.
- [x] Implementar `sources`, deltas não vazios, terminal `done`/`error`, JSON serializado, cabeçalhos sem cache e ausência de geração sem contexto. Falhas na abertura retornam HTTP; falhas na leitura usam SSE sem mudar o status e sem `done` posterior.
- [x] Implementar prazo total absoluto, capacidade compartilhada sem fila e rejeição antes de chamadas externas; cancelamento por desconexão durante preparação, JSON e SSE; fechamento aguardado e liberação em conclusão, erro, timeout ou cancelamento.
- [x] Criar `scripts/check_stream.py`, seguro em modo de plano, com opt-in de uma consulta, validação/tempos de eventos e relatórios sem conteúdo; exemplos `curl -N`, configuração e contratos no README/OpenAPI.
- [x] Verificar ordem/serialização, Unicode/aspas/quebras de linha, fragmentos vazios, fontes equivalentes, contexto vazio, `length`, modelos/padrão/autenticação, falhas pré-cabeçalhos e durante leitura, limpeza, logs e regressão JSON com substitutos.
- [x] Comprovar entrega progressiva em conexão HTTP real com Uvicorn e gateway substituto controlado, mantendo o provedor em andamento até o cliente receber o primeiro delta; fechar servidor e conexões ao final.

Evidências de 28/10/2026: `python -m pytest -q --tb=short --maxfail=3`: **297 passed** (209 anteriores e 88 novos), com o aviso conhecido de depreciação do TestClient. A suíte precisou executar fora do sandbox por restrição de sockets internos/loopback; a fixture padrão continua proibindo conexões externas. Somente os **14 testes HTTP** usam uma exceção explícita restrita a `127.0.0.1`, com Uvicorn em porta temporária e gateway pelo SDK real + `httpx.MockTransport`; configuração, token e Qdrant são sintéticos. Nenhuma credencial real é lida pelas fixtures. A prova de progresso recebeu `sources` e o primeiro `delta` enquanto o provedor ainda aguardava um sinal e não tinha concluído; somente após esse recebimento o teste aguardou 80 ms e liberou o restante. Em uma execução registrada, primeiro delta em **0,056 s** e `done` em **0,138 s** após iniciar o cliente (medição local ilustrativa, não benchmark).

A validação inclui capacidade compartilhada nas duas direções (JSON/SSE), 429 sem novas operações externas, desconexão nas quatro fases pré-cabeçalhos (prontidão, embedding, busca e abertura) e durante a geração de ambas as rotas, além de timeout real por HTTP. O fechamento assíncrono do provedor é aguardado, a vaga pode ser reutilizada e o servidor encerra sem tarefas órfãs. Testes adicionais de ASGI 2.3/2.4 cobrem saída antes da primeira iteração, cancelamento de tarefa, falha/espera na escrita e erro no fechamento. Erros terminais usam somente códigos/mensagens públicos; não há nova geração, fallback ou `done` após falha. O timeout total utiliza o mesmo instante limite na preparação e no envio, em vez de renovar o orçamento a cada fase.

`python -m scripts.check_stream` foi executado **somente no modo de plano**, sem rede ou leitura de token. O cliente `check_stream` também foi exercitado por HTTP real contra o substituto, observando o delta antes da liberação do provedor, com instantes UTC/tempo decorrido e sem imprimir pergunta, resposta, fontes ou credenciais. `pip check`: sem incompatibilidades declaradas (aviso de cache não gravável no sandbox); `git diff --check`: sem problemas. Dependências, PRD e AGENTS preservados. Nenhum modelo real, ingestão, publicação, commit ou alteração das Etapas 6–7.

Limitações: compatibilidade/streaming dos dois modelos e dimensão reais, revisão da extração, ingestão e qualidade semântica continuam pendentes. Swagger/OpenAPI foram verificados em memória, sem conferência visual no navegador, e não contam como prova de streaming. Buffering do proxy e entrega no ambiente publicado só serão verificados na etapa correspondente. Timeout/cancelamento são cooperativos; operações síncronas do Qdrant local não podem ser interrompidas enquanto bloqueiam o ciclo de eventos. O limite em memória exige um worker e não é uma cota global/financeira. A limpeza assíncrona é aguardada e pode acrescentar tempo ao encerramento após o prazo.

Comandos futuros preparados, **não executados com modelos reais**: cada `curl -N` ou `python -m scripts.check_stream --execute` representa uma consulta, com teto de **2 chamadas de modelos** (1 embedding e 1 geração de até `MAX_OUTPUT_TOKENS`). Executar os dois clientes equivale a até 4 chamadas, somente após pré-requisitos e autorização específica. A validação local sem consumo é `python -m pytest -q -s tests/test_stream_http.py`.

Aceite local: fragmentos chegam pela rede antes da conclusão; falhas após o início produzem `error`; desconexões liberam recursos; fluxo de RAG único e JSON preservado. Não conclui compatibilidade com serviços reais nem publicação.
Critérios relacionados: AC-04, AC-06 (local com substituto), AC-09, AC-10 e AC-13 (exemplos de consumo).

## Etapa 6 — Avaliar respostas e concluir documentação

### Preparação concluída

- [x] Conferir entregas anteriores antes de editar: suíte anterior com 297 testes aprovados; código e registros das Etapas 1–5 revisados. Bloqueios reais informados antes da implementação: gateway/dimensão, qualidade da extração e ingestão não confirmados. Sem contradição nova que exija alterar requisitos.
- [x] Completar 12 casos: R1–R8 preservadas em `evals/retrieval.json`; N1/N2/I1/C1 em `evals/behavior.json`. Perguntas, páginas esperadas, elementos mínimos, comportamento e critérios documentados em `evals/README.md`.
- [x] Reconferir textualmente as oito páginas físicas dos PDFs; guardar evidências integrais somente em `data/evals/stage6/references.json` (ignorado, modo 0600), com hashes dos quatro documentos. Triagem de N1/N2 sem ocorrências de PostgreSQL/B-tree/Netuno no texto das 257 páginas. Isso não certifica imagens/links nem substitui revisão visual.
- [x] Preparar `scripts/evaluate.py`, com plano seguro, fases de referências/recuperação/respostas/resumo, funções existentes do RAG, cache privado, ordem das fases, coleta separada da revisão humana e amostra alternativa R1/R7 escolhida antes da execução.
- [x] Planejar teto da avaliação: **12 embeddings de pergunta + 14 gerações**, sem retentativas; até `MAX_OUTPUT_TOKENS` por geração. Reutilizar as oito recuperações na coleta padrão e R1/R7 no alternativo. Não executar também `check_retrieval`, que repetiria embeddings. Repetições exigem casos explícitos e novo plano/autorização.
- [x] Completar README com instalação, configuração, preparação/ingestão, testes, autenticação/modelos, JSON/curl -N, base/páginas físicas, decisões, limitações, procedimento/resultados pendentes e uso de IA observado. Publicar somente metadados de resultados, sem prompts/trechos/respostas reais.

### Validação obtida sem modelos

- [x] Revisar cobertura prévia de contratos, erros, autenticação, limites e encerramento; preservar os testes JSON/SSE existentes. Acrescentar teste necessário de instrução dentro de documento mantida como dado, além dos testes do novo coletor e auditoria.
- [x] Executar suíte completa: **336 passed** (297 anteriores e 39 novos), com um aviso conhecido do TestClient. Nenhuma credencial real ou chamada de modelo na suíte; gateway HTTP simulado, Qdrant sintético/temporário e bloqueio de conexões externas preservados.
- [x] Verificar fases, teto/reutilização, ordem padrão/alternativo, falta de contexto sem geração, persistência privada, invalidação de contratos/documentos/prompts, conservação de tentativas, retomada sem repetição automática, aprovação humana separada por eixo e rejeição de saídas públicas/links simbólicos.
- [x] Executar os modos de plano e preparar as referências reais **localmente, sem modelos**. O resumo local informa zero casos recuperados e qualidade `pending`, com saída 1 esperada; não representa 0/8 medido nem resultado simulado de modelo.
- [x] Auditar árvore de trabalho não ignorada, índice (38 arquivos) e histórico local disponível: **5 commits**, **74 versões de blobs/caminhos**, **45 arquivos atuais**. Nenhum segredo/PDF/artefato privado encontrado pelos padrões verificados. Duas URLs sintéticas em testes de rejeição têm exceções exatas revisadas; nenhuma credencial real foi exibida. PDFs, `.env`, `.venv`, índices e evidências confirmados como ignorados por `git check-ignore`.
- [x] `pip check` sem incompatibilidades declaradas; `git diff --check` sem problemas. Dependências, PRD, AGENTS e histórico preservados, sem adição ao índice, commit ou publicação.

### Execução real e aceite pendentes

- [ ] Resolver/revisar ou aceitar explicitamente as perdas da extração e realizar a conferência visual geral antes da ingestão.
- [ ] Confirmar compatibilidade real do gateway e dimensão: teto separado de **2 embeddings + 2 gerações**; ingestão inicial: **até 18 embeddings** para os 285 trechos anteriores. As flags de confirmação não substituem essas verificações ou autorização.
- [ ] Após pré-requisitos e autorização específica, avaliar recuperação R1–R8: fonte pertinente no top-4 em ao menos 7/8, ou registrar ajustes justificados; conferir utilidade do trecho além do acerto de página.
- [ ] Coletar os 12 casos no padrão e R1/R7 no alternativo; revisar todas as afirmações materiais, fontes/páginas, completude, limites e segurança conforme seção 12.2. Registrar identificação/data/notas na revisão privada e resultados públicos somente após conferência.
- [ ] Corrigir falhas reais observadas com mudanças pequenas e repetir apenas os casos afetados após autorização. Não houve avaliação real ou falha semântica observada que justificasse modificar prompt, perguntas, gabaritos ou limiar nesta entrega.

Evidências de **28/10/2026**: `.venv/bin/python -m pytest -q --tb=short --maxfail=3`: **336 passed, 1 warning, 9,72 s**. Após os ajustes finais do coletor/auditoria, os testes pertinentes de avaliação, auditoria e prompts foram repetidos: **42 passed, 1 warning, 2,82 s**. Execução fora do sandbox por restrição de sockets internos e loopback; os 14 testes HTTP controlados continuam restritos a `127.0.0.1`, sem provedor real. Os 39 novos testes verificam infraestrutura/contratos com substitutos, não comportamento semântico dos modelos. `python -m scripts.audit_git`: `no_findings`, com limites heurísticos explícitos, sem sondar credenciais, buscar remotos ou reescrever histórico. A revisão documental e textual das apostilas é evidência distinta dos testes automatizados. A auditoria não garante ausência de formatos desconhecidos, objetos inacessíveis ou histórico remoto não disponível.

Comandos reais preparados em [evals/README.md](evals/README.md): primeiro `python -m scripts.evaluate --phase retrieval --execute --gateway-verified --extraction-reviewed` (**até 8 embeddings**); depois `--phase answers` com as mesmas confirmações (**até 4 embeddings novos + 12 gerações**); por último `--phase answers --model alternate` (**zero embeddings novos + 2 gerações**). Após a revisão humana, `python -m scripts.evaluate --phase summary --execute` não consome modelos e só retorna sucesso com todos os critérios. Teto conjunto incluindo compatibilidade e ingestão inicial pendentes: **32 embeddings + 16 gerações (48 chamadas)**, sem execução nesta entrega. Não repetir verificações manuais antigas adicionalmente sem novo plano de consumo.

Resultados disponíveis em [evals/results.md](evals/results.md): preparação validada, resultados semânticos **pendentes**. Limitações mantidas: conjunto pequeno, glifos/ordem de extração, ausência de interpretação de imagens/áudio/vídeo, trechos separados por página, ausência de limiar calibrado e dependência da revisão humana. A etapa foi encerrada no escopo autorizado sem modelos; o aceite real da seção 12.2 **não está concluído**. Não avançar para publicação.

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

## Inconsistência concreta e esclarecimento da Etapa 5

- **Seção 9.4 — origem de `delta`:** a regra geral restringe deltas a fragmentos do gateway, mas o caso sem contexto exige explicação local sem geração. **Esclarecido pela solicitação explícita da Etapa 5 em 28/10/2026, item 3:** enviar fontes vazias, explicação em `delta` e `done` com `insufficient_context`, sem chamar o modelo de geração. A explicação local é, portanto, a exceção autorizada à origem no gateway. Implementação, documentação e testes seguem esse escopo; PRD não foi alterado silenciosamente.

## Verificações técnicas pendentes

- [x] **Inspeção textual dos PDFs — Etapa 1:** quatro arquivos fornecidos em `data/raw/`; 65/53/63/76 páginas e 71/60/74/80 trechos, respectivamente na ordem do PRD. Amostras e limitações registradas no README; nenhuma exclusão aplicada.
- [ ] **Qualidade da extração — antes de indexar:** revisar visualmente páginas de pouco texto e resolver/aceitar os glifos suspeitos e a ordem dos sumários. A leitura textual e o código 0 do dry-run não comprovam completude da base.
- [ ] **Gateway — Etapa 2:** adaptador e comando implementados e verificados com HTTP simulado. Confirmar contrato efetivo, streaming dos dois modelos, parâmetros de saída e encaminhamento dos tipos de entrada Cohere com até quatro chamadas pequenas; execução real ainda não autorizada nem realizada nesta entrega.
- [ ] **Dimensão dos embeddings — Etapa 2:** medir a dimensão retornada para documento e pergunta e registrar compatibilidade; validar lotes e coleção na Etapa 3. Nenhum valor presumido.
- [x] **Versões mínimas — Etapa 1:** dependências diretas fixadas após 32 testes e `pip check`; aviso do TestClient documentado, sem adicionar httpx2.
- [x] **SDK e recursos assíncronos — Etapa 2:** OpenAI 2.29.0 verificado com HTTP simulado, `AsyncOpenAI`, `extra_body`, streaming e fechamento assíncrono. Retentativas desativadas. Compatibilidade com o gateway real continua pendente.
- [x] **Cliente Qdrant — Etapa 3:** versão 1.19.1 instalada e fixada; recursos assíncronos, persistência/metadados locais e REST simulada verificados. A compatibilidade do servidor remoto real (incluindo metadados de coleção) segue pendente.
- [ ] **Serviços gratuitos — Etapa 7:** confirmar limites e políticas vigentes ao preparar a publicação e documentar recuperação/reingestão. Nenhuma infraestrutura criada na Etapa 0.
