# Central de demandas

Programa local para pedir, aceitar e acompanhar demandas entre setores da fábrica: painel com mapa de setores,
solicitações em quadro e lista, gaveta com histórico, pausas, comentários e anexos, cronoanálise e administração de
setores e pessoas. Roda num computador da fábrica e atende celulares, tablets e outros computadores do mesmo Wi-Fi.

Só Python 3.10+ (biblioteca padrão). Nada para instalar além dele.

## Como usar
1. Dê dois cliques em `iniciar.bat`. O navegador abre em `http://127.0.0.1:8090`.
2. Neste computador você entra como **Escritório** (Administrador): em **Administração**, cadastre os setores e as
   pessoas (cada pessoa tem um código de 4 dígitos).
3. As pessoas entram em **Quem é você?** com setor, nome e código, e passam a pedir e atender demandas.
4. Para usar em outros aparelhos: clique em **⚙ Rede** (canto inferior esquerdo), ligue o acesso pela rede e feche e
   abra o `iniciar.bat`. O painel mostra o endereço e dois PINs:
   - **PIN do escritório:** abre tudo, inclusive a Administração;
   - **PIN dos operadores:** abre só a tela de operador.
   O PIN é pedido uma vez por aparelho e vale por 30 dias. Gerar um PIN novo derruba quem entrou com o antigo.

Feche a janela preta do servidor para desligar.

## Dados
Ficam em `data/` (fora do Git):

| Arquivo | O que guarda |
|---|---|
| `demandas.json` | setores, pessoas, demandas abertas e recentes e notificações |
| `demandas-arquivo.json` | concluídas e canceladas antigas (arquivo morto) |
| `demandas-anexos/` | anexos (JPG, PNG, PDF; até 5 MB cada, 5 por demanda, 300 MB no total) |
| `rede.json`, `sessoes.json` | configuração do acesso pela rede e sessões dos aparelhos (só o hash) |

Toda gravação é atômica e guarda o arquivo anterior como `.bak`: se o principal corromper, a leitura volta ao
`.bak`. **Backup:** copie a pasta `data/` inteira com o programa fechado.

Trazer dados de outra instalação: copie `demandas.json`, `demandas-arquivo.json` e `demandas-anexos/` para esta
`data/` com o programa fechado. O formato é o mesmo do módulo Demandas do CutFlow, de onde este programa saiu.

## Estrutura
| Caminho | Papel |
|---|---|
| `servidor.py` | servidor HTTP: página, arquivos do módulo, API, PIN, sessões e defesas (Host, Origin, CSP) |
| `store.py` | gravação segura dos JSON |
| `demandas/` | o módulo: `api.py` (rotas, regras e permissões), `demandas_calc.py` (tempos e cronoanálise), `demandas_store.py` (dados e anexos), `demandas.js`/`.css` (tela), fontes, `CONTRATO.md` |
| `web/` | a página (`index.html`) e a casca (`app.js`: `api()`, avisos, atualização e painel ⚙ Rede) |
| `tests/` | testes Python e o teste de tela em jsdom |

Variáveis opcionais: `DEMANDAS_PORT` (porta, padrão 8090) e `DEMANDAS_DATA` (pasta de dados).

## Qualidade
Regra em [docs/QUALIDADE.md](docs/QUALIDADE.md). Ferramentas de desenvolvimento em `requirements-dev.txt`
(coverage, ruff, mutmut) e, para o teste de tela, `npm install jsdom` dentro de `tests/`.

```bash
py -3 qa.py all
```

```bash
py -3 qa.py mutate demandas/api.py
```
