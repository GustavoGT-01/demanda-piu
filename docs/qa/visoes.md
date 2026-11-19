# QA das visões: Painel, Solicitações, Histórico, Operador, Calendário e Cronoanálise

Sessão F da bateria de testes. Nenhum código da aplicação foi alterado; bugs são só reportados.

- Servidor: `tests/test_qa_visoes.py` (`py -3 -m unittest tests.test_qa_visoes`): 45 casos, 43 passam, 2 são falhas esperadas (`expectedFailure`: V-06 e V-09). `ruff check` limpo.
- Tela: `tests/check_visoes.js` (`node tests/check_visoes.js`, jsdom contra o servidor real com dados semeados em pasta temporária): 510 verificações passam, 0 falham, 24 linhas `KNOWN-BUG` (8 bugs, alguns repetidos por fuso). `KNOWN-BUG` não reprova; `FIXED` aparece se o comportamento correto voltar.
- Tela real: navegador embutido, cópia de `data-demo` em pasta do scratchpad, porta 8106 (parada ao fim). Percorridos Painel, Solicitações, Histórico, Calendário e Cronoanálise no fuso America/Sao_Paulo; confirmaram V-02 e V-03 (captura da Semana com a lateral em "dom, 15/11" numa quarta).

Legenda: **PY** = test_qa_visoes.py (classe), **JS** = check_visoes.js (função), **NAV** = conferido no navegador.

## Matriz de cobertura

### Painel
| Funcionalidade | Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| KPIs | 6 cartões | números certos (abertas, andamento, pausadas, atrasadas, urgentes, concluídas hoje) | passou | JS painel; NAV |
| KPIs | clique em cada KPI | vai a Solicitações com o filtro certo e zera o resto (urg = Em aberto + Urgente) | passou | JS solicitacoes |
| Mapa | "Mais críticos" / "A–Z" | ordem por pontuação; A–Z por nome; botão marcado; volta | passou | JS painel; NAV |
| Mapa | `dm-idle`, `dm-hasLate`, `dm-pick` | só nos setores certos; `dm-pick` ao voltar do filtro, some com Limpar | passou | JS painel/solicitacoes |
| Mapa | etiquetas, "Sem usuários", "Em dia", barra, resumo | texto e largura | passou | JS painel |
| Mapa | sem setor ativo | "Nenhum setor ativo…" | passou | JS vazio |
| Atenção | pontuação e marcas | atrasada 100, urgente 60, pausada 20+ min, sem aceite 25+ min; ordem | passou | JS painel |
| Atenção | Ver / Cobrar / Reatribuir | abre gaveta, cobra, abre caixa | passou | JS painel |
| Atenção | teto 7 itens, contagem total | 7 de 120 | passou | JS volumes |
| Feed | 10 eventos, clique, hora | 14 no servidor, 10 na tela | passou | JS painel/volumes; PY PainelEOperador |
| Vazio | KPIs zero, "Nada crítico", "Sem eventos" | | passou | JS vazio |

### Solicitações
| Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|
| `dm-q` | ID, título, motivo, responsável; caixa e espaços; sem resultado; HTML vira texto; vazio | passou | JS solicitacoes |
| `dm-fSt` | todos os 8 valores (aberto, atrasadas, concluídas 4 no topo × 3 na coluna de 24 h, canceladas = coluna única) | passou | JS solicitacoes |
| `dm-fSec` / `dm-fPrio` / `dm-fType` | cada valor, setor sem solicitação, combinações (5 filtros), sem resultado | passou | JS solicitacoes |
| Limpar filtros | zera os cinco campos e o contador | passou | JS; NAV |
| Quadro/Lista | colunas, contadores, ordem, 24 h, teto 60 cartões e 90 linhas, abrir gaveta (clique e Enter) | passou | JS solicitacoes/volumes |
| Vazio | avisos nas colunas e na lista | passou | JS vazio |

### Histórico
| Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|
| `dm-hq` | ID, título, motivo; responsável não busca; HTML; vazio | passou | JS historico |
| `dm-hSt` / `dm-hFrom` / `dm-hTo` | cada valor, combinações, sem resultado | passou | JS historico |
| `hrel` (relações) | total por par, clique filtra, `aria-pressed`, não muda com filtro, conta arquivadas | passou | JS historico |
| `dm-hArq` | 30/90/365 dias, janela pedida, de 40 e 100 dias entram, de 400 fica fora, gaveta de arquivada | passou | JS historico; PY Historico |
| `hclear` | zera busca, status, origem, destino | passou | JS historico |
| `hclear` | zerar também o arquivo morto | **falhou** (V-02) | JS; NAV |
| Teto | 400 linhas, contador "450 de 450" | passou | JS volumes |
| Rota `historico` | só ADM; corpo inválido (14 variações); limites inclusivos; ordem; vazio; arquivo + principal vence; `HIST_MAX`; saída pública; sem mudar o rev | passou | PY Historico |

### Visão do operador
| Caso | Resultado | Onde |
|---|---|---|
| Abas Recebidas/Enviadas com contagem; sem abas do ADM | passou | JS operador |
| Filtros Minhas / Fila do setor / Concluídas e Em aberto / Concluídas; ordem; janela de 2 dias | passou | JS operador |
| Botões por estado, cadeado da do colega, vazio com atalho "Ver fila do setor" | passou | JS operador |
| Troca de aba volta ao filtro padrão; faixa de números | passou | JS operador |
| "Ver como": só leitura nos cartões | passou | JS verComo |
| "Ver como": botão ＋ Nova solicitação do cabeçalho | **falhou** (V-08) | JS verComo |
| Vista do servidor só traz o setor dele e o que ele pediu; sem dados de ADM | passou | PY PainelEOperador |

### Calendário
| Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|
| Mês | 42 células, hoje, fim de semana, contagem por dia, chips (máx. 3), "+ n mais", fora do mês vazio | passou | JS fronteiras |
| Fronteiras | 1º ms do mês/semana/dia entra, último ms do anterior não; último ms entra, 1º do seguinte não | passou | JS fronteiras (6 fusos/datas) |
| ‹ ›, "Este mês" | 13 meses para cada lado, título certo, arquivo morto só em mês passado (31 dias de folga) | passou | JS fronteiras; NAV |
| `dm-calSec` | filtra; sombreado muda por setor | passou | JS calendarioHorario/vazio |
| Semana | 7 colunas, cabeçalho, blocos, linha do agora | passou | JS fronteiras |
| Semana | lateral abre no dia de hoje/escolhido | **falhou** (V-03) | JS; NAV |
| Dia | 1 coluna, título, ‹ ›, itens das 00:00 e 23:59 (cortados) | passou (24 h); **falhou em dia de 25 h** (V-07) | JS fronteiras |
| Lateral do dia | lista, densidade em 4 faixas, pico | passou | JS fronteiras |
| Sombreado | desligado: referência 7h–17h (14); ligado: 17; feriado: 15; feriado de outro setor; horário próprio: 9 | passou | JS calendarioHorario |
| Resumo | "n no período", atrasadas, % no prazo | passou | JS fronteiras/vazio |
| Vazio | 0 / 0 atrasadas / "—" | passou | JS vazio |
| Fuso | America/Sao_Paulo (3 datas, incl. 29/02/2028), New_York 08/03/2026, Berlin 25/10/2026, Auckland 05/04/2026 | passou, exceto V-04/V-05/V-07 | JS fronteiras |

### Cronoanálise
| Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|
| Hoje / 7 / 30 dias | KPIs = rota; valores calculados à mão; Hoje conta desde 00:00 local | passou | JS cronoanalise; PY Crono; NAV |
| KPIs, insights, ranking, motivos (Pareto), tabela por setor | números e textos | passou | JS cronoanalise |
| Rota `crono` | só ADM; período só 1/7/30; nulos; médias; pausa; prazo exato no prazo e +1 ms atrasado; canceladas; fronteira do Hoje; 7 e 30 dias inclusivos; motivos; setores; ranking top 6; gantt 14+4 com as 8 chaves; `expediente` só com horário ligado | passou | PY Crono |
| 13 h | 9 linhas, ordem, legenda | passou | JS cronoanalise |
| Dia / Semana / Mês, ‹ ›, "Este mês" | eixo, hachurado de fim de semana, `--dm-gcols` | passou | JS cronoanalise/fronteiras; NAV |
| Mês | 17 meses à frente (28/29/30/31 dias) sem recusa; nenhuma janela > 31 dias | passou (fuso sem horário de verão) | JS cronoanalise |
| Mês em fuso com horário de verão | janela de 745 h | **falhou** (V-01) | JS fronteiras |
| Por setor / Por pessoa | grupos, ordem, "Fila do setor" | passou | JS cronoanalise |
| Teto `GANTT_MULTI`=120 e `cortado` | 120 linhas, aviso, urgentes dentro, Por pessoa | passou | PY Cronograma; JS volumes |
| Quem entra no corte | só as em aberto antes das concluídas | **falhou** (V-06) | PY; JS volumes |
| Rota `cronograma` | só ADM; corpo inválido; janela de 31 dias exata (+1 ms = 400); setor/pessoa; cancelada fora; entra pelo prazo; leitura não grava | passou | PY Cronograma |
| Janela invertida "é ordenada" | 400 em vez de ordenar | **falhou** (V-09) | PY (expectedFailure) |
| Horário de serviço | aviso "Fora do horário de serviço" fechado/aberto/desligado; `cr-off` por setor; legenda | passou | JS cronoanalise |
| Linha "Agora" em janela sem hoje | | **falhou** (V-05) | JS fronteiras |
| Dia de 23/25 h | colunas = horas do dia | **falhou** (V-04) | JS fronteiras |
| Vazio | KPIs "—", "Sem dados", "Sem solicitações no intervalo" | passou | JS vazio |

## Bugs encontrados

Todos reproduzidos (jsdom e, onde marcado, navegador). Gravidade pela chance de acontecer numa fábrica no Brasil (sem horário de verão desde 2019).

**V-01 · baixa (só fuso com horário de verão) · Cronoanálise Mês falha em outubro na Europa.**
Passos: fuso Europe/Berlin, hoje em outubro de 2026, Cronoanálise > Mês. Esperado: cronograma do mês. Obtido: o mês tem 745 h; a rota recusa ("Período de até 31 dias") e a tela fica em "Carregando o cronograma…" com toast de erro, sem estado de erro. Suspeitos: `demandas/demandas.js:805-822` (`crJanela`), `demandas/api.py:944` (`ate - de > CRONO_MAX`), `demandas/demandas.js:920-927` (sem tratamento do erro). No servidor reproduz com `ate = de + 31*DIA + 1` (PY `test_janela_maxima_de_31_dias_e_exata`).

**V-02 · baixa (a confirmar com o dono) · "Limpar" do Histórico não volta o arquivo morto.**
Passos: Histórico, "+ arquivo: 1 ano", Limpar. Esperado: filtros zerados. Obtido: busca/status/origem/destino zeram, `dm-hArq` continua em 365 e as arquivadas seguem na lista (NAV: `hArq=365` após Limpar). Suspeito: `demandas/demandas.js:2087` (`case 'hclear'` não mexe em `D.hArq`/`D.arq`). Pode ser intencional (escopo de dados, não filtro); sem menção no CONTRATO.

**V-03 · média-baixa · Semana: a lateral mostra sempre o domingo.**
Passos: Calendário > Semana numa quarta. Esperado: lateral do dia de hoje (ou do dia escolhido). Obtido: "dom, 15/11" (NAV e JS); as colunas da semana não são clicáveis, então não dá para trocar o dia. Suspeito: `demandas/demandas.js:778` (`c.modo === 'mes' ? 0 : GS`) e `:762` (`cal-col` sem `data-act="calday"`). No domingo parece certo.

**V-04 · baixa (dia de 23/25 h) · grade do Dia sempre com 24 colunas.**
Passos: Cronoanálise > Dia em 08/03/2026 (New_York) ou 25/10/2026 (Berlin). Esperado: colunas = horas do dia. Obtido: `--dm-gcols:24`; as linhas da grade ficam desalinhadas dos rótulos de hora. Suspeito: `demandas/demandas.js:869` (`modo === 'dia' ? 24`).

**V-05 · baixa · linha "Agora" colada na borda em janela que não contém o instante atual.**
Passos: Cronoanálise > Semana, ‹ (ou qualquer janela passada/futura) com linhas. Esperado: sem linha "Agora". Obtido: marcador em `left:100%` (passada) ou `0%` (futura). Suspeito: `demandas/demandas.js:861` (`dm-gnow` sempre desenhado; `L()` limita a 0–100).

**V-06 · média · o teto de 120 linhas do cronograma dá vaga a concluídas antigas antes de solicitações em aberto.**
Passos: 130 em aberto (normais) + 320 concluídas antigas; Cronoanálise > Semana/Mês. Esperado (CONTRATO: "escolhidas pela atenção"): as 120 vagas só com em aberto, atrasadas e urgentes primeiro. Obtido: 10 urgentes + 110 concluídas; 110 em aberto ficam de fora, com o aviso "mostrando as 120 mais urgentes". Suspeito: `demandas/demandas_calc.py:436` com `chave_atencao` (`:254-256`), que ordena concluída pelo prazo mais antigo. Reproduz em PY `test_known_bug_corte_deveria_preferir_as_em_aberto_as_concluidas_antigas`.

**V-07 · baixa (dia de 25 h) · Dia e lateral do dia perdem a última hora.**
Passos: Calendário > Dia (ou clicar no dia no Mês) em 25/10/2026 (Berlin) ou 05/04/2026 (Auckland) com solicitação às 23:59. Esperado: aparece. Obtido: some (8 de 9 itens). Suspeito: `demandas/demandas.js:747` e `:780` (`+ DAY` em vez da próxima meia-noite local).

**V-08 · baixa-média · "Modo visualização" ("só leitura") deixa o ＋ Nova solicitação do cabeçalho ativo.**
Passos: Administração > Usuários > "Ver como" qualquer pessoa; clicar em "＋ Nova solicitação" no cabeçalho. Esperado: botão escondido como o flutuante. Obtido: o formulário abre (a criação sairia como Escritório). Suspeito: `demandas/demandas.js:1647` (`.dm-hdnew` só esconde sem papel; o `.dm-fab` da linha 1646 considera `D.imp`) e `:2101` (`case 'new'` sem guarda de `D.imp`).

**V-09 · baixa · CONTRATO diz "invertida é ordenada", a rota devolve 400.**
Passos: `POST cronograma` com `de > ate`. Esperado: janela ordenada (`demandas/CONTRATO.md:261`). Obtido: 400 "Fim inválido." Suspeito: `demandas/api.py:943` (`ate` com mínimo `de + 1`). Corrigir o código ou o contrato.

Observações sem bug: o contador do Histórico mostra todos os filtrados mas a tela lista 400 (documentado no código); a coluna "Concluídas (24h)" do quadro não bate com o contador do topo quando há concluída antiga (por desenho); "Fila do setor" do operador lista também as do colega (com cadeado).

## O que não ficou coberto
- Teste de mutação (`qa.py mutate`) e medição de cobertura: não rodados nesta sessão (só os testes pedidos e o ruff).
- Navegação até antes de 1970 no Calendário (a rota `historico` rejeita `de` negativo; o clique não foi exercitado).
- Ações da gaveta e dos botões do operador (aceitar, pausar, concluir): são de outra sessão; aqui só presença e estado dos botões.
- Rolagem horizontal, responsividade e aparência (cores, animação de entrada); só estrutura e texto.
- Horário de verão no servidor (o `inicio_do_dia` do "Hoje" foi conferido só no fuso do PC; os fusos com horário de verão foram exercitados na tela, com o servidor no mesmo fuso).
- Navegador real só no fuso America/Sao_Paulo e só com os dados de demonstração.
