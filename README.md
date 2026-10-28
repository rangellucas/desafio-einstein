# Consulta educacional sobre Saúde Mental

Implementação das **Etapas 1 e 2** do [PRD](PRD.md): API mínima, inspeção local de PDFs e adaptador do gateway com verificação explícita. A Etapa 2 foi testada com respostas simuladas; a compatibilidade real permanece pendente. O produto tem finalidade educacional; não realiza diagnóstico, prescrição ou atendimento clínico individual. O estado detalhado está no [checklist](CHECKLIST.md).

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

A API mínima e o dry-run não leem credenciais nem exigem arquivo `.env`. [.env.example](.env.example) documenta a configuração do comando do gateway e das etapas futuras. Não preencha segredos no exemplo versionado. Nenhum módulo carrega `.env` automaticamente.

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

**Estado em 28/10/2026:** testes com substitutos aprovados; endereço, credencial, aceitação dos parâmetros, dimensão e streaming dos modelos reais ainda não verificados. Em caso de incompatibilidade, registrar o erro categorizado, revisar o contrato com o fornecedor e planejar nova execução autorizada antes de continuar a parte dependente. Nenhuma ingestão ou implementação da Etapa 3 foi iniciada.

## Extração e dry-run

Coloque manualmente os quatro arquivos da seção 4.1 do PRD em `data/raw/`, preservando os nomes, inclusive o espaço em `kJpr4dDC 2.pdf`. Depois execute:

```bash
source .venv/bin/activate
python -m scripts.ingest --dry-run
# Opcional: diretório local alternativo, com os mesmos quatro nomes.
python -m scripts.ingest --dry-run --input-dir /caminho/dos/pdfs
```

O comando usa `pypdf`, normaliza espaços e quebras de linha, e divide cada página em trechos de até 1.200 caracteres, com 200 de sobreposição. Prefere limites de parágrafo ou frase quando permitem avanço. Não remove cabeçalhos, rodapés, páginas curtas nem caracteres suspeitos. A sobreposição pode começar no meio de uma palavra; conteúdos que continuam em outra página ficam separados.

Cada trecho em memória mantém `document_name`, página física a partir de 1, `chunk_index` a partir de 0, texto e offsets `start`/`end` no texto normalizado. IDs, hash, versão do pipeline e metadados de embeddings serão implementados na Etapa 3. Não há indexação nesta entrega.

O relatório JSON mostra contagens por documento e página, páginas sem texto, páginas curtas (menos de 80 caracteres não vazios), páginas com NUL/U+FFFD e posições sugeridas de amostra. O limite de 80 é apenas uma heurística de triagem. Ele não detecta toda perda de conteúdo, colunas desordenadas ou imagens. Nenhum texto extraído é impresso ou salvo pelo comando. PDFs e demais dados locais ficam excluídos pelo `.gitignore`.

O modo sem `--dry-run` é rejeitado com código 2. Arquivos ausentes, ilegíveis, criptografados ou sem páginas geram falhas e código 1; os outros arquivos continuam sendo inspecionados. Código 0 significa que os quatro arquivos foram lidos, **sem certificar qualidade ou completude do conteúdo**. `manual_review_required` permanece verdadeiro. O comando não importa SDK de modelos nem cliente Qdrant, não abre conexões e não grava os documentos ou trechos.

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

## Testes e evidências

```bash
source .venv/bin/activate
python -m pytest -q
python -m pip check
```

Na Etapa 1, foram obtidos **32 testes aprovados**, sem conexões externas ou credenciais. As fixtures geram PDFs sintéticos apenas nos diretórios temporários dos testes; PDFs reais não são usados pela suíte. Conexões externas de sockets são bloqueadas nos testes comuns. Foram verificados limpeza, preservação integral do texto normalizado, tamanho, avanço, sobreposição, limites de parágrafo/frase, referências físicas, páginas vazias, glifos suspeitos, PDF criptografado, dry-run sem exportar texto ou alterar arquivos, PDFs ausentes/corrompidos e API em memória.

Na Etapa 2, o resultado final em 28/10/2026 foi **97 testes aprovados** (32 existentes e 65 novos), sem chamadas reais. A suíte inclui HTTP simulado com `httpx.MockTransport`, passando pelo SDK instalado: corpo, rota e autenticação sintética; tipos de entrada; ordem, quantidade e dimensão de vetores; rejeição de vetores inválidos, booleanos e valores não finitos; escolha dos dois modelos; leitura incremental antes de consumir o restante do stream; encerramento normal, saída antecipada, erro, cancelamento e timeout; falhas HTTP, conexão e SSE; ausência de retentativas/redirecionamentos; teto de quatro chamadas e limite de saída; comando seguro por padrão e relatórios sem conteúdo. A validação foi feita antes das conversões permissivas do SDK para evitar aceitar um booleano como componente numérico. Essa suíte precisou executar fora do sandbox por causa dos sockets internos; a fixture continuou bloqueando conexões externas. O único aviso foi a depreciação do TestClient já registrada na Etapa 1.

`pip check`: nenhuma incompatibilidade declarada. A combinação instalada emite um aviso de depreciação de `httpx` no TestClient do Starlette; os testes passam. Não foi adicionada a biblioteca alternativa `httpx2`, que não faz parte das dependências aprovadas.

A suíte completa precisou executar fora do sandbox: a criação de sockets internos do TestClient fica bloqueada nele. Os 31 testes de processamento e CLI também passaram dentro do sandbox. Separadamente, Uvicorn foi iniciado em `127.0.0.1` e respondeu HTTP 200 em `/health`, `/docs` e `/openapi.json`; foi encerrado ao final. Essa verificação também precisou da permissão de socket local. Não houve chamadas reais de modelos, gravação no Qdrant ou publicação.

## Responsabilidades e pendências

`app/main.py` cria a API e a rota de saúde; `app/config.py` concentra constantes e valida a configuração do gateway com Pydantic; `app/ingestion.py` extrai, divide e resume; `scripts/ingest.py` valida argumentos e apresenta o relatório. `app/gateway.py` concentra o SDK e o contrato candidato; `scripts/check_gateway.py` coordena a verificação explícita. Os `TypedDict` descrevem registros e relatórios, sem classes de serviço.

A extração e a rota de saúde continuam síncronas. O FastAPI executa a rota `def` em seu pool de threads. O PDF é aberto com `with` e fechado após a extração. A API não mantém clientes externos nem executa ingestão durante importação, inicialização, atendimento ou encerramento.

No gateway, `async def` define operações que podem suspender durante I/O; `await` aguarda o SDK sem bloquear o ciclo de eventos. `asyncio.run` cria e encerra esse ciclo no comando. `iter_chat_parts` é um gerador assíncrono: cada `yield` entrega ao consumidor um fragmento ou motivo de término, e `async for` solicita o próximo. `open_chat_stream`, com `asynccontextmanager`, usa `yield` para disponibilizar o iterador dentro de `async with`; a abertura é aguardada antes de disponibilizá-lo, e a saída fecha o stream inclusive em erro/cancelamento. O comando reutiliza um cliente nas quatro requisições e o fecha ao sair do contexto. `asyncio.timeout` limita a chamada inteira. O compartilhamento de clientes pelo ciclo de vida da API e as rotas RAG/SSE pertencem às etapas posteriores.

Qdrant, `/ready`, `/models`, chat, autenticação da API e rotas SSE ainda não foram implementados. Nenhuma dimensão real de embedding foi medida. A qualidade da recuperação e das respostas ainda não foi avaliada. A inconsistência SSE registrada no checklist continua pendente para a Etapa 5 e não afeta o adaptador de streaming do provedor nesta etapa.

O repositório possui histórico prévio, preservado nesta entrega. Nenhum commit foi criado nem arquivo adicionado ao índice durante a Etapa 2. As exclusões de `.env`, `.venv/` e `data/` foram confirmadas na Etapa 1. A auditoria completa de segredos e artefatos privados no conteúdo versionado/histórico permanece pendente para a etapa correspondente; não foi realizada aqui.

Código, testes e documentação foram preparados com auxílio do Codex e validados conforme as evidências descritas. O [PRD](PRD.md) e as [instruções](AGENTS.md) foram preservados; esta entrega implementa somente a Etapa 2 sobre a Etapa 1 existente, sem executar modelos reais.
