# 04 · E-mail: avisar por e-mail quem recebe uma demanda

> Estudo e proposta. Nenhuma linha do programa muda agora. Consultas na web feitas em 28/10/2026.

## 1. Resumo

1. Dá para fazer só com a biblioteca padrão: `smtplib` (STARTTLS na 587 ou SSL na 465) e `email.message.EmailMessage`, com texto e HTML.
2. O envio sai da tela: a ação grava a demanda, depois põe o e-mail numa fila em disco (`data/email-fila.json`). Uma thread de fundo envia, com novas tentativas espaçadas e um limite.
3. Pessoa e setor ganham o campo opcional `email`, editado só pelo ADM. Registros antigos continuam valendo sem ele.
4. Começa só com "demanda criada". Os outros eventos ficam como caixinhas nas ⚙ Configurações, desligadas de início. Todos os e-mails de uma demanda formam um fio só (`[SOL-1043] título`).
5. Conta de envio recomendada: o SMTP da própria empresa ou uma caixa do Microsoft 365 / Google Workspace com domínio próprio. Gmail pessoal com senha de app serve para testar. Outlook.com pessoal não serve mais.

## 2. Como é hoje

- **Sem nada de e-mail.** Não há `smtplib`, `ssl` nem thread de fundo. `main()` só sobe o servidor e chama `serve_forever()` (`servidor.py:459-472`).
- **Ponto de disparo.** `_gravar` aplica a ação sob o LOCK e grava. Se a ação devolve uma função, ela vira o `depois` (`demandas/api.py:753-759`). Hoje só `_anexo_apagar` devolve uma (`demandas/api.py:554`). `_handle` roda o `depois` fora do LOCK, depois de gravar (`demandas/api.py:848-856`).
- **`_criar` devolve `None`** (`demandas/api.py:321-349`). Portanto, hoje a criação não tem `depois`: o gancho precisa de uma mudança em `_gravar`, não só em `_criar`.
- **Eventos.** Todo evento de negócio passa por `_evento` (`demandas/api.py:228-232`). Com mais de 500 eventos, sai o mais antigo depois do `created` (`demandas/api.py:231`, teto em `demandas/demandas_store.py:22-23`). O comentário **não** é evento: vai para `d["comentarios"]` (`demandas/api.py:485-495`).
- **Atraso.** Só é detectado quando alguém grava algo (`marcar_atrasos`, `demandas/api.py:286-297`). Um e-mail de "atrasada" sairia atrasado, até haver um timer (estudo 02).
- **Pessoa e setor sem e-mail.** O setor nasce com `{id, nome, icone, cor, ativo}` (`demandas/api.py:606`). A pessoa nasce com `{id, nome, setor, mat, ativo}` mais `sal` e `hash` (`demandas/api.py:670-672`). O banco guarda chaves extras sem apagar (`_unicos`, `demandas/demandas_store.py:76-82`; `_normaliza`, `:122-129`). Assim, um `email` novo sobrevive à leitura sem migração.
- **Vista pública.** `pessoa_publica` e `setor_publico` escolhem campo a campo o que vai para a tela (`demandas/demandas_calc.py:117-124`). A lista de pessoas vai para **todo** papel, operador também (`demandas/demandas_calc.py:161`). Um `email` só aparece se for posto ali de propósito. Isso é bom: dá para mostrar só ao ADM.
- **Modais de cadastro.** `renderSF` (`demandas/demandas.js:829-842`) e `renderUF` (`demandas/demandas.js:855-867`). As rotas `_setor_salvar` (`demandas/api.py:590-612`) e `_pessoa_salvar` (`demandas/api.py:660-686`) já exigem ADM (`_so_adm`) e já têm o controle de versão `_rev`.
- **Gaveta.** O histórico é desenhado a partir de `r.eventos` com os rótulos de `EVL` (`demandas/demandas.js:14`, `:641`, `:654`).
- **Link direto.** A tela não lê `location.hash`: um link `…/#SOL-1043` hoje só abre a tela inicial.
- **Configuração da máquina.** O "⚙ Rede" aparece só com `papel === 'maquina'` (`web/app.js:67-68`). `/api/rede` recusa quem vem da rede (`servidor.py:388-391`, `:432-441`). `data/` inteira já fica fora do Git (`.gitignore`, linha `data/`).
- **Gravação atômica pronta.** `store.atomic_write` grava `.tmp` com fsync e guarda o anterior em `.bak` (`store.py:58-68`).

## 3. Opções comparadas

### 3.1 Como disparar o envio

| Opção | Prós | Contras | Esforço |
|---|---|---|---|
| A. Enviar dentro do pedido (no `depois`) | Simples | SMTP leva de 1 a 30 s e pode travar: a tela espera. Se cair, o e-mail se perde | Baixo, mas **reprovado**: trava a tela |
| B. Thread por envio (`threading.Thread` solta) | A tela não espera | Perde o e-mail se o programa fechar; sem reenvio; sem limite de threads | Baixo |
| **C. Fila em disco + uma thread de fundo** | A tela não espera. Sobrevive a reinício. Faz reenvio com espera crescente. Um envio por vez | Um arquivo a mais e uma thread para testar | Médio |
| D. Fila dentro do `demandas.json` (outbox na mesma gravação) | Nunca perde o e-mail entre gravar e enfileirar | Cada tentativa regrava o banco inteiro e muda o `rev`: todas as telas recarregam a cada 3 s (`web/app.js:27-36`) | Médio, **reprovado** |

### 3.2 Onde registrar "e-mail enviado para X"

| Opção | Prós | Contras |
|---|---|---|
| Evento em `d["eventos"]` gravado pela thread | Aparece na gaveta sem mudar a tela | A thread teria de pegar o LOCK e regravar o banco: muda o `rev` e recarrega todas as telas. Ocupa vaga no teto de 500 e empurra eventos de negócio para fora. E-mail falho também viraria evento |
| Evento "e-mail na fila" gravado junto com a ação | Grátis: mesma gravação | Registra a intenção, não o envio. Também ocupa o teto |
| **Só no `data/email-log.json`; a gaveta do ADM junta o log ao histórico na hora de desenhar** | Não toca no banco nem no `rev`. Mostra o status real (enviado, falhou, tentando) | Com o teto do log, os envios antigos somem da gaveta. Isso é aceitável: o registro permanente fica na caixa de e-mail, que é o objetivo do dono |

### 3.3 Conta de envio (provedor)

Fontes e datas na seção 6.1.

| Provedor | Limite | Exigências | Custo | SPF/DKIM/DMARC | Chance de cair no spam |
|---|---|---|---|---|---|
| **SMTP da própria empresa** (hospedagem do site, Locaweb, servidor interno) | O da hospedagem; costuma ser de centenas por hora | Usuário e senha. Às vezes só sai de dentro da rede | Já pago | Já costuma estar no domínio; conferir com o TI | Baixa, se o domínio tem SPF e DKIM |
| **Microsoft 365 / Exchange Online** | 10.000 destinatários por dia, 30 mensagens por minuto (fontes secundárias) | SMTP AUTH ligado na caixa. Autenticação básica sem mudança até dez/2026; a partir de então vem desligada por padrão, mas o admin pode religar. Data final só será anunciada no 2º semestre de 2027. Caminho duradouro: OAuth2 | Licença de uma caixa (já existente ou uma de serviço) | Domínio próprio já configurado no M365 | Baixa |
| **Google Workspace** | 2.000 mensagens por dia; até 100 destinatários por mensagem via SMTP | Senha de app (exige verificação em 2 etapas). Senha comum não funciona desde 14/03/2025 | Licença de uma caixa | SPF/DKIM configurados no Admin | Baixa |
| **Gmail pessoal com senha de app** | 500 por dia (fontes divergem para SMTP) | Verificação em 2 etapas + senha de app | Grátis | Remetente `@gmail.com`; não dá para alinhar ao domínio da empresa | Média: e-mail de empresa vindo de conta pessoal. Serve para **teste** |
| **Outlook.com / Hotmail pessoal** | — | Autenticação básica desligada desde 16/09/2024. Só OAuth2 com app registrado; relatos de que a senha de app também é recusada | Grátis | — | **Não recomendado**: inviável sem OAuth2 |
| **Amazon SES** | Sandbox: 200 por dia, só para endereços verificados. Produção: pedido revisado por humano | Conta AWS, domínio verificado, credencial SMTP própria | US$ 0,10 por 1.000 (avulso); planos novos desde jul/2026 (fontes secundárias) | DKIM fácil (Easy DKIM); SPF/DMARC no DNS | Baixa, com domínio próprio |
| **Brevo** | Grátis: 300 por dia | Conta, remetente verificado, chave SMTP | Grátis até 300 por dia | Autenticar o domínio no DNS | Baixa a média |
| **Mailgun** | Grátis: 100 por dia | Conta, domínio verificado | Grátis; pagos a partir de cerca de US$ 35/mês (não confirmado no site oficial) | Exige registros DNS | Baixa |
| **Resend** | Grátis: 3.000 por mês, 100 por dia, 1 domínio | Conta, domínio verificado | Grátis; Pro US$ 20/mês | Exige registros DNS | Baixa |

Volume esperado numa fábrica: dezenas de demandas por dia, na casa de 20 a 200 e-mails. Todos os provedores acima dão conta, exceto o Outlook.com pessoal.

## 4. Recomendação e por quê

- **Disparo: opção C (fila em disco + uma thread).** É a única que cumpre "nunca travar a tela" e não perde o e-mail num reinício.
- **Registro: log próprio, sem evento novo no banco.** Não gasta o teto de 500 eventos, não muda o `rev` nem recarrega as telas, e mostra o status real. A gaveta do ADM ganha linhas "✉ e-mail enviado para joao@…" vindas do log.
- **Eventos:** "criada" ligado. "Aceita", "concluída", "cobrada", "atrasada", "comentário" e "cancelada" ficam como opção, desligadas. Cópia para o solicitante: opcional, desligada. Na fábrica o solicitante quase sempre é outro operador sem e-mail próprio.
- **Conta:** primeiro, perguntar ao TI se há SMTP da empresa ou uma caixa de serviço no M365 ou no Workspace (`demandas@empresa`). Se for M365, já planejar o OAuth2 por credencial de aplicativo (seção 5.8), porque a senha simples pode vir desligada a partir de dez/2026. Para testar hoje: Gmail pessoal com senha de app.
- **Senha:** em `data/email.json`, cifrada com DPAPI do Windows quando der. Nunca volta para a tela.

## 5. Como encaixa no código atual

### 5.1 Fluxo

```
tela ──POST demanda/criar──► _handle ─► LOCK ─► _gravar ─► _criar ─► _evento("created")  ← anota em _EVS
                                                       └─► ds.commit(doc)  (gravou)
                                                       └─► monta os envios a partir de _EVS (ainda sob o LOCK, lê doc)
                                      ◄── fora do LOCK: depois() = email.enfileirar(envios)  (só grava a fila, ~ms)
                                      ◄── resposta para a tela
thread "email" (daemon, criada em main()) ─► acorda (Event ou a cada 30 s) ─► pega o próximo vencido ─► SMTP ─► log
```

### 5.2 Arquivos e funções que mudariam

| Arquivo | Mudança |
|---|---|
| `email_envio.py` (novo, raiz, ao lado de `store.py`) | `config()`, `salvar_config()`, `enfileirar(envios)`, `montar(envio, cfg) -> EmailMessage`, `enviar_um(msg, cfg)`, `trabalhador()`, `estado()` (pendentes, falhas, últimos do log), `teste(para)`. Lock próprio `FILA_LOCK`, separado do LOCK do banco. DPAPI em `_protege` e `_desprotege` via `ctypes` |
| `servidor.py` | Em `main()`, entre `api_mod()` e `serve_forever()` (`servidor.py:463-472`): `threading.Thread(target=email_envio.trabalhador, daemon=True).start()`. Rotas `GET/POST /api/email` e `POST /api/email/teste`, só na própria máquina, no mesmo molde de `/api/rede` (`servidor.py:388-391`, `:432-441`) |
| `demandas/api.py` | `_evento` também anota `(d["id"], ev)` numa lista `_EVS` (como `_RV`, só muda sob o LOCK). `_comentar` anota `"comment"`. `_gravar` zera `_EVS` no começo. Depois do `ds.commit`, monta os envios (destinatários, título, prazo) e junta à função `depois` que a ação já devolver (`_anexo_apagar`). `_setor_salvar` e `_pessoa_salvar` aceitam `email` |
| `demandas/demandas_calc.py` | `pessoa_publica` e `setor_publico` ganham `email` **só para o ADM** (parâmetro `adm=True` vindo de `vista` com `pessoa is None`) |
| `demandas/demandas.js` | Campo e-mail em `renderSF` e `renderUF` e no envio dos dois. Na gaveta do ADM, as linhas `✉` do log entram no histórico. Abrir `#SOL-n` ao carregar |
| `web/index.html`, `web/app.js` | Seção "E-mail" do diálogo ⚙ Configurações (estudo comum aos temas 01-05) |
| `demandas/CONTRATO.md`, `README.md` | Campo `email`, arquivos novos, como configurar |

Por que `email_envio.py` fica na raiz e não em `demandas/`: a configuração é da máquina, como `rede.json`. A thread vive no `servidor.py`. O módulo `demandas/` só gera os envios.

### 5.3 Formato dos dados

**`data/email.json`** (fora do Git, já coberto por `data/`):

```json
{
  "v": 1,
  "ligado": true,
  "host": "smtp.empresa.com.br",
  "porta": 587,
  "seguranca": "starttls",
  "usuario": "demandas@empresa.com.br",
  "senha": {"dpapi": "AQAAANCMnd8BFdERjHoAwE/Cl+sBAAAA..."},
  "remetente": "Central de demandas <demandas@empresa.com.br>",
  "dominio_msgid": "empresa.com.br",
  "instalacao": "k7f3q9",
  "link_base": "http://192.168.0.10:8090/",
  "eventos": {"created": true, "started": false, "done": false, "nudge": false,
              "late": false, "comment": false, "canc": false},
  "copia_solicitante": false,
  "fila_setor": "setor_ou_pessoas"
}
```

- `seguranca`: `"starttls"` (587), `"ssl"` (465) ou `"nenhuma"` (só para relé interno na rede local, com aviso na tela).
- `senha`: `{"dpapi": base64}` no Windows. `{"texto": "..."}` só se o DPAPI falhar, com aviso na tela.
- `instalacao`: 6 letras sorteadas na primeira configuração. Evita que dois `SOL-1043` de instalações diferentes tenham o mesmo `Message-ID` (seção 5.6).

**`data/email-fila.json`**:

```json
{
  "v": 1,
  "itens": [
    {"id": "e1a2b3", "dem": "SOL-1043", "ev": "created", "para": ["joao.pereira@empresa.com.br"],
     "cc": [], "dados": {"titulo": "Corrigir solda do quadro da carreta 12", "de": "MONTAGEM · Carlos Souza",
     "para": "SOLDA · João Pereira", "prio": "Alta", "prazo": 1761674400000, "motivo": "Defeito de qualidade",
     "desc": "Trinca no cordão…", "quem": "Carlos Souza"},
     "criado": 1761660000000, "tent": 0, "prox": 1761660000000, "erro": ""}
  ]
}
```

O texto do e-mail é montado com `dados`, uma foto da demanda tirada sob o LOCK. A thread nunca lê o `demandas.json`, então não precisa do LOCK do banco.

**`data/email-log.json`** (teto de 2.000; saem os mais antigos):

```json
{"v": 1, "itens": [
  {"t": 1761660004000, "dem": "SOL-1043", "ev": "created", "para": ["joao.pereira@empresa.com.br"],
   "status": "ok", "tent": 1, "erro": ""},
  {"t": 1761650000000, "dem": "SOL-1039", "ev": "created", "para": ["pintura@empresa.com.br"],
   "status": "falhou", "tent": 6, "erro": "535 5.7.3 Authentication unsuccessful"}
]}
```

O erro é guardado só como o código e a frase do servidor SMTP, cortado em 200 caracteres. Nunca guarda senha nem a conversa SMTP.

**Pessoa e setor** no `demandas.json`: campo opcional novo.

```json
{"id": "p7", "nome": "João Pereira", "setor": "SOL", "mat": "M107", "ativo": true, "email": "joao.pereira@empresa.com.br"}
{"id": "SOL", "nome": "Solda", "icone": "🔩", "cor": "#E4572E", "ativo": true, "email": "solda@empresa.com.br"}
```

### 5.4 Reenvio e limites

- Uma mensagem por vez, uma conexão SMTP por rodada, `timeout=20` s.
- Espera entre tentativas: 1 min, 5 min, 15 min, 1 h, 3 h. Na 6ª falha, sai da fila e vai para o log como `falhou`.
- Erro permanente (5xx de destinatário inválido, por exemplo `550`) falha na hora, sem nova tentativa. Erro de autenticação (`535`) **pausa a fila inteira** e mostra o aviso nas Configurações: insistir com a senha errada pode bloquear a conta.
- Teto da fila: 500 itens. Acima disso, o mais antigo vai para o log como `descartado`, com aviso.
- Ritmo: no máximo 20 mensagens por minuto, abaixo dos 30 por minuto do M365.
- E-mail desligado ou sem configuração: `enfileirar` não grava nada. Não acumula fila "para depois".
- Ao ligar o programa, a thread lê a fila e continua de onde parou.
- Janela de perda: se o programa cair entre o `ds.commit` e a gravação da fila (milissegundos), aquele e-mail não sai. Para um aviso, é aceitável; a demanda em si está gravada.

### 5.5 Destinatário

| Caso | Para quem vai |
|---|---|
| `para.p` definido e a pessoa tem `email` | A pessoa |
| `para.p` definido, a pessoa sem `email` | O `email` do setor, se houver; se não, ninguém (log: "sem destinatário") |
| `para.p = null` (fila do setor) | `fila_setor = "setor_ou_pessoas"` (padrão): o e-mail do setor; sem ele, todas as pessoas **ativas** do setor que têm e-mail, em `Para`, no máximo 20. Opção `"so_setor"`: só o e-mail do setor |
| Cópia para o solicitante (opcional) | `Cc` para `de.p`, se tiver e-mail. Pedido feito pelo Escritório (`de.p = null`): ninguém |
| Eventos que interessam ao solicitante (aceita, concluída) | Vão para o solicitante (`de.p`, ou o e-mail do setor de origem). Cobrada, atrasada, comentário e cancelada vão para o responsável |

Validação do campo `email` (servidor, em `_setor_salvar` e `_pessoa_salvar`):
- opcional: vazio ou ausente vira "sem e-mail" (a chave é removida);
- até 254 caracteres, sem espaço nem quebra de linha, uma `@` só, com algo antes e um domínio com ponto depois. Regex simples: `^[^@\s,;<>"]{1,64}@[A-Za-z0-9.-]{1,252}\.[A-Za-z]{2,}$`;
- guardado em minúsculas;
- sem `\r` ou `\n`: isso também bloqueia injeção de cabeçalho. `EmailMessage` já recusa quebra de linha em cabeçalho, mas a validação vem antes;
- e-mail repetido entre pessoas é permitido (duas pessoas podem dividir a caixa do setor).

Quem edita: só o ADM. As duas rotas já chamam `_so_adm` e o operador nem alcança essas rotas (`servidor.py:64`). O operador não vê e-mail de ninguém: `pessoa_publica` só inclui o campo para o ADM.

Compatibilidade: registros sem `email` continuam válidos. `_normaliza` preserva a chave. O `v` do banco **não** muda. Uma versão antiga do programa lendo um banco novo mantém o campo (o `_unicos` copia o dict inteiro), só não o usa.

### 5.6 Um fio por demanda

- 1º e-mail da demanda: `Message-ID: <SOL-1043.k7f3q9@empresa.com.br>`. Ele é fixo e calculável, então não precisa ser guardado.
- E-mails seguintes: `Message-ID` próprio e único, `<SOL-1043.e5.k7f3q9@empresa.com.br>` (5 = número do envio). Mais `In-Reply-To: <SOL-1043.k7f3q9@…>` e `References: <SOL-1043.k7f3q9@…>`.
- Assunto sempre `[SOL-1043] título`, idêntico em todos os e-mails do fio. Nada de "· concluída" no assunto: o evento vai na primeira linha do corpo. Hoje nenhuma rota muda o título depois de criado, então o assunto fica estável.
- **Gmail:** a documentação da API do Gmail pede, para pôr uma mensagem num fio, "References e In-Reply-To conforme a RFC 2822" **e** "os assuntos precisam ser iguais" (developers.google.com/workspace/gmail/api/guides/threads, consultado em 28/10/2026). Ela fala da API, mas é o mesmo critério observado na caixa. Por isso: assunto idêntico + References.
- **Outlook:** agrupa a "conversa" pelo assunto sem prefixos e pelos cabeçalhos de resposta. Não achei documentação oficial atual do critério exato: **não confirmado**. Assunto idêntico + References é o que funciona nos dois.
- **Cuidado:** nunca repetir um `Message-ID`. O Gmail descarta como duplicada uma mensagem com `Message-ID` já visto. Por isso o sufixo `instalacao` e o número do envio.
- Se o 1º e-mail falhou, os seguintes ainda apontam para ele. O cliente agrupa pelo assunto, e nada quebra.

### 5.7 Conteúdo

- `EmailMessage` com `set_content(texto)` e `add_alternative(html, subtype="html")`. O cliente que não mostra HTML vê o texto.
- HTML simples, com estilo **inline** em tabela de 600 px. Clientes de e-mail ignoram `<style>` e CSS externo. Sem imagem externa (o Outlook bloqueia e conta como rastreador) e sem fonte da web.
- O que vai: a linha do evento ("Nova demanda para o seu setor"), título, `de → para` (setor e pessoa), prioridade, prazo (data e hora), motivo, tipo e descrição curta (até 400 caracteres, com "…").
- Botão "Abrir a demanda" → `link_base + "#SOL-1043"`. **Limite atual:** o link só funciona **dentro da rede da fábrica** e com o acesso pela rede ligado. Pelo celular na rede 4G ou em casa, ele não abre, até haver hospedagem (estudo 03). O e-mail diz isso em letra pequena. Também vai exigir o PIN e o "Quem é você?". A tela hoje não abre a demanda pelo `#`: é uma mudança pequena em `boot()`.
- Sem anexos, por padrão. Fotos da demanda ficam no sistema.
- Escape: título, descrição, motivo e nomes passam por `html.escape(texto, quote=True)` no HTML. No texto simples vão como estão. O assunto passa pelo `EmailMessage`, que codifica o UTF-8 (RFC 2047) e recusa quebra de linha.
- Cabeçalhos: `From` (remetente configurado), `To`, `Cc`, `Subject`, `Date` (`email.utils.formatdate(localtime=True)`), `Message-ID`, `In-Reply-To`, `References`, `Auto-Submitted: auto-generated` (RFC 3834, evita resposta automática de férias em laço) e `X-Central-Demanda: SOL-1043`.
- Rodapé: "E-mail automático da Central de demandas. Para não receber mais, peça ao escritório para tirar seu e-mail do cadastro."

### 5.8 OAuth2 sem biblioteca externa

- **SMTP com XOAUTH2:** cabe na stdlib. `smtp.auth("XOAUTH2", lambda _=None: "user=%s\x01auth=Bearer %s\x01\x01" % (usuario, token))`. O `smtplib` faz o base64. O formato está na documentação da Microsoft (seção 6.1).
- **Microsoft 365, credencial de aplicativo (client credentials):** viável só com `urllib` + `json`. É um `POST` em `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token` com `client_id`, `client_secret`, `scope=https://outlook.office365.com/.default` e `grant_type=client_credentials`. O token dura cerca de 1 h; a thread renova antes. A preparação exige o admin do M365: registrar o app no Entra, dar a permissão `SMTP.SendAsApp`, dar o consentimento, rodar `New-ServicePrincipal` e `Add-MailboxPermission` no PowerShell do Exchange. Esforço do nosso lado: médio. Esforço do TI: médio.
- **Google:** o "service account" com delegação de domínio exige assinar um JWT com RSA (RS256). Não há RSA na stdlib, então ficaria fora sem biblioteca externa. O fluxo de usuário (código de autorização + refresh token) daria com `urllib`, mas pede um app no Google Cloud e uma tela de consentimento. Para o Google, a **senha de app** resolve hoje e é a recomendação.
- **Conclusão:** fase 1 só com usuário e senha (ou senha de app). Fase 3, se a conta for M365: OAuth2 por credencial de aplicativo, sem biblioteca externa.

### 5.9 Senha SMTP

- Guardada em `data/email.json`, que já fica fora do Git.
- **DPAPI do Windows via `ctypes`:** `crypt32.CryptProtectData` e `CryptUnprotectData`, com `DATA_BLOB`, mais `LocalFree` no buffer devolvido. Cerca de 40 linhas. A senha fica presa ao **usuário do Windows** que roda o programa: copiar o arquivo para outro PC não revela a senha. Se o programa passar a rodar com outro usuário, como serviço ou no Linux (hospedagem), a senha precisa ser digitada de novo. A tela detecta e avisa "senha precisa ser digitada de novo".
- Fora do Windows (CI, testes): cai para `{"texto": ...}` com aviso. Os testes simulam o `ctypes`.
- **Nunca devolve a senha para a tela.** `GET /api/email` responde `"senha": true/false` (tem ou não tem). No `POST`, senha ausente ou `null` mantém a atual, `""` apaga e texto novo substitui. O campo aparece como `••••••••` com o texto "guardada — digite para trocar".
- Nada de senha em log, em `print` ou na mensagem de erro. `smtplib.set_debuglevel` fica desligado.
- **"Enviar teste":** `POST /api/email/teste {"para": "..."}`. Esse envio roda **na hora**, numa thread, com `timeout` de 20 s, e devolve o resultado traduzido ("Conectou, mas o usuário ou a senha foram recusados (535)"). Só a máquina pode usar. Permite testar com a senha digitada antes de salvar.

### 5.10 Rotas e quem pode usar

| Rota | Quem | O que faz |
|---|---|---|
| `GET /api/email` | só a máquina (`_remote()` falso) | Configuração sem a senha, estado da fila (pendentes, falhas, pausada) e os últimos 20 do log |
| `POST /api/email` | só a máquina | Salva a configuração (validada) |
| `POST /api/email/teste` | só a máquina | Envia o teste agora |
| `POST /api/email/fila` | só a máquina | `{"acao": "retomar" \| "reenviar_falhas" \| "limpar_falhas"}` |
| `POST /api/local/demandas/setor/salvar`, `pessoa/salvar` | ADM (máquina ou PIN do escritório) | Campo `email` opcional |
| `vista` | ADM | Recebe `email` de pessoas e setores e `emails: {"SOL-1043": [{t, para, status}]}` só das demandas da vista, para a gaveta |

Por que só a máquina configura: é a regra do "⚙ Rede" e a senha da conta é da empresa. O ADM pela rede pode cadastrar e-mails de pessoas, mas não ver nem trocar a conta de envio.

## 6. Riscos e segurança

- **Travar a tela:** resolvido pela fila. O `depois` só grava um arquivo pequeno. O SMTP roda apenas na thread.
- **Thread morta em silêncio:** o laço inteiro fica em `try/except Exception`, registra o erro no log e continua. `estado()` mostra "última rodada há X min". Se passar de 5 min, a tela de Configurações avisa.
- **Concorrência:** `FILA_LOCK` próprio protege fila e log. A thread nunca pega o LOCK do banco. O `depois` roda fora do LOCK do banco: não há como dois locks se cruzarem.
- **Injeção de cabeçalho:** os campos de e-mail são validados, sem `\r\n`, e o `EmailMessage` recusa quebra de linha. O título vai no assunto codificado.
- **HTML no e-mail:** tudo que vem do usuário passa por `html.escape`. Nenhum link além do `link_base` configurado na máquina.
- **TLS:** `ssl.create_default_context()` (confere o certificado e o nome). `"nenhuma"` só com aviso vermelho e apenas para IP da rede local.
- **Vazamento de senha:** DPAPI, nunca na resposta, nunca em log. O arquivo fica em `data/`, fora do Git.
- **Bloqueio da conta:** erro 535 pausa a fila. Respeitar os 20 por minuto.
- **Spam e reputação:** remetente com domínio da empresa, SPF e DKIM do provedor. O volume fica bem abaixo do limite de 5.000 por dia do Gmail para "remetente em massa", que exige DMARC.
- **Laço de resposta automática:** `Auto-Submitted: auto-generated`. Opcionalmente `Reply-To` para uma caixa humana (o escritório).
- **Destinatário errado:** e-mail digitado errado vai para um desconhecido. Por isso só o ADM edita, com o "Enviar teste" e o log visível.
- **LGPD (Lei 13.709/2018):**
  - **Dado pessoal:** e-mail corporativo nominal (`joao.pereira@`) é dado pessoal. O e-mail do setor (`solda@`) em geral não é.
  - **Base legal:** execução de contrato de trabalho e legítimo interesse do empregador em comunicar tarefas do próprio trabalho (art. 7º, V e IX). Não precisa de consentimento. Precisa de transparência: avisar as pessoas que receberão e-mails da Central.
  - **Minimização:** só o e-mail, e nada de telefone. O operador não vê e-mail de ninguém.
  - **Opt-out:** o ADM apaga o e-mail da pessoa. O rodapé do e-mail diz como pedir. Desligar os eventos opcionais é geral, nas Configurações.
  - **Sem dado sensível:** o e-mail leva só o que a demanda tem. Recomendar no cadastro que a descrição não traga dado de saúde (atestado, acidente com nome), porque ela vai para fora do sistema. A descrição vai cortada em 400 caracteres e a opção "não mandar a descrição" fica disponível.
  - **Operador de dados:** o provedor de e-mail (Microsoft, Google, Brevo) passa a tratar esses dados. Usar a conta da empresa, que já tem contrato.
  - **Retenção:** o log tem teto de 2.000 e guarda só endereço, demanda e status. Uma pessoa excluída continua nos e-mails já enviados, na caixa do destinatário.

### 6.1 Fontes externas (consultadas em 28/10/2026)

- Microsoft Message Center **MC786329**, "Exchange Online to retire Basic Auth for Client Submission (SMTP AUTH)", versão de 27/01/2026: sem mudança até dez/2026; desligado por padrão no fim de dez/2026 com opção de religar; tenants novos sem básico; data final anunciada no 2º semestre de 2027. https://mc.merill.net/message/MC786329 . Avisos anteriores (março a abril de 2026, p. ex. Univ. de Toronto, jul. e dez. de 2025) estão superados.
- Microsoft Learn, "Authenticate an IMAP, POP or SMTP connection using OAuth" (atualizada em 17/10/2025): XOAUTH2, `SMTP.SendAsApp`, client credentials, `New-ServicePrincipal`. https://learn.microsoft.com/en-us/exchange/client-developer/legacy-protocols/how-to-authenticate-an-imap-pop-smtp-application-by-using-oauth
- Google Workspace, "Transition from less secure apps to OAuth": desde 14/03/2025, SMTP, IMAP e POP sem senha comum; senha de app ainda é aceita. https://knowledge.workspace.google.com/admin/sync/transition-from-less-secure-apps-to-oauth
- Google Workspace, "Gmail sending limits in Google Workspace": 2.000 por dia, janela móvel de 24 h. https://knowledge.workspace.google.com/admin/gmail/gmail-sending-limits-in-google-workspace
- Gmail pessoal 500 por dia e M365 10.000 destinatários por dia e 30 por minuto: fontes secundárias (smtp2go.com e warmy.io). Não conferi a página oficial da Microsoft.
- Outlook.com pessoal: Microsoft Support, "Outlook and other apps are unable to connect to Outlook.com when using Basic authentication", e Neowin sobre 16/09/2024. Que a senha de app também é recusada vem de relato de fornecedor (BlueMail) e da Microsoft Q&A, **não confirmado** oficialmente.
- Google, "Email sender guidelines": SPF ou DKIM para todos; SPF, DKIM e DMARC acima de 5.000 por dia desde 01/02/2024. https://support.google.com/a/answer/81126
- Gmail API, "Managing threads": assunto igual + References/In-Reply-To. https://developers.google.com/workspace/gmail/api/guides/threads
- Amazon SES: US$ 0,10 por 1.000 e sandbox de 200 por dia (fontes secundárias, usecarly.com e smtpedia.com); planos novos em jul/2026, não confirmados no site da AWS.
- Brevo 300 por dia, Resend 3.000 por mês e 100 por dia, Mailgun 100 por dia: fontes secundárias (sendlayer.com e wpmailsmtp.com, 2026). Conferir nos sites antes de contratar.

## 7. Testes que a implementação vai exigir

Pela regra de `docs/QUALIDADE.md`. `email_envio.py` entra no **escopo crítico** (meta de 80% de cobertura e de mutação): mexe com senha e com a thread.

**Unitários (`tests/test_email_envio.py`)**
- `montar`:
  - assunto `[SOL-1043] título`;
  - `Message-ID` fixo no `created` e único nos seguintes;
  - `In-Reply-To` e `References` presentes;
  - texto e HTML presentes;
  - `<script>`, `&` e aspas no título saem escapados no HTML;
  - descrição cortada em 400 caracteres;
  - título de 140 caracteres;
  - acento no assunto (RFC 2047);
  - `Auto-Submitted` presente.
- Validação de e-mail:
  - válidos;
  - vazio vira "sem e-mail";
  - 254 e 255 caracteres;
  - sem `@`, com duas `@`;
  - com espaço, `\r\n`, `,` ou `;`;
  - maiúsculas viram minúsculas;
  - tipo errado (número, lista).
- Destinatário:
  - pessoa com e-mail;
  - pessoa sem e-mail com setor com e-mail;
  - fila do setor com e-mail do setor;
  - fila sem e-mail do setor (pessoas ativas, inativa fica fora, teto de 20);
  - `so_setor`;
  - cópia ao solicitante com `de.p` e com o Escritório;
  - ninguém (vai para o log).
- Reenvio:
  - espera de 1, 5, 15, 60 e 180 min;
  - a 6ª falha vai para o log;
  - 550 falha na hora;
  - 535 pausa a fila;
  - timeout conta como temporário;
  - teto de 500 da fila;
  - teto de 2.000 do log.
- Configuração:
  - a senha nunca aparece no `estado()` nem no `GET`;
  - `null` mantém, `""` apaga, texto troca;
  - porta fora de 1–65535;
  - `seguranca` inválida;
  - remetente inválido.
- DPAPI: `ctypes` simulado, ida e volta; falha cai para `texto` com aviso; blob corrompido pede a senha de novo.
- `enviar_um` com `smtplib.SMTP` simulado:
  - STARTTLS na 587, SSL na 465;
  - `login` chamado com usuário e senha;
  - XOAUTH2 com o formato exato;
  - `quit` mesmo com erro.

**Integração**
- `tests/test_api_email.py`:
  - `demanda/criar` com e-mail ligado põe 1 item na fila **depois** do commit;
  - ação que falha (400) não enfileira;
  - `comentar` só enfileira com `comment` ligado;
  - `marcar_atrasos` dentro de outra ação gera `late` se ligado;
  - a resposta da tela não espera o SMTP (servidor SMTP falso que dorme 5 s; a criação volta em menos de 1 s).
- Servidor SMTP falso local:
  - uma thread com `socketserver` que fala o mínimo de SMTP numa porta livre, nunca a 8090;
  - fluxo completo: criar, a fila, a thread, a mensagem recebida, o log `ok`;
  - reinício do programa com item pendente continua o envio.
- `servidor.py`: `/api/email` vindo da rede devolve 403; com papel `completo` também 403 (só a máquina); `GET` sem `senha`.
- Compatibilidade: `demandas.json` antigo sem `email` carrega e grava igual; pessoa com `email` sobrevive a `load` e `commit`; `vista` de operador **sem** `email` de ninguém.

**jsdom (`tests/demandas_check.js`)**
- `renderUF` e `renderSF` mostram o campo; e-mail inválido mostra `dm-em`; salvar manda `email`.
- A gaveta do ADM mostra a linha `✉`; a do operador não.
- A seção E-mail das Configurações: senha mascarada, botão de teste, contadores da fila.
- Abrir `#SOL-1043` abre a gaveta.

**Mutação**
- `py -3 qa.py mutate email_envio.py` e as funções mexidas em `demandas/api.py` (`_evento`, `_gravar`, `_comentar`, `_setor_salvar`, `_pessoa_salvar`) e em `demandas_calc.py` (`pessoa_publica`, `setor_publico`). Meta de 80%, com atenção a: limites da espera e do teto, a condição "só depois do commit", o "só ADM vê e-mail" e o 535 que pausa.

## 8. Fases e esforço estimado

| Fase | Entrega | Esforço |
|---|---|---|
| 1 | Campo `email` em pessoa e setor (API, tela, validação, vista só do ADM) | 0,5 dia + testes |
| 2 | `email_envio.py`: config, DPAPI, montar, enviar, fila, thread, log; gancho em `_evento` e `_gravar`; só o evento "criada" | 2 dias + 1 dia de testes e mutação |
| 3 | Seção E-mail das ⚙ Configurações (com o diálogo comum), "Enviar teste", estado da fila, log | 1 dia + testes jsdom |
| 4 | Eventos opcionais, cópia ao solicitante, linhas `✉` na gaveta, abrir `#SOL-n` | 1 dia |
| 5 (se M365) | OAuth2 por credencial de aplicativo com `urllib` | 1 dia + apoio do TI |

Total: cerca de 6 a 7 dias, com testes.

## 9. Ligações com os outros estudos

- **01 backup:** `email.json`, `email-fila.json` e `email-log.json` entram no backup. A senha cifrada com DPAPI **não** abre em outro PC: o backup restaurado em outra máquina pede a senha de novo. Avisar isso no backup.
- **02 avisos:** e-mail é mais um canal do mesmo gancho (`_EVS` em `_evento`). O ideal é um só "despachante" de eventos para avisos na tela, som e e-mail. O timer de atraso do 02 é o que permite um e-mail de "atrasada" na hora certa. A mesma thread de fundo pode servir aos dois.
- **03 continuidade e hospedagem:**
  - com hospedagem, o link do e-mail passa a abrir de qualquer lugar;
  - o DPAPI deixa de existir no Linux, e a senha passaria para uma variável de ambiente ou um cofre do provedor;
  - no SaaS, cada empresa tem a sua conta de envio e o `instalacao` vira o id da empresa;
  - um provedor transacional (SES, Brevo) com domínio do SaaS fica mais simples que uma conta por cliente.
- **05 calendário e cronograma:** o prazo no e-mail usa o mesmo cálculo (`calc.prazo`). Se o 05 introduzir turnos e feriados, o e-mail mostra o prazo novo sem mudança aqui. Um anexo `.ics` com o prazo é possível no futuro, mas fica fora do padrão "sem anexos".

## 10. Mockups

| Arquivo | O que mostra |
|---|---|
| `mockups/04-email-recebido.html` | Cliente de e-mail genérico (visual neutro). À esquerda, a caixa de entrada com o fio "[SOL-1043] …" agrupando 3 mensagens: criada → aceita → concluída. À direita, o e-mail da demanda nova SOL-1043 aberto, com o HTML proposto (inline), o aviso de "só na rede da fábrica" e os cabeçalhos do fio |
| `mockups/04-configuracoes-email.html` | Diálogo ⚙ Configurações com a seção E-mail ativa: servidor, porta, segurança, usuário, senha mascarada, remetente; eventos que enviam; destinatário da fila do setor; "Enviar teste para…"; estado da fila (0 pendentes, 2 falhas); registro dos últimos envios com status |
| `mockups/04-cadastro-email.html` | Modais reais de "Editar usuário" e "Editar setor" da Administração com o campo e-mail novo (um deles com erro de validação). E a gaveta da SOL-1043 com "✉ e-mail enviado para joao.pereira@…" no histórico |
