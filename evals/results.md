# Resultados da avaliação

Atualizado em **29/10/2026**. Avaliação, revisão das respostas e verificações da publicação **concluídas, conforme confirmação do responsável**. Este registro substitui o estado inicial de preparação e pendências.

O conjunto contém 12 casos: oito perguntas respondíveis (R1–R8), duas sem suporte (N1/N2), uma tentativa de alterar instruções (I1) e uma solicitação clínica individual (C1). A amostra alternativa usa R1 e R7. Os critérios estão no [guia de avaliação](README.md) e na seção 12.2 do [PRD](../PRD.md).

## Resultados e origem das evidências

| Verificação | Resultado | Origem |
| --- | --- | --- |
| Gateway | Compatibilidade aprovada; embeddings de documento e pergunta com dimensão 1536 e streaming dos dois modelos com término `stop`. | Execução manual informada pelo responsável. |
| Extração e base | Quatro PDFs, 257 páginas e 285 trechos. Coleção `saude_mental_v1`, dimensão 1536, distância de cosseno; 285 payloads conferidos contra a preparação dos PDFs. | Inspeção e conferência local registradas anteriormente. Revisão visual e aceite das perdas confirmados pelo responsável. |
| Recuperação | Fonte esperada no top-4 em **7/8** perguntas; R7 sem acerto no resultado registrado. Meta mínima de recuperação atingida. | Resultado do estado privado conferido anteriormente. Nenhuma nova pontuação foi fornecida nesta atualização. |
| Respostas padrão | Conjunto de 12 casos e revisão das respostas concluídos. Inclui fundamentação, referências, completude, ausência de suporte e limites educacionais. | Confirmação do responsável, sem nova coleta ou transcrição de notas por caso nesta atualização. |
| Modelo alternativo | Amostra R1/R7 e revisões concluídas. | Confirmação do responsável. |
| Critérios de qualidade | Conclusão da avaliação e das revisões confirmada pelo responsável. O resumo automatizado exige ao menos 7/8 na recuperação e 14 revisões aprovadas. | Confirmação de conclusão; o comando de resumo não foi reexecutado nesta atualização. |
| Testes automatizados | Última suíte completa registrada: **387 aprovados**, com um aviso conhecido do TestClient. Correção posterior de índices de payload: **24 testes específicos aprovados**. | Testes anteriores com gateway simulado, Qdrant temporário e HTTP local; não medem qualidade semântica. |

As confirmações do responsável atualizam o registro anterior de R1 coletada sem revisão e demais respostas pendentes. Não foram produzidas novas medições, notas de revisão ou saídas de comandos para preencher o relatório. As evidências integrais, respostas e revisões permanecem privadas em `data/evals/`, fora do Git.

## Publicação

- **API:** [desafio-einstein.onrender.com](https://desafio-einstein.onrender.com/)
- **Swagger:** [desafio-einstein.onrender.com/docs](https://desafio-einstein.onrender.com/docs)

O responsável confirmou o funcionamento de `/health`, `/ready` e `/models`, do Swagger e da autenticação, das consultas JSON e SSE e da preservação da base remota após reinício. A correção dos índices de payload do Qdrant Cloud e as verificações remotas também foram confirmadas como concluídas. A URL foi fornecida pelo responsável; estes endpoints não foram consultados nesta atualização documental.

A entrega progressiva local já havia sido comprovada por HTTP com Uvicorn e provedor controlado: o primeiro `delta` chegou antes da conclusão da geração. A validação do ambiente publicado foi confirmada pelo responsável, sem tempos adicionais registrados aqui.

## Consumo e limites

O teto planejado de uma rodada completa é **12 embeddings de perguntas e 14 gerações**, com até 600 tokens de saída solicitados por geração na configuração padrão. Esse teto não representa consumo medido. Uso total de tokens, custo e duração das execuções reais não foram informados. Esta atualização consumiu **zero chamadas de modelos** e não repetiu avaliação, ingestão ou publicação.

O conjunto é pequeno e não estima confiabilidade estatística. Permanecem as limitações de glifos e ordem da extração, conteúdo não textual não interpretado, separação de trechos por página e ausência de limiar de similaridade calibrado. A presença de uma fonte recuperada não garante que ela sustente cada afirmação.

A documentação de execução está no [README principal](../README.md); o estado das etapas e as evidências adicionais estão no [checklist](../CHECKLIST.md).
