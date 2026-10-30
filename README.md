# Consulta sobre saúde mental

API feita para um desafio técnico: responde perguntas em português com base em quatro apostilas de saúde mental e retorna as fontes por documento e página. Oferece resposta JSON, streaming via SSE, Swagger para explorar os endpoints e uma página mínima em `/teste` para acompanhar o texto progressivamente.

O uso é educacional, sem diagnóstico ou prescrição individual. Cada pergunta é independente, sem histórico de conversa.

**API publicada:** [Swagger](https://desafio-einstein.onrender.com/docs). As consultas exigem o token de acesso; a primeira requisição após inatividade pode demorar alguns segundos.

## Executar localmente

Use Python **3.12.3**. Na raiz do projeto, em Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp -n .env.example .env
```

Preencha o `.env` local. O comando de cópia preserva um arquivo existente; credenciais e dados privados ficam fora do Git.

| Variável | Configuração local |
| --- | --- |
| `LLM_BASE_URL` | URL base fornecida pelo gateway, incluindo `/v1` se necessário, sem o sufixo `chat/completions` ou `embeddings`. |
| `LLM_API_KEY` | Chave do gateway. |
| `QDRANT_COLLECTION` | `saude_mental_v1` para a base atual. |
| `EMBEDDING_DIMENSION` | `1536`, dimensão confirmada no gateway e na base atual. Em outra integração, meça antes de indexar. |
| `QDRANT_PATH` | `data/qdrant` (padrão). Deixe `QDRANT_URL` e `QDRANT_API_KEY` vazias para usar o modo local, sem servidor separado. |
| `API_ACCESS_TOKEN` | Opcional localmente. Quando preenchido, protege as duas rotas de consulta com Bearer. |

As demais opções podem ficar com os padrões de [.env.example](.env.example): `azure/gpt-5-mini` para geração, `azure/gpt-6-luna` como alternativa e `cohere/embed-v4.0` para embeddings.

O projeto lê variáveis exportadas no processo; não carrega `.env` automaticamente. Depois de editar o arquivo, carregue-o no terminal:

```bash
set -a
source .env
set +a
```

## Preparar a base

Os PDFs e o índice não acompanham o repositório. Coloque os quatro arquivos em `data/raw/`, com os nomes da [seção 4.1 do PRD](PRD.md#41-documentos-previstos), e confira a extração:

```bash
python -m scripts.ingest --dry-run
```

Esse comando não consome modelos nem grava no Qdrant. Revise as páginas sinalizadas: há limitações conhecidas de glifos e ordem do texto; imagens, áudio e vídeo não são interpretados.

Se ainda não verificou o gateway, execute o comando abaixo com a dimensão vazia no `.env` e o ambiente recarregado. São **até 4 chamadas reais: 2 embeddings e 2 gerações**, com até 600 tokens de saída solicitados por geração. Depois, preencha `EMBEDDING_DIMENSION` com o valor retornado e recarregue o ambiente.

```bash
python -m scripts.check_gateway --execute
```

Com o gateway conferido e a extração revisada, faça a ingestão. Para os PDFs atuais, o dry-run contabilizou **257 páginas e 285 trechos**, com teto de **18 chamadas de embeddings**, sem geração de respostas:

```bash
python -m scripts.ingest --execute --gateway-verified --extraction-reviewed \
  --max-embedding-calls 18
```

As opções de confirmação pressupõem essas verificações já realizadas. Se o dry-run apontar outro teto, revise-o antes de executar. Chamadas reais podem ser cobradas; não há retentativas automáticas. Uma ingestão repetida da mesma base reutiliza os trechos já gravados.

Use apenas um processo por diretório Qdrant local: pare a API antes de ingerir ou executar outros comandos que abram o mesmo índice.

## Subir e consultar a API

Com a base preparada e o ambiente carregado:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Abra [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Se configurou `API_ACCESS_TOKEN`, use **Authorize** e informe somente o token, sem o prefixo `Bearer`.

Em outro terminal, ative o ambiente virtual e exporte o `.env` como acima. Confira o processo, a base e os modelos sem consumir o gateway:

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
curl --fail http://127.0.0.1:8000/models
```

`/health` indica que o processo responde. `/ready` retorna 200 para a base utilizável ou 503 se ela estiver indisponível; não verifica o gateway.

Cada consulta abaixo pode consumir **1 embedding e 1 geração**, limitada por `MAX_OUTPUT_TOKENS` (600 por padrão). Para receber JSON:

```bash
curl --fail http://127.0.0.1:8000/chat \
  -H "Authorization: Bearer $API_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"question":"Como a atenção primária participa do cuidado em saúde mental?"}'
```

A resposta contém `answer`, `model`, `sources` e `finish_reason`. As fontes trazem documento, excerto e **página física do PDF, contando a partir de 1**, que pode diferir da numeração impressa. Para trocar de modelo, acrescente `"model":"azure/gpt-6-luna"` ao corpo.

Para acompanhar os eventos SSE:

```bash
curl --fail -N http://127.0.0.1:8000/chat/stream \
  -H "Authorization: Bearer $API_ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  --data '{"question":"Como a atenção primária participa do cuidado em saúde mental?","model":"azure/gpt-6-luna"}'
```

O stream envia `sources`, fragmentos `delta` e um terminal `done` ou `error`. `finish_reason: length` indica corte pelo limite de saída; `insufficient_context` indica falta de suporte. O Swagger serve para explorar o contrato; para medir a chegada dos eventos, use `python -m scripts.check_stream --execute --model azure/gpt-6-luna` **no lugar do curl SSE**, pois também faz uma consulta real.

## Demonstração no navegador

Com a API local em execução, abra [http://127.0.0.1:8000/teste](http://127.0.0.1:8000/teste). A página é pública e fica fora do Swagger. Carrega `/models` e seleciona o padrão; se falhar, bloqueia o envio e pede para recarregar.

Informe o **token da aplicação**, sem `Bearer`, se a API exigir autenticação. A página não persiste o token e o envia apenas no cabeçalho do POST. Deixe vazio no desenvolvimento local sem autenticação. Escolha o modelo, escreva uma pergunta independente de até 1.500 caracteres e clique em **Enviar**. Cada consulta pode consumir **1 embedding e 1 geração**; não há repetição automática.

A resposta aparece conforme os eventos SSE chegam e cada envio substitui o anterior. As fontes mostram identificador, documento e página física do PDF. **Parar** cancela a requisição e preserva o texto recebido. O estado distingue conclusão, limite de saída, contexto insuficiente, erro e encerramento sem terminal; um texto parcial pode estar incompleto. A página apresenta texto simples, sem Markdown, interpretação de HTML ou histórico de conversa.

## Testes

Com o ambiente virtual ativo:

```bash
python -m pytest -q
python -m pip check
```

A suíte usa dados sintéticos, gateway simulado e Qdrant temporário, sem credenciais ou consumo de modelos. Cobre ingestão e retomada, validação, autenticação, erros, limites e cancelamento. Os testes de streaming usam Uvicorn e HTTP local para conferir que fragmentos chegam antes da conclusão.

## Avaliação do RAG

O conjunto tem 12 casos: oito perguntas com fontes esperadas, duas fora da base, uma tentativa de alterar as instruções e uma solicitação clínica individual. Primeiro se verifica a recuperação; depois, as respostas do modelo padrão e dois casos no alternativo, com revisão das afirmações e referências.

Para visualizar o plano, sem chamadas de modelos:

```bash
python -m scripts.evaluate --phase retrieval
python -m scripts.evaluate --phase answers
python -m scripts.evaluate --phase answers --model alternate
```

A execução real exige a base pronta, ambiente exportado e as confirmações descritas no [guia de avaliação](evals/README.md). Uma rodada completa pode consumir **até 12 embeddings e 14 gerações**, além da preparação da base. Pare a API se usar o mesmo índice local.

Após preencher as revisões em `data/evals/stage6/reviews.json`, gere o resumo local, sem consumir modelos:

```bash
python -m scripts.evaluate --phase summary --execute
```

O resumo só retorna sucesso com pelo menos **7/8** na recuperação e as **14 revisões aprovadas**. Perguntas, respostas e trechos coletados ficam em `data/evals/`, fora do Git.

O resultado numérico registrado da recuperação foi **7/8**. A avaliação e a revisão das respostas foram concluídas, conforme confirmação do responsável no [relatório de resultados](evals/results.md). Os testes com substitutos verificam o código, sem medir a qualidade dos modelos.

## Decisões técnicas

- **FastAPI e Pydantic:** contratos validados e Swagger; `/teste` é a exceção mínima para demonstrar SSE na mesma origem, sem build de frontend.
- **RAG com funções e SDK OpenAI direto:** o fluxo é fixo — embedding da pergunta, busca e geração. O adaptador concentra os detalhes do gateway, sem LangChain ou LangGraph.
- **Qdrant:** guarda vetores e trechos juntos. Usa armazenamento local no desenvolvimento e Cloud na configuração de publicação, para preservar a base fora do disco temporário do Render.
- **Trechos por página:** até 1.200 caracteres, com sobreposição de 200. Facilita conferir as fontes, mas separa conteúdos que continuam na página seguinte. A busca traz até quatro trechos, sem limiar de similaridade calibrado.
- **Ingestão manual:** fica fora do startup e das consultas. IDs determinísticos permitem retomar sem duplicar pontos ou recalcular embeddings já persistidos.
- **JSON e SSE compartilham o mesmo RAG:** JSON acumula os fragmentos; SSE os repassa conforme chegam. Os clientes externos são assíncronos e reutilizados durante a execução da API.

Os limites iniciais são duas consultas simultâneas por processo e 90 segundos por consulta. Perguntas e respostas não são armazenadas por padrão. A configuração de publicação está em [render.yaml](render.yaml) e o registro das verificações está no [checklist](CHECKLIST.md).

## Uso de IA no desenvolvimento

Usei o Codex no planejamento por etapas a partir do PRD, na implementação de código e testes, na revisão de erros e na documentação. O [PRD](PRD.md) definiu os contratos e o [checklist](CHECKLIST.md) registrou as entregas e verificações.

Não usei LLM para reescrever as apostilas nem como avaliador das respostas. A conferência de fundamentação compara as afirmações da resposta com o contexto utilizado, o documento e a página.
