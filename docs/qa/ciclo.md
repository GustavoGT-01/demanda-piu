# QA · Ciclo da solicitação e anexos (sessão C)

Escopo: depois de criada, na gaveta e nos cartões do operador: aceitar, pausar, retomar, concluir, repassar, cancelar,
cobrar, prioridade, estender, comentar, anexos, máquina de estados, eventos, permissões e botões por papel.
Testes: `tests/test_qa_ciclo.py` (API, 118 testes) e `tests/check_ciclo.js` (tela em jsdom contra o servidor real, 183 casos).
Rodar: `py -3 -m unittest tests.test_qa_ciclo` e `node tests/check_ciclo.js`.
Tela real: conferida no navegador embutido (demo copiada, porta 8103) como operador (Carlos, CNC) e como Escritório.

Nota sobre o pedido: o limite do comentário é **1000** caracteres (CONTRATO.md e código), não 2000 (2000 é a descrição).

## Matriz de cobertura

Legenda: **P** = passou · **KB** = falha esperada (bug confirmado). PY = `test_qa_ciclo.py`, JS = `check_ciclo.js`.

| Funcionalidade | Campo / botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| Máquina de estados | 11 ações × 5 situações × 5 quem | 275 combinações: sucesso, 403/409 certos, falha não grava nada nem deixa arquivo órfão | P | PY `Maquina.test_matriz_acao_situacao_ator` |
| Máquina de estados | done/canc | nenhuma ação reabre | P | PY `test_nenhuma_transicao_sai_de_done_ou_canc` |
| Aceitar | botão Aceitar e iniciar | fila, designada ao outro do setor (vira dele), dois aceites simultâneos (um 200, um 409), clique duplo grava uma vez | P | PY `Maquina`; JS seções 1 e 5 |
| Pausar | 6 motivos | cada um grava; "Outro", vazio, minúsculas, tipos errados = 400 | P | PY `Limites.test_pausa_*`; JS modal (6 radios, um por um) |
| Pausar | observação ≤ 500 | 500 ok, 501 = 400, vazia/nula/espaços, \n \t \r \x00 = 400, emoji, strip antes de contar | P | PY `Limites`; JS (700 chars viram 500; quebra de linha vira espaço) |
| Pausar | teto 200 pausas | com limite reduzido = 400 | P | PY `test_pausa_teto_de_200_pausas_por_demanda` |
| Pausar | surrogate solto na observação | deveria ser 400; dá HTTP 500 | KB | PY `BugsConhecidos`; JS seção 5 (QA-C-01) |
| Retomar | botão | só responsável, só pausada; pausa fecha | P | PY `Maquina`; JS |
| Concluir | observação ≤ 500 | 500 ok, 501 = 400, vazia/nula/ausente, tipos, controles | P | PY `Limites`; JS (650 → 500) |
| Concluir | pausada/aberta | fecha a pausa; da fila só o responsável | P | PY `Maquina` |
| Repassar | setor / pessoa / nota ≤ 500 | setor inválido/inativo, pessoa de outro setor/inativa, vazia = fila, mesma pessoa, outro do setor mantém pausa | P | PY `Limites`, `Maquina`; JS (modal troca lista de pessoas) |
| Cancelar | motivo ≤ 500 | 500 ok, 501 = 400; só quem pediu ou ADM; pausa fecha | P | PY `Limites`, `Maquina`; JS |
| Cobrar | botão | quem pediu/ADM; evento e avisos (ADM não avisa a si mesmo) | P | PY `Eventos`; JS |
| Prioridade | 4 valores | inválidos = 400; igual = não grava; texto do evento; só ADM | P | PY `Limites`, `Permissao`; JS (select) |
| Estender | minutos 1…1440 | 0, 1441, negativo, bool, float, texto, nulo = 400; só ADM; só ativa | P | PY `Limites`; JS (+30 min, +1 h) |
| Estender | teto 43200 | 43200 exato ok, +1 = 400 | P | PY `test_estender_teto_de_30_dias_no_minuto_exato` |
| Comentar | texto 1…1000 | 1 e 1000 ok, 1001/vazio/espaços/nulo/controles = 400, \n ok, teto 300, setores da demanda, não vira evento | P | PY `Limites`; JS (maxlength, Enter, 1500 → 1000, HTML como texto) |
| Anexos | assinatura | JPG/PNG/PDF mínimos aceitos; um byte a menos, GIF/ZIP/EXE/HTML/SVG/WEBP/BMP/PDF com espaço ou BOM = 400; tipo vem dos bytes | P | PY `Anexos` |
| Anexos | tamanho | 5 MB exato ok, +1 byte = 413 | P | PY; JS (cliente recusa +1 byte; 5 MB passa) |
| Anexos | 5 por demanda; cota | 6º = 400, apagar libera; cota no byte exato (507) | P | PY `Anexos` |
| Anexos | nome | limpo (controle, U+202E, U+200B), 120 ok/121 = 400, vazio, traversal só como texto | P | PY `test_nome_*` |
| Anexos | enviar/ler/apagar por quem | por papel e situação (cancelada = 409 no envio; apagar só ADM ou autor e só ativa); ler: pedinte/destino/ADM, colega do pedinte = 403 | P | PY `Anexos`; JS |
| Anexos | tela | extensão, MIME, vazio, 5 MB+1, falso .jpg, 6º, visualizador, PDF, remover com confirmação | P | JS seção 2 |
| Anexos | uso no Administrador | contador após remover | KB | JS, PY (QA-C-02) |
| Anexos | aviso de limite | toast "No máximo 5" some na hora | KB | JS (QA-C-03) |
| Permissão | sem tk / tk ruim / vencido | 403 / 401 em 12 rotas; ADM com tk age como pessoa | P | PY `Permissao` |
| Permissão | id | malformado 400, inexistente 404 | P | PY `test_demanda_inexistente_e_id_malformado` |
| Eventos / sino | linha do tempo, quem, nota, avisos | ciclo inteiro; pedido do ADM → "adm"; corte em 120; created fica no teto | P | PY `Eventos`; JS |
| Botões por papel | cartão e gaveta | operador: aceitar/pausar/concluir/repassar/retomar; trava "🔒 Em andamento com X"; quem pediu: cobrar/cancelar; ADM: cobrar/reatribuir/+30/+1 h/prioridade/cancelar; encerradas sem ações; "Ver como" só leitura | P | JS seções 1–4 |
| Horário de serviço | desligado/ligado | ciclo completo; prazo, espera, execução, pausa, total, atraso úteis; estender em horas úteis; não cabe = 400; ações fora do expediente | P | PY `CicloSemHorario`, `CicloComHorario` |
| Tela real | aceitar, pausar (modal), retomar, anexar, visualizar, remover (Voltar/confirmar), comentar, concluir, Escritório: +30, +1 h, prioridade | conferido com capturas | P | manual (demo, porta 8103) |

Totais: PY 118 (115 P + 3 KB); JS 183 casos (180 P + 3 KB, 0 falhas); 275 combinações dentro de um teste PY.

## Bugs encontrados

**QA-C-01 · Observação/comentário com meio emoji dá HTTP 500 (média-baixa)**
- Passos: `POST demanda/pausar` (ou `comentar`) com texto terminando num surrogate solto, ex. `"a\ud83d"`. A tela produz isso ao cortar com `slice(0, 500)` / `slice(0, 1000)` no meio de um emoji.
- Esperado: 400 (ou gravar).
- Obtido: HTTP 500 "Erro interno do servidor" (UnicodeEncodeError ao gravar o JSON); estado fica intacto.
- Suspeita: `api.py` `_texto` (linha ~82) não rejeita surrogates; `demandas_store.py` grava com `ensure_ascii=False`.

**QA-C-02 · Total de anexos desatualizado após remover (baixa)**
- Passos: ADM anexa um arquivo grande, remove, abre Administração.
- Esperado: contador com o uso real.
- Obtido: continua mostrando o total de antes ("2,9 MB" com 2 KB no servidor; reproduzido na tela real) porque a tela não refaz a leitura (rev igual).
- Suspeita: `api.py` `_gravar`/`_anexo_apagar`: a vista é montada antes do `depois()` que apaga o arquivo.

**QA-C-03 · Aviso de limite de anexos some na hora (baixa, UX)**
- Passos: gaveta com 4 anexos, escolher 3 arquivos.
- Esperado: o usuário perceber que 2 ficaram de fora.
- Obtido: toast "No máximo 5 anexos" é trocado em ms por "1 anexo(s) enviado(s)".
- Suspeita: `demandas.js` `addFilesTo` (~1588).

Observações (não são bugs): cartão do operador não oferece Repassar em demanda pausada, mas a gaveta oferece e a API permite; ✕ de anexo usa o **nome** de quem enviou (`a.por === myName()`), então duas pessoas com o mesmo nome veriam ✕ no anexo uma da outra (a API devolve 403) — não testado de ponta a ponta; apagar anexo não deixa evento na linha do tempo.

## Não ficou coberto
- Seletor de arquivos nativo do navegador (simulado) e download real de PDF.
- Teste de mutação e cobertura medida (este trabalho só criou os testes).
- Teto real de 300 comentários / 200 pausas / 300 MB (usados limites reduzidos por mock).
- Concorrência além do aceite simultâneo; e-mails dos eventos; modo offline (já em `demandas_check.js`).
- Duplicidade de nome no ✕ de anexo; arquivo morto.
