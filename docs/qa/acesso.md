# QA — Acesso e permissões (sessão A)

Área: tela "Quem é você?", código de 4 dígitos, bloqueio, token (`tk`), sair/trocar de usuário, "Ver como", papéis
(`maquina`, `completo`, `operador`), rotas só do Escritório, visão da pessoa (`calc.ve`) e a autorização do `servidor.py`
(`_auth_ok`, `_operador_ok`, `OPERADOR_RE`, `OPERADOR_ROTAS`).

Arquivos desta sessão (todos novos, nada existente foi editado):

| Arquivo | O que é | Como rodar |
|---|---|---|
| `tests/test_qa_acesso.py` | 85 testes `unittest`: api.py direto (relógios trocados, pbkdf2 leve) e servidor.py pelo HTTP | `py -3 -m unittest tests.test_qa_acesso` |
| `tests/check_acesso.js` | jsdom contra o `servidor.py` real, 125 conferências (+ 3 marcas `KNOWN-BUG`, 2 `OBS`) | `cd tests && NODE_PATH=./node_modules node check_acesso.js` |
| `docs/qa/acesso.md` | esta matriz | — |

Resultado da última execução: Python 85 de 85 passaram (11,6 s) · jsdom 125 PASS, 0 FAIL, nas duas rodadas seguidas ·
`ruff check tests/test_qa_acesso.py` limpo. Os três bugs abaixo estão marcados `known-bug` (imprimem `KNOWN-BUG`,
não reprovam; se alguém corrigir, o mesmo teste passa a imprimir `FIXED`).

Como o jsdom enxerga "outro aparelho": o script sobe um servidor com o acesso pela rede ligado e troca o `_remote` no
processo dele, de modo que o pedido com o cabeçalho `X-Teste-Rede` conta como da rede. Sem o cabeçalho = o próprio PC
(`maquina`); com cookie do PIN completo = `completo`; com cookie do PIN dos operadores = `operador`, de verdade (o
`/api/eu` não é falsificado).

Conferência na tela real (navegador embutido, `data-demo` copiado para o scratchpad, porta 8101, modo demo; servidor
parado ao fim): setor sem escolher, nome sem escolher, código curto, código errado, bloqueio de 5 erros com o código
certo barrado e outra pessoa entrando, olho, Entrar com Enter e com clique, Cancelar, trocar de usuário, Sair,
Administrador, Ver como (faixa, "Voltar ao ADM", botão desabilitado para inativos) e sessão perdida. Tudo bateu com os
testes. Os três bugs foram vistos também na tela.

## Matriz de cobertura

`P:` = `tests/test_qa_acesso.py` (classe.método) · `J:` = `tests/check_acesso.js` (texto da conferência) ·
`T:` = conferido à mão na tela real.

### 1. Tela "Quem é você?"

| Funcionalidade | Campo/botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| Abertura | tela de entrada | PC principal abre em "Quem é você?"; título, subtítulo; chip "Identifique-se", sino desabilitado, sem "Nova solicitação", sem abas | passou | J: "PC principal abre…", "título e subtítulo…", "sem usuário: …" · T |
| Tipo de acesso | Operador / Administrador | começa em Operador (`aria-pressed`); no PC principal os dois existem | passou | J: "começa em Operador", "a opção Administrador existe" |
| Setor | botões de setor | só setores ativos com pessoa ativa (sem setor vazio, sem setor inativo); nenhum marcado ao abrir; dica "Escolha o setor" | passou | J: "só os setores ativos…", "nenhum setor marcado…" |
| Setor | botão de setor | escolher marca o botão e lista só as pessoas ativas dele (inativa não aparece); trocar de setor desmarca o nome e limpa o erro | passou | J: "setor CNC: só Carlos e Bruno", "trocar de setor desmarca…" |
| Nome | botão de pessoa | escolher marca, limpa erro, leva o foco ao código | passou | J: "escolher o nome marca…" |
| Código | campo | vazio / 1 / 3 / 4 dígitos (limite exato) / 5 / 9 dígitos (além do limite) / letras / misturado / espaços / dígitos árabes | passou | J: `campo do código: "…" → "…"` (10 casos) |
| Código | atributos | `type=password`, `maxlength=4`, `inputmode=numeric`, `autocomplete=off` | passou | J: "campo do código: password…" |
| Código | botão olho | mostra (`text` + 🙈), oculta (`password` + 👁), rótulo acessível | passou | J: "olho: …", "botão do olho…" · T |
| Entrar | botão | sem setor: "Selecione o seu setor." (campo vermelho, `role=alert`) | passou | J · T |
| Entrar | botão | sem nome: "Selecione o seu nome." | passou | J · T |
| Entrar | botão | sem código / 3 dígitos: "Digite os 4 dígitos do seu código.", sem ir ao servidor | passou | J: "Entrar sem código…", "3 dígitos: não vai ao servidor…", "(conferência: nenhum pedido…)" |
| Entrar | botão | digitar tira o vermelho e a mensagem | passou | J: "digitar tira o vermelho…" |
| Entrar | código errado | "Código errado.", campo limpo, foco no código, campo vermelho, segue na tela | passou | J: "erro 1 de 5…", "código errado: campo limpo…" · T |
| Entrar | caso normal | pessoa entra, "Bem-vindo(a), X!", chip nome+setor, abas só Recebidas/Enviadas, nova solicitação e sino liberados, tela de entrada some da árvore de acessibilidade | passou | J: "toast de boas-vindas" … "a tela de entrada some…" · T |
| Entrar | Enter no campo | envia o formulário | passou | T (Enter com 5 palpites e login do Bruno) |
| Administrador | botão | some setor/nome/código, aparece o aviso, Entrar entra como Escritório com "Bem-vindo(a), Escritório!" e as 6 abas | passou | J: "Administrador: some setor…", "Administrador entra direto…" · T |
| Administrador (sem permissão) | botão | aparelho de operador não tem o botão nem o texto "Administrador" | passou | J: "operador: sem a opção Administrador…" · P: `AuthOperador.test_lista_publica_do_operador_pelo_http` |
| Administrador | /api/eu lento | enquanto `/api/eu` não responde, nenhum "Administrador" na tela; aparece quando responde `maquina` | passou | J: "enquanto /api/eu não responde…", "quando /api/eu responde…" |
| Administrador | /api/eu fora do ar | aparelho de operador com `/api/eu` falhando mostra Administrador, mas Entrar é recusado ("Este aparelho não tem acesso de administrador.") e nada abre | passou (ver Observação O2) | J: "…Entrar como Administrador nesse aparelho é recusado…" |
| ⚙ Configurações | botão | oculto no aparelho de operador e no de PIN completo pela rede | passou | J: "operador: sem o botão ⚙…", "aparelho do escritório pela rede: sem o botão ⚙…" |
| Lista pública | e-mail | tela de entrada do operador sem nenhum e-mail | passou | J: "operador: nenhum e-mail na tela de entrada" · P: `Papeis.test_lista_publica_do_operador_so_tem_ativos_e_sem_segredo` |

### 2. Entrar com o código (api.py, `entrar` / `_check_code`)

| Funcionalidade | Campo | Caso | Resultado | Onde |
|---|---|---|---|---|
| Entrar | código certo | 200 com `{tk, eu, vista}` nos papéis operador, maquina e completo; vista é de pessoa | passou | P: `EntrarCodigo.test_entra_com_o_codigo_certo_em_qualquer_papel` |
| Entrar | token | 32 caracteres urlsafe; cada entrada gera um token novo | passou | P: `…test_token_tem_32_caracteres…` |
| Entrar | código | zeros à esquerda valem ("0007"); "7" e "0070" erram | passou | P: `…test_zeros_a_esquerda_valem` |
| Entrar | código errado | 403 "Código errado." (inclusive o código de outra pessoa) | passou | P: `…test_codigo_errado_403…` |
| Entrar | código inválido | 19 formatos (vazio, None, 3 e 5 dígitos, letras, espaço antes/depois, `\n`, dígitos largos, ponto, sinal, int, float, bool, lista, dict, `\x00`) e campo ausente → 403 | passou | P: `…test_codigo_vazio_ausente_ou_de_formato_ruim` |
| Entrar | pessoa | inexistente, vazia, None, int, lista, dict, bool, "P0", " p0", campo ausente → 404 "Pessoa não encontrada." | passou | P: `…test_pessoa_que_nao_entra_404` |
| Entrar | pessoa inativa / setor inativo | 404; reativada volta a entrar | passou | P: `…test_pessoa_ou_setor_inativo_nao_entra` |
| Entrar | cadastro sem sal válido | 404 | passou | P: `…test_cadastro_sem_sal_valido_nao_entra` |
| Entrar | corpo | não objeto (lista, texto, None, número) → 400 "Pedido inválido." | passou | P: `…test_corpo_nao_objeto_400` |
| Entrar | resposta | sem `sal`, `hash`, e-mail nem o código | passou | P: `…test_resposta_nao_vaza_sal_hash_nem_email`, `…test_vista_ao_entrar_e_a_da_pessoa` |
| Entrar | pelo HTTP | 403/429/404/400 chegam com o status e o texto certos | passou | P: `AuthCompleto.test_bloqueio_e_token_pelo_http` |

### 3. Bloqueio por tentativas (`TENTATIVAS=5`, `BLOQUEIO_S=60`)

| Caso | Resultado | Onde |
|---|---|---|
| constantes 5 e 60 | passou | P: `Bloqueio.test_constantes` |
| 4 erros não bloqueiam; o acerto zera a conta (4 + acerto + 4 de novo) | passou | P: `…test_quatro_erros_ainda_deixam_entrar…` |
| 5º erro ainda responde 403; a partir do 6º é 429 "Bloqueado por 1 minuto…", até com o código certo ou vazio | passou | P: `…test_quinto_erro_bloqueia…` · J: "erro 5 de 5", "depois do 5º erro nem o código certo entra" · T |
| limite exato: 59,999 s ainda bloqueia, 60 s libera | passou | P: `…test_limite_exato_do_bloqueio` |
| tentativa durante o bloqueio não estica o prazo | passou | P: `…test_bloqueio_nao_renova…` |
| depois de liberar, a conta recomeça (4 erros, 5º, bloqueia de novo) | passou | P: `…test_depois_do_bloqueio_a_conta_recomeca` |
| bloqueio é por pessoa (outras entram) | passou | P: `…test_bloqueio_e_por_pessoa` · J: "o bloqueio do Carlos não impede o Bruno" · T |
| erro de formato conta como erro; pessoa inexistente não conta | passou | P: `…test_erro_de_formato_conta_como_erro`, `EntrarCodigo.test_pessoa_inexistente_nao_conta…` |
| quem já está dentro não cai com o bloqueio | passou | P: `…test_bloqueio_nao_derruba_quem_ja_esta_dentro` |
| trocar o código pelo Escritório libera o bloqueio | passou | P: `…test_trocar_o_codigo_pelo_escritorio_libera_o_bloqueio` |
| 24 palpites errados em paralelo: exatamente 5 recebem 403, 19 recebem 429 | passou | P: `…test_palpites_em_paralelo_nao_passam_de_cinco` |
| acerto não deixa registro em memória; 2 erros ficam `[2, 0.0, 0]` | passou | P: `…test_em_curso_zera_ao_fim…` |

### 4. Token (`TK_VIDA_S=12 h`, `TK_MAX=500`), expiração, sair, revogação

| Caso | Resultado | Onde |
|---|---|---|
| constantes 43200 e 500 | passou | P: `Token.test_constantes` |
| validade: 11 h 59 min 59,999 s vale; no instante exato é 401 "Identifique-se de novo." e não volta | passou | P: `…test_validade_de_12h_limite_exato` |
| o uso não renova a validade | passou | P: `…test_tk_nao_renova_com_o_uso` |
| tk ruim (vazio, lixo, 5000 caracteres, int, float, bool, lista, dict, bytes) → 401; `tk: null` → 403 (operador) ou Escritório (maquina/completo) | passou | P: `…test_tk_ruim_401_e_sem_tk_depende_do_papel` |
| tk de pessoa vale em qualquer papel e nunca vira Escritório | passou | P: `…test_tk_de_pessoa_vale_em_qualquer_papel…` |
| dois tokens da mesma pessoa são independentes | passou | P: `…test_tokens_da_mesma_pessoa_sao_independentes` |
| teto de 500: o 501º entra e o mais antigo sai | passou | P: `…test_teto_de_500_tokens…` |
| só o hash vai ao disco; reiniciar o servidor não derruba | passou | P: `…test_so_o_hash_vai_para_o_disco…` · J: "o tk não vai para localStorage, cookie nem para o HTML" |
| reinício não traz de volta o vencido nem linha estranha (curta, sem vencimento, id não texto, vencimento bool/texto) | passou | P: `…test_reinicio_nao_traz_de_volta…` |
| arquivo de sessões ruim (5 formatos) = ninguém identificado; mais de 500 linhas fica com as 500 mais novas | passou | P: `…test_arquivo_de_sessoes_ruim…`, `…test_arquivo_com_mais_de_500…` |
| falha ao gravar o arquivo não derruba a entrada | passou | P: `…test_falha_ao_gravar_nao_derruba_a_entrada` |
| `sair`: derruba o tk, é idempotente, aceita corpo sem tk / tk não texto / tk inventado, não afeta outro tk, grava no disco, 400 se corpo não objeto | passou | P: `…test_sair_derruba_o_tk_e_e_idempotente`, `…test_sair_grava_no_disco` |
| trocar o código, desativar, apagar a pessoa ou restaurar backup derruba o tk; reativar não ressuscita | passou | P: `…test_desativar_trocar_codigo_apagar_ou_restaurar…` |
| setor desativado / apagado dá 401 ao tk da pessoa (ver O3) | passou | P: `…test_setor_desativado_ou_apagado…` |
| `_ator` confere `ativo` de novo mesmo com tk que escapou da revogação | passou | P: `…test_pessoa_desativada_com_tk_antigo…` |

### 5. Sair, trocar de usuário, sessão perdida (tela)

| Funcionalidade | Botão | Caso | Resultado | Onde |
|---|---|---|---|---|
| Quem é você? com alguém dentro | chip | abre o diálogo, mostra "Você está aqui agora", tem Sair e Meus avisos | passou | J: "chip abre…", "mostra quem está logado", "botões Sair e Meus avisos…" · T |
| Cancelar | botão | fecha sem mudar de usuário | passou | J: "Cancelar fecha sem mudar de usuário" |
| Trocar de usuário | Entrar (diálogo) | código errado: erro dentro do diálogo, o usuário atual e o tk dele seguem valendo | passou | J: "troca com código errado…", "troca que falhou não derruba…" |
| Trocar de usuário | Entrar (diálogo) | código certo: novo usuário entra, o tk do anterior vira 401, a tela passa a ser a do novo | passou | J: "trocar de usuário: Fernanda entra", "…revoga o tk do anterior", "tela passa a ser da Fernanda", "Fernanda (ESP) vê os 3…" · T |
| Sair | botão | volta ao "Quem é você?", revoga o tk no servidor, sem abas/conteúdo, sino desabilitado, código vazio | passou | J: "Sair: volta…", "Sair revoga o tk…", "depois de Sair: …" · T |
| Sair | memória do último usuário | a tela de entrada continua com o último setor/nome marcados | OBS O1 | J: linha `OBS` |
| Administrador → sair do usuário | Entrar | entrar como Administrador estando como pessoa revoga o tk da pessoa | passou | J (Bruno → Escritório no roteiro de Ver como/Administrador) |
| Sessão perdida (`lost`) | — | Escritório desativa a pessoa: a tela dela volta sozinha ao "Quem é você?" com "Identifique-se de novo.", aviso 🔒 e código vazio | passou | J: "desativada pelo Escritório…", "com a mensagem…", "e o código vazio" · T |
| Sessão perdida | lista de pessoas | a lista da tela de entrada fica a de antes (mostra a pessoa já desativada, não mostra quem foi criado depois) | **falhou → bug B2** | J: `KNOWN-BUG B2` · T |
| Sessão perdida | escolher a desativada | "Pessoa não encontrada." | passou | J: "escolher a pessoa desativada que ainda aparece…" |

### 6. "Ver como" (Escritório vê como a pessoa, só leitura)

| Caso | Resultado | Onde |
|---|---|---|
| botão 👁 Ver como: desabilitado para pessoa inativa e para pessoa de setor inativo; habilitado e com dica para a ativa | passou | J: "Ver como: desabilitado…" (2), "habilitado…" · T |
| faixa "Modo visualização" com nome, setor e "Só leitura"; abas Recebidas/Enviadas; chip continua Escritório | passou | J: "faixa…", "Ver como mostra a tela de operador…", "o chip continua…" · T |
| sem botão flutuante e sem "＋ Nova solicitação" no corpo | passou | J |
| **botão "＋ Nova solicitação" do cabeçalho continua visível e abre o formulário do Escritório** | **falhou → bug B1** | J: `KNOWN-BUG B1` + "(B1) o formulário … abre" · T |
| nenhum botão de ação nos cartões; na gaveta: só "Modo visualização: só leitura", sem comentário nem aceitar/pausar/cancelar/cobrar/estender | passou | J: "Ver como: nenhum botão de ação…", "gaveta em Ver como: …" (2) |
| os pedidos mostrados em Ver como Bruno são exatamente os que o Bruno de verdade vê (outro aparelho, papel operador) e não vazam os de ESP | passou | J: "Ver como Bruno mostra exatamente…", "Ver como não vaza…" |
| **abrir um cartão em Ver como grava no servidor (`nota/lida` do Escritório)** | **falhou → bug B3** | J: `KNOWN-BUG B3` · T |
| Voltar ao ADM: some a faixa, voltam as abas de administração e a nova solicitação | passou | J |
| sem permissão: operador/pessoa não alcança Administração, logo não alcança Ver como (a tela só mostra o botão a `D.role==='adm'`) | passou (por construção) | J: "pessoa: só as abas…" |

### 7. Papéis e rotas só do ADM (api.py)

| Funcionalidade | Caso | Resultado | Onde |
|---|---|---|---|
| `GET ""` por papel | maquina e completo = vista de ADM com `anexos_uso`; operador = só `setores` e `pessoas` públicas; papel ausente, `None`, "Maquina", "ADM", "admin", "", "operador ", 1 → 403 | passou | P: `Papeis.test_get_por_papel` |
| Lista pública | só ativos, sem hash/sal/e-mail, campos `id,nome,setor,mat,ativo,_rv`; o ADM vê o e-mail | passou | P: `…test_lista_publica_do_operador_so_tem_ativos_e_sem_segredo` |
| Vista da pessoa | sem e-mail | passou | P: `…test_pessoa_nao_recebe_email_na_vista` |
| 12 rotas só do ADM (`setor/*`, `pessoa/*`, `agenda/salvar`, `demanda/prioridade`, `demanda/estender`, `historico`, `crono`, `cronograma`) | pessoa de qualquer setor → 403 "Só o escritório pode fazer isso.", nos papéis operador e maquina; o banco não muda | passou | P: `…test_rotas_so_do_adm_dao_403_para_pessoa_e_nada_muda` |
| idem com corpo válido (não é a validação que barra) | 403 e banco idêntico | passou | P: `…test_rotas_so_do_adm_com_corpo_valido_ainda_dao_403` |
| idem com tk ruim | 401 antes do 403 | passou | P: `…test_so_adm_com_tk_ruim_e_401_antes_do_403` |
| sem tk no papel operador | 403 "Identifique-se para usar as demandas." em todas as rotas de ator | passou | P: `…test_sem_tk_no_papel_operador_toda_rota_de_ator_da_403` |
| sem papel / papel "x" | 403 | passou | P: `…test_sem_papel_nenhum_toda_rota_de_ator_da_403` |
| ADM (maquina e completo) | alcança as rotas de ADM e age como "Escritório" | passou | P: `…test_adm_alcanca_as_rotas_de_adm_e_vira_escritorio` |
| rota desconhecida | 404 antes de checar identidade; `GET entrar` 404 | passou | P: `…test_rota_desconhecida_e_404_antes_da_identidade` |
| api e servidor concordam | o conjunto "só ADM" medido no api.py é igual ao fora do `OPERADOR_RE` (rota nova sem os dois lados reprova) | passou | P: `…test_o_servidor_e_o_api_concordam…` |

### 8. O que a pessoa vê (`calc.ve`)

| Caso | Resultado | Onde |
|---|---|---|
| Helena (PCP) vê só o que pediu; Carlos vê destino CNC + o dele; Bruno destino CNC + o dele (não o do Carlos); Fernanda destino ESP | passou | P: `VisaoDaPessoa.test_cada_pessoa_ve…`, `…test_colega_do_setor_de_origem…` · J: "tela do Bruno…", "Fernanda (ESP) vê…", "operador (Fernanda): vê só o setor ESP" |
| ADM vê tudo | passou | P: `…test_adm_ve_tudo` |
| vista da pessoa = `calc.ve` aplicado ao banco, para as 4 pessoas | passou | P: `…test_a_vista_da_pessoa_bate_com_calc_ve…` |
| vista da pessoa sem `anexos_uso`, sem avisos do ADM, feed só das demandas dela | passou | P: `…test_vista_da_pessoa_nao_traz_dados_de_adm` |
| avisos só do setor e da pessoa (e os do ADM só do ADM) | passou | P: `…test_notas_so_do_setor_e_da_pessoa` |
| aviso de outra pessoa não marca (nem pelo ADM) → 403 "Notificação de outra pessoa." | passou | P: `…test_nota_de_outra_pessoa_nao_marca` |
| anexo: quem vê a demanda lê; quem não vê → 403 "Sem acesso a este anexo."; ADM por GET; operador sem tk 403; id inexistente/malformado 404 | passou | P: `…test_anexo_so_para_quem_ve_a_demanda` |
| pessoa não age em demanda que não vê (comentar, cobrar, cancelar, aceitar → 403) | passou | P: `…test_pessoa_nao_age_em_demanda_que_nao_ve` |
| criar como pessoa ignora `de_s` e usa o setor dela | passou | P: `…test_criar_como_pessoa_usa_o_setor_dela…` |

### 9. servidor.py: `_auth_ok`, `_operador_ok`, PIN e papéis

| Caso | Resultado | Onde |
|---|---|---|
| o próprio PC = `maquina` sem cookie; `/api/eu` e vista de ADM | passou | P: `AuthRede.test_o_proprio_pc_e_maquina_sem_cookie` |
| rede desligada: 403 "Acesso pela rede desligado." em `/`, `/api/eu`, vista e POST | passou | P: `…test_rede_desligada_barra_tudo_da_rede` |
| sem sessão na rede: `/` e `/index.html` (GET/HEAD) mostram a página de PIN; o resto 401 "Entre com o PIN." | passou | P: `…test_sem_sessao_na_rede` |
| cookie de outro nome, vazio, sem nome, valor solto e sessão vencida → 401 | passou | P: `…test_cookie_falso_de_outro_nome_ou_vencido…` |
| PIN errado não dá cookie; PIN completo → `completo`; PIN operador (também com espaços) → `operador`; os dois PIN são diferentes | passou | P: `…test_pin_errado_nao_da_cookie…` |
| cookie com `HttpOnly`, `SameSite=Strict`, `Path=/`, `Max-Age` de 30 dias | passou | P: `…test_cookie_sem_httponly…` |
| login do próprio PC não existe (403) | passou | P: `…test_login_do_proprio_pc_nao_existe` |
| origem estranha 403; host estranho, sem porta ou com porta errada 421 | passou | P: `…test_origem_estranha_e_host_estranho` |
| sessão de papel desconhecido fecha em 403 (nunca abre) | passou | P: `…test_sessao_de_papel_desconhecido_fecha_em_403` |
| só o PC principal configura: `/api/rede`, `/backup`, `/email`, `/avisos`, `/servidor` = 200 no PC, 403 para `completo` e `operador` (GET e POST) | passou | P: `…test_so_o_pc_principal_configura` |
| PIN novo derruba as sessões certas (operador só as de operador; completo todas) | passou | P: `…test_pins_novos_derrubam…` |
| PIN: 5 erros travam o IP por 5 minutos (limites 299,9 s / 300,1 s), outro IP segue | passou | P: `…test_pin_5_erros_travam…` |
| `OPERADOR_ROTAS`/`OPERADOR_RE`: 15 caminhos permitidos (GET e HEAD, com `?query`) | passou | P: `AuthOperador.test_permitidas` |
| idem: 25 negados (rotas de ADM, barras a mais, maiúsculas, `..`, ponto inicial, subpasta, 61 caracteres, `.py`, `/data`, HEAD) com a mensagem exata | passou | P: `…test_negadas` |
| PUT/DELETE/PATCH/OPTIONS → 501 | passou | P: `…test_metodos_que_o_servidor_nao_tem` |
| GET nas rotas de POST e POST nas de GET → 403 | passou | P: `…test_get_na_rota_de_post_e_post_na_rota_de_get` |
| 12 rotas de ADM + 15 variações (barra, maiúscula, `%20`, `..`, prefixo) pelo operador, com e sem tk → 403 `OPERADOR_MSG` | passou | P: `…test_rotas_so_do_adm_pelo_operador_com_ou_sem_tk` |
| operador: entrar, vista, criar, `aviso/prefs`, sair e tk revogado | passou | P: `…test_rotas_de_pessoa_pelo_operador` |
| negado não executa nada (banco intacto) | passou | P: `…test_negado_nao_executa_nada` |
| PIN completo na rede: rotas de ADM sim, configuração não | passou | P: `AuthCompleto.test_pin_completo_na_rede…` |
| pessoa no PC principal continua só pessoa (403 nas rotas de ADM) | passou | P: `…test_pessoa_no_pc_principal_tambem_e_so_pessoa` |
| tela do operador (papel real): usar a tela inteira não recebe nenhum 403; sem erro de script; rota de ADM, `/api/rede` e `GET vista` = 403 | passou | J: "operador: usar a tela…", "…rota de ADM direto no servidor = 403", "…/api/rede e GET vista = 403" |
| PIN completo na rede: tem Administrador e entra como Escritório | passou | J |

## Bugs encontrados

Todos de severidade baixa/média, nenhum compromete segurança (o servidor barra a escrita de quem não tem papel).
Nada foi corrigido, conforme a regra.

### B1 — "Ver como" (só leitura) deixa o "＋ Nova solicitação" do cabeçalho ativo, que cria como Escritório

- **Passos:** entrar como Administrador → Administração → Usuários → "👁 Ver como" numa pessoa ativa → clicar em
  "＋ Nova solicitação" no canto superior direito.
- **Esperado:** a faixa diz "Só leitura: as ações ficam com a própria pessoa"; o botão do cabeçalho some, como já somem o
  botão flutuante (`.dm-fab`) e o do corpo da tela.
- **Obtido:** o botão continua visível e abre o formulário "Nova solicitação" do **Escritório** (campo "Solicitante" com o
  setor, sem tk). Enviar cria a demanda em nome do Escritório. Vi o formulário aberto na tela real e no jsdom; não enviei
  o formulário (não era preciso: o código só barra por `D.role`).
- **Suspeito:** `demandas/demandas.js:1647` (`root.querySelector('.dm-hdnew').hidden = who;`, enquanto a linha seguinte
  esconde o `.dm-fab` com `|| !!D.imp`) e `demandas/demandas.js:2101` (`case 'new': if(!D.role) return; openNew();`, sem
  checar `D.imp`).
- **Teste:** `check_acesso.js`, `kb('B1', …)` e "(B1) o formulário de nova solicitação abre mesmo em Ver como".

### B2 — Depois de "Identifique-se de novo." a tela de entrada mostra a lista de pessoas de antes

- **Passos:** uma pessoa está logada num aparelho; o Escritório a desativa (ou o token vence); a tela dela volta sozinha
  ao "Quem é você?". Criar uma pessoa nova no mesmo setor e olhar a lista de nomes sem recarregar a página.
- **Esperado:** a lista refletir o cadastro atual: sem a pessoa desativada e com a nova (como acontece depois de
  "Sair", que chama `loadPub()`).
- **Obtido:** a lista é a do carregamento da página: a pessoa desativada ainda aparece (escolhê-la dá "Pessoa não
  encontrada.") e a nova não aparece até recarregar a página. Num tablet que fica ligado o dia todo, só dá para entrar
  como pessoa cadastrada depois da abertura recarregando a página, se antes alguém caiu em `lost()`.
- **Suspeito:** `demandas/demandas.js:502-507` (`lost()` faz `become(null)` e `render()` sem `await loadPub()`, ao
  contrário de `logout()` em `demandas/demandas.js:494-501`).
- **Teste:** `check_acesso.js`, `kb('B2', …)`.

### B3 — "Ver como" (só leitura) grava no servidor ao abrir um cartão (marca avisos do Escritório como lidos)

- **Passos:** Administrador → Ver como uma pessoa → abrir um cartão que tenha aviso não lido para o Escritório (por
  exemplo uma demanda urgente) → a gaveta abre.
- **Esperado:** nenhuma gravação em modo visualização (a faixa promete só leitura; a pessoa e o Escritório não devem
  ter o estado alterado por quem apenas olha).
- **Obtido:** a tela envia `POST nota/lida` como Escritório (`markReadFor` roda no `openDrawer`), o que muda o contador do
  sino do Escritório (o sino em Ver como também é o do Escritório, não o da pessoa). Visto na rede do jsdom e no
  `fetch` da tela real.
- **Suspeito:** `demandas/demandas.js:1197-1205` (`openDrawer` chama `markReadFor(id)` sem checar `D.imp`) e
  `demandas/demandas.js:428-432` (`markReadFor`); o mesmo vale para "Marcar todos como lidos" (`case 'noteall'`,
  `demandas/demandas.js:2095`), que também não checa `D.imp`.
- **Teste:** `check_acesso.js`, `kb('B3', …)`.

## Observações (comportamento atual, sem veredito de bug)

- **O1 — "Sair" lembra o último usuário.** Depois de Sair, a tela de entrada continua com o setor e o nome do último
  usuário marcados (só o código some). Pode ser conveniência num tablet; num aparelho compartilhado mostra quem usou por
  último. Decidir com o dono. (`D.lg` não é limpo em `logout()`, `demandas/demandas.js:494`.)
- **O2 — Aparelho de operador com `/api/eu` fora do ar mostra "Administrador".** `D.srv = null` faz `restrito()` dar
  falso, então a opção aparece. O servidor recusa mesmo assim ("Este aparelho não tem acesso de administrador.") e nada
  abre; é só uma tela que abre mais do que deveria. O teste documenta e segue verde.
- **O3 — Reativar um setor "ressuscita" o tk de quem não foi desativado.** Desativar o setor faz o tk dar 401; reativar
  faz o mesmo tk voltar a valer (só a pessoa desativada tem o tk revogado). O CONTRATO só cita "desativar a pessoa,
  trocar o código ou restaurar". Fixei o comportamento atual em `Token.test_setor_desativado_ou_apagado…`.
- **O4 — `anexo/ler` com id mal formado responde 404 antes de checar a identidade** (um operador sem tk recebe 404, não
  403). Não vaza nada (só valida o formato). Documentado em `Papeis.test_sem_tk_no_papel_operador_…`.
- **O5 — Bloqueio por pessoa permite travar um colega de propósito** (5 palpites errados em qualquer aparelho trancam a
  pessoa por 1 minuto). É o desenho declarado no CONTRATO (defesa do pbkdf2 de 100 000 voltas), anotado só por completude.
- **O6 — `GET //` da rede chega como `/`.** Quem junta a barra é a biblioteca padrão do Python (3.12+), antes do servidor;
  por isso `//` não está entre os caminhos negados do operador.

## O que NÃO ficou coberto

- Vencimento do tk **na tela**: coberto só no api.py (relógio trocado); no jsdom não há como adiantar 12 h do servidor.
- Interface de **configuração de rede** (liga/desliga, PIN novo) além do que decide papéis e sessões: é de outra área.
- Fluxo completo de **restaurar backup → todo mundo se identifica de novo** (só `esquecer_pessoas()` no api.py; o
  `_backup` do servidor é de outra sessão).
- Pessoa com **e-mail** configurado nas telas do operador além do HTML da tela de entrada e das listas públicas.
- **Cobertura de linhas e teste de mutação** (`py -3 qa.py all` / `qa.py mutate`): não foram rodados nesta sessão (a
  regra pede dos arquivos de aplicação alterados; aqui nenhum foi alterado). A consolidação deve incluir os dois testes
  novos em `qa.py` (`CRITICO` e a lista de checks de tela, hoje só `tests/demandas_check.js`).
- Dispositivos reais de rede (tablet de verdade), HTTPS e `Secure` no cookie: não aplicável a este servidor (HTTP puro).
- A tradução de `Mostrar ou ocultar o código` e leitores de tela: só conferi os atributos, não um leitor.
- Digitar rápido na tela real com a ferramenta de automação perdeu dígitos quando havia um caractere inválido no meio
  ("12ab345" virou "12"). Reproduzi tecla a tecla e funciona ("12" + "a" + "3" = "123"); considerei artefato da ferramenta,
  não do aplicativo (o jsdom confirma "12ab345" → "1234").
