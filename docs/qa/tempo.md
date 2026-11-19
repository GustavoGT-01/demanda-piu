# QA — regras de tempo e horário de serviço (sessão E)

Testes: `tests/test_qa_tempo.py` (Python, `py -3 -m unittest tests.test_qa_tempo`), `tests/check_tempo.js` (jsdom contra o
servidor real com relógio falso, `node tests/check_tempo.js`), vetores `tests/vetores_qa.json` (1620 casos gerados pelo
Python, conferidos nos dois lados; regerar com `QA_GERAR_VETORES=1 py -3 -m unittest tests.test_qa_tempo.Vetores`).
Datas: segunda 16/11/2026 e sexta 13/11/2026 (horário comercial 07–12 e 13–17). Nenhum código da aplicação foi alterado.

## Resultado da execução

| Suíte | Casos | Passou | Falhou | Falha esperada (bug) |
|---|---|---|---|---|
| `test_qa_tempo.py` | 80 testes (+ ~1.400 iterações de propriedade com semente fixa, 1620 vetores) | 76 | 0 | 4 |
| `check_tempo.js` | 50 conferências (1620 vetores em 2 fusos + 6 limites + 41 de tela) | 47 | 0 | 3 (KNOWN-BUG) |

`ruff check tests/test_qa_tempo.py`: sem erros.

## Matriz regra → caso → resultado → teste

Teste = `tests/test_qa_tempo.py::<Classe>::<método>` (código [Txx] na docstring); `JS` = `tests/check_tempo.js`.

| Regra | Caso (limite exato e um além) | Resultado | Onde |
|---|---|---|---|
| Atrasada | prazo−1, prazo exato, prazo+1 ms, +10 dias; new/prog/pause; done/canc nunca | passou | LimitesDeAtraso T01 |
| Atrasou concluída | fim = prazo, +1 ms; canc; sem fim | passou | T02 |
| Prazo | `prazo_em` vence est; 0 vale; bool/float/texto/None caem no corrido | passou | T03 |
| SLA | 50% às 07:00, 100,0% no prazo exato e +1 ms, 200%; fim de semana não anda; est ≤ 0 → None | passou | T04, T04b |
| Atraso congelado | 0, 1 min, 90 min, almoço; congelado × recalculado × sem `agenda_v` | passou | T05 |
| Fronteira de turno | abertura conta, fecho não (07/12/13/17, ±1 ms); espera criada no fecho/abertura/almoço | passou | Duracoes T10, T10b; JS |
| Espera | sem início usa fim, depois agora; cancelada | passou | T11 |
| Pausa atravessa noite/fim de semana | sex 16:00→seg 08:00 = 2 h; quarta→quinta noite = 0, +1 ms = 1 ms | passou | T12 |
| Pausa aberta | ativa até agora; fechada até o fim; sábado | passou | T13; JS (seg 07:10) |
| Pausa antes de reatribuição | fora do trecho de execução; segue em "pausado"; pausa atravessando o novo início | passou | T14, T48 (API completa) |
| Pausa fora do expediente | madrugada, almoço, domingo = 0; 1 ms dentro = 1 | passou | T15 |
| espera+execução+pausa = total | 300 casos aleatórios | passou | T16 |
| `congela` / `util` | done e canc; idempotente; vale sem agenda; ativa ignora `util`; sem `agenda_v` não grava | passou | T17 |
| Atenção sem aceite 25 min | 24:59,999 não, 25:00 sim; cruza fim de semana; só `new` | passou | Atencao T60, T60b; JS (16:55) |
| Atenção pausada 20 min | 19:59,999 não, 20:00 sim; cruza a noite; pausa fechada não | passou | T61; JS (seg 07:10) |
| Atenção atrasada | prazo exato não, +1 ms sim; done/canc não | passou | T62 |
| Atenção "late" em minutos úteis (Python) | prazo sex 17:00, agora seg 07:30: esperado 30, obtido 3750 | **falha esperada** (B2) | T63 |
| "Faltam / Atrasada há" na tela | 16:50, 17:00:00,000 (0 min, não atrasa), +1 ms, sábado, seg 07:15, 07:30, +1 ms, 08:30, almoço 12:00–13:00, 13:30 | passou (exceto B5) | JS `tela` |
| Cronômetro e SLA na tela | sábado = 30 min parado; C: espera 10, execução 10, pausa 1h 40, total 2h; barra 50% | passou | JS `tela`; navegador (8105) |
| `estender` | prazo no fecho +30 → abertura +30; almoço; 24 h úteis; vencido soma do prazo vigente | passou | Estender T20, T21 |
| `estender` aviso de atraso | novo prazo = agora mantém; +1 ms rearma e o tick avisa de novo | passou | T22 |
| `estender` sem horário / versão antiga / 30 dias | corrido; grade da versão antiga; 43200 passa e 43201 recusa (estado intacto); util = est | passou | T23–T26 |
| Versões `agenda_v` / `agendas` | A na v1, B na v2: medidas diferentes; vista leva só as em uso; concluir libera a versão, `util` fica | passou | VersoesDaAgenda T30, T31, T33 |
| Desligar / ligar depois | antiga segue útil; nova corrida; criada antes de ligar fica corrida (prazo, atraso, tick) | passou | T34, T35, T36, T37, T38 |
| Poda de versões (50) | 52 versões, todas com demanda ativa: sobram 50 e as mais velhas em uso somem | **falha esperada** (B3) | T32 |
| Migração v0/v1→v2, recusa de v3, agenda ilegível, 53 versões ao carregar | `.bak` guardado; v3 → 500 sem tocar no arquivo; ilegível → desligada; fica com as 50 maiores | passou | Migracao T39–T39d |
| Feriado geral / por setor | geral, só CNC, ESP e PCP; datas no mesmo dia; sáb/dom; virada de ano | passou | TurnoNoturnoEFeriado T43, T44; JS |
| Turno noturno | 22:00 conta, 06:00 não; sexta vai a sábado; feriado vale no dia do início (terça, sábado, sexta) | passou | T41, T41b, T42; JS; vetores |
| Horário próprio por setor | SLD sábado; feriado só do SLD; soma pula | passou | T45, T38 |
| Reatribuir (mesma grade) | CNC→PCP mantém util(criado, prazo) = est | passou | Reatribuicao T47 |
| Reatribuir entre setores | prazo do setor antigo × medida do novo (240 min para est 60) | **falha esperada** (B1); caracterização passa | T47c, T47b |
| `marcar_atrasos` / `tick` | prazo, +1 ms, uma vez; est 10 h não atrasa em 10 h corridas; done/canc; rev só muda com atraso; feriado; noturno | passou | Tick T50–T54 |
| `crono`, `gantt`, `expediente` | só com agenda ativa; `setores` só os próprios; médias úteis por versão; união sem sobreposição | passou | CronoEExpediente T70–T73 |
| Demanda antiga sem `agenda_v` / versão ausente | sempre corrido, prazo = criado + est | passou | T36, T37 |
| Concluída fora do expediente depois do prazo | texto "no prazo" × KPI/barra "atrasou" | **falha esperada** (B4); controle passa | ConcluidaForaDoExpediente T49, T49b; JS |
| Horário de verão simulado (TZ trocada) | turno da noite 7 h (virada), 9 h (volta); dia de 23/25 h; hora pulada; comercial inalterado; propriedades em 120 agendas | passou | HorarioDeVerao T90–T94c; vetores `dst` |
| Tetos | `soma_util`: 399–401 ok, 402 estoura; `util_entre`: 3699/3700, 3701 e 100 anos = 3700; sem grade sem teto | passou (ver observação 1) | Tetos T80–T82; JS |
| Propriedades | soma↔medida (e minimalidade), monotonia, aditividade, composição, util(criado, prazo) = est | passou | Propriedades T95–T99 |
| Paridade JS×Python | 1620 vetores (util, expediente, aberto; ±1 ms nas bordas; sem e com horário de verão) | passou | Vetores T100, T101; JS 1 |

## Bugs encontrados

Todos reproduzidos antes de listar. Nenhum foi corrigido.

**B1 — Reatribuir entre setores com horários diferentes deixa `prazo_em` e as durações em grades distintas (médio).**
Passos: horário ligado; ESP só trabalha sábado 06–10; demanda de 60 min criada sexta 16:30 no CNC (prazo seg 07:30); sexta
16:45 o ADM reatribui para o ESP. Esperado: prazo e medidas na mesma grade (no prazo, tempo útil = estimativa). Obtido: o
`prazo_em` continua o do CNC e `grade_de` passa a ler o ESP: o útil entre criação e prazo é 240 min para est 60; no sábado
10:00 o SLA já é 400% e ela não está atrasada; o aviso só dispara na segunda 07:30. Suspeita: `demandas/api.py` `_reatribuir`
(~l.545) não recalcula `prazo_em`; `demandas_calc.py` `grade_de` (l.51–57) lê `para.s`. Teste: `T47c` (`expectedFailure`).

**B2 — `calc.atencao` marca "late" em minutos corridos, a tela em minutos úteis (baixo).**
Passos: prazo sex 17:00, agora seg 07:30. Esperado 30 min (o que o `attention()` do JS mostra). Obtido 3750. Hoje
`calc.atencao` só é chamada pelos testes, então não aparece ao usuário. Suspeita: `demandas_calc.py` l.274
(`_min(agora - prazo(d))` sem `ag.util_entre`). Teste: `T63`.

**B3 — A poda de 50 versões apaga versão ainda usada por demanda ativa (baixo).**
Passos: 52 salvamentos de agenda, cada um seguido de uma demanda nova (todas ativas). Esperado: nenhuma versão em uso some.
Obtido: ficam 50; as versões 1 e 2 somem e essas demandas passam a medir em tempo corrido (`grade_de` → None), sem aviso.
Suspeita: `api.py` `_agenda_salvar` l.916 (`[:-ds.MAX["versoes"]]`), e igual no carregamento (`demandas_store.py` l.146).
Teste: `T32`.

**B4 — Concluída depois do prazo, fora do expediente: "no prazo" no cartão, "atrasou" no KPI e na barra (baixo).**
Passos: horário ligado; demanda de 30 min criada sexta 16:30 (prazo sexta 17:00); aceita 16:40, concluída sábado 10:00.
Esperado: as leituras concordarem. Obtido: `atrasou_concluida` = True (conta como atrasada no crono, no SLA do setor, barra
`dm-bad`), mas `util.atraso` = 0 e o cartão diz "Concluída 10:00 · no prazo" (confirmado na tela, `check_tempo.js`).
Suspeita: `demandas_calc.py` l.132 (`atraso` útil) × l.139 (`atrasou_concluida` compara o relógio); o mesmo ocorre com
atraso menor que ~3 s por causa do `round(…, 1)`. Teste: `T49` e KNOWN-BUG B4 no JS.

**B5 — Tela diz "Faltam 0 min" numa demanda atrasada quando o atraso útil é zero (baixo).**
Passos: B (prazo sex 17:00) vista sexta 17:00:00,001 ou sábado 12:00. Esperado "Atrasada há 0 min" (a pílula já é
"atrasada"). Obtido "Faltam 0 min" o fim de semana inteiro. Suspeita: `demandas.js` l.148 `hsDif` devolve `-0` e l.172
`rem >= 0` é verdadeiro para `-0`. Teste: KNOWN-BUG B5 em `check_tempo.js` (só JS).

## Observações (comportamento aceito, sem bug)

1. `soma_util` alcança 401 dias de trabalho (1 h/dia, a partir da abertura), não 400: o percurso é `dias + 2`. Fixado em `T80`.
2. Depois de reatribuir, a pausa anterior fica dentro da nova espera e também em "pausado": espera+execução+pausa passa do
   total (`T48`). O docstring de `execucao_ms` só promete que a execução não a desconte.
3. Atrasada fora do expediente com atraso útil 0 exibe "Atrasada há 0 min" (vide B5 para o `-0`).
4. Turno todo dentro da hora inexistente do horário de verão (02:30–03:30) não quebra e dá entre 0 e 1 h (`T94`). O Brasil
   não tem horário de verão desde 2019; o JS e o Python concordam nos 1620 vetores, inclusive nas viradas.

## O que NÃO ficou coberto

- Navegador embutido: só o cenário fora do expediente (quarta 04:14) com a base copiada; os instantes exatos da matriz
  foram verificados no jsdom com relógio controlado, não no navegador (o relógio real não se controla).
- Thread de fundo `servidor.tick` em processo real (a API `api.tick` está coberta; o jsdom roda sem a thread).
- Horário de verão só com as regras dos EUA (as do runtime do Windows); fusos com meia hora ou regras europeias não.
- Cronograma multidia (`cronograma`) além do `expediente` e do crono com agenda; arquivo morto (`historico`) em tempo útil.
- A tela de edição do horário (sub-aba Expediente) e a validação de `agenda/salvar`: já cobertas por `Horario` e
  `horarioDaTela`, não repetidas.
