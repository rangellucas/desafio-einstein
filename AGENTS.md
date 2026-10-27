# Instruções do projeto

Leia o [PRD.md](PRD.md), fonte de verdade dos requisitos e contratos, antes de trabalhar. Consulte o [CHECKLIST.md](CHECKLIST.md) para o estado das etapas, decisões e pendências. As regras de trabalho estão na seção 15 do PRD.

- Execute somente a etapa solicitada. Concluir uma etapa não autoriza a próxima. Antes de editar, apresente um plano curto com arquivos afetados e validação prevista.
- Aponte inconsistências concretas; peça esclarecimento antes de implementar o comportamento afetado. Não altere requisitos silenciosamente.
- Siga a stack e os limites das seções 3–6. Prefira funções pequenas, fluxo explícito e classes apenas com necessidade concreta. Crie módulos quando implementar suas responsabilidades, sem arquivos vazios preventivos.
- Não acrescente bibliotecas, serviços ou frameworks sem apresentar necessidade e alternativas, preferindo opções gratuitas.
- Não acesse nem imprima valores de chaves. Não versione credenciais, PDFs, textos extraídos, embeddings ou índices privados. Não registre perguntas, respostas, prompts completos ou dados sensíveis por padrão.
- Chamadas reais de modelos, ingestão completa e publicação exigem solicitação de execução ou autorização explícita já concedida. Antes de executar, informe objetivo e quantidade máxima prevista de chamadas. Nunca faça ingestão no startup, build ou atendimento de perguntas; testes comuns e CI não consomem modelos.
- Preserve o propósito educacional, a rastreabilidade por documento e página física e o fluxo de RAG compartilhado entre JSON e SSE (seções 7–10). Não invente fontes, capacidades do gateway, dimensão de embeddings ou resultados de avaliação.
- Use tipos nas entradas e saídas relevantes. Explique `async`, `await`, `yield`, geradores e ciclo de vida quando surgirem, ligados ao fluxo real. Comentários devem explicar decisões, limites e efeitos externos.
- Execute verificações proporcionais à etapa. Diferencie revisão documental, testes com substitutos e verificações reais; não declare evidências que não obteve.
- Ao terminar, atualize o checklist com evidências, relate mudanças, validação e pendências e sugira uma mensagem de commit. Crie commits apenas quando solicitado, preservando o histórico existente.
