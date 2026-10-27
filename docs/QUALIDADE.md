# Regra obrigatória: qualidade, testes automatizados e teste de mutação

Nenhuma funcionalidade, correção, refatoração, módulo, API, componente ou aplicação está concluída sem os
testes pertinentes criados ou atualizados **e executados**. Vale para este projeto e como padrão para qualquer
aplicação nova.

## Como aplicar neste projeto

Comandos (raiz do projeto, Windows: `py -3`; CI: `python`):

| Comando | O que faz |
|---|---|
| `py -3 qa.py unit` | `unittest` de todo `tests/test_*.py`, um processo por arquivo de teste, em paralelo |
| `py -3 qa.py js` | `node --check` em `web/app.js`, `demandas/*.js` e `tests/*.js`; o check jsdom `tests/demandas_check.js` quando o `jsdom` existe (`npm install jsdom` em `tests/`) |
| `py -3 qa.py lint` | `ruff check` (`ruff.toml`) |
| `py -3 qa.py cover` | roda os testes com cobertura (em paralelo); linhas e branches por arquivo e a meta do escopo crítico |
| `py -3 qa.py all` | lint + js + cover: **os testes rodam uma vez só**, já com cobertura (a mutação fica de fora) |
| `py -3 qa.py mutate` | **mutação do código alterado**: as instruções que mudaram desde o último commit, nos arquivos do escopo crítico |
| `py -3 qa.py mutate arquivo [--funcoes f1,f2]` | mutação de um arquivo (as funções do escopo crítico dele, ou as pedidas) |
| `py -3 qa.py mutate --tudo` | o escopo crítico inteiro; demora: só quando pedido |

Ferramentas de desenvolvimento: `requirements-dev.txt` (coverage, ruff, mutmut). Não fazem parte do programa.

Como a mutação fica rápida sem deixar de ser completa:
- cada mutante roda **só os arquivos de teste que executam a linha dele** (a cobertura do `cover` grava qual
  teste executou cada linha); se o `cover` estiver velho, a mutação mede antes a cobertura só dos testes do alvo;
- mutante numa linha que **nenhum teste executa** não roda nada e conta como sobrevivente ("sem teste" no relatório);
- **cache** (`.qa/mutacao-cache.json`): mutante de função cujo código e testes não mudaram reaproveita o resultado
  anterior; o relatório mostra quantos vieram do cache. `--sem-cache` refaz tudo;
- arquivos de teste que não podem rodar em paralelo ficam em `SERIAL` no `qa.py` e rodam no fim, sozinhos.

**Escopo crítico** (meta: 80% de cobertura e de mutação; 90% nos cálculos de dinheiro e tempo):
o PIN, as sessões e a autorização do operador em `servidor.py`, `store.py` e a pasta `demandas/` inteira
(`api.py`, `demandas_calc.py`, `demandas_store.py`). Código novo entra com a meta cheia.

Fora do escopo, por decisão registrada: Playwright (o E2E em jsdom contra o servidor real já existe).

## 1. Papel
Engenheiro de software sênior, de QA e testes automatizados (unitários, integração e E2E), especialista em
teste de mutação e responsável por prevenir regressões. Não basta código que aparenta funcionar: testes
executáveis demonstram o comportamento esperado e detectam erros relevantes.

## 2. Antes de alterar o código
1. Identificar linguagem, frameworks, arquitetura e ferramentas de teste.
2. Inspecionar testes, configurações, dependências, comandos e CI.
3. Rodar a suíte existente quando viável (linha de base).
4. Identificar testes quebrados preexistentes, falhas ambientais e áreas sem cobertura.
5. Definir os testes necessários para a alteração.
6. Verificar as ferramentas de mutação compatíveis.
7. Preservar os padrões existentes; não criar frameworks de teste redundantes.

Não alterar regras de negócio, contratos de API, permissões, banco de dados ou funcionalidades não
relacionadas só para facilitar a aprovação dos testes.

## 3. Testes unitários
Toda função nova ou mudança de comportamento: comportamento normal; mínimos, máximos e limites; entradas
vazias, nulas, inválidas ou inesperadas; tipos incorretos e conversões; erros e exceções; regras de negócio e
cálculos; casos extremos; dinheiro, arredondamento, datas e quantidades; permissões e validações; dependências
externas simuladas quando apropriado; regressões de problemas corrigidos.
Os testes verificam resultados reais, não só que algo foi chamado. Evitar testes frágeis, dependentes entre si,
mocks excessivos e asserções que copiam a implementação.

## 4. Testes de integração
Quando houver comunicação entre componentes: frontend e backend, APIs e contratos, autenticação e autorização,
dados e integridade, módulos internos, upload e download, processamento assíncrono, integrações externas,
configuração. Ambientes isolados; nunca dados de produção. Sucesso, falha e recuperação.

## 5. Testes E2E
Fluxos críticos com interface: acesso, CRUD, formulários e filtros, fluxo interface → API → dados, mensagens,
navegação e persistência, fluxos principais e regressões. Ferramentas compatíveis com a stack, sem duplicar.

## 6. Teste de mutação (obrigatório)
Procedimento: identificar o código alterado e as regras afetadas; rodar os testes antes; gerar mutações realistas
(condições, comparações, aritmética, validações removidas, retornos, constantes, chamadas, limites, autorização,
tratamento de erro); rodar os testes contra os mutantes; registrar mortos, sobreviventes e não avaliados;
analisar cada sobrevivente relevante; criar ou melhorar testes; rodar de novo; registrar resultados e limitações.

Segurança: nunca deixar mutação no código de produção; nunca rodar mutantes contra dados reais; preservar o
trabalho do desenvolvedor; não sobrescrever arquivos alterados sem autorização; não dar mutante como equivalente
sem análise; não excluir mutantes para subir a pontuação; não usar exclusões amplas; documentar ferramenta
incompatível e escolher alternativa; se não rodou, não declarar aprovado.

Metas: 80% de pontuação no código relevante, 90% nas regras de negócio críticas quando viável. A pontuação não
substitui a análise dos sobreviventes. Distinguir mortos, sobreviventes, inválidos ou equivalentes (com
justificativa) e não cobertos ou não executados. Cobertura de linhas não é eficácia de teste.

## 7. Cobertura
Linhas, instruções, branches e decisões, funções, regras críticas e pontuação de mutação. Referência: 80% no
código relevante, 90% nos componentes críticos, sem números artificiais. Código legado: metas incrementais para o
código novo e alterado, sem reduzir a cobertura global.

## 8. Regressão
Toda correção de bug: reproduzir a falha; teste que falha pelo motivo certo; corrigir; teste passa; rodar os
testes relacionados; a suíte completa quando viável; avaliar mutações relevantes.

## 9. Automação
Comandos padronizados (tabela acima) para unitários, integração, E2E, cobertura, mutação, suíte completa e
verificações estáticas, centralizados no `qa.py` e integrados ao CI sem duplicar etapas.

## 10. Segurança e integridade
Autorização no backend; acesso indevido a recursos de outros; validação e sanitização de entradas; uploads e
limites; erros seguros; integridade transacional; nenhum segredo em log; proteção de operações destrutivas;
nenhuma mudança involuntária em permissões e contratos. Nunca dados reais sensíveis nos testes.

## 11. Desempenho
Só para operações com risco real (encaixe, geração de arquivos, consultas pesadas, tarefas assíncronas), com
limites e critérios registrados.

## 12. Quando aplicar
Sempre: função nova, bug, módulo, API, componente de tela, serviço, refatoração, aplicação nova, dados e
modelos, regra de negócio, qualquer tarefa. Alteração pequena: testes direcionados e impacto. Alteração crítica
ou ampla: suíte completa e mutação correspondente. Estratégia incremental, com verificações completas nos
pontos de validação.

## 13. Critério de conclusão
Requisitos atendidos; testes criados ou atualizados; testes direcionados rodados; suíte de regressão rodada;
mutação rodada ou impossibilidade documentada; sobreviventes relevantes analisados; verificações estáticas
rodadas; nenhuma regressão escondida; resultados e limitações registrados. Falhas preexistentes separadas das
novas. Nunca enfraquecer testes para aprovar.

## 14. Relatório ao fim de cada tarefa
1. Implementação. 2. Testes unitários (executados, aprovados, falhos). 3. Integração/E2E. 4. Cobertura (percentual
e escopo). 5. Mutação (ferramenta, mutantes, mortos, sobreviventes, inválidos/equivalentes, pontuação).
6. Regressões. 7. Verificações estáticas. 8. Falhas ou limitações. 9. Pendências. 10. Conclusão: aprovado,
aprovado com ressalvas ou reprovado, com justificativa. Nunca inventar números nem reaproveitar métricas antigas.

## 15. Prioridade
A qualidade dos testes faz parte da implementação. Não esperar pedido, não adiar testes, compilação não é
prova. Falha causada pela alteração: corrigir antes de concluir. Problema preexistente fora do escopo:
documentar sem mudanças arriscadas. Conflito entre rapidez e confiabilidade: validação proporcional ao risco,
explicando qualquer redução de escopo.
