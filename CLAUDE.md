# Central de demandas

**Regra obrigatória de qualidade: [docs/QUALIDADE.md](docs/QUALIDADE.md).** Nenhuma tarefa está concluída sem
os testes pertinentes criados e executados, a cobertura medida, o teste de mutação do código alterado e o
relatório final de 10 itens (seção 14), com números da execução atual.

Comandos (Windows `py -3`):
- `py -3 qa.py all`: lint, sintaxe dos JS, check de tela (jsdom em `tests/node_modules`), testes e cobertura.
- `py -3 qa.py mutate [arquivo]`: teste de mutação (escopo crítico por padrão).
- `py -3 servidor.py` ou `iniciar.bat`: roda o programa em http://127.0.0.1:8090.
- `iniciar-demo.bat`: modo demonstração em http://127.0.0.1:8091, base `data-demo/` e selo na tela
  (`DEMANDAS_MODO=demo`); `py -3 demo.py seed [--refazer] [--rede]` gera os dados fictícios. Nunca grava em `data/`.

Projeto independente: não importa nem lê nada de outro projeto.
