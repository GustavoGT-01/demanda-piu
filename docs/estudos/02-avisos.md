# Estudo 02 · Avisos no celular e no PC

Estudo e mockups apenas. Nenhuma linha do programa muda agora. Consultas na web feitas em **28/10/2026**.

## 1. Resumo

1. **Camada 1 já, em http, sem dependência nova**: banner (já existe), som curto, título da aba piscando com o
   contador e vibração no Android. Funciona com a página aberta, em qualquer aparelho da rede.
2. **No PC principal (`http://127.0.0.1`) dá para ir além hoje**: o navegador trata 127.0.0.1 como seguro, então
   aviso do sistema (Notification API) e Wake Lock funcionam ali sem HTTPS. Nos celulares da rede, não.
3. **No servidor, antes de qualquer push**: aviso por **pessoa** (hoje é por setor), aviso de **comentário** (hoje
   não existe) e uma **checagem de atraso a cada minuto** na thread de fundo do backup (estudo 01).
4. **Camada 2 (app fechado) só com HTTPS**: PWA + Web Push. Vale a pena quando o sistema for hospedado (estudo 03).
   Certificado próprio na rede local funciona, mas exige instalar o certificado em cada celular.
5. **Enviar Web Push exige criptografia que a stdlib não tem.** Recomendo aceitar `pywebpush` como dependência
   opcional e isolada só para isso, em vez de escrever ECDSA/ECDH/AES-GCM à mão. Decisão do dono.

## 2. Como é hoje

### Servidor e dados
- Toda nota de aviso nasce em `_nota` (`demandas/api.py:234-239`): `{id, aud, tipo, dem, texto, quem, t, lida}`.
  O público `aud` é **um setor ou "adm"**. Não existe nota para uma pessoa.
- `lida` é **uma só para o setor inteiro**: `nota/lida` e `nota/todas` conferem só `aud` (`demandas/api.py:559-580`).
  Se um operador do CORTE abre o sino, o aviso some como "não lido" para todos do CORTE.
- A vista entrega à pessoa todas as notas do setor dela (`demandas/demandas_calc.py:156-157`).
- Quem recebe o quê hoje:

  | Evento | Público da nota | Onde |
  |---|---|---|
  | Nova demanda | setor de destino; "adm" também se urgente | `api.py:347-349` |
  | Repassada para outro setor | novo setor de destino | `api.py:442-443` |
  | Pessoa desativada (volta à fila) | setor de destino | `api.py:309` |
  | Aceita | setor solicitante (se for outro setor) | `api.py:364-365` |
  | Pausada | "adm" e setor solicitante | `api.py:382-384` |
  | Concluída | setor solicitante (se for outro setor) | `api.py:409-410` |
  | Cancelada | setor de destino | `api.py:423` |
  | Cobrança | setor de destino | `api.py:453` |
  | Prioridade elevada a urgente | setor de destino (tipo "nudge") | `api.py:466-467` |
  | Atraso | "adm" e setor de destino | `api.py:286-297` |
  | **Comentário** | **nenhuma nota** | `api.py:485-493` |
  | Retomada | nenhuma nota | `api.py:388-396` |

- Teto de **120 notas no total**, somando todos os setores (`demandas/demandas_store.py:23`, corte em `api.py:239`).
- O atraso só é marcado quando alguém grava algo: `_gravar` chama `marcar_atrasos` (`api.py:753-759`). Não há timer.
- `_gravar` devolve um callback `depois`, que roda fora do LOCK e depois de gravar (`api.py:853-855`).
- A normalização do arquivo **descarta chaves desconhecidas no topo** do `demandas.json` (só copia `rev`, `seq`,
  `setores`, `pessoas`, `demandas`, `notas`: `demandas_store.py:117-134`). Campos extras dentro de cada nota
  sobrevivem (`demandas_store.py:131-133`).
- O token da pessoa (`tk`) vive só na memória, por 12 h (`api.py:43`, `api.py:147-156`).

### Servidor HTTP
- Só `http://`. Cookie sem `Secure` (`servidor.py:426`).
- CSP `default-src 'self'; script-src 'self'` (`servidor.py:36-37`). Um service worker do próprio servidor passaria.
- Tipos servidos: só `.js`, `.css`, `.woff2`, `.html` (`servidor.py:38-39`). Manifest (`.webmanifest`/`.json`) e
  ícone `.png` não seriam servidos hoje.
- Arquivos estáticos: só `/`, `/app.js` e o `STATIC` do módulo em `/local/demandas/` (`servidor.py:338-348`,
  `demandas/api.py:802`). Um service worker em `/local/demandas/sw.js` só controlaria `/local/demandas/`, e a
  página fica em `/`. Ele teria de sair em `/sw.js`.
- O operador só alcança as rotas da lista `OPERADOR_RE` (`servidor.py:59-65`). Rota nova de aviso precisa entrar ali.
- `main()` sobe o servidor sem nenhuma thread de fundo (`servidor.py:459-472`).

### Tela
- A tela pergunta `/api/rev` a cada 3 s (`web/app.js:27-36`, `web/app.js:72-73`) e recarrega a vista quando muda.
- `notesCheck` compara as notas novas com as já vistas (`D.seen`) e, para os tipos de `ALERT_KINDS`
  (`urg, late, pause, new, nudge, canc`), chama `showAlert` se a tela está visível ou um toast da casca se não está
  (`demandas/demandas.js:15-16`, `demandas/demandas.js:197-214`). Aceita e concluída viram só toast.
- `showAlert` empilha no máximo 3 cartões `dm-alert`, que somem em 26 s (`demandas/demandas.js:224-237`).
- O sino `#dm-bell` tem badge com o número de não lidas e balança (`dm-ring`) quando chega algo
  (`demandas/demandas.js:216-223`, `demandas/demandas.js:1249`, `demandas/demandas.css:66-69`).
- A gaveta `#dm-notif` lista as 40 últimas notas, sem agrupar e sem filtro, com "Marcar todas como lidas" e
  "Ver solicitação" (`demandas/demandas.js:678-696`, `demandas/demandas.js:1254`).
- Não há som, título piscando, vibração, Notification API nem service worker.

## 3. O que funciona sem HTTPS e o que exige HTTPS

"Contexto seguro" = `https://`, ou `http://localhost`, `http://127.0.0.0/8`, `http://[::1]` e `file://`.
**IP de rede local como `http://192.168.x.x` não conta** (MDN, Secure contexts, consultado em 28/10/2026).

| Recurso | Exige contexto seguro? | `http://127.0.0.1` (PC principal) | `http://192.168.x.x` (celular na rede) | Fonte |
|---|---|---|---|---|
| Banner na tela, sino, título piscando | Não | Sim | Sim | (é HTML/JS comum) |
| Som (Web Audio) | Não, mas precisa de um toque antes na página | Sim, depois do 1º toque | Sim, depois do 1º toque | Chrome autoplay policy |
| `navigator.vibrate` | MDN não diz que exige; exige interação prévia com a página | PC não vibra | **Só Android** (Chrome); iOS e Firefox Android não têm | MDN Vibration; caniuse |
| Notification API (`new Notification`) | **Sim** | Sim (desktop) | **Não** | MDN Notifications API |
| Service worker | **Sim** | Sim | **Não** | MDN Service Worker API |
| Push API / Web Push | **Sim** (precisa de service worker) | Só com internet e o navegador aberto em 2º plano | **Não** | MDN Push API |
| Screen Wake Lock | **Sim** | Sim | **Não** | MDN Screen Wake Lock |
| Badging API (número no ícone) | **Sim**, e pensada para app instalado | Só com PWA instalado | **Não** | MDN Badging API |

Descoberta importante: **Wake Lock também exige HTTPS.** O pedido colocava Wake Lock na camada 1; nos celulares
por http ele não funciona. Fica para o PC principal e para a camada 2.

### Navegador por navegador
- **Chrome Android**: com HTTPS, notificação **só pelo service worker** (`registration.showNotification`); o
  construtor `new Notification()` lança erro na maioria dos navegadores móveis (MDN Notifications API). Push
  funciona com o navegador fechado. Vibração e Wake Lock funcionam. Existe a opção
  `chrome://flags/#unsafely-treat-insecure-origin-as-secure` para tratar um IP como seguro, mas é para teste, por
  aparelho, e **não confirmei** que exista no Chrome Android atual. Não recomendo.
- **Safari iOS / iPadOS**: Web Push **só a partir do iOS 16.4 e só com o site adicionado à Tela de Início**, com
  manifest `display: standalone` (ou `fullscreen`) e pedido de permissão disparado por toque do usuário. Não exige
  conta de desenvolvedor Apple. O servidor precisa alcançar `*.push.apple.com` (WebKit, "Web Push for Web Apps on
  iOS and iPadOS", consultado em 28/10/2026). **Não vibra** (caniuse: sem suporte em nenhuma versão). Wake Lock a
  partir do 16.4 (caniuse). Badge no ícone a partir do 16.4 (WebKit).
- **Chrome e Edge desktop**: Notification API, service worker, push, Wake Lock (84+) e badge do app instalado.
  Em `http://127.0.0.1` tudo isso já vale.
- **Aba em segundo plano** (todos com Chromium): desde o Chrome 88, uma aba escondida há mais de 5 min e em
  silêncio há 30 s tem seus timers agrupados **uma vez por minuto** (Chrome for Developers, "Heavy throttling of
  chained JS timers", consultado em 28/10/2026). O polling de 3 s vira até 1 min de atraso no aviso. Quem tocou som
  nos últimos 30 s fica fora dessa regra, mas não vale a pena tocar som só para isso.

## 4. Opções comparadas

| Opção | Prós | Contras | Custo | Esforço |
|---|---|---|---|---|
| **A. Camada 1: tela aberta** (som, título, vibração, banner) | Funciona hoje em http; stdlib pura; nada para instalar | Só com a página aberta; aba escondida atrasa até 1 min; iPhone não vibra | Zero | Pequeno |
| **A+. Notificação do sistema no PC principal** | Aviso do Windows mesmo com a aba atrás; 127.0.0.1 já é seguro | Só no PC principal (o escritório); precisa do navegador aberto | Zero | Pequeno |
| **B1. Camada 2 com hospedagem HTTPS** (estudo 03) + PWA + Web Push | Avisa com app fechado em Android, iOS 16.4+ (instalado) e desktop; certificado gratuito (Let's Encrypt) | Exige hospedagem e envio cifrado (ECDSA P-256, ECDH, HKDF, AES-128-GCM); iOS só com PWA instalado | Hospedagem (estudo 03) | Médio |
| **B2. Camada 2 na rede local com certificado próprio** (mkcert ou CA própria) | Sem internet para a página; o `ssl` da stdlib serve HTTPS | Instalar e confiar a CA **em cada celular**; no iOS é perfil + "confiança total" em Ajustes; IP fixo obrigatório; a chave da CA dá poder de interceptar tudo (README do mkcert); push ainda precisa de internet (FCM/APNs/Mozilla) | Zero em dinheiro, alto em suporte | Médio + suporte contínuo |
| **B3. ntfy** (app de terceiros que recebe avisos por HTTP simples) | O servidor só faz um POST com `urllib` (stdlib); funciona sem HTTPS na central; apps Android e iOS | Cada pessoa instala outro app; no servidor público ntfy.sh o tópico é "público" (quem souber o nome lê); ideal seria hospedar o próprio ntfy | Grátis no ntfy.sh; plano pago existe (preço não confirmado) | Pequeno |
| **C1. Telegram (bot)** | API HTTPS simples, dá para chamar com `urllib`; gratuito | Cada pessoa precisa ter Telegram e iniciar conversa com o bot; dados saem para terceiro | Zero (não confirmei a gratuidade na página da API; é a prática conhecida) | Pequeno |
| **C2. WhatsApp Business Platform** | Todo mundo usa | Cobrança por mensagem entregue, por categoria de modelo e país; desde 01/10/2026 mensagens de atendimento acima de 1.000/mês por número também são cobradas (Meta, pricing, 28/10/2026); exige cadastro empresarial | Por mensagem | Médio + burocracia |
| **C3. E-mail** | Assíncrono, registro escrito | Não é imediato; setor e pessoa não têm e-mail hoje | Ver estudo 04 | Ver estudo 04 |

### Quem envia o Web Push (dentro de B1/B2)
O servidor precisa, por mensagem: assinar um JWT **ES256** (ECDSA P-256) para o VAPID, gerar um par ECDH P-256
temporário, derivar chaves com HKDF-SHA-256 e cifrar com **AES-128-GCM** (RFC 8291 / RFC 8292; web.dev,
"The Web Push Protocol", consultado em 28/10/2026).

- **Stdlib**: tem `hmac`/`hashlib` (dá para fazer HKDF) e `ssl` (dá para servir HTTPS), mas **não tem** curva
  elíptica nem AES-GCM. Escrever P-256 e AES-GCM em Python puro é possível (algumas centenas de linhas), porém lento,
  sem tempo constante e um risco de segurança que o projeto teria de manter. Não recomendo.
- **`pywebpush`** 2.5.0 (PyPI, publicado em 30/08/2026): depende de `cryptography>=47`, `http-ece`, `py-vapid`,
  `requests` e `aiohttp`. Quebra a regra "só stdlib".
- **Meio-termo recomendado**: aceitar só **`cryptography`** (biblioteca padrão de fato do Python, com binários
  prontos para Windows) e escrever o envio (JWT + aes128gcm + `urllib`) em ~150 linhas próprias, testáveis. Fica
  isolado num arquivo `avisos_push.py`, importado só se a camada 2 estiver ligada. Sem a biblioteca, o programa roda
  igual e a seção mostra "push indisponível".

## 5. Recomendação

1. **Fazer agora a camada 1 (opção A + A+)**, junto com as mudanças de servidor que valem para qualquer camada:
   aviso por pessoa, aviso de comentário, leitura por pessoa, checagem de atraso por timer e preferências.
2. **Não fazer HTTPS na rede local (B2).** O atrito de instalar certificado em cada celular de fábrica, e de refazer
   quando o celular é trocado ou o IP muda, é maior que o ganho.
3. **Camada 2 (B1) junto com a hospedagem do estudo 03**, com o meio-termo `cryptography`. Até lá, se o dono
   quiser aviso com app fechado já, a opção mais barata é **ntfy (B3)** num servidor próprio.
4. Camada 3: e-mail (estudo 04). Telegram só como opção futura. WhatsApp não, pelo custo e burocracia.

Por quê: a camada 1 resolve o caso principal (operador com o celular ou tablet aberto na tela da central, e o
escritório no PC principal) sem dependência nova. O que impede avisos bons hoje não é a falta de push: é o aviso
ir para o setor inteiro, a leitura ser compartilhada e o atraso só aparecer quando alguém grava.

## 6. Como encaixa no código atual

### 6.1 Quem recebe o quê (proposta)

| Evento | Recebe | Hoje |
|---|---|---|
| Nova demanda com pessoa escolhida | a pessoa (`para.p`) e, em segundo plano, o setor | só o setor |
| Nova demanda para a fila (`para.p = null`) | todas as pessoas ativas do setor de destino | o setor |
| Aceita, pausada, concluída | o **solicitante** (`de.p`); se foi o escritório, "adm" | o setor solicitante |
| Cancelada | o responsável (`para.p`) ou o setor, se na fila | o setor |
| Cobrança, prioridade urgente | o responsável ou o setor; "adm" recebe cópia | o setor |
| Atraso | o responsável ou o setor, e "adm" | setor e "adm" |
| Comentário | **o outro lado**: quem comentou do lado do pedido avisa o responsável (ou setor); do lado do destino avisa o solicitante | nada |
| Retomada | ninguém (evita barulho) | ninguém |

### 6.2 Formato de dados

Nota ganha `pid` (pessoa) e `lidas` (quem leu). Compatível: nota antiga sem `pid` = para o setor todo; `lida`
continua valendo para "adm".

```json
{"id": 812, "aud": "COR", "pid": "p14", "tipo": "new", "dem": "SOL-1043", "texto": "", "quem": "Rafael Souza",
 "t": 1793180520000, "lida": false, "lidas": []}
```

Preferências e inscrições de push ficam **num arquivo novo `data/avisos.json`**, gravado com `store.atomic_write`,
fora do `demandas.json`. Motivos: (1) a normalização descarta chaves novas no topo do `demandas.json`
(`demandas_store.py:117-134`); (2) mudar preferência não deve mudar o `rev` e fazer todos os aparelhos recarregarem
(`web/app.js:33`); (3) o endpoint de push é um segredo (MDN Push API) e não deve ir em backup que circula.

```json
{
  "v": 1,
  "padrao": {
    "eventos": {"new": true, "fila": true, "accepted": true, "pause": true, "done": true, "canc": true,
                "nudge": true, "late": true, "comment": true},
    "som": "curto", "vibrar": true, "silencio": {"ini": "22:00", "fim": "06:00"}, "urgente_fura": true,
    "agrupar_min": 10, "checar_atraso_s": 60
  },
  "pessoas": {
    "p14": {"eventos": {"fila": false}, "silencio": {"ini": "14:00", "fim": "06:00"}, "_rv": 3}
  },
  "push": {
    "p14": [{"endpoint": "https://fcm.googleapis.com/fcm/send/…", "p256dh": "…", "auth": "…",
             "criado": 1793180000000, "aparelho": "Android · Chrome"}]
  },
  "vapid": {"pub": "…", "priv_arquivo": "data/vapid-privada.pem"}
}
```

- Na pessoa só ficam as diferenças do padrão. Some do arquivo = volta ao padrão.
- **Som, vibração e "tela acesa" valem por aparelho**: ficam no `localStorage` do navegador (o tablet do chão pode
  tocar alto e o celular pessoal não). **Eventos e horário de silêncio ficam no servidor**, porque o push da camada 2
  precisa filtrar lá, e porque a pessoa troca de aparelho.
- "Só no meu turno": o projeto não tem turno (`demandas_calc.py:39-40` é tempo corrido). Proposta: o horário de
  silêncio já cobre ("fora do turno = silêncio"). Se o estudo 05 criar turnos, a preferência passa a apontar para o
  turno.

### 6.3 Funções que mudariam

| Arquivo | Mudança |
|---|---|
| `demandas/api.py` `_nota` (`:234`) | parâmetro `pid=None`; grava `pid` e `lidas: []` |
| `demandas/api.py` `_criar`, `_aceitar`, `_pausar`, `_concluir`, `_cancelar`, `_cobrar`, `_prioridade`, `marcar_atrasos` | escolher o destino da nota pela tabela 6.1 |
| `demandas/api.py` `_comentar` (`:485`) | criar nota tipo `comment` para o outro lado |
| `demandas/api.py` `_nota_lida`, `_notas_todas` (`:563-580`) | pessoa marca em `lidas`; "adm" continua em `lida` |
| `demandas/demandas_calc.py` `vista` (`:156`) | pessoa recebe notas do setor sem `pid` e as com `pid` igual ao dela; `lida` calculada por pessoa |
| `demandas/demandas_store.py` `MAX` (`:23`) | `notas` de 120 para ~1000, ou teto por público; com aviso por pessoa, 120 some em poucas horas |
| `demandas/api.py` novo `tick(agora)` | sob LOCK: `marcar_atrasos`; se mudou, `commit`; devolve `depois` com os pushes |
| `demandas/avisos.py` (novo) | ler/gravar `data/avisos.json`, mesclar padrão + pessoa, decidir "toca ou não" (silêncio, agrupamento) |
| `demandas/avisos_push.py` (novo, camada 2) | VAPID + aes128gcm + envio por `urllib`; só carrega se `cryptography` existir |
| `servidor.py` `main()` (`:463-472`) | thread daemon de fundo, a mesma do backup (estudo 01), que chama `api_mod().tick()` a cada `checar_atraso_s` |
| `servidor.py` `TYPES`, `_static` (`:38`, `:338`) | camada 2: servir `/sw.js`, `/manifest.webmanifest` e ícones `.png` |
| `servidor.py` `OPERADOR_RE` (`:63-65`) | liberar `aviso/(prefs|inscrever|desinscrever)` |
| `demandas/demandas.js` `notesCheck` (`:197`) | depois de `showAlert`: `avisar(n)` = som + vibração + título piscando, respeitando preferências e agrupamento |
| `demandas/demandas.js` `renderNotif` (`:678`) | agrupar por demanda, filtro "Não lidos"/"Urgentes", link para preferências |
| `demandas/demandas.js` novo `vPrefs()` | tela "Meus avisos" (mockup) |
| `web/app.js` | seção Avisos do diálogo ⚙ Configurações |

### 6.4 Checagem de atraso por timer

Hoje o atraso só nasce quando alguém grava (`api.py:757`). De madrugada, uma demanda pode passar do prazo e
ninguém ser avisado até a primeira ação do dia.

```python
# servidor.py, em main(), entre api_mod() e serve_forever(): a mesma thread do backup (estudo 01)
def _fundo():
    while True:
        time.sleep(60)
        try:
            api_mod().tick()          # marca atrasos, grava se mudou, dispara pushes fora do LOCK
            # backup_se_for_hora()    # estudo 01
        except Exception as exc:      # thread de fundo não pode morrer calada
            print("[fundo] %r" % exc, file=sys.stderr)
threading.Thread(target=_fundo, daemon=True, name="fundo").start()
```

`tick` faz `_RV[0] = doc["rev"] + 1` como `_gravar` (`api.py:755`), então o `/api/rev` muda e todas as telas abertas
recebem o aviso de atraso pelo polling, sem push. Custo: um `load` do JSON por minuto (já fica em cache,
`demandas_store.py:139`).

### 6.5 Não incomodar demais
- **Agrupar**: avisos da mesma demanda dentro de 10 min tocam uma vez só; na gaveta viram um grupo
  "SOL-1043 · 3 avisos". No push, o cabeçalho `Topic` com o id da demanda faz o aviso novo **substituir** o anterior
  ainda não entregue (Web Push Protocol).
- **Limite de som**: no máximo um som a cada 20 s por aparelho; os outros só sobem o contador.
- **Silêncio**: fora da janela, nada toca e nada vibra; o sino e o contador continuam. Opção "Urgente toca mesmo no
  silêncio" (padrão ligado).
- **Não avisar a si mesmo**: já existe (`n.quem === me`, `demandas.js:204`); vale também para push.
- **Pedido de permissão**: só depois de um toque em "Quero receber", nunca ao abrir. Se a pessoa bloquear, só
  desbloqueia nas configurações do navegador (web.dev, "Subscribing a user", 28/10/2026).

### 6.6 Rotas novas

| Rota | Quem | O que faz |
|---|---|---|
| `POST /api/local/demandas/aviso/prefs` | pessoa (as próprias); ADM (as próprias, público "adm") | lê ou grava preferências (com `_rv`) |
| `POST /api/local/demandas/aviso/inscrever` | pessoa, ADM | camada 2: guarda a inscrição de push do aparelho |
| `POST /api/local/demandas/aviso/desinscrever` | pessoa, ADM | camada 2: apaga a inscrição do aparelho |
| `GET/POST /api/config/avisos` | **máquina** (como `/api/rede`, `servidor.py:388-391`) | padrões da central, estado do HTTPS/push, gerar chaves VAPID, aviso de teste |
| `GET /sw.js`, `GET /manifest.webmanifest` | todos (operador incluído em `OPERADOR_ROTAS`) | camada 2 |

## 7. Riscos e segurança
- **Inscrição de push é segredo**: quem tem o endpoint manda aviso para o aparelho. Fica em `data/avisos.json`,
  nunca na vista, nunca em log. Rota de inscrição exige `tk` válido e cabeçalho `Origin` (já conferido em
  `servidor.py:412-415`).
- **Chave privada VAPID**: arquivo separado em `data/`, fora de backups que vão por e-mail (estudo 01 e 04). Trocar a
  chave invalida todas as inscrições.
- **Conteúdo do push passa por terceiros** (Google FCM, Apple, Mozilla). Vai cifrado de ponta a ponta, mas o texto
  aparece na tela bloqueada. Proposta: só id, setor e prioridade; o título da demanda é opcional.
- **Aparelho compartilhado** (tablet do chão): preferência de som fica no aparelho; inscrição de push num tablet
  compartilhado deve ser do setor, não da pessoa. Ao "sair", desinscrever.
- **Pessoa desativada**: apagar as inscrições dela junto com `_devolve` (`api.py:300`).
- **Excesso de avisos** vira ruído e as pessoas bloqueiam a permissão; o bloqueio é difícil de desfazer.
- **Certificado próprio na rede (B2)**: a chave da CA permite interceptar todo HTTPS daquele celular. Mais um motivo
  para não seguir por esse caminho.
- **Thread de fundo**: precisa pegar o mesmo `LOCK`; exceção nunca pode matar a thread; teste com relógio falso.
- **Dependência `cryptography`**: fora do escopo "só stdlib"; precisa de versão fixa em `requirements.txt` e o
  programa precisa rodar sem ela.

## 8. Testes que a implementação vai exigir (docs/QUALIDADE.md)
- **Unitários (`tests/test_demandas_api.py`)**: destino de cada nota pela tabela 6.1, um teste por evento,
  incluindo comentário dos dois lados, demanda criada pelo escritório (`de.p = null`), mesmo setor nos dois lados.
  `nota/lida` por pessoa não marca para o colega. `nota/todas` só as da pessoa. Nota antiga sem `pid` continua
  aparecendo.
- **Unitários (`tests/test_demandas_calc.py`)**: `vista` filtra `pid` e calcula `lida` por pessoa.
- **Unitários (novo `tests/test_avisos.py`)**: mescla padrão + pessoa; silêncio atravessando a meia-noite
  (22:00 → 06:00) e nos limites exatos; urgente fura silêncio; agrupamento de 10 min; arquivo ilegível vira padrão.
- **Unitários do push (`tests/test_avisos_push.py`)**: vetores de teste do RFC 8291 (cifra) e JWT ES256 verificado
  com a chave pública; sem `cryptography`, a função diz "indisponível" sem quebrar.
- **Integração (`tests/test_servidor.py`)**: `tick` com relógio falso marca atraso uma vez só e muda o `rev`; thread
  de fundo sobrevive a exceção; operador alcança `aviso/prefs` e não alcança `/api/config/avisos`; da rede,
  `/api/config/avisos` dá 403.
- **jsdom (`tests/demandas_check.js`)**: nota nova chama som (AudioContext falso), `navigator.vibrate` falso e muda
  `document.title`; o título volta ao normal quando a aba fica visível; silêncio não chama som; gaveta agrupa e
  filtra "Não lidos"; "Marcar todos" chama `nota/todas`.
- **Mutação**: `py -3 qa.py mutate demandas/api.py --funcoes _nota,_comentar,_nota_lida,_notas_todas,marcar_atrasos,tick`
  e `demandas/avisos.py` inteiro, meta de 80% (código novo entra com a meta cheia); as contas de horário de silêncio
  são tempo, então meta de 90%.

## 9. Fases e esforço estimado

| Fase | Entrega | Esforço |
|---|---|---|
| 1 | Servidor: nota por pessoa, `lidas`, nota de comentário, destino pela tabela 6.1, teto de notas | 1,5 a 2 dias |
| 2 | Thread de fundo + `tick` (atraso a cada minuto), dividida com o estudo 01 | 0,5 a 1 dia |
| 3 | Camada 1 na tela: som, título piscando, vibração, agrupamento, gaveta nova | 1,5 dia |
| 4 | Preferências: `data/avisos.json`, rota `aviso/prefs`, tela "Meus avisos", seção Avisos em ⚙ Configurações | 1,5 a 2 dias |
| 5 | Bônus no PC principal: Notification API e Wake Lock em 127.0.0.1 | 0,5 dia |
| 6 | Camada 2 (depois da hospedagem): manifest, `/sw.js`, inscrição, VAPID, envio com `cryptography` | 3 a 4 dias |
| 7 | Opcional: ntfy ou Telegram | 1 dia cada |

Fases 1 a 5: cerca de 6 a 7 dias com os testes. Fase 6 depende do estudo 03.

## 10. Ligações com os outros estudos
- **01 backup**: mesma thread de fundo em `main()`. `data/avisos.json` entra no backup; a chave VAPID privada não
  deveria ir em backup enviado por e-mail.
- **03 continuidade e hospedagem**: HTTPS de verdade (Let's Encrypt) é o que destrava a camada 2. Em SaaS, as
  preferências e inscrições ficam por empresa. Se a central cair, push para de chegar sem ninguém perceber:
  vale um "último aviso enviado às…" na seção Avisos.
- **04 e-mail**: camada 3. Usa a mesma tabela "quem recebe o quê" e as mesmas preferências por evento; o horário
  de silêncio pode virar "resumo por e-mail ao fim do turno". O e-mail precisa do cadastro de e-mail em pessoa e
  setor, que hoje não existe.
- **05 calendário e cronograma**: se surgirem turnos e feriados, "só no meu turno" e o prazo do atraso passam a usar
  o calendário (hoje o atraso conta tempo corrido).

## 11. Mockups
Todos em `docs/estudos/mockups/`, HTML estático com o CSS do programa:

| Arquivo | O que mostra |
|---|---|
| `02-celular-avisos.html` | 3 celulares lado a lado: (a) operador com o app aberto recebendo "Nova demanda SOL-1043 de PCP · Urgente", com banner, badge, título da aba piscando e vibração indicada; (b) tela bloqueada com a notificação push da camada 2; (c) pedido de permissão em dois passos: o nosso cartão e o diálogo do navegador |
| `02-preferencias-avisos.html` | Tela "Meus avisos" do operador no celular: estado das camadas ("Avisos com o app fechado: disponível só com HTTPS"), liga/desliga por evento, som com teste, vibração, tela acesa, horário de silêncio e agrupamento |
| `02-central-avisos.html` | Gaveta do sino melhorada: filtros Todos / Não lidos / Urgentes, "Marcar todos como lidos", grupos por período e por demanda, com os avisos anteriores recolhidos |
| `02-configuracoes-avisos.html` | Seção Avisos do diálogo ⚙ Configurações: padrões da central por evento, checagem de atraso, estado do HTTPS e do push, chaves VAPID e aviso de teste |

### Fontes consultadas (28/10/2026)
- MDN, Secure contexts: https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts
- MDN, Notifications API: https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API
- MDN, Service Worker API: https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API
- MDN, Push API: https://developer.mozilla.org/en-US/docs/Web/API/Push_API
- MDN, Screen Wake Lock API: https://developer.mozilla.org/en-US/docs/Web/API/Screen_Wake_Lock_API
- MDN, Badging API: https://developer.mozilla.org/en-US/docs/Web/API/Badging_API
- MDN, Navigator.vibrate: https://developer.mozilla.org/en-US/docs/Web/API/Navigator/vibrate
- caniuse, Vibration e Wake Lock: https://caniuse.com/vibration, https://caniuse.com/wake-lock
- WebKit, Web Push for Web Apps on iOS and iPadOS: https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/
- Chrome for Developers, Autoplay policy: https://developer.chrome.com/blog/autoplay
- Chrome for Developers, Timer throttling no Chrome 88: https://developer.chrome.com/blog/timer-throttling-in-chrome-88
- web.dev, The Web Push Protocol: https://web.dev/articles/push-notifications-web-push-protocol
- web.dev, Subscribing a user: https://web.dev/articles/push-notifications-subscribing-a-user
- PyPI, pywebpush (JSON da versão 2.5.0): https://pypi.org/project/pywebpush/
- mkcert README: https://github.com/FiloSottile/mkcert
- ntfy: https://docs.ntfy.sh/
- Telegram Bot API: https://core.telegram.org/bots/api
- Meta, WhatsApp Business Platform pricing: https://developers.facebook.com/docs/whatsapp/pricing/

Não confirmados: suporte da Badging API no Chrome Android (a tabela do caniuse não carregou com versões); a flag
`unsafely-treat-insecure-origin-as-secure` no Chrome Android atual; preço do ntfy Pro; gratuidade do Telegram na
página da API (é a prática conhecida, mas a página lida não diz).
