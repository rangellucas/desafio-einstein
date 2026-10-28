# Consulta educacional sobre Saúde Mental

Implementação das **Etapas 1–4** do [PRD](PRD.md): inspeção local de PDFs, gateway, indexação retomável em Qdrant, recuperação, `/ready`, `/models` e consulta JSON autenticada em `/chat`. A integração foi testada com respostas simuladas e armazenamento local temporário; compatibilidade do gateway, ingestão dos PDFs e qualidade real das respostas permanecem pendentes. O produto tem finalidade educacional; não realiza diagnóstico, prescrição ou atendimento clínico individual. O estado detalhado está no [checklist](CHECKLIST.md).

## Instalação e execução

Execute os comandos na raiz do projeto. Ambiente verificado: Python **3.12.3**, com `venv` e `pip`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Para instalar somente as dependências de execução, use `requirements.txt`. As versões diretas estão fixadas após os testes desta etapa; dependências transitivas são resolvidas pelo pip.

Em outro terminal:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/openapi.json
```

`/health` retorna `{"status":"ok"}` e indica apenas que o processo responde. Abra `http://127.0.0.1:8000/docs` no navegador para acessar o Swagger. O HTML e o esquema foram verificados por HTTP; a renderização do Swagger no navegador não foi conferida nesta execução e usa os assets padrão do FastAPI, hospedados em CDN.

A rota `/health` e o dry-run não exigem credenciais. `/models` usa somente a lista/padrão configurados, sem consultar o gateway. `/ready` usa somente a configuração vetorial; sem configuração válida, retorna 503 e mantém `/health` e `/docs` disponíveis. [.env.example](.env.example) documenta as variáveis. Não preencha segredos no exemplo versionado. Nenhum módulo carrega `.env` automaticamente.

## Gateway: implementação simulada e verificação real pendente

[app/gateway.py](app/gateway.py) usa o SDK OpenAI **2.29.0**, fixado e testado com o `httpx 0.28.1` existente. Não foi adicionado outro SDK de modelos. `httpx` passou a ser dependência direta de execução para configurar o transporte. A [documentação oficial do SDK](https://developers.openai.com/api/reference/python) orientou o uso assíncrono e as opções extras; as assinaturas e o comportamento também foram conferidos no código da versão instalada. Essa documentação não comprova o contrato do gateway fornecido pelo projeto.

O contrato **candidato**, verificado apenas com HTTP simulado, é:

| Item | Formato enviado ou exigido |
| --- | --- |
| Endereço | `LLM_BASE_URL` fornecido pelo responsável pelo gateway, incluindo o prefixo de versão quando aplicável. O SDK acrescenta `embeddings` ou `chat/completions`. |
| Autenticação | `Authorization: Bearer` com `LLM_API_KEY`. A compatibilidade desse cabeçalho ainda será confirmada no gateway. |
| Embeddings | `POST embeddings`, modelo `cohere/embed-v4.0`, `input` como lista de textos, `encoding_format="float"` e `input_type` no corpo JSON por `extra_body`. |
| Tipos Cohere | `search_document` para documento e `search_query` para pergunta. O encaminhamento fica concentrado em `gateway.py`; não há fallback silencioso sem esse campo. |
| Retorno vetorial | `data` com um vetor numérico finito e não nulo por entrada, índices únicos de `0` a `n-1` e dimensão uniforme. O adaptador restaura a ordem pelos índices e valida a dimensão configurada, se houver. |
| Geração | `POST chat/completions`, mesmo adaptador para ambos os modelos, `messages`, `stream=true` e limite candidato `max_completion_tokens`. Não envia temperatura ou parâmetros de raciocínio por suposição. |
| Streaming | SSE compatível com Chat Completions: `choices[0].delta.content` e `finish_reason`. Ignora fragmentos sem texto, preserva Unicode e repassa cada fragmento sem acumular a resposta. Exige término explícito. |
| Consumo | Retentativas e redirecionamentos HTTP desativados. Uma falha interrompe a verificação; não tenta outros campos, endpoints ou modelos automaticamente. |

Para mostrar o plano **sem ler credenciais, criar cliente ou abrir conexão**:

```bash
source .venv/bin/activate
python -m scripts.check_gateway
```

O comando real preparado é `python -m scripts.check_gateway --execute`. **Não foi executado nesta entrega.** Ele fará, em sequência, no máximo estas **quatro requisições**, interrompendo na primeira falha:

| Ordem | Chamada | Entrada e limite |
| --- | --- | --- |
| 1 | Embedding `cohere/embed-v4.0`, `search_document` | Um texto sintético curto, sem PDF. |
| 2 | Embedding `cohere/embed-v4.0`, `search_query` | Uma pergunta sintética curta; compara a dimensão com a anterior. |
| 3 | Streaming `azure/gpt-5-mini` | Uma mensagem sintética; até `min(MAX_OUTPUT_TOKENS, 600)` tokens de saída solicitados. |
| 4 | Streaming `azure/gpt-6-luna` | A mesma mensagem e o mesmo limite. |

Não há chamada para listar modelos, sondagem de endpoints nem retentativa. O teto é de duas chamadas de embeddings e duas de geração por execução. O prazo total de **cada chamada**, incluindo a leitura do stream, é `REQUEST_TIMEOUT_SECONDS` (90 segundos por padrão). Chamadas podem ser cobradas pelo gateway; valores financeiros não foram informados nem estimados.

Configure no seu ambiente:

| Variável | Preenchimento para a verificação real |
| --- | --- |
| `LLM_BASE_URL` | **Obrigatória:** URL base exata do gateway, sem os sufixos `chat/completions`/`embeddings`, sem credenciais ou query. |
| `LLM_API_KEY` | **Obrigatória:** credencial privada do gateway. Não enviar em mensagens ou inserir no exemplo versionado. |
| `CHAT_MODELS` | Opcional; padrão `azure/gpt-5-mini,azure/gpt-6-luna`. Deve conter exatamente os dois identificadores do PRD, sem duplicatas. Ambos serão verificados. |
| `DEFAULT_CHAT_MODEL` | Opcional; padrão `azure/gpt-5-mini`, deve pertencer à lista. A verificação testa ambos, independentemente do padrão. |
| `EMBEDDING_MODEL` | Opcional; padrão e único identificador permitido nesta etapa: `cohere/embed-v4.0`. |
| `EMBEDDING_DIMENSION` | **Deixar vazia na primeira verificação.** Depois preencher com a dimensão observada e igual nos dois tipos. Nenhum valor foi presumido. |
| `MAX_OUTPUT_TOKENS` | Opcional; inteiro positivo, padrão 600. O comando limita a solicitação a no máximo 600 por modelo. |
| `REQUEST_TIMEOUT_SECONDS` | Opcional; número positivo e finito, padrão 90 por chamada. |

Qdrant, `API_ACCESS_TOKEN`, `MAX_CONCURRENT_REQUESTS` e `PORT` não são necessários para essa verificação. Caso use um `.env` privado preparado a partir do exemplo, exporte suas variáveis antes do comando. O trecho abaixo é para uma **execução futura autorizada**, não foi executado aqui:

```bash
source .venv/bin/activate
set -a
source .env
set +a
python -m scripts.check_gateway --execute
```

O relatório JSON contém quantidade de chamadas tentadas, checks concluídos, dimensão medida, modelos enviados, contagem de fragmentos/caracteres, tempo até o primeiro texto, duração e motivo de término. Não imprime URL, chave, mensagens, texto gerado, vetores ou erro bruto do provedor. Código de saída: `0` para plano ou verificação aprovada, `1` para falha da integração, `2` para configuração inválida (indicando nomes das variáveis, sem seus valores). Conclusão sem texto, interrupção por limite (`length`), ausência de motivo terminal, formato inválido ou dimensões divergentes são falhas para o aceite desta verificação. O adaptador preserva `length` para o tratamento nas etapas seguintes.

Mesmo uma execução com código `0` só confirma a aceitação do formato e o comportamento observado nesses quatro casos. Não comprova que o gateway respeita semanticamente `input_type` ou o teto de saída; conferir também o contrato do fornecedor. Contagens e tempos não provam ausência de buffering na futura rota HTTP da aplicação. Essa prova pertence à Etapa 5, com Uvicorn e cliente progressivo. O comando não é executado no startup, ingestão, build, testes comuns ou CI.

**Estado em 28/10/2026:** testes com substitutos aprovados; endereço, credencial, aceitação dos parâmetros, dimensão e streaming dos modelos reais ainda não verificados. Em caso de incompatibilidade, registrar o erro categorizado, revisar o contrato com o fornecedor e planejar nova execução autorizada antes de continuar a parte dependente. A Etapa 3 foi implementada com substitutos; nenhuma ingestão real foi executada.

## Extração e dry-run

Coloque manualmente os quatro arquivos da seção 4.1 do PRD em `data/raw/`, preservando os nomes, inclusive o espaço em `kJpr4dDC 2.pdf`. Depois execute:

```bash
source .venv/bin/activate
python -m scripts.ingest --dry-run
# Opcional: diretório local alternativo, com os mesmos quatro nomes.
python -m scripts.ingest --dry-run --input-dir /caminho/dos/pdfs
```

O comando usa `pypdf`, normaliza espaços e quebras de linha, e divide cada página em trechos de até 1.200 caracteres, com 200 de sobreposição. Prefere limites de parágrafo ou frase quando permitem avanço. Não remove cabeçalhos, rodapés, páginas curtas nem caracteres suspeitos. A sobreposição pode começar no meio de uma palavra; conteúdos que continuam em outra página ficam separados.

Cada trecho mantém `document_name`, página física a partir de 1, `chunk_index` a partir de 0, texto e offsets `start`/`end` no texto normalizado. A preparação acrescenta `chunk_id` e `document_id` UUID determinísticos, `document_hash` SHA-256, `pipeline_version` e `embedding_model`. A identidade inclui documento, hash do arquivo e do texto, página, posição, versão e parâmetros de divisão. Nenhum vetor é calculado no dry-run.

O relatório JSON mostra contagens por documento e página, páginas sem texto, páginas curtas (menos de 80 caracteres não vazios), páginas com NUL/U+FFFD e posições sugeridas de amostra. O limite de 80 é apenas uma heurística de triagem. Ele não detecta toda perda de conteúdo, colunas desordenadas ou imagens. Nenhum texto extraído é impresso ou salvo pelo comando. PDFs e demais dados locais ficam excluídos pelo `.gitignore`.

É obrigatório escolher `--dry-run` ou `--execute`; o segundo exige as confirmações e o orçamento descritos abaixo. Arquivos ausentes, ilegíveis, criptografados, sem páginas ou sem trechos geram falhas e código 1; os outros arquivos continuam sendo inspecionados. Código 0 no dry-run significa que os quatro arquivos foram lidos, **sem certificar qualidade ou completude do conteúdo**. `manual_review_required` permanece verdadeiro. O dry-run não lê credenciais, cria clientes, abre conexões ou grava documentos/trechos. O relatório inclui o teto de chamadas de embeddings, sem descontar pontos que eventualmente já existam na base.

## Inspeção real em 27/10/2026

Foram processados os quatro PDFs locais com `pypdf 6.21.3`: **257 páginas, 285 trechos previstos**, nenhum arquivo com falha e nenhuma página completamente sem texto extraível. Esses totais incluem capas, sumários, créditos e páginas com apenas marcadores; não representam uma base curada ou indexada.

As linhas abaixo seguem a ordem dos documentos da seção 4.1 do PRD. Foram lidos os textos extraídos do início, meio e fim, dos sumários e das páginas curtas. Não foi realizada comparação visual com a renderização dos PDFs; não há ferramenta de renderização instalada neste ambiente. Não é possível certificar a completude de imagens, tabelas ou diagramas por esta leitura textual.

| Documento | Páginas | Trechos | Amostras início/meio/fim | Páginas curtas | NUL/U+FFFD |
| --- | ---: | ---: | --- | --- | ---: |
| Ampliando o Conceito de Saúde Mental | 65 | 71 | 1, 33, 65 | 1, 35 | 84 |
| O sujeito, a Integralidade e Saúde Mental | 53 | 60 | 1, 27, 53 | 1, 31, 33, 35, 38, 39 | 73 |
| Saúde Mental na Atenção Primária | 63 | 74 | 1, 32, 63 | 1 | 109 |
| Desenvolvendo os Cuidados de Saúde Mental na APS | 76 | 80 | 1, 38, 76 | 1, 29 | 136 |

Limitações observadas, sem reproduzir trechos privados:

- **Glifos:** 402 caracteres NUL/U+FFFD no total; nas amostras, NUL aparece dentro de palavras, prejudicando sua leitura. Exemplos de páginas afetadas: documento 1, p. 33; documento 2, p. 27; documento 4, pp. 38 e 56. O relatório enumera todas as páginas detectadas em `suspicious_pages` e as contagens em `pages`.
- **Sumários:** página 2 dos quatro arquivos separa títulos e números de página; no documento 2 há itens intercalados. A ordem extraída não representa fielmente a disposição original. A limpeza não tenta reconstruí-la.
- **Conteúdo pouco extraível:** documento 1, p. 35, contém somente atribuição e número; documento 2, pp. 31, 33 e 35, contém marcadores de áudio, p. 38 contém legenda e p. 39 somente o número da página; documento 4, p. 29, contém título e número. É necessário conferir visualmente o conteúdo dessas páginas antes de decidir sua inclusão na base. Áudio e vídeo não são transcritos.
- **Páginas curtas úteis:** documento 4, pp. 55–58, foi conferido adicionalmente por ter textos curtos de etapas de um procedimento. Não é seguro excluir páginas apenas pelo tamanho.
- **Referência de página:** utiliza exclusivamente a posição física. Alguns números impressos aparecem no texto e outros não; não foi estabelecido um mapeamento global entre numeração impressa e física.

**Exclusões aplicadas: nenhuma.** Páginas curtas e glifos defeituosos são preservados para revisão; não foram consideradas irrelevantes automaticamente. Páginas realmente vazias em outros PDFs não geram trechos, mas mantêm sua posição e aparecem em `empty_pages`.

Antes de indexar, é necessário resolver ou aceitar explicitamente as perdas observadas, incluindo a conferência visual das páginas de pouco texto. A alternativa prevista no PRD é **avaliar `pdfplumber`** para comparar extração/ordem e mapeamento de glifos; não foi instalada nem se presume que corrigirá os problemas. Se páginas relevantes forem escaneadas, OCR exige revisão explícita do escopo. `pypdf` permanece como única biblioteca de PDF nesta entrega.

## Indexação, recuperação e prontidão — Etapa 3

O projeto usa `qdrant-client==1.19.1`, sem FastEmbed nem inferência automática. O [cliente oficial](https://github.com/qdrant/qdrant-client) oferece armazenamento local; a [documentação assíncrona](https://qdrant.tech/documentation/tutorials-develop/async-api/) orienta o uso de `AsyncQdrantClient`. As assinaturas, a persistência dos metadados e os formatos REST foram conferidos na versão instalada e com substitutos. O servidor remoto precisa suportar metadados de coleção; essa compatibilidade ainda não foi verificada em um cluster real.

`app/vector_store.py` abre o diretório local ou o endpoint remoto conforme a configuração. A coleção usa um vetor por trecho e distância de cosseno. Seus metadados guardam modelo, dimensão medida, versão do pipeline, parâmetros de divisão e manifesto com hash/quantidade de trechos de cada documento. Dimensão, distância, versão, modelo ou documentos diferentes causam falha, sem apagar, recriar ou adaptar uma coleção existente. Escolha uma nova `QDRANT_COLLECTION` para uma base incompatível. Não altere o pipeline sem atualizar sua versão.

O comando de ingestão consulta IDs antes de cada lote de até 16 trechos, confere o payload existente, calcula embeddings somente dos ausentes e faz `upsert` com confirmação de escrita. Os lotes podem atravessar a fronteira entre documentos. Quantidade, ordem, dimensão e validade numérica dos vetores são verificadas antes da gravação. Uma falha interrompe o comando; pontos já confirmados permanecem para retomada. Se o gateway concluir mas a escrita falhar, vetores que não tenham sido persistidos poderão precisar de nova geração em uma execução futura. Não há retentativa automática.

O relatório mantém o resumo de extração dos quatro documentos e acrescenta contagens previstas, reutilizadas e gravadas, total de chamadas tentadas e falhas categorizadas. Não imprime textos, vetores, URL, perguntas ou erros brutos de serviços. Código 0 da execução exige contagens finais compatíveis com o manifesto dos quatro documentos; execução parcial retorna 1. Erros de configuração indicam nomes das variáveis inválidas, sem valores; falhas ao abrir o armazenamento retornam código público genérico por segurança.

`app/rag.py:retrieve_chunks` valida a pergunta, confirma prontidão antes de consumir modelos, faz um único embedding `search_query` e consulta os quatro primeiros resultados, com documento e página. Não aplica limiar de confiança. A Etapa 4 acrescenta preparação do contexto e geração JSON sobre essa recuperação.

`GET /ready` é público e retorna `{"status":"ready"}` com 200 somente quando a coleção é compatível e as contagens total e por documento correspondem ao manifesto. Ausência de configuração/coleção, base vazia/parcial/incompatível, lock local ou falha do Qdrant resultam em 503 com `detail.code="base_unavailable"`, mensagem pública e `request_id`. Não chama o gateway nem modifica a base. O código não trata indisponibilidade como falta de conteúdo.

### Comandos reais preparados, ainda não executados

Primeiro confirme o gateway pela verificação da Etapa 2, se ainda pendente:

```bash
python -m scripts.check_gateway --execute
```

Essa verificação tem teto de quatro chamadas: dois embeddings sintéticos (documento e pergunta) e uma geração em streaming por modelo, até 600 tokens de saída solicitados em cada geração. Depois preencha `EMBEDDING_DIMENSION` com o valor medido e igual nos dois tipos.

Revise a extração e resolva ou aceite explicitamente as perdas descritas acima, incluindo a conferência visual pendente. Execute novamente o dry-run após qualquer mudança. As opções `--gateway-verified` e `--extraction-reviewed` atestam que essas verificações já foram realizadas; não as executam nem corrigem as limitações.

```bash
python -m scripts.ingest --dry-run
```

O dry-run de 28/10/2026 confirmou **4 documentos, 257 páginas e 285 trechos**, sem chamadas de modelos ou acesso ao Qdrant. Para esses arquivos/parâmetros, o teto é **18 chamadas** `POST embeddings`, modelo `cohere/embed-v4.0`, `input_type="search_document"`, até 16 entradas por chamada. O comando futuro autorizado é:

```bash
python -m scripts.ingest --execute \
  --gateway-verified --extraction-reviewed --max-embedding-calls 18
```

O teto é conferido antes de abrir clientes. Se a preparação passar a exigir mais de 18 lotes, o comando aborta; revise o plano antes de elevar o valor. Em retomadas, o consumo pode ser menor; repetir uma ingestão já concluída gera **zero embeddings** quando todos os pontos e seus payloads permanecem intactos. No modo local, pare a API antes de indexar ou avaliar com o mesmo diretório; somente um processo deve abri-lo. Reinicie a API após a ingestão.

As oito perguntas, duas por documento, estão em [evals/retrieval.json](evals/retrieval.json), com páginas físicas conferidas por leitura textual dos PDFs, elementos esperados e limitações. O arquivo contém perguntas/paráfrases, sem trechos extraídos. A avaliação mede se uma página esperada aparece entre os quatro primeiros resultados; não avalia respostas geradas. Primeiro veja o plano sem ler credenciais:

```bash
python -m scripts.check_retrieval
```

Depois da ingestão completa e de autorização para as chamadas, o comando preparado é:

```bash
python -m scripts.check_retrieval --execute --gateway-verified
```

Ele faz no máximo **8 chamadas** `POST embeddings`, modelo `cohere/embed-v4.0`, `input_type="search_query"`, uma pergunta por chamada; cada vetor alimenta uma busca top-4. Não há geração de resposta. O relatório contém IDs dos casos, documentos/páginas recuperados e posição da fonte esperada, sem perguntas ou trechos. Código 0 exige pelo menos **7/8** acertos; `below_target` ou falha retorna 1. A pontuação real segue pendente; a aprovação com dados sintéticos não é uma medição semântica desses oito casos.

| Execução futura | Teto de chamadas ao gateway | Teto de operações Qdrant |
| --- | ---: | ---: |
| Compatibilidade pendente da Etapa 2 | 4: dois embeddings e duas gerações | 0 |
| Ingestão inicial dos 285 trechos | 18 embeddings de documentos | 47 |
| Avaliação das oito perguntas | 8 embeddings de perguntas | 71 |
| `/ready`, por requisição | 0 | 7 |

O teto da Etapa 3 é **26 chamadas de embeddings** por ingestão inicial mais uma avaliação; incluindo a compatibilidade pendente, são **30 chamadas ao gateway**, duas delas de geração. Os tetos valem para uma execução de cada comando, sem repetição automática. São **118 operações Qdrant** na ingestão+avaliação: validação/existência/criação de coleção, consulta de IDs, upserts, contagens e busca. No modo local essas operações são locais; no remoto são requisições REST. Uma checagem manual de `/ready` acrescenta até 7 operações Qdrant. Não há sondagem automática de versão do servidor ou redirecionamento HTTP. Falhas interrompem as verificações.

### Ambiente para a Etapa 3

Exporte as variáveis no terminal ou carregue manualmente seu `.env` privado como descrito na seção do gateway. Não envie valores de chaves ao chat.

| Variável | Preenchimento |
| --- | --- |
| `LLM_BASE_URL` | URL base exata do gateway. Obrigatória para ingestão/avaliação reais, dispensada em `/ready`. |
| `LLM_API_KEY` | Chave privada do gateway; mesma obrigatoriedade da URL. |
| `EMBEDDING_MODEL` | Manter `cohere/embed-v4.0` (padrão). |
| `EMBEDDING_DIMENSION` | Obrigatória para ingestão, recuperação e `/ready`; preencher **somente após medição real**. |
| `QDRANT_COLLECTION` | Obrigatória; nome versionado, por exemplo `saude_mental_v1`. Não é criada no startup ou em `/ready`. |
| `QDRANT_PATH` | Modo local: diretório privado; padrão `data/qdrant`, ignorado pelo Git. |
| `QDRANT_URL` | Modo local: deixar vazia. Modo remoto: URL HTTPS completa do cluster, com a porta fornecida. Ao preencher, substitui o modo local. |
| `QDRANT_API_KEY` | Obrigatória no modo remoto. Usar chave com escrita para ingestão e de consulta para a API, quando disponível. |
| `REQUEST_TIMEOUT_SECONDS` | Opcional, padrão 90; prazo total por chamada de embeddings. Qdrant usa timeout de 15 segundos por operação remota. |

Os padrões dos modelos de chat e `MAX_OUTPUT_TOKENS=600` bastam para a verificação prévia da Etapa 2. `API_ACCESS_TOKEN`, `MAX_CONCURRENT_REQUESTS` e `PORT` não são usados pelos comandos da Etapa 3. Sem dimensão/coleção válidas, a API mantém a saúde do processo e responde 503 em `/ready`.

## Resposta JSON e Swagger — Etapa 4

`GET /models` retorna `models` (lista permitida) e `default_model` (padrão). Esses valores vêm de `CHAT_MODELS` e `DEFAULT_CHAT_MODEL`, validados pela mesma configuração usada no gateway. A rota é pública e funciona sem chave do gateway, coleção ou dimensão. Lista/padrão inválidos impedem a inicialização com mensagem pública sem valores de entrada. Não há consulta ao catálogo do provedor.

`POST /chat` aceita somente `question` e `model`. A pergunta deve ser string, conter de 1 a 1.500 caracteres após `strip()` e não pode ser vazia. `model` omitido ou `null` usa o padrão; string vazia ou identificador desconhecido é rejeitado. Campos extras e tipos incompatíveis retornam 422. Autenticação e validação são concluídas antes de prontidão, embedding, busca ou geração.

Configure `API_ACCESS_TOKEN` no ambiente privado para exigir `Authorization: Bearer <token-da-aplicação>`. Esse token é independente de `LLM_API_KEY`. Ausência ou valor incorreto resulta em 401 com `WWW-Authenticate: Bearer`. Sem token configurado, o desenvolvimento local permite consultas; na publicação ele deverá estar preenchido. `/health`, `/ready`, `/models`, `/docs` e `/openapi.json` permanecem públicos. O token não pode conter somente espaços.

O ciclo de vida abre e compartilha os clientes do gateway e do Qdrant, sem chamadas de modelos ou criação de coleção. Configuração ausente ou falha ao abrir uma dependência mantém as rotas públicas disponíveis; `/chat` retorna 503. O encerramento fecha ambos os clientes, inclusive se outro fechamento falhar. Reinicie a API após mudar as variáveis ou preparar uma base local antes ausente.

O fluxo de uma pergunta passa por estas funções:

1. `routes.authenticate` verifica o Bearer e cria `request_id`; `ChatRequest` valida e normaliza o corpo. `routes.chat` resolve e valida o modelo.
2. `rag.prepare_answer` chama `retrieve_chunks`: confere dimensão/prontidão, gera um embedding `search_query` e busca top-4 no Qdrant. Falha da base retorna erro, sem ser convertida em contexto vazio.
3. `prompts.build_context` remove textos exatamente duplicados e limita o contexto a 8.000 caracteres, contando cabeçalhos e separadores. Cada bloco recebe `[S1]`, documento e página física. As fontes correspondem somente aos blocos efetivamente incluídos; cada `excerpt` contém até 600 caracteres, enquanto o texto enviado ao modelo pode ser maior.
4. `prompts.build_messages` cria instruções fixas de sistema e uma mensagem de dados com pergunta/contexto. Não há histórico. O prompt exige português, fundamentação, referências fornecidas e reconhecimento de insuficiência; impede diagnóstico/prescrição individual e orienta ajuda humana/emergência local em relato de risco imediato. Perguntas e documentos não podem substituir as regras da aplicação.
5. Com fontes, `rag.generate_answer` usa `gateway.open_chat_stream`, o mesmo adaptador para ambos os modelos. Acumula os fragmentos para uma resposta JSON completa e fecha o stream. Sem fontes, retorna explicação local com `sources: []` e `finish_reason: "insufficient_context"`, sem geração.
6. `routes.chat` retorna `request_id`, `model`, `answer`, `sources` e `finish_reason`. `stop` indica término normal e `length` indica corte pelo limite de saída. Motivos de ferramenta/filtro, ausência de término, resposta vazia ou malformada não são apresentados como sucesso.

As fontes são os trechos disponibilizados ao modelo; sua presença não prova a fundamentação de cada frase. As regras do prompt também não garantem ausência de alucinação: a avaliação real continua pendente.

Erros controlados retornam `detail` com `code`, `message` pública e `request_id`. A validação de corpo usa o formato padrão do FastAPI. Base ausente/incompatível ou Qdrant indisponível retorna 503; falha/resposta inválida do gateway retorna 502; conexão indisponível, HTTP 429 ou 5xx do provedor retorna 503; timeout de chamada do gateway retorna 504. Mensagens brutas do provedor não são devolvidas. Não há retentativa automática nem fallback para outro modelo.

Nesta etapa, `REQUEST_TIMEOUT_SECONDS` limita separadamente o embedding e a geração (incluindo leitura e fechamento do stream). Qdrant remoto mantém timeout de 15 segundos por operação. O prazo total de consulta, o limite de concorrência/429 da aplicação, o tratamento de desconexão do consumidor e `/chat/stream` pertencem à Etapa 5. `MAX_CONCURRENT_REQUESTS` ainda não é aplicado. O JSON usa streaming somente entre backend e gateway; isso não constitui uma rota SSE pública.

Os logs de `app.rag`/`app.routes` em nível INFO contêm somente metadados: identificador, etapa/tempos, rota, modelo, quantidade de fontes e resultado/motivo de término ou erro categorizado. Não incluem perguntas, respostas, contexto, credenciais ou mensagens brutas de dependências. Não registram uso de tokens ausente. O nível/handler de logging fica a cargo do executor; a aplicação não ativa logs detalhados de SDKs.

### Validação manual preparada, sem execução real nesta entrega

Para verificar rotas públicas e o Swagger sem consumir modelos:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Em outro terminal:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/models
curl --fail http://127.0.0.1:8000/openapi.json
```

Abra `http://127.0.0.1:8000/docs`. Confira a lista em **GET /models**. Se o token estiver configurado, clique em **Authorize**, informe somente o token da aplicação (sem escrever `Bearer`) e confirme. Expanda **POST /chat**, clique em **Try it out** e use o exemplo de pergunta. O esquema documenta o contrato, páginas físicas, autenticação e erros.

Executar uma consulta válida pode consumir modelos. **Antes de testar respostas reais**, conclua a confirmação do gateway/dimensão, a revisão da extração e a ingestão da Etapa 3, e autorize o consumo. Plano manual: **três consultas**, uma com `azure/gpt-5-mini`, outra com `azure/gpt-6-luna` e outra omitindo `model`; no máximo **6 chamadas de modelos** (3 embeddings e 3 gerações, até `MAX_OUTPUT_TOKENS` por geração). Contexto vazio evita a geração; falhas interrompem a consulta. Esses testes não foram executados aqui.

No Swagger, confira `model`, `answer`, referências `[S1]`, `sources` com documento/página/excerto e `finish_reason`. Perguntas são independentes. Uma alternativa pelo terminal, para **uma das três consultas já planejadas**, é:

```bash
API_URL=http://127.0.0.1:8000
curl --fail-with-body "$API_URL/chat" \
  -H "Authorization: Bearer $API_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"question":"Como a atenção primária participa do cuidado em saúde mental?","model":"azure/gpt-5-mini"}'
```

Altere o modelo para `azure/gpt-6-luna` na segunda consulta e remova a propriedade na terceira. Sem base pronta, espere 503; isso não equivale ao sucesso com `insufficient_context`. Não simule contexto vazio apagando a coleção. A ausência de resultados é exercitada com substituto nos testes. Entradas inválidas, por exemplo `{"question":"   "}` ou modelo `"inexistente"`, e acesso sem Bearer quando configurado devem falhar sem serviços externos.

## Testes e evidências

```bash
source .venv/bin/activate
python -m pytest -q
python -m pip check
```

Na Etapa 1, foram obtidos **32 testes aprovados**, sem conexões externas ou credenciais. As fixtures geram PDFs sintéticos apenas nos diretórios temporários dos testes; PDFs reais não são usados pela suíte. Conexões externas de sockets são bloqueadas nos testes comuns. Foram verificados limpeza, preservação integral do texto normalizado, tamanho, avanço, sobreposição, limites de parágrafo/frase, referências físicas, páginas vazias, glifos suspeitos, PDF criptografado, dry-run sem exportar texto ou alterar arquivos, PDFs ausentes/corrompidos e API em memória.

Na Etapa 2, o resultado final em 28/10/2026 foi **97 testes aprovados** (32 existentes e 65 novos), sem chamadas reais. A suíte inclui HTTP simulado com `httpx.MockTransport`, passando pelo SDK instalado: corpo, rota e autenticação sintética; tipos de entrada; ordem, quantidade e dimensão de vetores; rejeição de vetores inválidos, booleanos e valores não finitos; escolha dos dois modelos; leitura incremental antes de consumir o restante do stream; encerramento normal, saída antecipada, erro, cancelamento e timeout; falhas HTTP, conexão e SSE; ausência de retentativas/redirecionamentos; teto de quatro chamadas e limite de saída; comando seguro por padrão e relatórios sem conteúdo. A validação foi feita antes das conversões permissivas do SDK para evitar aceitar um booleano como componente numérico. Essa suíte precisou executar fora do sandbox por causa dos sockets internos; a fixture continuou bloqueando conexões externas. O único aviso foi a depreciação do TestClient já registrada na Etapa 1.

Na Etapa 3, em 28/10/2026, foram obtidos **138 testes aprovados** (97 anteriores e 41 novos), com o mesmo aviso. As novas verificações usam quatro PDFs sintéticos, gateway HTTP simulado e Qdrant temporário; incluem persistência após reabrir o diretório, payloads e páginas, IDs estáveis, limite de lote, retomada após falha, repetição sem novos embeddings, incompatibilidades sem perda de dados, cobertura por documento, avaliação/ranks simulados, nomes de variáveis inválidas sem valores e `/ready` com fechamento do cliente. O caminho remoto passou pelo SDK e por `httpx.MockTransport`, incluindo criação de coleção com metadados, consulta de IDs, upsert, contagem e busca; nenhum servidor remoto real foi acessado. O dry-run real reconfirmou 285 trechos e teto de 18 chamadas; `scripts.check_retrieval` foi executado apenas no modo de plano. Nenhuma nota de relevância real foi produzida.

Na Etapa 4, em 28/10/2026, foram obtidos **209 testes aprovados** (138 anteriores e 71 novos), com o mesmo aviso. Os testes de API substituem configuração real e Qdrant e usam o SDK do gateway com HTTP simulado, mantendo o bloqueio de conexões externas. Verificam modelos/padrões, rejeição sem serviços externos, autenticação e segurança OpenAPI, contexto/deduplicação/fontes, limites de entrada/excertos/contexto, perguntas independentes, ausência de geração sem fontes, falhas de base/gateway, JSON/delta/término inválidos, timeout separado por chamada, fechamento e descarte de resposta parcial. Logs da aplicação foram conferidos sem conteúdo privado. Não foram executados modelos reais, ingestão ou publicação. HTML e esquema do Swagger foram verificados em memória; renderização/Authorize no navegador e respostas/fontes reais permanecem pendentes. Esses testes verificam o contrato e a separação das instruções, sem provar a qualidade semântica dos modelos.

Para repetir apenas as verificações novas, sem consumo de modelos:

```bash
python -m pytest -q tests/test_chat.py tests/test_prompts.py
```

`pip check`: nenhuma incompatibilidade declarada. A combinação instalada emite um aviso de depreciação de `httpx` no TestClient do Starlette; os testes passam. Não foi adicionada a biblioteca alternativa `httpx2`, que não faz parte das dependências aprovadas.

A suíte completa precisou executar fora do sandbox: a criação de sockets internos de asyncio/TestClient fica bloqueada nele; o bloqueio de conexões externas dos testes permaneceu ativo. Na Etapa 1, os 31 testes de processamento e CLI também passaram dentro do sandbox. Separadamente naquela etapa, Uvicorn foi iniciado em `127.0.0.1` e respondeu HTTP 200 em `/health`, `/docs` e `/openapi.json`; foi encerrado ao final. Essa verificação também precisou da permissão de socket local. Na Etapa 3 houve somente gravação de dados sintéticos em Qdrant temporário. Nenhuma chamada real de modelo, indexação dos PDFs privados ou publicação foi executada.

## Responsabilidades e pendências

`app/main.py` cria a API, `/health`, `/ready` e o ciclo de vida de ambos os clientes. `app/config.py` valida as configurações; `app/ingestion.py` extrai, divide, cria IDs e coordena a indexação; `app/vector_store.py` concentra validação, persistência e busca; `app/rag.py` prepara a consulta e acumula a geração JSON. `app/routes.py` trata autenticação e erros HTTP; `app/schemas.py` define contratos Pydantic; `app/prompts.py` limita/formata o contexto e prepara as instruções. Os comandos de `scripts/` chamam essas funções e apresentam relatórios. `app/gateway.py` preserva a única integração de modelos e seu contrato candidato. `TypedDict` descreve registros/relatórios, sem classes de serviço.

A extração e a rota de saúde continuam síncronas. O FastAPI executa a rota `def` em seu pool de threads. O PDF é aberto com `with` e fechado após a extração. A API não executa ingestão durante importação, inicialização, atendimento ou encerramento.

`async def` define operações que podem suspender durante I/O; `await` aguarda os SDKs sem bloquear o ciclo de eventos nas chamadas de rede. O modo Qdrant local executa trabalho em memória/disco no próprio processo e não garante I/O não bloqueante. `asyncio.run` cria e encerra o ciclo nos comandos. `asyncio.timeout` limita separadamente embedding e geração JSON. O `lifespan` é um gerador assíncrono gerenciado por `asynccontextmanager`: antes de `yield`, abre os clientes compartilhados quando a configuração permite; `yield` cede o atendimento ao FastAPI; na saída, `AsyncExitStack` encerra os recursos na ordem inversa, mesmo se algum fechamento falhar. Nenhuma coleção é criada nesse ciclo. Para mudar a configuração ou abrir uma base local criada posteriormente, reinicie a API.

No adaptador do gateway, `iter_chat_parts` é um gerador assíncrono: cada `yield` entrega um fragmento ou motivo de término, e `async for` solicita o próximo. `open_chat_stream` usa `yield` para disponibilizar o iterador dentro de `async with` e fecha o stream ao sair. `generate_answer` acumula esses fragmentos com lista e `"".join`, sem criar uma segunda integração. Preparação de contexto/mensagens e adaptador permanecem disponíveis para a futura rota SSE.

Pydantic valida entradas/saídas e proíbe campos extras no pedido; `strict=True` evita converter números em perguntas/modelos. `SecretStr` oculta tokens nas representações; a comparação Bearer usa `hmac.compare_digest` com bytes UTF-8. `set` remove duplicatas de texto preservando a primeira ocorrência pela lista de blocos. `Literal` restringe motivos públicos de término. Não foram criadas classes de serviço ou adicionadas dependências.

As rotas SSE e os controles da Etapa 5 ainda não foram implementados. Nenhuma dimensão real de embedding foi medida. A qualidade real da recuperação e das respostas ainda não foi avaliada. A inconsistência SSE registrada no checklist continua pendente para a Etapa 5 e não afeta o contrato JSON.

O repositório possui histórico prévio, preservado nesta entrega. Nenhum commit foi criado nem arquivo adicionado ao índice durante a Etapa 4. As exclusões de `.env`, `.venv/` e `data/` foram confirmadas na Etapa 1. A auditoria completa de segredos e artefatos privados no conteúdo versionado/histórico permanece pendente para a etapa correspondente; não foi realizada aqui.

Código, testes e documentação foram preparados com auxílio do Codex e validados conforme as evidências descritas. O [PRD](PRD.md) e as [instruções](AGENTS.md) foram preservados; esta entrega implementa somente a Etapa 4 sobre as etapas existentes, sem executar modelos reais.
