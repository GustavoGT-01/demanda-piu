# QA · Avisos, e-mail, backup, configurações e robustez transversal (sessão G)

Testes: `tests/test_qa_avisos.py` (Python, HTTP real, SMTP falso em 127.0.0.1) e `tests/check_robustez.js` (jsdom contra o
servidor real). Rodar: `py -3 -m unittest tests.test_qa_avisos` e `node tests/check_robustez.js`.
Nada foi enviado por e-mail de verdade; a tela real foi conferida numa cópia de `data-demo\` na porta 8107 (parada ao fim).

**Resultado da execução:** Python **94 casos: 90 passaram, 4 falhas esperadas (bugs B1–B4), 0 falhas inesperadas**
(`py -3 -m unittest tests.test_qa_avisos`, ~65 s; `ruff check` limpo). jsdom **119 PASS, 0 FAIL, 1 KNOWN-BUG (B5)**.
Cobertura de linhas e mutação **não** foram medidas para estes arquivos (são testes de QA; não alteram código da aplicação).

Legenda de resultado: ✅ passou · 🐞 falha esperada (bug confirmado) · 👁 conferido na tela real.

## 1. Sino e notas

| Funcionalidade | Campo / botão | Caso | Res. | Teste |
|---|---|---|---|---|
| nota/lida | nid | nota da fila: cada pessoa do setor marca a sua; quem pediu não recebe; ADM só vê as `adm` | ✅ | NT01 |
| nota/lida | repetir | marcar de novo (e `nota/todas`) não grava, rev não sobe | ✅ | NT02 |
| nota/lida | por pessoa (`pid`) | colega do setor não vê; Bruno/Helena/Escritório → 403 "Notificação de outra pessoa."; nada marcado | ✅ | NT03 |
| nota/lida, nota/todas | Escritório | só as notas `adm`; as do setor ficam | ✅ | NT04 |
| nota/todas | botão "Marcar todos como lidos" | marca só as minhas (fila + as só minhas); o colega mantém as dele | ✅ | NT05 |
| nota/lida | nid inválido | 99999, 0, -1, "1", 1.0, True, None, [], {}, 2**70, 1000 chars, ausente → 404 | ✅ | NT06 |
| nota/lida/todas | identidade | operador sem entrar 403; tk inexistente 401; pessoa desativada 401 | ✅ | NT07 |
| notas | limite 1000 | só as 1000 mais novas ficam; id nunca volta | ✅ | NT08 |
| vista | notas por setor | cada um só vê as do setor (e as dele) | ✅ | NT09 |
| gaveta do sino / contador | badge, "(n) título", filtros `aria-pressed`, Esc | varredura com dados de ataque | ✅ | check_robustez (xssEmTudo) · 👁 (99+) |

## 2. "Meus avisos" (`aviso/prefs`) e padrões da central (`/api/avisos`)

| Funcionalidade | Campo / botão | Caso | Res. | Teste |
|---|---|---|---|---|
| prefs da pessoa | padrão sem arquivo | 9 eventos ligados, curto, vibrar, 10 min, urgente fura; ler não cria arquivo | ✅ | AP01 |
| prefs | eventos | cada um dos 9, sozinho, por pessoa; só a diferença vai ao arquivo; Bruno/ADM não mudam | ✅ | AP02 |
| prefs | silêncio HH:MM | válidos 00:00, 23:59…; inválidos 24:00, 23:60, 7:00, "", " 22:00", "22:00\n", None, int… → 400 sem gravar | ✅ | AP03 |
| prefs | silêncio/eventos/urgente tipos errados | 400 com a frase certa; nada gravado | ✅ | AP04 |
| prefs | evento desconhecido, campos extras, `__proto__` | ignorados | ✅ | AP05 |
| prefs | som/vibrar/agrupar (são do aparelho) | ignorados, mesmo inválidos | ✅ | AP06 |
| prefs | `prefs` que não é objeto | 400 "Pedido inválido." | ✅ | AP07 |
| prefs | "Voltar ao padrão" | só `true` apaga; `false`/"true"/1 só leem; ganha de `prefs` | ✅ | AP08 |
| prefs | quem grava | ADM = chave `adm`; pessoa = a dela; tk errado 401; operador sem entrar 403 | ✅ | AP09 |
| prefs | avisos.json estragado | 7 formas de lixo → padrão; o salvar conserta | ✅ | AP10 |
| /api/avisos | som | curto/sino/desligado; 10 inválidos → 400 | ✅ | AC01 |
| /api/avisos | agrupar | 0/5/10; 14 inválidos → 400 | ✅ | AC02 |
| /api/avisos | vibrar, urgente fura | só booleano | ✅ | AC03 |
| /api/avisos | silêncio, eventos | válidos e inválidos | ✅ | AC04 |
| /api/avisos | um campo ruim | recusa o pedido todo | ✅ | AC05 |
| /api/avisos | padrão x pessoa | quem não mexeu acompanha; quem mexeu mantém | ✅ | AC06 |
| /api/avisos | corpo malformado / arquivo ruim | 400; salvar conserta | ✅ | AC07 |
| /api/avisos | permissão | só o computador principal (rede/operador em test_servidor.Avisos) | ✅ | AC08 |
| tela: Salvar padrões | som Sino → toast e arquivo | 👁 (porta 8107) | ✅ | tela |
| tela: silêncio com virada de meia-noite, urgente fura, agrupar 0/5/10, som/vibrar, aviso do Windows, tela acesa | 21:59/22:00/05:59/06:00, início=fim, turnos | **já cobertos** em `demandas_check.js` (`prefsDaTela`, `sistemaDaTela`, `avisosDaTela`); não repetidos | ✅ | existente |
| aparelho (localStorage) | 7 valores estragados em `dm-avisos-aparelho` e 6 em `dm-rascunho:adm` | nada quebra, formulário abre sem XSS | ✅ | check_robustez (armazenamentoEstragado) |
| Windows/tela acesa | fora de 127.0.0.1 | com `sistema`/`tela` guardados: nenhum aviso, nenhum wakeLock; a tela explica e mostra a origem escapada | ✅ | check_robustez (foraDoComputadorPrincipal) |

## 3. E-mail

| Funcionalidade | Campo / botão | Caso | Res. | Teste |
|---|---|---|---|---|
| config | padrão | desligado, 587, starttls, só "criada"; sem senha; sem `instalacao` | ✅ | EM01 |
| config | host (253/254), porta (1/65535/0/65536/"587"/587.0/True), segurança, usuário (254/255), remetente (300/301), link (200/201, `javascript:`, aspas), fila_setor, copia, descrição | limite exato e um além; recusado não muda nada | ✅ | EM02 |
| config | eventos (7) | um a um; tipos errados → "Eventos inválidos."; desconhecido ignorado | ✅ | EM03 |
| config | ligar | exige servidor e remetente; esvaziar o servidor ligado é recusado | ✅ | EM04 |
| config | um campo ruim | recusa tudo, arquivo intacto (bytes) | ✅ | EM05 |
| config | senha | 500/501; troca; `""` apaga; ausente/None mantém; nunca volta; cifrada no disco (DPAPI) | ✅ | EM06 |
| rotas | corpo malformado; `fila` com ação inválida | 400 | ✅ | EM07 |
| cadastro | e-mail de pessoa e de setor | limites (64 local, 254 total), caixa baixa, espaços, `""`/None remove, ausente mantém, injeção de cabeçalho/vírgula/`<>`/aspas | ✅ | EM08 |
| cadastro | visibilidade | só o Escritório vê e-mails (pessoa e lista pública do operador, não) | ✅ | EM09 |
| fila | 7 eventos → destinatários e cópia | created/started/comment×2/nudge/done/canc/late, com SMTP falso; prioridade e prazo não mandam; fio (In-Reply-To), `Auto-Submitted`, link `#SOL-n` | ✅ | EM10 |
| fila | evento/e-mail desligado | nada guardado; desligar não manda o que sobrou | ✅ | EM11 |
| fila | sem destinatário | só no registro (`sem_destinatario`) | ✅ | EM12 |
| gaveta ✉ | linhas do registro | só ADM, sem o item guardado | ✅ | EM13 |
| mensagem | XSS no HTML do e-mail | título, descrição, comentário, nome: escapados; assunto em texto puro | ✅ | EM14 |
| mensagem | link `#SOL-n` | com/sem barra final; sem link; href escapado | ✅ | EM15 · jsdom `linkDoEmail` (existente) |
| mensagem | descrição ligada/desligada | respeitada | ✅ | EM16 |
| mensagem | título com U+2028/U+0085 | **nunca vira e-mail** | 🐞 | EM17 (B3) |
| fila | falha permanente, Reenviar falhas, Limpar falhas | HTTP + SMTP 550 | ✅ | EM18 |
| fila | senha recusada (535) | pausa a fila, 1 login só, Retomar manda tudo | ✅ | EM19 |
| Enviar teste | caso normal | frase "Enviado para … sem criptografia em n,n s", não salva o formulário | ✅ | EM20 · jsdom (existente) |
| Enviar teste | destinatário 254/255, tipos, vazio | "E-mail do teste inválido." | ✅ | EM21 |
| Enviar teste | senha digitada x guardada | login com a certa | ✅ | EM22 |
| Enviar teste | 535, 550, porta fechada, STARTTLS/SSL sem suporte | frase em português, ok=false, senha não vaza, nunca 500 | ✅ | EM23 |
| tela: Enviar teste sem servidor | toast "Para testar, preencha…" | 👁 | ✅ | tela |

## 4. Backup

| Funcionalidade | Campo / botão | Caso | Res. | Teste |
|---|---|---|---|---|
| config | hora (00:00, 23:59 / 24:00, "03:00\n"…), on, ao_ligar, limite_mb (50/1000000, 49/1000001) | limite exato e um além; nada muda se recusado | ✅ | BK01 |
| config | retenção diárias/semanais/mensais/manuais 1–60 | 0, 61, "7", True, 7.0, None, não-objeto; chave desconhecida ignorada | ✅ | BK02 |
| config | pasta de destino | válida (acentos, espaços), cópia vai para ela e não para a padrão; relativa, dentro de `data`, raiz, pai inexistente, 261, tipos, arquivo → 400; `""` volta ao padrão | ✅ | BK03 |
| config | pasta com caractere nulo | **conexão cai sem resposta** | 🐞 | BK03b (B4) |
| config | vários campos, um ruim | recusa tudo | ✅ | BK04 |
| rotas | corpo malformado; sem criar pasta | 400 | ✅ | BK05 |
| Fazer agora | zip verificado, manifesto, sha, lista, sem `.part`, nada de rede/sessões | ✅ | BK06 · 👁 |
| lista / retenção | mais nova primeiro; só as 2 últimas manuais | ✅ | BK07 |
| cópias v0 e v1 do `demandas.json` | `demandas.json.v0.bak` / `.v1.bak` = arquivo antigo intacto, rev preservado, não pisa na cópia existente, nunca `.v2.bak` | ✅ | BK08a, BK08b |
| versão mais nova (v3) | 500 com a frase; arquivo intocado; backup recusado ("Cópia com defeito") | ✅ | BK09 |
| backup de banco v1 | copia sem migrar | ✅ | BK10 |
| Restaurar | confirmação `RESTAURAR` exata (6 variantes recusadas), prévia, dados voltam, "antes de restaurar" guarda o que ia se perder, sessões caem (401), SOL-n não volta, rev sobe, aviso na vista | ✅ | BK11 · 👁 |
| Restaurar/prévia | nome `../`, `..\`, caminho absoluto de zip válido fora da pasta, tipos, NUL, 2000 chars → 404 | ✅ | BK12 |
| verificação do zip | `..`, caminho absoluto, anexo com `..`, nome fora da lista, sem manifesto, formato 99, JSON ruim, dados v3, sem principal, hash errado, manifesto lista, vazio, "não é zip", zip truncado → 400, nada muda, nada fora de `data` | ✅ | BK13 |
| Restaurar | cópia só com `{"v":2}` e cheia de lixo | restaura e o programa segue | ✅ | BK14 |
| anexos | apagado volta com a restauração | ✅ | BK15 |
| pasta de destino sumiu | 500 "Pasta do backup não encontrada.", alerta grave sem caminho (vista do ADM), pessoa não vê, volta e recria | ✅ | BK16 |
| desligado | aviso "Backup automático desligado." e a thread não copia | ✅ | BK17 |
| tela | Fazer agora (toast, verificado), Restaurar desabilitado até digitar RESTAURAR, restaurou | 👁 | ✅ | tela |
| tela: Restaurar, RESTAURAR digitado, cancelar | já em `demandas_check.js` (`restaurarPelaTela`) | ✅ | existente |

## 5. Configurações, demonstração, `.bat`

| Funcionalidade | Caso | Res. | Teste |
|---|---|---|---|
| Rede | `on` só bool, `newpin` só `true`; ligar só vale ao religar (`active`); corpo ruim → 400 | ✅ | CF01 |
| PIN | 25 trocas: sempre 6 dígitos e diferentes; trocar um não troca o outro | ✅ | CF02 |
| Servidor | chaves, 12 últimas linhas do log, sem senha/PIN/caminho de pasta, contagem de cópias | ✅ | CF03 · 👁 |
| Demonstração | `DEMANDAS_MODO`: demo/DEMO/" Demo " → demo; "demonstracao", "1", "", "demo2" → normal | ✅ | CF04 |
| Demonstração | recusa a base real (4 grafias do caminho), exit 1, nada criado/alterado na pasta (cópia do programa em pasta temporária) | ✅ | CF05 |
| Demonstração | sobe na base própria, `/api/eu` e `/api/servidor` dizem `demo`, não toca `data` | ✅ | CF06 · 👁 selo |
| `.bat` | iniciar-demo aponta para data-demo/8091/demo; iniciar.bat nunca; parar.bat existe (eco com `)`: test_bat.py) | ✅ | CF07 |

## 6. Transversais

| Funcionalidade | Caso | Res. | Teste |
|---|---|---|---|
| Toda rota POST (31) | cada campo (e campos dentro de objetos) × 26 valores ruins + campo ausente, um por vez, como Escritório e como pessoa: ≥3000 pedidos, nunca 5xx nem conexão caída; arquivo continua válido | ✅ | RB01 |
| Campo extra / mass assignment | status, fim, `_rv`, pausas, eventos, comentários, anexos, quem, hash/sal, id no pedido nunca viram dado; autor vem do token | ✅ | RB02 |
| Conflito de revisão | setor/pessoa salvar/ativar/apagar com rev velha → 409 sem mudar; rev ruim → 400; agenda `v` | ✅ | RB03 |
| Duas telas, mesma revisão | 8 threads: 1×200 + 7×409 | ✅ | RB04 |
| Concorrência | 12 threads × 4 demandas + notas + vista: ids únicos, sem 5xx | ✅ | RB05 |
| Corpo grande | `Content-Length` > 16 MiB → 413 em 6 rotas | ✅ | RB06 |
| Corpo no limite | exato passa e +1 → 413 (5 rotas) | ✅ | RB07 |
| Content-Length ruim / corpo curto | 400/413, servidor de pé | ✅ | RB08 |
| Anexo 5 MB | exato OK; +1 e +3 → 413; base64/tipo/nome (120/121/vazio) | ✅ | RB09 |
| JSON de forma estranha | null/true/5/"x"/[]/BOM/NaN/duplicado/UTF-8 ruim | ✅ | RB10 |
| JSON muito aninhado | deveria ser 400 | 🐞 | RB11 (B1) |
| Métodos e caminhos | PUT/DELETE/…→501; 21 tentativas de travessia/código-fonte → 404 sem vazar | ✅ | RB12 |
| Cabeçalhos | CSP, nosniff, DENY, no-store em 200/400/404/413/421/403; erro é `text/plain` | ✅ | RB13 |
| Limite exato de 9 textos | título 5/140, descrição 2000, comentário 1000, setor 3/40, pessoa 2/60, obs. pausa/conclusão/cancelamento/repasse 500; emoji conta 1; NUL/controle 400; `\n` só onde permitido | ✅ | RB14 |
| XSS (dados) | título, descrição, comentário, nomes, anexo, pausa, nota voltam como dado em JSON `nosniff` | ✅ | RB15 |
| XSS (tela) | os mesmos campos + feriado + setores + pessoas em: entrada, 6 abas, 3 gavetas, sino, 5 seções de Configurações, "Ver como" (todas as pessoas), "Quem é você", Meus avisos: sem elemento `on*`, sem `<img src=x>`, sem `xssb`, `window.__xss` indefinido | ✅ | check_robustez (xssEmTudo) |
| Nome de anexo | U+202E e invisíveis saem; vazio vira `anexo.<tipo>` | ✅ | RB16 |
| Feriado | nome 60/61, tipos | ✅ | RB17 |
| Regex `.match` + `$` | `"1234\n"` como código e `"07:00\n"` como turno | 🐞 | RB18 (B2) |
| Link `#SOL-n` | 9 variantes (XSS, 11 dígitos, minúsculo, vazio, %00): sem erro, só abre demanda real | ✅ | check_robustez (linkEstranho) |
| Offline do Escritório | faixa "Sem conexão" (`role=status`), Fazer backup não finge, volta e funciona | ✅ | check_robustez (offlineDoEscritorio); operador em `demandas_check.js` |
| `aria-pressed` | abas (um marcado), filtros do sino, turnos | ✅ | check_robustez |
| `aria-*` / foco | diálogo com `role=dialog`, `aria-modal`, `aria-labelledby`; Esc fecha gaveta, sino e Configurações; foco no Fechar da gaveta; botões e campos com nome acessível em gaveta, Meus avisos e 5 seções | ✅ exceto campo do teste de e-mail | check_robustez · B5 |
| Layout 375 / 768 / desktop | sem rolagem horizontal da página (375: `scrollWidth`=375); gaveta e Configurações usáveis; Restaurar em 768 | 👁 ✅ | tela |
| Tema | alternar no botão "Alternar tema" muda `data-theme` (dark↔light) e as duas telas leem bem | 👁 ✅ | tela |

## Bugs encontrados

Todos reproduzidos antes de listar (servidor próprio na 8107 e/ou testes). Nenhum foi corrigido.

**B1 · JSON muito aninhado derruba a conexão sem resposta (esperado: 400 "JSON inválido.")** — severidade baixa/média (exige sessão ou
computador principal).
- Passos: `POST /api/local/demandas/vista` (e `/api/backup`, `/api/email`, `/api/avisos`, `/api/rede`) com corpo `"["*200000`.
- Esperado: 400. Obtido: `RemoteDisconnected` (sem status); traceback `RecursionError` no console do servidor; o servidor segue de pé.
- Suspeito: `servidor.py:443` (`_api`), `471`, `510`, `541`, `627` — `except (UnicodeError, ValueError)` não pega `RecursionError`. Teste: RB11.

**B2 · Validação com `re.match` + `$` aceita `\n` no fim** — baixa (higiene de dado).
- Passos: `pessoa/salvar` com `"codigo": "1234\n"` → 200 (login só entra com `"1234\n"`; `"1234"` dá 403). `agenda/salvar` com turno `["07:00\n","12:00"]` → 200 e grava `"07:00\n"`.
- Esperado: 400. Obtido: 200.
- Suspeito: `api.py:148` e `:823` (`CODE_RE.match`), `:270` (`SAL_RE.match`); `demandas_agenda.py:58` (`HHMM_RE.match`). Trocar por `fullmatch`. Teste: RB18.

**B3 · Demanda com título contendo U+2028 ou U+0085 nunca gera e-mail** — baixa/média (some o aviso, sem alarme).
- Passos: criar demanda com título `"Cortar chapas"`; e-mail ligado, evento "criada" ligado; rodar a thread.
- Esperado: e-mail enviado (a tela aceitou o título). Obtido: `ValueError: Header values may not contain linefeed…` em `montar`; o item vai a 6 tentativas e acaba como "falhou" com erro só "ValueError".
- Suspeito: `api.py:33` (`CTRL_RE` não inclui U+2028/U+0085) e `email_envio.py:244` (assunto). Corrigir a validação do título ou trocar esses separadores no assunto. Teste: EM17.

**B4 · Pasta de backup com caractere nulo derruba a conexão sem resposta (esperado: 400)** — baixa.
- Passos: `POST /api/backup {"local": "<pasta existente>\u0000x"}`.
- Obtido: `ValueError: mkdir: embedded null character` não tratado (só `OSError` é capturado); conexão cai.
- Suspeito: `demandas_backup.py:167` (`mkdir`, `salvar_config` só traduz `OSError`) / `servidor.py:496`; `_pasta_ok` (`:81`) deveria recusar `\x00`. Teste: BK03b.

**B5 · Campo "e-mail para teste" (`#dm-ml-para`) sem rótulo acessível** — baixa (acessibilidade).
- Passos: ⚙ Configurações → E-mail; inspecionar o `input`. Tem só `placeholder`, sem `<label>` nem `aria-label`.
- Esperado: nome acessível como os demais campos. Suspeito: `demandas/demandas.js:1800`. Verificado em check_robustez (linha `KNOWN-BUG`).

## Observações (comportamento, não bug confirmado)

- `agrupar_min: 5.0` é aceito e guardado como `5.0` (float igual a 5): inofensivo.
- `EMAIL_RE` é frouxa: `a@..com`/`a@b..com` passam; o servidor SMTP recusaria no envio (fica como falha).
- Endereço com acento (`josé@…`) passa no cadastro; sem SMTPUTF8 do servidor o envio falha (não testado contra servidor real).
- O comentário do solicitante copia o próprio autor em Cc quando "copiar o solicitante" está ligado (`api.py:1000`); estranho, mas dentro da regra escrita.
- O link do e-mail e o resto da configuração valem a hora do ENVIO, não a da criação do item.
- `avisos.json` guarda diferenças de pessoas apagadas (lixo pequeno; ids não se repetem).
- Tema: segue o botão (`data-theme`), não `prefers-color-scheme`; o selo "DEMONSTRAÇÃO" se sobrepõe ao título do diálogo em 375 px (cosmético).
- Banco de versão mais nova (v3) responde 500 por desenho ("atualize o programa").
- Métodos HTTP fora de GET/POST/HEAD respondem 501 em HTML do Python (texto escapado).

## O que NÃO ficou coberto

- Aviso do Windows e tela acesa em navegador real (só simulados no jsdom); som audível e vibração em aparelho.
- SMTP real/TLS (certificado, STARTTLS de verdade, SSL 465, Microsoft 365), SMTPUTF8, tempo de espera de 20 s.
- Ordem real de Tab e leitor de tela; contraste medido; 768 px só em Restaurar/Configurações.
- PBKDF2 com o custo real (100 000; testes usam 1000), disco cheio, cota de 300 MB, retenção GFS além dos testes existentes.
- Rede/PIN pelo IP da máquina e rotas de operador (já em `test_servidor.py`); e-mail de pessoa com rev antigo de outro setor.
- Cobertura de linhas e teste de mutação não medidos (esta sessão só criou testes e documentação).
