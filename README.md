# Consulta educacional sobre Saúde Mental

Implementação restrita à **Etapa 1** do [PRD](PRD.md): API mínima e inspeção local de PDFs. O produto tem finalidade educacional; não realiza diagnóstico, prescrição ou atendimento clínico individual. O estado detalhado está no [checklist](CHECKLIST.md).

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

A Etapa 1 não lê credenciais nem exige arquivo `.env`. [.env.example](.env.example) documenta variáveis previstas para etapas futuras, ainda sem carregamento ou integração. Não preencha segredos no exemplo versionado.

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

Resultado obtido: **32 testes aprovados**, sem conexões externas ou credenciais. As fixtures geram PDFs sintéticos apenas nos diretórios temporários dos testes; PDFs reais não são usados pela suíte. A conexão de sockets é bloqueada nos testes comuns. Foram verificados limpeza, preservação integral do texto normalizado, tamanho, avanço, sobreposição, limites de parágrafo/frase, referências físicas, páginas vazias, glifos suspeitos, PDF criptografado, dry-run sem exportar texto ou alterar arquivos, PDFs ausentes/corrompidos e API em memória.

`pip check`: nenhuma incompatibilidade declarada. A combinação instalada emite um aviso de depreciação de `httpx` no TestClient do Starlette; os testes passam. Não foi adicionada a biblioteca alternativa `httpx2`, que não faz parte das dependências aprovadas.

A suíte completa precisou executar fora do sandbox: a criação de sockets internos do TestClient fica bloqueada nele. Os 31 testes de processamento e CLI também passaram dentro do sandbox. Separadamente, Uvicorn foi iniciado em `127.0.0.1` e respondeu HTTP 200 em `/health`, `/docs` e `/openapi.json`; foi encerrado ao final. Essa verificação também precisou da permissão de socket local. Não houve chamadas reais de modelos, gravação no Qdrant ou publicação.

## Responsabilidades e pendências

`app/main.py` cria a API e a rota de saúde; `app/config.py` concentra constantes da preparação; `app/ingestion.py` extrai, divide e resume; `scripts/ingest.py` valida argumentos e apresenta o relatório. Os `TypedDict` descrevem os registros de página, trecho e relatório, sem adicionar classes de serviço.

As funções da aplicação são síncronas nesta etapa. O FastAPI executa a rota `def` em seu pool de threads. O PDF é aberto com `with` e fechado após a extração. A API não mantém clientes externos nem executa ingestão durante importação, inicialização, atendimento ou encerramento; o ciclo de vida desses clientes pertence às etapas posteriores.

Gateway, Qdrant, `/ready`, `/models`, chat, autenticação e SSE ainda não foram implementados. Nenhuma dimensão de embedding foi presumida. A qualidade da recuperação e das respostas ainda não foi avaliada. A inconsistência SSE registrada no checklist continua pendente para a Etapa 5.

O repositório Git local foi inicializado por solicitação explícita em 27/10/2026, na branch `main`. Nenhum commit foi criado nem arquivo adicionado ao índice; ainda não há conteúdo versionado ou histórico para auditar. Além da verificação em repositório temporário, as exclusões de `.env`, `.venv/` e `data/` foram confirmadas no repositório do projeto com `git check-ignore`. Revisar os arquivos selecionados antes do primeiro commit.

Código, testes e documentação desta etapa foram preparados com auxílio do Codex e validados com as evidências acima. O [PRD](PRD.md) e as [instruções](AGENTS.md) foram preservados; somente a Etapa 1 foi executada.
