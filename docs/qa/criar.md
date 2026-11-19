# QA: Nova solicitação e rascunho (sessão B)

Escopo: formulário "Nova solicitação" (ADM e pessoa/operador), rota `demanda/criar` (`demandas/api.py` `_criar`, `_cid`,
`_texto`, `_int`, `_pessoa_do_setor`), rascunho no aparelho, chave `cid`, teto de abertas, avisos e horário de serviço.

Onde está cada coisa:

| Arquivo | O que cobre | Como rodar |
|---|---|---|
| `tests/test_qa_criar.py` | API pelo `api.handle` (campo a campo) e pelo HTTP de `servidor.py` | `py -3 -m unittest tests.test_qa_criar` |
| `tests/check_criar.js` | formulário em jsdom contra o servidor real (ADM e pessoa) | `node tests/check_criar.js` |
| tela real | navegador embutido, cópia de `data-demo` na porta 8102 (parada ao fim) | manual (seção 4) |

## 1. Resultado da execução (18/11/2026)

| Item | Número |
|---|---|
| Python: testes / casos (válido, inválido, limite, permissão) | 91 testes / 298 casos |
| Python: passou / falhou / falha esperada (bug confirmado) | 89 / 0 / 2 |
| jsdom: casos | 140 (140 passou, 0 falhou) |
| jsdom: bugs conhecidos checados (linhas `KNOWN-BUG`) | 7, os 7 ainda reproduzem |
| Cobertura de `_cid`, `_anota_cid`, `_criar` (linhas 413 a 467 de `api.py`) | 100% de linhas e de ramos (só `test_qa_criar`) |
| `ruff check tests/test_qa_criar.py` | sem apontamentos |
| Mutação (cópia no scratchpad, 54 mutantes manuais) | 53 mortos, 1 sobrevivente, 98,1% (seção 5) |

## 2. Matriz de cobertura

Resultado: **P** = passou, **BUG** = comportamento errado confirmado (ver seção 3), **OBS** = comportamento a decidir.
Sigla do teste: `PY` = `tests/test_qa_criar.py`, `JS` = `tests/check_criar.js`, `TELA` = conferido no navegador.

### Título
| Campo/botão | Caso | Res. | Onde |
|---|---|---|---|
| título | 5 letras (mínimo) e 140 (máximo) | P | PY `Titulo.test_limites_exatos`; JS "título de 5/140" |
| título | 4 letras e 141 | P | PY idem; JS "4 letras", "141" (recusa na tela, sem pedido) |
| título | vazio, só espaços, nulo, ausente | P | PY `test_vazio_nulo_ausente`; JS "enviar vazio" |
| título | espaços/NBSP nas pontas não contam; internos ficam | P | PY `test_espacos_nas_pontas_nao_contam`; JS "espaços das pontas saem" |
| título | caracteres de controle (`\x00 \x07 \t \n \r \x1f \x7f`) | P | PY `test_caracteres_de_controle` |
| título | tipos errados (número, bool, lista, objeto) | P | PY `test_tipos_errados` |
| título | acentos, emoji, `<img onerror>` guardados crus | P | PY `test_unicode...`, `test_html_vai_cru`; JS acentos |
| título | 3 emojis (6 unidades no JS, 3 no Python) | BUG QA-C-02 | JS known-bug |
| título | cinco U+200B (invisível) aceito | BUG QA-C-04 | PY `test_known_bug_titulo_so_de_caracteres_invisiveis` (falha esperada) |
| mensagem de erro por campo (`dm-err`) | título/setor/motivo marcados com a frase de cada um; some ao corrigir | P | JS "erros marcados por campo", "o erro do título some" |

### Tipo, motivo, prioridade
| Campo/botão | Caso | Res. | Onde |
|---|---|---|---|
| tipo (5 botões) | cada `TIPOS` grava; marca só um; padrão Demanda | P | PY `test_tipos_validos`; JS "tipo X marcado" |
| tipo | inválido (vazio, maiúscula, espaço, None, número, lista) | P | PY `test_tipo_invalido` |
| motivo (8 botões) | cada `MOTIVOS` grava; nenhum marcado por padrão | P | PY `test_motivos_validos`; JS |
| motivo | inválido, vazio, ausente, outra normalização Unicode | P | PY `test_motivo_invalido` |
| motivo | obrigatório na tela (erro "Selecione o motivo") | P | JS "enviar vazio" |
| prioridade (4 botões) | cada `PRIO` grava; padrão Normal | P | PY `test_prioridades_validas`; JS |
| prioridade | inválida | P | PY `test_prioridade_invalida` |
| prioridade | frase "Prioridade inválido." (gênero) | BUG QA-C-05 | PY `test_known_bug_frase_de_prioridade_no_masculino` (falha esperada) |

### Tempo estipulado
| Campo/botão | Caso | Res. | Onde |
|---|---|---|---|
| atalhos 30 min, 1 h, 2 h, 4 h, 8 h | gravam 30/60/120/240/480; prazo = criado + est | P | PY `Tempo.test_atalhos_da_tela`; JS "atalho N min marcado" |
| campo livre | 1 min (mínimo), 43200 min (máximo) | P | PY `test_limites_exatos`; JS casos 1 e 43200 |
| campo livre | 0, 43201 min | P | PY idem; JS (recusa na tela, campo marcado) |
| campo livre | vazio, negativo, texto, 0,4 min | P | JS (recusa na tela) |
| campo livre | decimal: 0,5 min vira 1; 1,5 h vira 90; 89,6 vira 90; 2,4 vira 2; 0,01 h vira 1 | P | JS |
| campo livre | horas: 720 h = 43200 (ok), 721 h (recusa) | P | JS |
| campo livre | trocar a unidade reinterpreta o número (90 min vira 90 h) | OBS | JS "90 min trocados para horas" |
| API `est` | 0, 43201, -1, 1.5, 60.0, NaN, inf, "60", None, ausente, bool, lista, objeto | P | PY `test_invalidos` |
| erro de tempo | campo continua vermelho ao digitar tempo válido | BUG QA-C-07 | JS known-bug |
| atalho marcado | continua marcado ao digitar outro tempo no campo livre | BUG QA-C-10 | JS known-bug; TELA |
| prévia do prazo | texto "Prazo final: ... (x a partir de agora)" acompanha o tempo | P | JS, TELA |
| prévia do prazo | com horário de serviço ligado | BUG QA-C-06 | JS known-bug; TELA |
| layout | unidade ("horas") cai numa linha própria, largura total | OBS QA-C-09 | TELA (só visual) |

### Descrição
| Campo/botão | Caso | Res. | Onde |
|---|---|---|---|
| descrição | vazia, nula, ausente, só espaços/quebras: vira "Sem descrição adicional." | P | PY `Descricao.test_vazia...`; JS |
| descrição | 2000 (máximo) e 2001 | P | PY `test_limite_exato`; JS (a tela corta em 2000) |
| descrição | espaços nas pontas não contam no limite | P | PY |
| descrição | quebras de linha ficam; as das pontas saem | P | PY `test_quebras_de_linha_ficam`; TELA |
| descrição | tab, `\r`, `\r\n`, controles são recusados pelo servidor | P | PY `test_tab_e_outros_controles...` |
| descrição | tab colado: a tela não avisa no campo | BUG QA-C-01 | JS known-bug; TELA |
| descrição | tipos errados; unicode e HTML como texto | P | PY |

### Setor, pessoa e solicitante
| Campo/botão | Caso | Res. | Onde |
|---|---|---|---|
| setor responsável | lista só os ativos; "Selecione" vazio é erro | P | JS estrutura e "enviar vazio" |
| setor responsável (API) | inexistente, vazio, minúscula, não texto, ausente | P | PY `Destino.test_setor_invalido` |
| setor responsável | inativo recusado; reativado volta a valer | P | PY `test_setor_inativo` |
| setor responsável | setor sem ninguém: aceita; a tela avisa "ficará aguardando" | P | PY `test_setor_sem_ninguem...`; JS |
| `para` | não objeto (texto, lista, None, ausente) | P | PY `test_para_invalido` |
| pessoa responsável | liberada após escolher o setor; trocar de setor zera | P | JS |
| pessoa responsável | de outro setor, inexistente, inativa, tipos errados | P | PY `test_pessoa_de_outro_setor...` |
| pessoa responsável | evento `assigned` e aviso só para ela; fila avisa o setor todo | P | PY `test_pessoa_do_setor...`, `test_fila_do_setor...`; JS |
| solicitante (ADM) | escolhe qualquer setor ativo; obrigatório; inválido/inativo recusado | P | PY `Solicitante`; JS fromS |
| solicitante (pessoa) | fixo (ela mesma); `de_s` forjado é ignorado | P | PY `test_pessoa_nao_forja...`; JS; TELA |
| campos de sistema no corpo (`status`, `id`, `criado`, `prazo_em`...) | ignorados | P | PY `test_campos_de_sistema...` |

### Botões Cancelar, Enviar, fechar
| Botão | Caso | Res. | Onde |
|---|---|---|---|
| Enviar | vazio: recusa na tela, sem pedido, formulário aberto | P | JS; TELA |
| Enviar | caso válido completo: registro, evento, aviso, toast, modal fecha, rascunho some | P | JS "pedido completo"; TELA |
| Enviar | três cliques seguidos: grava uma vez | P | JS "clique duplo" |
| Enviar | servidor recusa (400): formulário fica aberto, botão volta | P | JS (tab, emoji) |
| Enviar | resposta perdida e reenvio com o mesmo `cid`: não duplica | P | JS "resposta perdida" |
| Enviar | pessoa com tk caído (401): volta ao login; rascunho sobrevive | P | JS pessoa |
| Enviar | sem conexão/sem permissão (operador sem tk, papel vazio, tk ruim/vencido, pessoa/setor desativado) | P | PY `Permissao` |
| Cancelar (`mclose`) | fecha e mantém o rascunho | P | JS; TELA |
| Esc | fecha o formulário e mantém o rascunho | P | JS |
| Descartar (rascunho) | limpa formulário e aparelho | P | JS |
| botão "Nova solicitação" | escondido sem identificação | P | JS operador |
| foco | clicar numa opção leva o foco ao Título | BUG QA-C-08 | JS known-bug; TELA |

### Rascunho (`dm-rascunho:adm` / `dm-rascunho:<id>`)
| Caso | Res. | Onde |
|---|---|---|
| guarda título, descrição, setores, motivo, tipo, prioridade, tempo, `cid`; nunca o `tk` | P | JS (ADM e pessoa) |
| reabrir recupera todos os campos e mostra "Rascunho recuperado de dd/mm hh:mm" | P | JS; TELA |
| título e descrição só com espaços: rascunho apagado | P | JS |
| expira: 23 h 59 min volta, 24 h 1 s não | P | JS |
| rascunho adulterado (tipo, est, setores, motivo, prioridade, `cid`, textos longos) passa pelas listas da tela | P | JS |
| JSON ruim ou não objeto é ignorado; localStorage bloqueado não quebra | P | JS (e `demandas_check.js` existente) |
| rascunho com anexos avisa "refaça os anexos" | P | JS |
| pessoa A não vê o rascunho da pessoa B no mesmo aparelho | P | JS |
| sobrevive ao "Identifique-se de novo" | P | JS |
| reabrir renova as 24 h | OBS QA-C-03 | JS known-bug |

### Chave `cid`
| Caso | Res. | Onde |
|---|---|---|
| formato: 8 e 64 aceitos; 7, 65, vazio, espaço, acento, ponto, quebra, não texto recusados | P | PY `Cid.test_formato` |
| sem `cid`: grava e não anota | P | PY `test_sem_cid_grava_e_nao_anota` |
| reenvio (ADM e pessoa): não duplica; nada muda no disco (nem rev) | P | PY `test_reenvio_*` |
| pedido recusado não gasta a chave | P | PY `test_pedido_recusado_nao_gasta_a_chave` |
| chave repetida vem antes da validação (contrato) | P | PY `test_chave_repetida_ganha_da_validacao` |
| memória de 500 (teto): a mais antiga é esquecida e então grava de novo | P | PY `test_a_memoria_guarda_so_as_ultimas` |
| 8 reenvios em paralelo gravam uma vez | P | PY `test_reenvios_em_paralelo...` |

### Teto, número, avisos, gravação
| Caso | Res. | Onde |
|---|---|---|
| teto de abertas: o último cabe, o seguinte recusa (mensagem), cancelada/concluída liberam | P | PY `TetoENumero` |
| teto vale para a pessoa; validação vem antes do teto | P | PY |
| numeração SOL-1001..., sem reuso e sem buraco por recusa; 10 criações em paralelo sem repetir | P | PY |
| aviso `new` (pessoa ou setor); `urg` só para prioridade urgente (ADM e pessoa) | P | PY `Gravacao`; JS |
| recusa não cria aviso nem muda o rev | P | PY |
| registro gravado confere campo a campo | P | PY `test_o_registro_inteiro`; JS |

### Horário de serviço ligado
| Caso | Res. | Onde |
|---|---|---|
| desligado: sem `prazo_em` nem `agenda_v` | P | PY `Horario` |
| ligado: grava `prazo_em` (soma só dos turnos) e `agenda_v` | P | PY; JS; TELA |
| dentro do turno, almoço, fora do expediente, sábado, feriado | P | PY |
| horário do setor destino; nova versão só para as novas | P | PY `test_horario_do_setor_destino...` |
| desligar depois não muda o prazo gravado | P | PY |
| 43200 min cabe no padrão; não cabe: recusa 400 sem gravar nem gastar `cid` | P | PY |
| prévia do formulário usa o mesmo cálculo | BUG QA-C-06 | JS; TELA |

### HTTP de verdade (`servidor.py`)
| Caso | Res. | Onde |
|---|---|---|
| POST válido grava; mesmo `cid` não duplica | P | PY `Http.test_cria_e_responde_a_vista` |
| erro de campo: 400 com a frase pura | P | PY `test_erro_de_campo...` |
| JSON inválido, corpo não objeto, bytes inválidos: 400 sem gravar | P | PY |
| corpo vazio: recusa por campo | P | PY |
| Origin de outro site: 403 sem gravar | P | PY |
| GET na rota de escrita não grava | P | PY |
| acentos e emoji passam | P | PY |

## 3. Bugs encontrados

Todos reproduzidos antes de listar. Nenhum foi corrigido. Gravidade: M = média, B = baixa.

### QA-C-01 (M) Descrição com tab (ou outro controle) colada: erro sem campo marcado
- Passos: ADM ou pessoa, "Nova solicitação"; preencher o mínimo; colar na Descrição `col1<TAB>col2` (cópia de planilha); Enviar.
- Esperado: o campo Descrição marcado (`dm-err`) com a frase do problema, ou o tab trocado por espaço.
- Obtido: o servidor recusa (400) e só aparece o aviso passageiro "Descrição: texto com caractere não permitido."; nenhum campo marcado; o rascunho guarda o texto ruim e volta igual na próxima abertura.
- Suspeita: `demandas/demandas.js` `submitNew` (linha ~1457, valida só título, setor, motivo e tempo); `CTRL_NL_RE` em `demandas/api.py:34` recusa tab de propósito (testado como contrato). O ajuste é na tela.
- Teste: JS `known('QA-C-01'...)`; TELA.

### QA-C-02 (B) Título curto com emoji passa na tela e o servidor recusa
- Passos: título `😀😀😀`; Enviar.
- Esperado: a tela recusa como o servidor (3 letras).
- Obtido: a tela conta 6 (`String.length` em unidades UTF-16), envia, o servidor conta 3 pontos de código e responde "Título: de 5 a 140 caracteres."; campo sem marca.
- Suspeita: `demandas.js:1459` (`t.length < 5 || t.length > 140`); contar com `[...t].length`.
- Teste: JS `known('QA-C-02'...)`.

### QA-C-03 (B, a decidir) Rascunho ganha mais 24 h a cada abertura
- Passos: rascunho gravado há 23 h; abrir o formulário (recupera); o armazenado passa a ter `t` = agora.
- Esperado: validade de 24 h contada da última digitação.
- Obtido: `renderForm()` chama `rascGrava()` ao abrir, regravando `t`; um rascunho aberto todo dia nunca expira.
- Suspeita: `demandas.js:1449` e `rascGrava` (1402).
- Teste: JS `known('QA-C-03'...)`.

### QA-C-04 (B) Título só de caracteres invisíveis é aceito
- Passos: `POST demanda/criar` com `titulo` = cinco U+200B (largura zero).
- Esperado: 400 "Título".
- Obtido: criada uma solicitação sem nome visível.
- Suspeita: `_texto` (`api.py:82`) só tira espaços (`strip`) e controles ASCII.
- Teste: PY `test_known_bug_titulo_so_de_caracteres_invisiveis` (falha esperada).

### QA-C-05 (B, cosmético) "Prioridade inválido."
- Passos: `POST demanda/criar` com `prio: "max"`.
- Esperado: "Prioridade inválida."
- Obtido: "Prioridade inválido." (o `_de` monta `nome + " inválido."`). Só aparece fora da tela (a tela só manda valores válidos).
- Suspeita: `api.py:104` e `api.py:436`.
- Teste: PY `test_known_bug_frase_de_prioridade_no_masculino` (falha esperada).

### QA-C-06 (M) Prévia do prazo ignora o horário de serviço
- Passos: ligar o horário de serviço (padrão seg a sex 07 a 12 e 13 a 17); terça 23:08, abrir Nova solicitação, tempo 480 min; ver a prévia; Enviar.
- Esperado: a prévia mostra o prazo que o servidor vai gravar.
- Obtido: prévia "Prazo final: 18/11 07:08 (8h a partir de agora)"; o servidor gravou `prazo_em` = 18/11 16:00 (diferença de 9 h); o cartão passa a mostrar 16:00. Com 43200 min: prévia 17/12, gravado 09/03. A pessoa também vê a prévia corrida (TELA).
- Suspeita: `demandas.js:1451` (`prevTxt` usa `now() + est * MIN`); já existe `hsGrade`/`hsUtil` na tela (linhas 94 a 123) mas falta a conta inversa (somar tempo útil). O estudo `docs/estudos/05-calendario-cronograma.md:268` lista essa prévia como pendente.
- Teste: JS `known('QA-C-06'...)`; TELA.

### QA-C-07 (B) Campo do tempo continua vermelho depois de corrigido
- Passos: tempo 0, Enviar (campo marcado); digitar 45 no campo livre.
- Esperado: a marca some ao digitar valor válido (como no título).
- Obtido: some só ao clicar num atalho ou trocar a unidade.
- Suspeita: `setEstFromInputs` (`demandas.js:1452`) zera `err.est` mas não tira a classe do DOM quando `rerender` é falso; o handler do título (linha 2243) tira.
- Teste: JS `known('QA-C-07'...)`.

### QA-C-08 (M) Clicar numa opção leva o foco ao Título
- Passos: focar a Descrição, digitar; tocar em um motivo, prioridade, tipo ou atalho de tempo (ou trocar um select de setor/unidade).
- Esperado: o foco fica onde estava.
- Obtido: o formulário é redesenhado e `openModal` foca o primeiro campo; o que se digita a seguir vai para o Título (reproduzido na tela: o texto "Linha 1..." entrou no título). Em tablet abre o teclado a cada toque.
- Suspeita: `demandas.js:1349` (`openModal` foca `input, textarea, select`) chamado por `renderForm` (1428) a cada clique.
- Teste: JS `known('QA-C-08'...)`; TELA.

### QA-C-09 (B, visual, só na tela) Unidade do tempo cai em linha própria
- Na tela real (modal de ~400 px) o seletor "minutos/horas" aparece sozinho abaixo do campo "Personalizado", com largura total, parecendo outro campo. Pode ser intencional; não há teste (jsdom não mede layout). Suspeita: `.dm-row` em `demandas.css` e a linha 1445 de `demandas.js`.

### QA-C-10 (B) Atalho de tempo continua marcado quando se digita outro tempo
- Passos: clicar "2 h"; no campo Personalizado digitar 45 (unidade horas).
- Esperado: nenhum atalho marcado.
- Obtido: "2 h" fica marcado enquanto o tempo válido é 45 h (a prévia mostra "45h"); só desmarca ao redesenhar.
- Suspeita: `setEstFromInputs` sem `rerender` (`demandas.js:1452`).
- Teste: JS `known('QA-C-10'...)`; TELA.

### Observações (não listadas como bug)
- Com resposta perdida, a tela diz "O servidor está desligado. Abra o iniciar.bat e tente de novo." (mensagem da camada `window.api`, fora do formulário). O reenvio com a mesma chave funciona.
- O campo livre abre com a unidade "horas" (1 h): quem digita 90 pensando em minutos vê "90 h" na prévia (a prévia mostra, mas é armadilha).
- `est` com decimal vindo de fora (`60.0`) é recusado; a tela sempre manda inteiro.
- Descrição maior que 2000 só chega cortada pela tela fora do `maxlength` (só por script); o servidor recusa 2001.

## 4. Conferência na tela real

Servidor de demonstração (cópia de `data-demo` no scratchpad, `DEMANDAS_PORT=8102`, `DEMANDAS_MODO=demo`), navegador embutido, janela 1280x1000. Parado ao fim; `data\` e a porta 8090 não foram usadas.
- ADM: abrir, enviar vazio (3 erros com frase), digitar título, descrição com quebra, acentos e `<b>`, setor, pessoa (Carlos Souza), motivo, urgente, tempo 2 h, depois 45 na unidade minutos, Cancelar, reabrir (rascunho recuperado com tudo), Enviar: SOL-1151 gravada igual ao digitado, notas `new` (CNC, pessoa p2) e `urg` (adm), rascunho removido, toast "Solicitação enviada para Corte CNC".
- Tab na descrição: aviso passageiro, nenhum campo marcado (QA-C-01).
- Foco no Título após tocar em opção (QA-C-08); atalho "2 h" marcado com 45 h na prévia (QA-C-10).
- Horário de serviço ligado: prévia 18/11 07:08 contra prazo gravado 16:00 (QA-C-06).
- Pessoa (Helena Prado, operador): solicitante fixo "PCP Helena Prado", sem rascunho do ADM, enviado com `de.p` = ela, aba Enviadas mostra o pedido, rascunho `dm-rascunho:p0` removido, sem `tk` nele.

## 5. Mutação

Ferramenta: roteiro próprio (`mut_criar.py`, na pasta de rascunho da sessão) que troca uma linha por vez numa CÓPIA do projeto e roda `tests.test_qa_criar` com `-f`. O repositório não foi alterado (outras 6 sessões escrevem nele; `qa.py mutate` altera arquivos no lugar).

Resultado: 54 mutantes (limites de `_texto` e `_int`, validações de tipo, motivo, prioridade, tempo, descrição, setor, pessoa, `de_s`, teto, numeração, agenda, eventos, avisos, `cid`, `CID_RE`, teto de `cids`), **53 mortos, 1 sobrevivente, 0 inválidos, pontuação 98,1%**.
- Sobrevivente: "numeração ignora o arquivo morto". Era só coberto por `test_demandas_api.py`; foi adicionado `test_numero_continua_depois_do_maior_do_arquivo_morto` e o mutante passou a morrer (reconferido: morto).

## 6. O que NÃO ficou coberto

- Anexos do formulário (adicionar, remover, enviar após criar): fora desta área.
- Aparelho de operador real pela rede (cookie de papel `operador`, PIN): é de `tests/test_servidor.py`; aqui só `papel=operador` com e sem `tk` direto na API.
- E-mail ao criar (evento `created` na fila): é da sessão de avisos.
- Mutação do JS do formulário (não há ferramenta no projeto) e `qa.py mutate` oficial.
- Layout, teclado virtual e rolagem no tablet (só jsdom e navegador desktop).
- Colar um tab de verdade pela área de transferência (simulado por valor + evento `input`).
- Fuso/horário de verão no cálculo do prazo (é da sessão de tempo).
