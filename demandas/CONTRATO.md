# Contrato do módulo Demandas (fonte de verdade entre banco, backend e frontend)

Pasta `demandas/` da Central de demandas, porte da central do projeto DEMANDA. Rotas em
`/api/local/demandas/<rest>` (o `servidor.py` chama `handle(method, rest, body, ctx)`), estáticos em
`/local/demandas/<arquivo>` (só os do `STATIC`).

## Arquivos e donos
| Arquivo | Dono | Papel |
|---|---|---|
| `demandas_store.py` | banco | carga/gravação de `data/demandas.json`, arquivo morto, anexos em `data/demandas-anexos/` |
| `api.py`, `demandas_calc.py` | backend | rotas, regras, autorização, vista, cálculos de tempo |
| `demandas.js`, `demandas.css` | frontend | tela |
| `contrato.json` | coordenação | exemplos do que a API devolve (o front desenvolve contra eles) |

O `servidor.py` põe esta pasta no `sys.path`; o `store.py` da raiz traz a gravação segura que o `demandas_store.py` usa.

## Tempo e identificadores
- Tempo sempre em **milissegundos desde a época** (int), como no DEMANDA. Cálculos recebem `agora` como
  parâmetro (testável); a API usa `int(time.time() * 1000)`.
- Setor: `id` = sigla `^[A-Z0-9]{2,4}$`. Pessoa: `id` = `"p" + n` (n sequencial), `mat` = `"M" + (100 + n)`.
- Demanda: `id` = `"SOL-" + n`, n = maior existente (principal + arquivo morto) + 1, começa em `SOL-1001`.
- Anexo: `id` = `"a" + 16 hex` (`secrets.token_hex(8)`), arquivo `<id>.<jpg|png|pdf>`.
- Nota: `id` int sequencial.

## Formato de `data/demandas.json` (versão `v = 1`)
```json
{"v": 1, "rev": 0, "seq": {"pessoa": 0, "demanda": 1000, "nota": 0},
 "setores": [{"id": "CNC", "nome": "CNC", "icone": "⚙️", "cor": "#3B82F6", "ativo": true, "_rv": 0}],
 "pessoas": [{"id": "p0", "nome": "Carlos", "setor": "CNC", "mat": "M100", "ativo": true,
              "sal": "<32 hex>", "hash": "<pbkdf2 hex>", "_rv": 0}],
 "demandas": [{"id": "SOL-1001", "titulo": "...", "tipo": "dem", "motivo": "Outro", "prio": "norm",
               "est": 60, "de": {"s": "PCP", "p": "p1"}, "para": {"s": "CNC", "p": null},
               "desc": "...", "status": "new", "criado": 0, "iniciado": null, "fim": null, "atraso_avisado": false,
               "pausas": [{"ini": 0, "fim": null, "motivo": "...", "obs": "", "por": "Carlos"}],
               "eventos": [{"t": 0, "ev": "created", "quem": "Helena", "nota": ""}],
               "comentarios": [{"quem": "Helena", "t": 0, "texto": "..."}],
               "anexos": [{"id": "a0123456789abcdef", "nome": "foto.jpg", "tipo": "jpg", "bytes": 1234, "por": "Helena", "t": 0}],
               "_rv": 0}],
 "notas": [{"id": 1, "aud": "CNC", "pid": null, "tipo": "new", "dem": "SOL-1001", "texto": "", "quem": "Helena", "t": 0,
            "lida": false, "lidas": []}],
 "cids": [["3f2a…-uuid", "SOL-1001"]]}
```
- `de.p = null` quando quem pediu foi o Escritório (ADM). `para.p = null` = fila do setor.
- `email` (opcional) em pessoa e setor: quem recebe o aviso por e-mail. Só o ADM edita (`setor/salvar`,
  `pessoa/salvar`; campo ausente = não mexe, `""` = apaga) e só a vista do ADM o recebe. Minúsculas, até 254
  caracteres, `^[^@\s,;<>"]{1,64}@[A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,}$`.
- Nota (aviso do sino): `aud` = setor ou `"adm"`; `pid` = só esta pessoa do setor (`null` = o setor todo). `lida`
  é a leitura do ADM; cada pessoa lê por si (`lidas` = ids de quem já leu). Nota antiga sem `pid` vale para o
  setor todo e conta como lida se `lida` já era `true`.
- `cids` (opcional; arquivo antigo sem ele = vazio): as últimas 500 chaves de pedido de `demanda/criar` e
  `demanda/comentar` (`cid`, `^[A-Za-z0-9_-]{8,64}$`, gerado pela tela) com o que gravaram. Chave repetida = a
  resposta anterior se perdeu e a tela mandou de novo: devolve a vista sem gravar.
- `data/demandas-arquivo.json`: `{"v": 1, "demandas": [...]}` com concluídas/canceladas antigas tiradas do
  principal quando ele passa do teto (mesmo formato de demanda). Nunca volta ao principal.
- Ambos são `*.json` no topo de `data/`, então entram sozinhos no backup, que é um `.zip` com
  `manifesto.json` e SHA-256 por arquivo (`demandas_backup.py`).

## Domínios fixos (iguais ao DEMANDA)
- `tipo`: `dem` Demanda 📌 · `alt` Alteração ✏️ · `set` Entre setores 🔁 · `man` Manutenção 🛠️ · `mat` Material 📦
- `motivo`: Falta de material · Quebra de máquina · Defeito de qualidade · Mudança de projeto · Ajuste de
  planejamento · Retrabalho · Solicitação do cliente · Outro
- motivos de pausa: Aguardando material · Aguardando outro setor · Máquina parada · Aguardando aprovação ·
  Troca de turno ou intervalo · Informação incompleta
- `prio`: `low` Baixa · `norm` Normal · `high` Alta · `urg` Urgente
- `status`: `new` Aberta · `prog` Em andamento · `pause` Pausada · `done` Concluída · `canc` Cancelada
  (Atrasada é derivado: ativa e `agora > prazo`; ativa = new/prog/pause)
- eventos: created, assigned, started, paused, resumed, done, canc, reassigned, prio, deadline, nudge, late, comment(não), attach
  (`attach` = anexo enviado; comentário não vira evento, como no DEMANDA)
- tipos de nota: new, urg, accepted, pause, done, canc, nudge, late, comment
- ícones de setor: 🗂️ ⚙️ 🔩 🪵 🪚 🧽 🛠️ 🧵 ✂️ 🪡 📦 ✅ 🔧 🏷️ 🚚 🎨 🧪 🖥️ 🧰 🏭
- cores de setor: #6366F1 #3B82F6 #0EA5E9 #06B6D4 #0D9488 #10B981 #65A30D #D97706 #E4572E #EC4899 #8B5CF6 #64748B

## Limites
| Campo | Regra |
|---|---|
| título | 5 a 140 caracteres | 
| descrição | até 2000 (vazia vira "Sem descrição adicional.") |
| comentário | 1 a 1000 · obs de pausa/conclusão/cancelamento/reatribuição até 500 |
| nome pessoa / setor | 2 a 60 / 3 a 40 |
| `est` (min) | 1 a 43200 · estender: 1 a 1440 por vez |
| código da pessoa | `^[0-9]{4}$`, pbkdf2-sha256 100 000 iterações com sal de 16 bytes (igual à Produção) |
| tetos | setores 60 · pessoas 500 · demandas no principal 5000 (acima disso arquiva concluídas/canceladas mais antigas) · arquivo morto 50000 · pausas 200, eventos 500, comentários 300 por demanda · notas 1000 (as mais antigas saem) · `cids` 500 |
| anexos | JPG/PNG/PDF pelos bytes iniciais (`FF D8 FF`, `89 50 4E 47 0D 0A 1A 0A`, `%PDF-`) · até 5 MB cada · até 5 por demanda · cota total de 300 MB em `data/demandas-anexos/` |
| texto | sem caractere de controle (`[\x00-\x1f\x7f]`, exceto `\n` em descrição/comentário) |

## API do banco (`demandas_store.py`)
```python
V = 1
LOCK: threading.Lock                     # segurado pelo api.py em toda leitura+escrita
MAX = {...}; ANEXO_MAX = 5 * 1024 * 1024; ANEXOS_POR_DEMANDA = 5; COTA = 300 * 1024 * 1024
class StoreError(Exception): status: int   # 400/404/413/507 com mensagem pronta para a tela
def path() -> Path                       # store.data_dir() / "demandas.json"
def anexos_dir() -> Path                 # store.data_dir() / "demandas-anexos"
def empty() -> dict
def load(cache: bool = True) -> dict     # normaliza, migra por "v" (cópia .bak antes de migrar), cache por (mtime, size)
def commit(doc: dict) -> dict            # rev += 1, arquiva se passou do teto, grava atômico; devolve doc
def load_arquivo() -> list               # demandas do arquivo morto (só leitura, cache por mtime)
def salvar_anexo(dados: bytes, nome: str) -> dict   # confere tipo/tamanho/cota; devolve {id, nome, tipo, bytes}
def ler_anexo(aid: str) -> tuple[bytes, str]        # (dados, tipo); StoreError 404 se não existe/id ruim
def apagar_anexo(aid: str) -> None
def uso_anexos() -> dict                 # {"bytes": int, "cota": COTA}
```
Chamar `salvar_anexo` fora do `LOCK` é permitido (grava arquivo novo com nome inédito); o metadado entra na
demanda sob o `LOCK`. Se a gravação do JSON falhar depois, o api.py apaga o arquivo órfão.

## Identidade e papéis
- `ctx["papel"]` vem do servidor: `"maquina"` (o próprio PC), `"completo"` (PIN do escritório) ou `"operador"`
  (PIN dos operadores, pedido uma vez por aparelho).
- **ADM / Escritório**: papel `maquina` ou `completo` agindo sem pessoa. Registrado como `"Escritório"`.
- **Pessoa**: `POST entrar {pessoa, codigo}` confere o código (bloqueio: 5 erros = 60 s por pessoa, 429) e
  devolve `{tk, eu, vista}`. `tk` = token aleatório (`secrets.token_urlsafe(24)`) guardado em memória e em
  `data/pessoas-sessoes.json`, só como `sha256(tk) -> (pessoa, vence)` — o token em claro nunca vai para o
  disco, e a página também o guarda só em memória. Validade 12 h, máx. 500 (descarta o mais antigo); cai ao
  desativar a pessoa, trocar o código ou restaurar uma cópia. Como está no disco, reiniciar o servidor não
  derruba ninguém. Toda ação como pessoa manda `"tk"` no corpo. `tk` ruim/vencido = 401 "Identifique-se de novo."
- Papel `operador` só age como pessoa (sem `tk` = 403).
- `tenant` ainda não existe: tudo roda numa empresa só. Ele chega com a fase 1 do estudo 03, junto da
  interface de armazenamento (`Banco`/`BancoJson`) e do `papel_do_pedido` que substitui a decisão por
  `ctx["papel"]` — obrigatória antes de qualquer hospedagem. Até lá, rota nova não precisa passar tenant:
  um campo que chega e ninguém lê é código morto, sem teste que o defenda.

## Rotas
Todas devolvem a **vista** do ator (ADM ou pessoa), salvo onde indicado. Erros: `ApiError(status, msg)`
com 400 (dado inválido), 401 (tk), 403 (sem permissão), 404 (não existe), 409 (estado mudou, ex.: aceitar
uma demanda que já foi aceita; cadastro com `rev` velho), 413 (anexo grande), 429 (código bloqueado),
507 (cota de anexos).

| Método e caminho | Corpo | Quem pode |
|---|---|---|
| `GET ""` | — | ADM: vista completa. Operador: só `setores` e `pessoas` públicas (para a tela "quem é você") |
| `POST entrar` | `{pessoa, codigo}` | qualquer papel → `{tk, eu, vista}` |
| `POST sair` | `{tk}` | → `{ok: true}` |
| `POST vista` | `{tk}` | pessoa → vista da pessoa |
| `POST demanda/criar` | `{titulo, tipo, motivo, prio, est, para:{s,p}, desc, de_s?}` | ADM (`de_s` obrigatório) ou pessoa (`de` = ela) |
| `POST demanda/aceitar` | `{id}` | pessoa do setor destino, status new → prog; vira responsável |
| `POST demanda/pausar` | `{id, motivo, obs}` | responsável, prog → pause |
| `POST demanda/retomar` | `{id}` | responsável, pause → prog |
| `POST demanda/concluir` | `{id, nota}` | responsável, ativa → done |
| `POST demanda/cancelar` | `{id, motivo}` | ADM ou quem pediu (`de.p`), ativa → canc |
| `POST demanda/reatribuir` | `{id, s, p, nota}` | ADM (qualquer ativa) ou pessoa do setor destino (new ou ela é a responsável) |
| `POST demanda/cobrar` | `{id}` | ADM ou quem pediu, ativa |
| `POST demanda/prioridade` | `{id, prio}` | ADM |
| `POST demanda/estender` | `{id, minutos}` | ADM, ativa |
| `POST demanda/comentar` | `{id, texto}` | ADM, ou pessoa do setor de origem ou destino |
| `POST anexo/enviar` | `{id, nome, dados}` (`dados` = base64) | ADM, quem pediu ou pessoa do setor destino; demanda não cancelada |
| `GET anexo/<aid>` | — | ADM → `{id, nome, tipo, dados}` (base64) |
| `POST anexo/ler` | `{tk, aid}` | pessoa que vê a demanda → `{id, nome, tipo, dados}` |
| `POST anexo/apagar` | `{id, aid}` | ADM ou quem enviou, demanda ativa |
| `POST nota/lida` | `{nid}` | quem vê a nota (ADM: as "adm"; pessoa: as do setor dela para o setor todo ou só para ela); marca só para quem pediu |
| `POST nota/todas` | `{}` | idem, marca todas as que o ator vê |
| `POST aviso/prefs` | `{}` lê · `{prefs: {eventos?, silencio?, urgente_fura?}}` grava · `{padrao: true}` volta ao padrão | cada um as próprias (ADM = `"adm"`) → `{prefs}` (padrão + diferenças, e `proprio`); não muda o `rev` |
| `POST setor/salvar` | `{modo: "novo"\|"editar", id, nome, icone, cor, rev}` | ADM |
| `POST setor/ativar` | `{id, rev}` (alterna) | ADM; desativar recusa com demanda aberta (400 com `abertas`) |
| `POST setor/apagar` | `{id, rev}` | ADM; recusa se há histórico (principal ou arquivo) |
| `POST pessoa/salvar` | `{modo, id?, nome, setor, codigo?, rev}` | ADM; código obrigatório no novo |
| `POST pessoa/ativar` | `{id, rev}` | ADM; desativar devolve as demandas dela à fila do setor |
| `POST pessoa/apagar` | `{id, rev}` | ADM; recusa se há histórico |
| `POST crono` | `{dias: 1\|7\|30}` | ADM → objeto de cronoanálise (abaixo) |
| `POST cronograma` | `{de, ate, por: "setor"\|"pessoa"}` | ADM → objeto de cronograma (abaixo); janela de até 31 dias |

Pessoa usa `tk` em todas as rotas de ação; ADM não manda `tk`. As regras de negócio foram portadas de um
projeto anterior e hoje vivem aqui: este arquivo é a descrição delas, e `api.py` com `demandas_calc.py` são
a implementação. Não há nada a consultar fora deste projeto.

Avisos gerados (tabela 6.1 do estudo 02). "Ponta" = a pessoa dela (`pid`) ou, sem pessoa, o setor; a origem
sem pessoa (pedido do Escritório) = "adm":
criar → `new` para o destino (+ `urg` para adm se urgente); aceitar → `accepted` para a origem; pausar → `pause`
para adm e, se quem pediu foi uma pessoa, para ela; concluir → `done` para a origem; cancelar → `canc` para o
destino; reatribuir → `new` para o destino quando muda o setor ou a pessoa escolhida; cobrar → `nudge` para o
destino (+ adm se quem cobrou foi uma pessoa); prioridade urgente → `nudge` para o destino; comentar → `comment`
(até 120 caracteres) para o outro lado (quem atende comentou → origem; senão → destino); atraso → `late` para adm e
destino, uma vez por demanda (`atraso_avisado`), em qualquer gravação e a cada minuto pela thread de fundo
(`api.tick(agora)`, que só grava se alguma demanda passou do prazo).

Na tela (camada 1, `demandas.js`): aviso novo de outra pessoa toca um som (urgente: alarme de três notas), vibra
onde há `navigator.vibrate` e, com a aba escondida, faz o título piscar até a pessoa voltar; o título fica
"(N) Central de demandas". Avisos da mesma demanda dentro do tempo de juntar tocam uma vez; no máximo um som a cada
20 s. Evento desligado pela pessoa fica só no sino (sem banner, som e vibração). No horário de silêncio (início
incluído, fim não; início > fim atravessa a meia-noite; início = fim = sem silêncio) nada toca nem vibra, salvo urgente com "urgente fura"; o
banner e o sino continuam.

Preferências de aviso: `data/avisos.json` (`demandas_avisos.py`), fora do `demandas.json`:
```json
{"v": 1,
 "padrao": {"eventos": {"new": true, "fila": true, "accepted": true, "pause": true, "done": true, "canc": true,
                        "nudge": true, "late": true, "comment": true},
            "som": "curto", "vibrar": true, "agrupar_min": 10,
            "silencio": {"ligado": false, "ini": "22:00", "fim": "06:00"}, "urgente_fura": true},
 "pessoas": {"p14": {"eventos": {"fila": false}, "silencio": {"ligado": true}}, "adm": {"eventos": {"pause": false}}}}
```
- Eventos: `new` = escolheram a pessoa (urgente do Escritório conta como `new`), `fila` = nova na fila do setor
  (nota sem `pid`), os outros = o tipo da nota. Som: `curto`, `sino`, `desligado`. Agrupar: 0, 5 ou 10 min. Hora
  `HH:MM`.
- Da pessoa ficam só as diferenças de eventos, silêncio e `urgente_fura`; igual ao padrão = some do arquivo.
- Som, vibração e "juntar" valem por aparelho, em `localStorage["dm-avisos-aparelho"]` (`{som?, vibrar?,
  juntar?}`, só o que difere do padrão da central). Arquivo ausente ou ilegível = todo mundo no padrão.
- Só em `127.0.0.1`/`localhost` (contexto seguro): `sistema` (Notification API, só com a aba escondida; título `<tipo> · SOL-n`, corpo = título da demanda, `tag` = id) e `tela` (Screen Wake Lock, pedido de novo ao voltar à aba) no mesmo `localStorage`. A permissão só é pedida no Salvar.
- Padrões da central: `GET/POST /api/avisos` (servidor.py, só o computador principal).

## Vista (resposta)
Ver `contrato.json`. Campos:
```
rev, agora, papel ("adm"|"pessoa"), eu (null | {id, nome, setor, mat}),
setores [{id, nome, icone, cor, ativo, _rv}],
pessoas [{id, nome, setor, mat, ativo, _rv}]        # nunca sal/hash
demandas [{...campos gravados sem _interno, + prazo, atrasada, espera, execucao, pausado, total, sla}]
notas [{id, aud, pid, tipo, dem, texto, quem, t, lida}]  # só as que o ator vê; lida = a dele; sem "lidas"
feed [{t, tipo: "warn"|"ok"|"", dem, msg}]          # 14 eventos mais recentes, sem "assigned"
anexos_uso {bytes, cota}                            # só ADM
```
- Derivados por `demandas_calc.metricas(d, agora)`, em minutos com fração: `espera`, `execucao`,
  `pausado`, `total`; `prazo` = criado + est·60000; `atrasada`; `sla` = total/est·100.
- ADM vê todas as demandas do principal. Pessoa vê as do setor dela (destino) e as que ela pediu.
- O histórico (aba Histórico) da ADM inclui o arquivo morto: `GET ""` traz só o principal; o arquivo vem em
  `POST historico {de, ate}` → `{demandas: [...]}` (ADM).

## Cronoanálise (`POST crono`)
```
{dias, desde, kpis: {abertas, concluidas, no_prazo, pct_prazo|null, espera, execucao, estimado, pausado},
 setores: [{s, n, espera, execucao, pausado, estimado, sla}],     # ordenado por sla asc, n desc
 motivos: [{motivo, n}],                                         # top 8 desc
 ranking: [{p, n, sla}],                                         # top 6
 gantt: {ini, fim, linhas: [{id, de, para, titulo, segs: [{k: "wait"|"exec"|"pause", a, b}], prazo, atrasada, viva}]}}
```
Médias `null` quando não há dado. Gantt: janela agora−10h a agora+3h, 14 ativas por atenção + 4 concluídas recentes.

## Cronograma multidia (`POST cronograma`)
```
{ini, fim, por, agora, cortado,
 grupos: [{chave, n, ativas,
           linhas: [{id, de, para, titulo, segs, prazo, atrasada, viva, p, plano: {a, b}}]}]}
```
Mesma janela e os mesmos trechos do gantt, só com outro recorte: `{de, ate}` em ms (até 31 dias; invertida é
ordenada), `por` agrupando por sigla de setor ou por `pid` (`chave: null` é a fila do setor, um grupo só).
Grupos ordenados por `ativas` desc, `n` desc, `chave`; linhas de cada grupo por `criado`. Entram as ativas e as
concluídas que cruzam a janela ou cujo prazo cai nela — cancelada não entra. O teto é `calc.GANTT_MULTI` (120)
linhas, escolhidas pela atenção (atrasada e urgente primeiro), e `cortado` diz se sobrou alguma de fora.

`p` (a pessoa) e `plano` (a barra `criado` → `prazo`) existem **só** aqui: a linha do `crono.gantt` continua
exatamente com as oito chaves listadas acima, e `por`, `agora`, `grupos` e `cortado` não existem lá.

## Frontend
- `STATIC` (CSS, JS e fontes) é tudo o que o servidor entrega desta pasta. `REV_FILE = "demandas.json"`.
- `web/index.html` tem `<main data-view="demandas">`; o `demandas.js` monta `<section id="dmboard">` dentro dele e
  registra `window.NestLocal.views.demandas = {open, rev, refresh}`. A casca `web/app.js` dá o `api()` (POST com
  `X-Tab`, lança `Error` com `.status`) e o `toast()`, e chama `refresh()` quando o `/api/rev` muda.
- Todo dado vindo da API entra escapado (`esc`) ou por `textContent`. Nada de `eval`/`new Function`.
