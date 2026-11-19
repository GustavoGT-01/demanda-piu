# QA · Administração (Setores, Usuários, Expediente)

Testes: `tests/test_qa_admin.py` (117 casos unittest direto no `api.py`, 6 falhas esperadas = bugs) e
`tests/check_admin.js` (210 conferências jsdom contra o servidor real, 7 `KNOWN-BUG`, 0 falhas).
Rodar: `py -3 -m unittest tests.test_qa_admin` e `NODE_PATH=tests/node_modules node tests/check_admin.js`.
Tela real (navegador embutido, porta 8104, cópia de `data-demo`): conferida a mão; ver "Tela real" no fim.

Legenda de onde: **PY** = `test_qa_admin.py` (classe), **JS** = `check_admin.js` (função), **existente** = já coberto em `test_demandas_api.py`.

## Setores

| Funcionalidade | Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| setor/salvar novo | sigla | 2, 4 caracteres, só dígitos | passou | PY SetorSalvar.test_sigla_valida_nos_limites |
| | sigla | 1, 5, minúscula, espaço, acento, `AB\n`, vazia, None, número, lista | passou (400) | PY test_sigla_invalida |
| | sigla | repetida, inclusive de setor inativo | passou | PY test_sigla_repetida_ate_de_setor_inativo |
| | nome | 3 e 40 ok; 2, 41, vazio, só espaços, tab, \n, \x00, \x7f, None, número: 400; strip | passou | PY test_nome_limites, test_nome_com_espacos… |
| | ícone / cor | todos os 20 e 12 aceitos; fora da lista, minúscula, vazio, tipos errados: 400 | passou | PY test_icone_e_cor_* ; JS (tela × servidor) |
| | e-mail | válido (minúsculas, strip), 254 ok / 255 400, local 64 ok / 65 400, formatos inválidos, injeção de cabeçalho | passou | PY test_email, test_email_invalido, test_email_limite_254 |
| | e-mail | vazio/espaços/None apaga; ausente não mexe | passou | PY test_email_vazio_apaga_e_ausente_nao_mexe |
| | modo / rev | modo inválido; rev ausente, string, None, bool, float: 400; novo aceita qualquer inteiro | passou | PY test_modo_invalido, test_rev_do_pedido |
| | limite | `ds.MAX["setores"]` | passou | PY test_limite_de_setores |
| setor/salvar editar | campos | muda nome/ícone/cor/e-mail, sigla é chave (id errado 404), validações valem | passou | PY test_editar_campos_e_sigla_imutavel |
| | `_rv` | rev -1/+1/0 → 409; mesmo rev não vale 2×; `_rv` só muda no registro tocado | passou | PY test_editar_nao_muda_ativo_e_conflito_409, test_rv_so_muda… |
| | permissão | pessoa (tk), operador sem tk, sem papel, tk falso (401); papel completo ok | passou | PY test_so_o_adm_salva, test_tk_de_pessoa… |
| setor/ativar | desativar | com 1/3 demandas (nova, andamento, pausada): 400 com contagem; aberta só como origem pode; concluída/cancelada libera | passou | PY SetorAtivar |
| | reativar | sem conferir demandas | passou | PY test_reativar_nao_confere_demandas |
| | efeito | pessoa do setor inativo não entra (404) e perde o tk (401); setor inativo não recebe pessoa nem demanda | passou | PY test_setor_inativo_* |
| | rev/id/permissão | 409, 404, 400, 403 | passou | PY test_rev_id_e_corpo, test_so_o_adm |
| | contrato | CONTRATO diz "400 com `abertas`"; o erro só tem a frase | **falhou** | PY test_known_bug_contrato… → QA-ADM-03 |
| setor/apagar | vazio | apaga setor + pessoas, revoga tk | passou | PY SetorApagar.test_apaga… |
| | histórico | principal (origem e destino), só no arquivo (origem, destino, pessoa do setor), pessoa com histórico em outro setor: 400 sem apagar nada | passou | PY test_recusa_historico_* |
| | rev/404/permissão | 409 vence histórico; 404; 403 | passou | PY test_rev_404_e_permissao, test_rev_velha_vence_o_historico |
| | agenda | apagar setor com horário próprio/feriado dele | **falhou** | PY test_known_bug_excluir_setor… e Expediente.test_known_bug_agenda… → QA-ADM-01 |
| Modal Novo setor (tela) | abrir, maxlength 40/4/254, 20 ícones, 12 cores, prévia, sem Desativar/Excluir | passou | JS setores |
| | `sf-save` | vazio → 2 erros; nome 2/41/"  ab  " erro, 3/40/40+espaços ok; sigla 1 e vazia erro; sigla sugerida "Corte e Dobra"→CD; digitação filtra/maiúscula/corta em 4; e-mail 4 formatos + 255 erro; ícone/cor marcam; criar grava tudo | passou | JS setores |
| | sigla repetida, Cancelar | erro "já está em uso"; Cancelar não grava | passou | JS setores |
| | erro some ao corrigir | sigla válida deveria limpar o erro | **falhou** | JS setores → QA-ADM-09 |
| Modal Editar setor | sigla travada, contadores, salvar, e-mail vazio apaga | passou | JS setorEditar |
| | `sf-toggle` | recusa com demanda aberta (toast); desativa; cartão "Inativo"; vira "Reativar"; reativa | passou | JS setorEditar |
| | `sf-del` | com histórico: aviso sem confirmar; sem histórico: confirmar/Voltar; histórico só no arquivo: servidor recusa | passou | JS setorEditar |
| | conflito 409 | modal aberto + outro aparelho salva → deveria dar 409 | **falhou** | JS setorEditar → QA-ADM-06 |
| 👥 Usuários do cartão | filtra a lista pelo setor | passou | JS setorEditar |

## Usuários

| Funcionalidade | Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| pessoa/salvar novo | nome | 2 e 60 ok; 1, 61, vazio, espaços, tab, \n, \x00, None, número: 400; strip | passou | PY PessoaSalvar.test_nome_limites |
| | código | obrigatório; 4 dígitos (0000, 9999, 0123 ok); 0, 3, 5 dígitos, letras, espaço, dígitos árabes, int, bool, lista: 400 | passou | PY test_codigo_obrigatorio… |
| | código | `"1234\n"` aceito | **falhou** | PY test_known_bug_codigo… → QA-ADM-02 |
| | código | nunca em claro (arquivo nem vista), sal diferente por pessoa | passou | PY test_codigo_nunca_vai_em_claro…, test_codigo_igual… |
| | setor | inexistente, vazio, None, minúsculo, inativo: 400 | passou | PY test_setor_do_novo |
| | e-mail | igual aos setores (254/255, vazio, inválido) | passou | PY test_email |
| | matrícula/id | M100+n, ids não reusados após apagar, seq | passou | PY test_matricula_e_ids…, test_id_nao_e_reusado… (+existente test_numero_sem_repetir) |
| | rev/modo/limite/permissão | 400/400/limite 500/403 (tk, operador, sem papel) | passou | PY test_rev_do_pedido_e_modo, test_limite_de_pessoas, test_so_o_adm |
| pessoa/salvar editar | nome/e-mail | muda; e-mail vazio apaga; inválidos 400 | passou | PY PessoaEditar.test_nome_e_email… |
| | código | vazio/None/ausente mantém; novo troca, derruba tk, zera bloqueio; inválido 400 | passou | PY test_codigo_vazio…, test_trocar_codigo_zera_bloqueio |
| | setor | inexistente/inativo 400; transferir devolve só as ativas dela à fila do setor antigo; pessoa de setor inativo editável sem trocar | passou | PY test_transferir_* , test_pessoa_de_setor_inativo… |
| | rev/404 | 409; id errado 404 | passou | PY test_rev_404_e_id |
| pessoa/ativar | desativar | devolve novas, em andamento e pausadas (fecha pausa), concluída fica, só as dela; revoga tk; não entra | passou | PY PessoaAtivar |
| | reativar | volta a entrar, não recupera demandas; inativo não é responsável | passou | PY test_reativar…, test_inativo_nao_e_escolhido… |
| | permissão | 403 (tk, operador); pessoa não se desativa | passou | PY test_rev_404_e_permissao, test_a_pessoa_nao… |
| pessoa/apagar | histórico | origem, destino, cancelada, arquivo (de e para): 400 | passou | PY PessoaApagar |
| | sem histórico | apaga e revoga tk; 409/404/403 | passou | PY PessoaApagar |
| Leituras | vista | ADM vê inativos e matrícula; operador só ativos, sem e-mail/hash/sal; pessoa não vê e-mail de ninguém | passou | PY AdminLeituras |
| Lista (tela) | busca | nome parcial, MAIÚSCULA, matrícula parcial/exata, espaços, sem resultado, HTML não injeta | passou | JS usuarios |
| | filtros | setor, status Ativos/Inativos, combinados com busca | passou | JS usuarios |
| Modal Novo usuário | `uf-save` | vazio → erro nome/setor/código; nome 1 e 61, código 3, e-mail inválido/255 erro; criar com nome 2, e-mail 254, código 0042 → toast com o código, M101, entra com o código | passou | JS usuarios |
| | `uf-gen`, `uf-eye` | código novo de 4 dígitos; alterna password/text; digitação filtra e corta em 4 | passou | JS usuarios |
| | setor | só ativos no seletor; do filtro já vem escolhido | passou | JS usuarios |
| | erro some ao corrigir | nome/código válidos deveriam limpar o erro | **falhou** (tela real) | QA-ADM-09 |
| Modal Editar usuário | salvar | sem código mantém hash; código 2 dígitos erro; código novo entra e o antigo 403; aviso ao trocar de setor | passou | JS usuarioEditar |
| | `uf-toggle` | desativar: demanda volta à fila, linha "Inativo", "Ver como" desabilitado, não entra, filtro Inativos; reativar | passou | JS usuarioEditar |
| | `uf-del` | com histórico: aviso sem confirmar; sem: Voltar/Excluir; só no arquivo: servidor recusa | passou | JS usuarioEditar |
| | conflito 409 | igual ao do setor | **falhou** | JS usuarioEditar → QA-ADM-06 |
| Ver como | habilitado/desabilitado, toast, tela só leitura, sair | passou | JS usuarioEditar; tela real |
| Permissão (tela) | operador/pessoa logada | sem aba Administração, sem botões, sem e-mail; tk recebe 403 em 7 rotas | passou | JS permissao |

## Expediente

| Funcionalidade | Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| Ligar/desligar | `hs-ativa` | de fábrica, ligar gasta versão, desligar gasta versão; não-booleano 400 | passou | PY Expediente.test_de_fabrica, test_ligar_e_desligar…, test_ativa_precisa_ser_booleano; JS expediente |
| | Salvar/Descartar | desabilitados sem alteração; habilitam ao alterar; voltar ao igual desabilita | passou | JS expediente |
| Dias | `hs-dia` | 1..7, ordenados, repetidos; 0, 8, -1, "1", bool, 1.0, None, não-lista: 400 | passou | PY test_dias_*; JS |
| Turnos | HH:MM | 00:00, 23:59 ok; 24:00, 7:00, 07:60, vazio, espaço, `07:00:00`, tipos errados: 400 | passou | PY test_hhmm_validos_e_invalidos |
| | HH:MM | `"07:00\n"` aceito e gravado | **falhou** | PY test_known_bug_hhmm… → QA-ADM-02 |
| | início = fim | 400 (tela: `＋ Turno` já nasce 17:00–17:00 e dá erro até editar) | passou | PY; JS |
| | limite 6 | 6 ok, 7: 400 | passou | PY test_limite_de_6_turnos; JS |
| | sobreposição | 1 min, contido, igual, encostar vale; virada de noite; semana circular dom→seg | passou | PY test_sobreposicao, test_virada_*, test_semana_circular… |
| | ≥ 15 min/semana | 14 recusa, 15 vale (1 dia, e 3×5); sem dias/turnos; desligado dispensa | passou | PY test_minimo…, test_o_minimo_so_vale_com_o_horario_ligado; JS |
| | ordem | gravados ordenados | passou | PY test_turnos_sao_gravados_em_ordem |
| Por setor | "horário próprio" | marcar copia o padrão; desmarcar remove; só escolher o setor não é alteração | passou | JS expediente |
| | regras | mesmas do padrão, com "Setor X:"; setor inexistente/minúsculo/inativo; tipos errados | passou | PY test_horario_do_setor_*, test_setor_da_excecao |
| | após salvar | tela deveria ficar no setor editado | **falhou** | JS → QA-ADM-07 |
| Feriados | data | bissexto, 0001/9999 ok; 29/02 não bissexto, mês 13, dia 31 de abril, formatos, `\n`, tipos: 400 | passou | PY test_data_do_feriado |
| | nome | 60 ok (também 60+espaços), 61 400, vazio, ausente; None/número 400 | passou | PY test_nome_do_feriado_limite_60 |
| | nome | caractere de controle aceito | **falhou** | PY test_known_bug_nome… → QA-ADM-04 |
| | setores | por setor, vários, todos; inexistente/minúsculo/tipos: 400; duplicado (mesma data+mesmo conjunto, em qualquer ordem) 400; chaves diferentes ok | passou | PY test_feriado_por_setor…, test_feriado_duplicado |
| | limite 400 | 400 ok, 401 recusa | passou | PY test_limite_de_400_feriados |
| | linha em branco | não é enviada; "nada mudou" não sobe versão | passou | JS expediente |
| | só nome / nome 61 | servidor recusa com a frase na tela | passou | JS expediente |
| | feriado com 2 setores | só o 1º aparece; editar só o nome preserva os 2; trocar para "Todos" zera | passou (preserva) / **falhou** (aparência) | JS → QA-ADM-05 |
| Versão `v` / 409 | `agenda/salvar` | v velha/adiantada/ausente/tipo errado: 409; inválido vence a versão velha | passou | PY test_versao_*, test_invalido_vence… |
| | nada mudou | reordenar/espaços/dias repetidos = igual: não grava, não gasta versão | passou | PY test_nada_mudou_nao_gasta_versao_nem_grava |
| | 409 na tela | edição em andamento não se perde; 409 mantém form editável; Descartar traz a versão nova | passou | JS expediente |
| | tela sem edição própria | deveria acompanhar a versão nova sozinha | **falhou** | JS → QA-ADM-08 |
| Poda de `agendas` | | mantém versão das ativas + vigente; sai quando concluir; teto de versões; cópia = vigente | passou | PY test_poda_*, test_copia_da_versao… |
| Permissão | só ADM | 403 para tk, operador, sem papel; 401 tk falso; papel completo ok | passou | PY test_so_o_adm_salva; JS permissao |

## Bugs encontrados

Todos reproduzidos antes de listar. Nenhum foi corrigido.

**QA-ADM-01 · Média · excluir setor deixa o horário órfão e trava o Expediente.**
Passos: criar setor PIN; salvar agenda com horário próprio e/ou feriado de PIN; excluir PIN (setor/apagar).
Esperado: a agenda perde as referências a PIN (ou a exclusão é recusada). Obtido: `agenda.setores.PIN` e o feriado ficam; todo `agenda/salvar` seguinte falha com 400 "Setor inválido no horário por setor" e a tela não lista PIN, então o ADM não consegue remover o horário. Suspeito: `api.py:810` (`_setor_apagar` não limpa `doc["agenda"]`/`doc["agendas"]`) combinado com `demandas_agenda.py:93-95,111-113`. Testes: PY SetorApagar/Expediente `test_known_bug_*`.

**QA-ADM-02 · Baixa · `^…$` + `match` aceita quebra de linha final.**
Passos: `pessoa/salvar` com `codigo: "1234\n"`; `agenda/salvar` com turno `"07:00\n"`. Esperado 400; obtido aceito e gravado com `\n` (o código passa a só entrar com a quebra). Suspeito: `api.py:31` (`CODE_RE`, usado com `.match` em 823 e 148) e `demandas_agenda.py:20` (`HHMM_RE`, `.match` em 58). Usar `fullmatch`/`\Z`. Testes: `test_known_bug_codigo_com_quebra…`, `test_known_bug_hhmm…`.

**QA-ADM-03 · Baixa · CONTRATO.md promete `abertas` que não existe.**
`CONTRATO.md:173` diz "desativar recusa com demanda aberta (400 com `abertas`)"; `ApiError` só leva a frase ("Setor com N demanda(s) em aberto…", `api.py:805`). Corrigir o contrato ou devolver o campo. Teste: `test_known_bug_contrato_promete_abertas…`.

**QA-ADM-04 · Baixa · nome de feriado aceita caractere de controle.**
`agenda/salvar` com nome `"Na\nta\x00l"` é gravado; os demais textos usam `CTRL_RE` e recusam. Suspeito: `demandas_agenda.py:107-109`. Teste: `test_known_bug_nome_do_feriado…`.

**QA-ADM-05 · Baixa · feriado com vários setores aparece como um só.**
Passos: agenda com feriado `setores:["CNC","PCP"]` (via API) → Administração › Expediente. Esperado: indicar todos os setores. Obtido: o seletor mostra só "CNC"; editar só o nome preserva os dois (ok), mas trocar o seletor para "Todos" apaga ambos sem aviso. Suspeito: `demandas.js:988` (`f.setores[0]`) e `hsInput` linha 1008. Teste: JS expediente (`QA-ADM-05`).

**QA-ADM-06 · Média · conflito de revisão (409) nunca dispara pelos modais Setor/Usuário.**
Passos: aba A abre "Editar setor" (ou usuário); aba B renomeia e salva; A atualiza sozinha (rev) e o ADM clica Salvar. Esperado: 409 "Alterado em outro aparelho". Obtido: salva por cima, perdendo a edição de B ("Setor atualizado"). Causa: `rev` é lido na hora de salvar (`s._rv`/`p._rv` da vista atual), não o do registro quando o modal abriu: `demandas.js:2190`, `2211`, também `2193`, `2198`, `2218`, `2222`. Guardar `rev` em `D.sform`/`D.uform` ao abrir (`openSF` 1495, `openUF` 1531). Teste: JS setorEditar e usuarioEditar.

**QA-ADM-07 · Baixa (UX) · Expediente volta ao "Horário padrão" depois de salvar.**
Quem editava o setor CNC cai em "Horário padrão da fábrica" ao salvar/descartar. Causa: `D.hs = null` em `hsSalva` (1040) e `hs-undo` (1023) perde `escopo`. Teste: JS expediente.

**QA-ADM-08 · Média · formulário do Expediente fica "sujo" e velho quando outro aparelho salva.**
Passos: abrir Expediente sem editar (v5); outro aparelho salva v6 com conteúdo diferente. Esperado: a tela acompanha a v6 (a intenção de `hsIni`). Obtido: continua mostrando "Versão 5 · alterações não salvas" com o conteúdo antigo, Salvar habilitado (leva 409) até clicar Descartar. Causa: `hsSujo` compara a cópia com a agenda **atual** da vista (`demandas.js:969`), não com a versão em que o formulário nasceu; assim `!hsSujo()` em `hsIni` (973) nunca é verdadeiro quando o conteúdo mudou. Guardar um instantâneo base em `D.hs` e comparar com ele. Teste: JS expediente (2 ocorrências).

**QA-ADM-09 · Baixa (UX) · erro de validação não some ao corrigir o campo.**
Sigla do setor, nome e código do usuário continuam vermelhos depois de válidos (o nome do setor limpa). Visto na tela real e no jsdom. Suspeito: `demandas.js:2247-2248,2255` (não zeram `err.id/name/code`). Teste: JS setores (sigla).

**Observações (sem teste):**
- Tela real: colar/inserir de uma vez "12-34" no código do usuário resulta "123", pois o `maxlength=4` corta antes do filtro de não-dígitos (`demandas.js:1542`, `2255`).
- E-mail de domínio com pontos seguidos (`a@b..com`) é aceito pela regex (`api.py:36`); inofensivo.
- `＋ Turno` nasce com início = fim (inválido até editar); comportamento já testado em `demandas_check.js`, aparentemente intencional.
- Reativar usuário cujo setor está inativo é permitido, mas ele continua sem entrar (coerente).

## Tela real (navegador embutido, 127.0.0.1:8104, cópia de `data-demo`)

Conferido com cliques e digitação: Setores (cartões, Novo setor vazio→erros, criar PI, editar nome/e-mail/cor, desativar, recusa de desativar CNC com 9 abertas, recusa de excluir CNC com histórico, reativar, excluir com confirmação), Usuários (lista, Novo usuário com erros de nome/setor/código, criar com código 4821 → toast, busca "ze t", Ver como com faixa "Voltar ao ADM", editar, desativar, excluir com confirmação), Expediente (layout, ligar, turno 17–17 recusado com frase, 17–18 salvo "Versão 1", Salvar/Descartar habilitando). Não repeti na tela real, por a sessão do navegador ter caído: feriados, horário próprio por setor e o 409 (cobertos no jsdom). Servidor da 8104 parado; `data\` real e porta 8090 intocados.

## O que NÃO ficou coberto

Perda de conexão (`D.off`) bloqueando `sf-save`/`uf-save`/`hs-save`; reinício do servidor com tokens (coberto em outro lugar); concorrência real com threads; efeito da agenda em prazos/atrasos (outras sessões); layout em celular/tablet; acessibilidade por teclado; feriado e horário próprio no navegador real.
