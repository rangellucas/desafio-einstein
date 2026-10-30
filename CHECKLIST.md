# Checklist de execução

Requisitos e critérios de aceite: [PRD](PRD.md), seções 12–16. Instruções de execução: [README](README.md).

**Estado em 29/10/2026:** etapas 0–7 e documentação concluídas. A revisão dos PDFs, a avaliação e as verificações da publicação foram confirmadas pelo responsável; os resultados estão consolidados em [evals/results.md](evals/results.md). Essa confirmação atualiza os registros anteriores de pendência, sem nova execução pelo agente. API: [desafio-einstein.onrender.com](https://desafio-einstein.onrender.com/) · [Swagger](https://desafio-einstein.onrender.com/docs).

**Incremento em 30/10/2026:** interface mínima `/teste` implementada localmente conforme solicitação própria. Testes sem modelos aprovados; validação visual no navegador pendente. A página ainda não foi publicada. Detalhes e limites nas evidências ao final.

## Etapas

- [x] **0 — Requisitos e instruções:** PRD, AGENTS e checklist definidos, com escopo, contratos e critérios de aceite. AC-14.
- [x] **1 — Estrutura e PDFs:** FastAPI, configuração, exclusões do Git, extração por página e dry-run. Inspeção textual registrada; revisão visual e aceite das perdas confirmados pelo responsável. AC-01, AC-02, AC-08, AC-09, AC-12 e AC-13.
- [x] **2 — Gateway:** SDK OpenAI para os dois modelos, embeddings de documento/pergunta e streaming. Verificação manual do gateway informada como aprovada, com dimensão 1536. AC-05, AC-06, AC-09 e AC-14.
- [x] **3 — Indexação e recuperação:** Qdrant local/remoto, IDs determinísticos, retomada, validação da coleção e `/ready`. Base local conferida; ingestão e recuperação reais confirmadas. AC-01, AC-02, AC-03, AC-09, AC-10 e AC-14.
- [x] **4 — JSON e modelos:** `/models`, `/chat`, fontes por documento/página, autenticação, validação e erros. Teste manual da API e conferência do Swagger confirmados pelo responsável. AC-03, AC-04, AC-05, AC-07, AC-08, AC-09 e AC-10.
- [x] **5 — Streaming:** `/chat/stream` compartilha o RAG com JSON; eventos, timeout total, concorrência e cancelamento implementados. Entrega progressiva comprovada por HTTP local com provedor controlado. AC-04, AC-06, AC-09, AC-10 e AC-13.
- [x] **6 — Avaliação e documentação:** 12 casos, amostra alternativa, coletor, revisão das respostas e auditoria. Conclusão da avaliação e das revisões confirmada pelo responsável e consolidada no relatório. AC-04, AC-05, AC-07, AC-08, AC-09, AC-10, AC-12, AC-13 e AC-14.
- [x] **7 — Publicação:** configuração Render, transferência dos vetores e diagnósticos preparados. Publicação, verificações remotas e preservação da base após reinício confirmadas pelo responsável. Abrange AC-01 a AC-14, com foco em AC-06 e AC-11.

Cada nova alteração ou execução exige solicitação própria. Concluir uma etapa não autoriza consumo adicional de modelos, reingestão ou publicação.

## Evidências principais

| Verificação | Evidência registrada |
| --- | --- |
| PDFs | Quatro documentos, 257 páginas e 285 trechos, sem exclusões na extração inicial. Detectados 402 caracteres NUL/U+FFFD e problemas de ordem nos sumários; revisão/aceite posterior confirmado pelo responsável. |
| Gateway | Verificação manual informada como aprovada: dois embeddings com dimensão 1536 e streaming dos dois modelos com término `stop`. |
| Base local | Coleção `saude_mental_v1`, `cohere/embed-v4.0`, dimensão 1536 e cosseno. Os 285 payloads foram conferidos contra os PDFs atuais; contagens por documento: 71/60/74/80, na ordem do PRD. |
| Recuperação | Último resultado numérico registrado: 7/8 fontes esperadas no top-4, R7 sem acerto. A conclusão posterior da avaliação foi informada pelo responsável, sem novas métricas nesta revisão. |
| Testes automatizados | Última suíte completa registrada: **387 aprovados**, com um aviso conhecido do TestClient. Gateway simulado, Qdrant temporário e conexões externas bloqueadas; testes HTTP restritos a loopback. Não equivalem à avaliação semântica. |
| Streaming local | Uvicorn e provedor controlado: o cliente recebeu `sources` e o primeiro `delta` enquanto a geração ainda aguardava liberação. Testes em [tests/test_stream_http.py](tests/test_stream_http.py). |
| Qdrant Cloud | Relatório remoto identificou `missing_payload_index` em `document_name`. Correção prepara quatro índices `keyword`, sem regravar vetores; **24 testes** específicos aprovados no ajuste. Verificação remota posterior confirmada pelo responsável. |
| Publicação | API no Render, com `/health`, `/ready`, `/models`, Swagger, autenticação, JSON/SSE e integridade após reinício confirmados pelo responsável. URL fornecida e registrada no README e no relatório. |
| Dependências e privacidade | `pip check` aprovado e auditoria local anterior com `no_findings`; `.env`, PDFs, índices e evidências privadas ignorados. A auditoria é heurística e limitada ao histórico local disponível. |

As contagens acima são evidências anteriores, não testes executados nesta revisão documental. O procedimento e os critérios de avaliação estão em [evals/README.md](evals/README.md); o [relatório](evals/results.md) distingue medições registradas de conclusões confirmadas pelo responsável.

## Decisões mantidas

- Python, FastAPI, Pydantic, Uvicorn e SDK OpenAI direto; funções para o fluxo fixo de RAG, sem framework de orquestração.
- `pypdf` com limpeza conservadora e trechos dentro da página física, contada a partir de 1. Sem OCR, interpretação de imagens ou reescrita das apostilas por LLM.
- Qdrant local no desenvolvimento e Cloud na publicação; ingestão manual, separada do startup e das consultas. Coleções incompatíveis são preservadas e exigem nova versão.
- JSON e SSE usam a mesma recuperação e geração. Clientes assíncronos compartilhados, um worker, timeout total e limite de concorrência por processo.
- Token obrigatório no Render, credencial de consulta no Qdrant para a API e ausência de logs de perguntas, respostas, prompts e credenciais por padrão.
- Avaliação com fontes e revisão humana, sem LLM avaliador. Similaridade não comprova fundamentação; não há limiar calibrado.

**Exceção SSE esclarecida na Etapa 5:** sem contexto, a API envia fontes vazias, explicação local em `delta` e `done` com `insufficient_context`, sem geração externa. Essa exceção à origem dos deltas no gateway foi autorizada no escopo da etapa; o PRD foi preservado.

## Fechamento documental

- [x] Atualizar [evals/results.md](evals/results.md) e [evals/README.md](evals/README.md) com o estado final confirmado, preservando a origem das evidências e os conteúdos privados.
- [x] Registrar a URL pública da API e do Swagger no README.
- [x] Consolidar a conclusão da avaliação e das verificações de prontidão remota, streaming e persistência após reinício, conforme confirmação do responsável. Nenhuma nova execução foi necessária para o registro.

Limitações permanentes: perdas da extração, conteúdo não textual não interpretado, continuidade entre páginas, conjunto pequeno de avaliação e possibilidade de respostas sem fundamentação suficiente. Os serviços gratuitos têm limites e podem suspender por inatividade; manter os dados privados necessários à recuperação, sem mecanismos artificiais de atividade.

## Revisão documental — 29/10/2026

- [x] Acrescentar ao README o plano de avaliação sem modelos, teto de consumo, resumo local e critérios de aprovação.
- [x] Resumir o checklist, preservando as conclusões confirmadas, as evidências principais e as pendências de documentação.
- [x] Validar 24 links locais, 18 blocos Bash, consistência das URLs e `git diff --check` nos quatro documentos. Os três comandos de plano já haviam sido conferidos na revisão anterior. Nenhuma chamada de modelo, ingestão, publicação ou nova execução da suíte neste fechamento.

## Interface mínima de demonstração SSE — 30/10/2026

- [x] Registrar a exceção de frontend no [PRD, seção 10.1](PRD.md#101-interface-mínima-de-demonstração), restrita à página `/teste`, sem histórico, Markdown, dependências novas ou alteração no RAG.
- [x] Criar [app/static/demo.html](app/static/demo.html) com aviso educacional, token em senha sem persistência, seleção de modelo via `/models`, pergunta, Enviar/Parar, estado, texto e fontes por identificador/documento/página física. Bloquear envio se os modelos não carregarem; selecionar `default_model`.
- [x] Entregar o HTML por rota pública fora do Swagger, com caminho relativo ao módulo em [app/main.py](app/main.py). Manter a autenticação configurada das consultas e os comandos atuais do Render.
- [x] Consumir um único POST `/chat/stream` por envio, com Bearer somente se preenchido, validação após trim e limite de 1.500 pontos de código, bloqueio de simultaneidade, decoder UTF-8 persistente e buffer de eventos incompletos. Renderizar conteúdo como texto e preservar quebras de linha.
- [x] Tratar fontes, deltas, três motivos de conclusão, erro público, falha HTTP/conexão e EOF sem terminal. Cancelar por `AbortController`, preservar texto e liberar controles após a limpeza, sem repetição automática.
- [x] Acrescentar [tests/test_demo.py](tests/test_demo.py): HTML público sem token mesmo com autenticação configurada, arquivo independente do diretório de trabalho, ausência no OpenAPI, consulta ainda protegida e nenhuma criação/chamada de gateway, com rede externa bloqueada pelas fixtures.
- [x] Executar regressões: `tests/test_demo.py`, `tests/test_api.py`, `tests/test_chat.py`, `tests/test_stream.py`, `tests/test_stream_http.py` e `tests/test_check_stream.py`: **160 aprovados**, um aviso de depreciação do TestClient/httpx. Incluem contratos, autenticação, cancelamento e primeiro delta por HTTP loopback com Uvicorn e provedor controlado antes da conclusão.
- [x] Executar a suíte completa uma vez: **402 aprovados em 10,79 s**, dois avisos (TestClient/httpx e índices de payload sem efeito no Qdrant local). Nenhum consumo de modelos. A tentativa selecionada no sandbox ficou sem saída e foi interrompida; regressões e suíte completa concluíram fora dele, com as mesmas fixtures de isolamento.
- [x] Validar sintaxe do JavaScript em Node e executar harness temporário, fora da aplicação, com `ReadableStream`, `fetch` e DOM substituídos. Cenários aprovados: modelo padrão e troca de modelo no POST; Bearer preenchido/omitido; pergunta vazia/excessiva e Unicode; bloqueio de simultaneidade; substituição da resposta; fragmentos separados; CRLF e acentos partidos byte a byte; múltiplos eventos por bloco; fontes; conteúdo com marcação tratado como texto; três motivos de `done`; erro após parcial; EOF sem terminal; terminal truncado; SSE inválido; falha de `/models`; HTTP 401/422/429/502/503/504; falha de conexão; cancelamento antes dos cabeçalhos e após texto, com preservação e liberação dos controles.
- [ ] Validar no navegador com resposta sintética controlada e confirmar **visualmente** que o primeiro fragmento aparece enquanto a resposta está aberta. Não havia navegador ou automação de navegador instalados. A simulação Node confirmou apenas a atualização do DOM substituto com stream aberto; não comprova pintura, layout ou comportamento do navegador. Repetir nele os cenários de fragmentos/eventos partidos, acentos, fontes, erro após parcial, EOF sem terminal e cancelamento. Sem modo falso na aplicação.
- [x] Atualizar README com acesso local, URL futura no Render, escopo, consumo, evidências, pendências e rollback. Revisão de diff e links locais registrada após as alterações.
- [ ] Publicação e verificação real desta interface, somente mediante autorização futura. Não executadas neste incremento; teto da verificação: **1 embedding e 1 geração**, objetivo informado previamente e sem repetição automática. Não houve ingestão nem alteração da coleção.

Mudança preparada para commit próprio sugerido: `feat: adiciona interface mínima de demonstração SSE`. Nenhum commit criado. Retirada: reverter esse commit e publicar novamente; recuperação imediata: usar um deploy anterior disponível no Render. Sem migração ou alteração da coleção.

### Diagnóstico local de base indisponível — 30/10/2026

- Consulta HTTP local sem modelos: `/health` retornou **200** e `/ready`, **503**. O diretório `data/qdrant/collection/saude_mental_v1` existe; isso não comprova integridade nem configuração do processo em execução.
- O `.env` existe, mas as variáveis de Qdrant/gateway não estavam exportadas no ambiente da execução de diagnóstico. O ambiente do terminal que iniciou o Uvicorn não foi inspecionado; valores de chaves não foram lidos ou exibidos. O projeto não carrega `.env` automaticamente.
- Próxima verificação: reiniciar a API após carregar o ambiente conforme README e consultar `/ready` novamente. Causa definitiva e recuperação ainda não confirmadas. Sem alteração de código, ingestão ou chamadas de modelos neste diagnóstico.
