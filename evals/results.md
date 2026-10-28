# Registro de resultados — Etapa 6

Data: **28/10/2026**. Estado: **preparado, avaliação real pendente**. Nenhum gateway ou modelo real foi consumido nesta etapa; nenhuma dimensão ou pontuação semântica foi presumida.

| Verificação | Evidência obtida | Pendente |
| --- | --- | --- |
| Conjunto | R1–R8 preservadas e páginas reconferidas textualmente; N1/N2/I1/C1 definidos, critérios em [README](README.md). | Revisão visual geral da extração. |
| Evidências privadas | `references.json` criado localmente para os quatro PDFs, com páginas, hashes e triagem textual dos temas sem suporte. | Não versionar nem publicar. |
| Recuperação real | Nenhuma execução. | Oito embeddings; fonte no top-4 em ao menos 7/8 e revisão da pertinência do trecho. |
| Respostas padrão | Nenhuma execução. | 12 casos e revisão humana de fundamentação, referências, completude e limites/segurança. |
| Respostas alternativas | Nenhuma execução. | R1/R7 no outro modelo permitido, sem alteração de código. |
| Critérios 12.2 do PRD | Sem resultados reais para aplicar o aceite. | Todas as metas e registro das falhas/correções/repetições. |

| Caso | Recuperação top-4 | Fundamentação | Referências | Completude | Limites | Segurança |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Pendente | Pendente | Pendente | Pendente | — | — |
| R2 | Pendente | Pendente | Pendente | Pendente | — | — |
| R3 | Pendente | Pendente | Pendente | Pendente | — | — |
| R4 | Pendente | Pendente | Pendente | Pendente | — | — |
| R5 | Pendente | Pendente | Pendente | Pendente | — | — |
| R6 | Pendente | Pendente | Pendente | Pendente | — | — |
| R7 | Pendente | Pendente | Pendente | Pendente | — | — |
| R8 | Pendente | Pendente | Pendente | Pendente | — | — |
| N1 | — | Pendente | Pendente | Pendente | Pendente | — |
| N2 | — | Pendente | Pendente | Pendente | Pendente | — |
| I1 | — | Pendente | Pendente | Pendente | — | Pendente |
| C1 | — | Pendente | Pendente | Pendente | Pendente | — |
| R1 alternativo | Reutilizada quando coletada | Pendente | Pendente | Pendente | — | — |
| R7 alternativo | Reutilizada quando coletada | Pendente | Pendente | Pendente | — | — |

Bloqueios herdados: gateway/dimensão ainda não confirmados, perdas de extração sem revisão/aceite e ingestão completa não executada. A infraestrutura foi validada com substitutos; respostas sintéticas de testes não são respostas dos modelos. Não há falhas semânticas reais observadas nem correções de prompt/recuperação justificadas por essa avaliação. Não foi aplicado limiar de similaridade.

Reaproveitamento planejado: oito contextos para a fase padrão; R1/R7 também para o alternativo. Teto da avaliação: **12 embeddings + 14 gerações**. Pré-requisitos separados, ainda pendentes: compatibilidade **2 embeddings + 2 gerações** e ingestão inicial **até 18 embeddings**, conforme os 285 trechos do dry-run anterior. Executar uma vez cada um desses procedimentos representa teto conjunto de **32 embeddings + 16 gerações (48 chamadas)**. Não executar os antigos testes manuais de chat/stream ou `check_retrieval` adicionalmente sem novo plano de consumo.

Os testes automatizados verificam contratos, apuração, privacidade, reutilização, ordem das fases e recursos, sem avaliar a correção dos modelos. A evidência final da suíte e da auditoria está no [checklist](../CHECKLIST.md). Limitações permanecem mesmo após um futuro aceite: conjunto pequeno, glifos/ordem de extração, conteúdos em imagens/links não interpretados, trechos separados por página, dependência do julgamento humano e possibilidade de alucinação fora dos casos observados. Publicação não pertence a esta etapa.
