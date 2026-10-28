# Estudo 03 · Continuidade (quando o PC servidor desliga) e hospedagem futura

Estudo e mockup. Nenhuma linha do programa muda agora. Consultas externas feitas em 28/10/2026.

## 1. Resumo

1. **Agora (fase 0, local robusto):** no-break para o PC **e para o roteador**, PC sem suspensão, servidor como
   tarefa agendada "ao iniciar o sistema" com laço de reinício, faixa "Sem conexão com a central" nos aparelhos,
   rascunho que não se perde e sessão da pessoa que sobrevive ao reinício.
2. **Já na fase 0, sem custo de hospedagem:** pôr o armazenamento atrás de uma interface e passar um `tenant`
   implícito ("padrão") por dentro. É o que evita reescrever tudo depois.
3. **Hospedado (empresa única):** VPS pequena (US$ 4 a 7 por mês) com Caddy na frente. Antes disso, o código
   **precisa** deixar de tratar loopback como "máquina", senão todo visitante vira administrador.
4. **SaaS:** um SQLite por empresa (stdlib `sqlite3`), resolvido pelo subdomínio. Postgres só quando houver mais
   de um servidor de aplicação.
5. Decisão do dono que mais muda o roteiro: empresa única ou várias. O roteiro abaixo serve para as duas.

## 2. Como é hoje

### Ligar e desligar
- `iniciar.bat` acha o Python (`iniciar.bat:7-18`), abre o navegador (`iniciar.bat:21`), roda `servidor.py`
  em primeiro plano (`iniciar.bat:22`) e para em `pause` (`iniciar.bat:25`). Fechar a janela preta desliga tudo.
  Não há início com o Windows nem reinício se o processo cair.
- Se alguém abrir o `iniciar.bat` com o servidor já ligado, o segundo processo falha com
  "Já existe um servidor na porta" (`servidor.py:464-468`, porta exclusiva em `servidor.py:453-456`), mas o
  navegador já foi aberto antes (`iniciar.bat:21`). Funciona, mas assusta.
- O `py` da linha `iniciar.bat:9` costuma ser instalado por usuário. Como serviço (conta SYSTEM) ele pode não
  estar no PATH: o serviço precisa do caminho absoluto do `python.exe`.

### O que os aparelhos veem quando o servidor some
- A casca pergunta `/api/rev` a cada 3 s (`web/app.js:27-36,72-73`). Se falhar, o `catch` vazio só espera o
  próximo ciclo (`web/app.js:35`). **Nada aparece na tela.** A pessoa continua vendo dados velhos como se fossem
  atuais.
- Ao clicar numa ação, `api()` troca o erro de rede por "O servidor está desligado. Abra o iniciar.bat e tente de
  novo." (`web/app.js:14`). No módulo, `call()` mostra só um toast de 2,6 s (`demandas/demandas.js:152-170`).
- **O `tk` da pessoa vive só na memória do servidor** (`demandas/api.py:4`, `demandas/api.py:147-157`) e só na
  memória da página (`demandas/demandas.js:25`). Se o servidor reinicia, toda pessoa recebe 401 na próxima
  ação; `call()` chama `lost()` (`demandas/demandas.js:165`), que chama `closeModal()`
  (`demandas/demandas.js:320-325`), e `closeModal()` zera `D.form` (`demandas/demandas.js:708-713`).
  **Resultado: quem estava escrevendo uma solicitação perde o texto** no momento em que o servidor volta.
- Se a resposta de `demanda/criar` se perder (rede caiu depois de gravar), não há chave de idempotência. Reenviar
  cria uma solicitação duplicada (`demandas/demandas.js:797`, `demandas/api.py:848-856`).

### Pontos que importam para hospedar
- Papel `maquina` = qualquer cliente de loopback, sem PIN (`servidor.py:273-285`).
- Host aceito: `127.0.0.1:porta`, `localhost:porta` ou IPv4 literal com a rede ligada
  (`servidor.py:236-242`, `servidor.py:261-271`). Nome como `central.local` ou domínio é recusado com 421.
- Origin aceito só com `http://` (`servidor.py:412-415`).
- Cookie `HttpOnly; SameSite=Strict`, sem `Secure` (`servidor.py:426`).
- Bloqueio de PIN por IP do socket: 5 erros = 5 min (`servidor.py:198-213`). Teto de 200 sessões, a mais antiga
  sai (`servidor.py:217-218`).
- `/api/rede` devolve os dois PINs a quem for `maquina` (`servidor.py:371-375`, `servidor.py:388-391`).
- Bind em `0.0.0.0` ou `127.0.0.1` (`servidor.py:465`). Sem TLS. Sem log de acesso (`servidor.py:250-251`).
- Texto da tela de PIN: "Digite o PIN mostrado no computador principal, em ⚙ Rede" (`servidor.py:54`).

### Dados
- Pasta de dados única, escolhida por variável de ambiente para o processo todo (`store.py:42-45`).
- Cada ação reescreve o `demandas.json` inteiro com fsync e `.bak` (`store.py:83-93`,
  `demandas/demandas_store.py:216-223`).
- Um `threading.Lock()` só em memória para tudo (`demandas/demandas_store.py:21`, `demandas/api.py:22`).
- Cache em memória por mtime (`demandas/demandas_store.py:139-148`, `servidor.py:90-107`).
- Limites: 5000 demandas abertas e recentes, 500 eventos por demanda (`demandas/demandas_store.py:22-23`). Com
  2 a 4 KB por demanda, o arquivo pode chegar a 10-20 MB, regravado inteiro a cada clique (estimativa minha).
- Anexos: arquivos em `data/demandas-anexos/`, enviados em base64 dentro do JSON (`servidor.py:34`,
  `demandas/demandas_store.py:279-311`).

## 3. Opções comparadas

### 3.1 Iniciar com o Windows e reiniciar se cair

| Opção | Prós | Contras | Custo | Esforço |
|---|---|---|---|---|
| Atalho na pasta Inicializar (`shell:startup`) | Não precisa de administrador. Dá para ligar e desligar pela tela | Só sobe depois que alguém entra no Windows. Janela preta à vista | 0 | 0,5 dia |
| Tarefa agendada "ao iniciar o sistema" + laço de reinício num `.bat` | Nativo do Windows. Sobe antes do logon. Sem instalar nada | Precisa de administrador uma vez para criar. "Reiniciar se falhar" do Agendador não é confiável para processo que sai com erro; por isso o laço | 0 | 1 dia |
| Serviço com NSSM | Reinício e log prontos | Projeto parado: última versão estável 2.24, de 2014 (conhecimento prévio; o site nssm.cc deu erro 503 na consulta de 28/10/2026, não confirmei). Instalar um `.exe` de fora | 0 | 1 dia |
| Serviço com WinSW | Licença MIT, ativo no GitHub (2.x estável, 3.x pré-lançamento), log com rotação ("roll") | Um `.exe` e um XML a mais. Tem que conferir a versão antes | 0 | 1 dia |
| Logon automático (Sysinternals Autologon) | Permite usar o atalho simples | Qualquer um que ligar o PC entra na conta. Desnecessário com tarefa ou serviço | 0 | 0,5 dia |

### 3.2 PC servidor desligado

| Medida | O que resolve | Custo | Esforço |
|---|---|---|---|
| No-break 600-1200 VA no PC **e** no roteador/ponto de acesso | Quedas curtas de energia. Sem o roteador no no-break, o servidor fica ligado e ninguém alcança | Faixa de preço de mercado não confirmada | Compra |
| BIOS "Restore on AC power loss = Power On" | PC volta sozinho depois de queda longa | 0 | 15 min |
| Desligar suspensão e hibernação, horário ativo do Windows Update | PC que "dorme" derruba o servidor sem ninguém perceber | 0 | 15 min |
| IP fixo (reserva no DHCP do roteador) | Os aparelhos guardam `http://IP:8090`; IP novo = todos perdidos | 0 | 15 min |
| PC reserva com restauração do backup (estudo 01) | PC queimou ou foi roubado | Um PC que já existe | Roteiro + teste |
| Faixa de "sem conexão" e rascunho | A pessoa sabe que está desconectada e não perde o que digitou | 0 | 2 dias |

### 3.3 Hospedagem

| Caminho | Prós | Contras | Custo aproximado | Esforço |
|---|---|---|---|---|
| Continuar local + túnel (Cloudflare Tunnel, Tailscale) | Sem servidor novo. Acesso de fora | PC da fábrica continua sendo o ponto único de falha. Mesmos problemas de proxy da seção 5.2 | 0 a baixo | 3-5 dias |
| VPS empresa única (Caddy + domínio) | Independe do PC da fábrica. HTTPS automático | Exige as mudanças da seção 5.2 e backup fora | US$ 4-7/mês + domínio | 2-3 semanas |
| SaaS, um SQLite por empresa | Isolamento forte (arquivo por empresa), backup e exclusão por empresa triviais, só stdlib | Um processo por VPS. Migrações rodam em N arquivos | Igual à VPS no começo | +4-6 semanas |
| SaaS, Postgres com `empresa_id` | Vários servidores de aplicação, banco gerenciado | Dependência fora da stdlib (`psycopg`), isolamento depende de cada consulta ou de RLS | +US$ 15 ou mais/mês por banco gerenciado (não consultei) | +6-10 semanas |

Preços de VPS (consulta em 28/10/2026, sem impostos):
- DigitalOcean Basic: 512 MiB/10 GB por US$ 4; 1 GiB/25 GB por US$ 6; backup semanal +20% do preço
  (https://www.digitalocean.com/pricing/droplets).
- AWS Lightsail Linux: 512 MB por US$ 5 com IPv4; 1 GB por US$ 7. Mesmo preço em São Paulo, com metade da
  franquia de tráfego (https://aws.amazon.com/lightsail/pricing/).
- Hetzner Cost-Optimized CX23: 2 vCPU, 4 GB, 40 GB por € 5,99, só na Europa. A página marcava os planos como
  "currently not available" na consulta (https://www.hetzner.com/cloud/cost-optimized/).
- Magalu Cloud (preço em reais, data center no Brasil): **não consegui confirmar o preço** do menor plano.
- Domínio `.com.br`: R$ 40 por ano no Registro.br, segundo o reajuste de 2017 e um guia de registradora
  (homehost.com.br). Não consegui abrir a tabela oficial (https://registro.br/dominio/valores/ veio vazia).
- Câmbio não consultado. Para um aparelho só, US$ 6 + domínio dá algo como R$ 40-50 por mês ao câmbio do dia.

Para a Central, 1 GB de RAM sobra: Python stdlib, um processo, dezenas de pessoas.

## 4. Recomendação

1. **Fase 0 já:**
   - no-break no PC e no roteador;
   - BIOS e energia ajustados;
   - IP fixo;
   - tarefa agendada "ao iniciar o sistema" chamando um `servidor-sempre.bat` com laço;
   - faixa de reconexão;
   - rascunho local;
   - sessão da pessoa persistida (hash, como `sessoes.json`);
   - chave de idempotência em `demanda/criar`.

   Não exige nada de fora do Windows nem do Python. WinSW fica como alternativa se o dono preferir um serviço de
   verdade.
2. **Fase 1, ainda local:**
   - camada de armazenamento atrás de uma interface (`Banco`), com o JSON de hoje como primeira implementação;
   - `tenant` implícito "padrão" em toda chamada;
   - lock e cache por tenant;
   - papel decidido por uma função só (`papel_do_pedido`), não por "é loopback".

   Isso destrava os dois caminhos sem mudar nada para o usuário.
3. **Fase 2 (hospedar):**
   - VPS com Caddy;
   - modo `DEMANDAS_MODO=hospedado`, que desliga o papel `maquina`;
   - login por pessoa com usuário e senha;
   - código de 4 dígitos só dentro de uma sessão de empresa;
   - limitação de taxa;
   - backup fora.
4. **Fase 3 (SaaS):**
   - SQLite por empresa;
   - contas e convites;
   - cobrança;
   - LGPD.

**Por quê:** a falha mais provável hoje não é o disco queimar. É o PC suspender, reiniciar com atualização ou
alguém fechar a janela preta, sem ninguém nos celulares perceber. E a mudança que mais custa depois é separar o
armazenamento e o papel, porque eles estão espalhados por `api.py` e `servidor.py`.

## 5. Como encaixa no código atual

### 5.1 Fase 0: local robusto

**`servidor-sempre.bat` (novo)**, chamado pela tarefa agendada:
- Mesma busca de Python do `iniciar.bat`, mas aceita `DEMANDAS_PY` com caminho absoluto.
- Laço: roda `servidor.py`. Se sair, grava data e código de saída em `data/servidor.log`, espera 5 s e roda de
  novo.
- Para de tentar se sair 10 vezes em 2 minutos, para não entrar num laço de erro.
- Sem `start` do navegador e sem `pause`.

**`iniciar.bat`:** antes de subir, pergunta `http://127.0.0.1:8090/api/rev`. Se responder, só abre o navegador
e sai: "A Central já está ligada (iniciada com o Windows)".

**Tarefa agendada** (criada uma vez por um `instalar-inicio.bat` rodado como administrador):

```
schtasks /create /tn "Central de demandas" /sc onstart /ru SYSTEM /rl highest ^
  /tr "\"C:\...\servidor-sempre.bat\""
```

Também desmarcar "parar a tarefa se rodar mais de 3 dias" (padrão do Agendador). Pelo `schtasks` isso exige
importar XML. Confirmar na implementação.
- **Não confirmado:** se uma tarefa "ao fazer logon" do próprio usuário pode ser criada sem administrador.
  Por isso o interruptor da tela (mockup) usa o atalho em `shell:startup` como caminho sem administrador, e o
  modo "antes do logon" mostra a instrução de rodar o instalador.

**`servidor.py`:**
- `INICIO = time.time()` e `VERSAO = "1.0.0"` no topo.
- `/api/rev` passa a devolver `{"rev", "inicio"}`. Mudou o `inicio` = o servidor reiniciou.
- Rota nova `GET /api/servidor`, **só papel `maquina`**, igual a `/api/rede`:

```json
{"versao": "1.0.0", "inicio": 1761650000, "python": "3.12.4",
 "disco": {"livre": 182000000000, "total": 475000000000},
 "dados": {"demandas_json": 2380000, "arquivo_json": 9100000, "anexos": 41000000},
 "backup": {"ultimo": 1761643800, "onde": "D:\\Backup Central"},
 "inicio_windows": {"modo": "tarefa", "ativo": true},
 "urls": ["http://192.168.0.20:8090"], "nome_pc": "ESCRITORIO-01"}
```

- `disco` vem de `shutil.disk_usage`, `dados` de `os.stat` e `uso_anexos()`
  (`demandas/demandas_store.py:255-270`), `backup` do estudo 01.
- `POST /api/servidor {"inicio_windows": true|false}`, só `maquina`: cria ou apaga o atalho em `shell:startup`.
  O modo tarefa só é lido, porque o processo do servidor não deve ter direito de administrador.

**Sessão da pessoa persistida (`demandas/api.py:147-174`):**
- Guardar `sha256(tk) -> {pessoa, vence}` em `data/pessoas-sessoes.json`, como `servidor.py:169-187` já faz com
  o PIN.
- O `tk` continua fora do storage da página: o reinício do servidor não derruba ninguém, mas recarregar a página
  ainda pede o código. Isso mantém a decisão de segurança atual (`demandas/demandas.js:25`).

**Idempotência:**
- `demanda/criar` e `comentar` aceitam `cid` (UUID gerado ao abrir o formulário).
- O servidor guarda os últimos 500 `cid` em `doc["cids"]` com o id criado. `cid` repetido devolve a vista sem
  gravar.

**Faixa de conexão (`web/app.js:27-36`):**
- Contar falhas seguidas. Na 2ª (cerca de 6 s), mostrar a faixa: "Sem conexão com a central, tentando de novo
  em N s · última atualização às 14:32 · [Tentar agora]".
- Espera crescente: 3, 5, 10, 20, 30 s (teto). "Tentar agora" zera a espera.
- Pôr `data-offline` no `#dmboard`. O CSS desabilita `[data-act]` de escrita
  (aceitar, pausar, concluir, nova, comentar...) e deixa abrir a gaveta para leitura.
- Ao voltar, esconder a faixa, toast "Conexão restabelecida" e chamar `refresh()` sempre, não só se o `rev`
  mudou.
- Se `inicio` mudou e a sessão da pessoa não foi persistida, avisar antes da próxima ação.
- Quando hospedado, a mensagem de `web/app.js:14` não pode citar o `iniciar.bat`. Vem do servidor
  (`/api/eu` diz o modo).
- `navigator.onLine` e o evento `online` só servem de dica: o Wi-Fi pode estar ligado e o PC servidor
  desligado.

**Rascunho (`demandas/demandas.js:752-800`, `demandas/demandas.js:708-713`, `demandas/demandas.js:320-325`):**
- A cada `input` no formulário de nova solicitação, gravar
  `{titulo, desc, tipo, toS, toP, motivo, prio, est, cid}` em `localStorage["dm-rascunho:" + pessoa]`, dentro de
  `try/catch`. **Nunca o `tk`.**
- `lost()` não descarta o rascunho. Ao reabrir "Nova solicitação": "Rascunho recuperado de 14:31 ·
  [Descartar]".
- Anexos (objetos `File`) não dá para guardar: avisar "refaça os anexos".
- Apagar o rascunho só depois de `demanda/criar` responder com sucesso.
- Textos de pausa, conclusão e comentário: manter o modal aberto quando a falha é de rede (hoje já fica) e
  guardar no mesmo esquema.

**PC reserva (com o estudo 01):**
1. Python instalado e uma cópia do programa na mesma pasta.
2. Restaurar o último backup de `data/` (inclui `rede.json` e `sessoes.json`: os aparelhos continuam logados).
3. Dar ao reserva o mesmo IP: trocar a reserva no DHCP ou configurar IP fixo.
4. Ligar a tarefa de início.

- **Tempo de troca estimado: 10 a 20 min** se o reserva já estiver preparado. Perde-se o que foi gravado depois
  do último backup.
- **Por que o mesmo IP:** `ip_host` só aceita IP literal (`servidor.py:236-242`), então um nome como
  `central.local` não serve hoje como saída.

### 5.2 Fase 2: hospedado, empresa única

| Ponto | Hoje | Hospedado |
|---|---|---|
| Papel `maquina` | Loopback = ADM sem PIN (`servidor.py:283-285`) | **Falha grave:** atrás do Caddy na mesma VPS, todo pedido chega de 127.0.0.1. Todo visitante vira Escritório e lê os PINs em `/api/rede`. Em `DEMANDAS_MODO=hospedado` o papel `maquina` não existe, e `_remote()` não decide mais nada |
| Host | Só localhost ou IP (`servidor.py:265-271`) | Lista `DEMANDAS_HOSTS=central.empresa.com.br`. Hoje o domínio daria 421, e a "correção" ingênua (Caddy reescrevendo Host para 127.0.0.1) abriria o furo acima |
| Origin | `http://` + Host (`servidor.py:413`) | `https://` + host configurado. Hoje todo POST daria 403 atrás do HTTPS |
| Cookie | Sem `Secure` (`servidor.py:426`) | `Secure; HttpOnly; SameSite=Lax` e prefixo `__Host-`. Mais HSTS no Caddy |
| IP do cliente | `client_address[0]` (`servidor.py:421`) | Ler `X-Forwarded-For` **só** se o pedido vier do proxy confiável (127.0.0.1), pegando o último valor que o Caddy pôs. Sem isso, 5 erros de qualquer pessoa bloqueiam todo mundo (`servidor.py:204-212`) |
| Bind | `0.0.0.0` com rede ligada (`servidor.py:465`) | Sempre `127.0.0.1`. Só o Caddy fala com a internet |
| Tela ⚙ Rede/Configurações | Só no "próprio PC" (`web/app.js:68`) | Não existe "próprio PC". Configurações viram uma área do administrador logado. Rede some. Servidor mostra saúde da VPS |
| Texto da entrada | "PIN mostrado no computador principal" (`servidor.py:54`) | Tela de entrada nova (mockup `03-login-hospedado.html`) |

**Entrada: duas opções**

| Opção | Como | Prós | Contras |
|---|---|---|---|
| A. Sessão de empresa + código de 4 dígitos | Empresa entra uma vez por aparelho (senha do administrador ou link de aparelho). Depois o "Quem é você?" de hoje | Igual ao chão de fábrica de hoje. Tablet compartilhado funciona | 4 dígitos na internet: 5 erros/60 s por pessoa (`demandas/api.py:41-42`) = 7200 palpites/dia, metade de 10 000 em cerca de 17 h. Só aceitável **atrás** da sessão de empresa |
| B. Usuário e senha por pessoa | E-mail ou matrícula + senha, pbkdf2 (já existe `_hash`, `demandas/api.py:118-119`) com mais iterações | Rastro por pessoa, padrão de mercado | Operador de chão esquece senha. Tablet compartilhado vira troca de conta |

**Recomendação:** A para operadores e B para administradores. O PIN de 6 dígitos sai: na internet ele é uma
senha compartilhada, fraca e sem dono.

**Força bruta e limitação de taxa:**
- Por IP real (XFF confiável) e por conta: 10 tentativas por 15 min, com atraso crescente.
- Teto global de logins errados por minuto.
- `rate_limit` também no Caddy (módulo de terceiros; confirmar).
- O teto de 200 sessões (`servidor.py:217`) e de 500 `tk` (`demandas/api.py:44`) vira teto **por empresa**.
  Hoje, quem tem o PIN derruba os outros só logando repetidas vezes.

**Backup fora:**
- Cópia diária cifrada para armazenamento de objetos (S3, R2, B2) em outra região, mais o backup do provedor
  (DigitalOcean: +20% semanal).
- Teste de restauração mensal (estudo 01).

**Caddy, exemplo:**

```
central.empresa.com.br {
    encode gzip
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy 127.0.0.1:8090
}
```

O serviço Python vira uma unidade `systemd` com `Restart=always`. É o mesmo laço da fase 0, agora no Linux.

### 5.3 Fase 3: SaaS multiempresa

**Isolamento dos dados**

| Opção | Quando |
|---|---|
| Pasta por empresa (`data/empresas/<slug>/demandas.json`) | Passo intermediário barato: o `store` atual passa a receber a pasta. Mas o JSON inteiro regravado continua |
| **SQLite por empresa** (`data/empresas/<slug>/central.db`) | Recomendado. Stdlib `sqlite3`, modo WAL, um escritor por arquivo. Exclusão LGPD = apagar a pasta. Backup por empresa |
| Postgres com `empresa_id` + Row Level Security | Mais de um servidor de aplicação, centenas de empresas ativas, relatórios entre empresas |

**Por que o JSON e o LOCK não escalam:**
- O lock é por processo (`demandas/demandas_store.py:21`). Dois processos (dois workers, ou um reinício
  sobreposto) leem o mesmo `rev`, gravam por cima um do outro e perdem atualização.
- O cache por mtime (`demandas/demandas_store.py:139-148`) esconde isso até o pior momento.
- Regravar 10-20 MB com fsync a cada clique custa caro mesmo com uma empresa só.
- Com várias empresas no mesmo processo, um lock global serializa todas.

**Quando o SQLite basta:**
- Um processo por VPS, com `ThreadingHTTPServer` ou trocado por algo assíncrono depois.
- Escritas curtas: uma ação = uma transação de poucas linhas.
- Uma fábrica gera bem menos de 10 escritas por segundo. Mesmo 100 empresas cabem numa VPS de 2 a 4 GB.
- Passa a não bastar quando precisar de dois servidores de aplicação atrás de um balanceador, ou failover
  automático.

**Contas e convites:**
- `empresas`: slug, nome, plano, status, criada.
- `usuarios`: e-mail, hash, papéis por empresa.
- Convite = token de uso único com validade de 72 h, enviado por e-mail (estudo 04).
- Papéis: dono (cobrança, excluir empresa), administrador (o "Escritório" de hoje), operador (pessoa).

**Testes de isolamento:**
- Toda rota com duas empresas, A e B. Usuário de A pedindo id de B leva 404 (não 403, para não confirmar que
  existe).
- Anexo de B com aid válido também leva 404.
- `cid`, `seq` e `rev` são por empresa.
- Um teste de propriedade percorre a tabela de rotas e falha se alguma não passar pelo `tenant`.

**Outros pontos do SaaS:**
- **Cobrança:** Stripe, Asaas ou Iugu (Pix e boleto). Webhook muda `empresas.status`. Inadimplente = só
  leitura.
- **LGPD:** termos de uso, política de privacidade, DPA (a empresa cliente é controladora e o SaaS é operador).
  Exportação dos dados da empresa (JSON e anexos em ZIP), exclusão com prazo e registro, encarregado (DPO)
  indicado. Os dados são nome, matrícula e ações de funcionários: pouco sensível, mas é dado pessoal.
- **Anexos:** sair do disco local para armazenamento de objetos, com chave `empresa/<slug>/<aid>`, URL
  assinada de curta duração e cota por plano. O envio em base64 dentro do JSON (`servidor.py:34`) passa a
  upload direto.
- **Monitoramento e logs:**
  - log de acesso estruturado (hoje desligado, `servidor.py:250-251`), sem PIN, código nem `tk`;
  - `/saude` para um verificador externo (UptimeRobot ou similar);
  - erros com `empresa` e rota;
  - alerta de disco.

### Compatibilidade com o `demandas.json` atual
- **Fase 0:** só acrescenta `doc["cids"]` (lista opcional; arquivo antigo sem ela = vazia) e o arquivo novo
  `pessoas-sessoes.json`. `V` pode continuar 1.
- Atenção: `_normaliza` monta um `empty()` novo e copia só as chaves conhecidas
  (`demandas/demandas_store.py:117-134`). Por isso `cids` precisa entrar em `empty()` e em `_normaliza`, senão
  some na primeira leitura. Uma versão mais antiga do programa descartaria `cids` sem outros danos.
- **Fase 1:** a interface `Banco` com a implementação `BancoJson` lê e grava o mesmo arquivo. Nada muda em disco.
- **Fase 3:** um importador `json -> sqlite` (`py -3 servidor.py --importar data/ --empresa acme`), mantendo
  ids `SOL-n`, `p<n>` e hashes de código. O `.json` original fica guardado como `demandas.json.v1.bak`, como já
  faz `_migra` (`demandas/demandas_store.py:158-164`).

### Rotas novas e quem pode usar

| Rota | Fase | Quem |
|---|---|---|
| `GET /api/rev` com `inicio` | 0 | Todos que já podem hoje |
| `GET /api/servidor` | 0 | Só `maquina` (local) / dono e administrador (hospedado) |
| `POST /api/servidor` (início com o Windows) | 0 | Só `maquina` |
| `POST /api/entrar-empresa`, `/api/sair-empresa` | 2 | Público, com limitação de taxa |
| `POST /api/conta/senha`, `/api/conta/convite` | 2-3 | Administrador; convite aceito pelo público com token |
| `GET /saude` | 2 | Público, sem dados (só "ok" e versão) |

## 6. Riscos e segurança

- **Papel `maquina` atrás de proxy, túnel ou qualquer coisa que conecte de 127.0.0.1:** acesso total sem senha.
  Vale também para Cloudflare Tunnel ou ngrok rodando no próprio PC da fábrica, **mesmo na fase 0**. O README
  deveria avisar desde já.
- Confiar em `X-Forwarded-For` vindo de qualquer um permite forjar IP e escapar do bloqueio. Só do proxy
  conhecido.
- Rascunho no `localStorage` de tablet compartilhado: outra pessoa pode ver o texto. A chave é por pessoa, o
  rascunho é apagado ao enviar e expira em 24 h. Nunca guardar `tk`, PIN ou código.
- Persistir sessões de pessoa: gravar só o hash, como `sessoes.json`. Trocar o código ou desativar continua
  revogando (`demandas/api.py:171-174`).
- Tarefa como SYSTEM: o servidor roda com privilégio máximo. Melhor uma conta local sem administrador
  (`/ru CentralSvc`), dona só da pasta do programa.
- Laço de reinício escondendo erro: limite de tentativas e log com motivo.
- SaaS: vazamento entre empresas é o risco número 1. Testes de isolamento obrigatórios em toda rota.
- Backup fora sem cifra expõe dados pessoais (LGPD).

## 7. Testes que a implementação vai exigir (docs/QUALIDADE.md)

**Unitários (Python):**
- `papel_do_pedido`: local com loopback = `maquina`. Hospedado com loopback = **nunca** `maquina`. IP de rede
  sem sessão = `None`.
- XFF: aceito só do proxy, último valor, IPv6, cabeçalho malformado.
- Bloqueio por IP real: 5 erros de um IP não bloqueiam outro.
- Sessões de pessoa: gravam só o hash, sobrevivem ao recarregar, vencem, são revogadas ao trocar o código, e
  arquivo ruim = ninguém logado.
- `cid`: repetido não grava duas vezes, teto de 500, arquivo antigo sem `cids`.
- `/api/servidor`: números coerentes com pasta de teste (`DEMANDAS_DATA`), recusa da rede (403), sem caminho
  absoluto vazando para não-`maquina`.
- `Banco`: a mesma bateria roda contra `BancoJson` e, depois, `BancoSqlite` (teste de contrato).

**Integração (servidor real em porta livre, como `tests/test_servidor.py:42-110`):**
- Reiniciar o servidor no meio: pessoa continua logada, `inicio` muda.
- Modo hospedado com Host do domínio, Origin `https`, cookie com `Secure`.
- Pedido de loopback sem sessão = 401.
- Dois tenants: isolamento em todas as rotas, anexos inclusive.
- Concorrência: 20 threads gravando, `rev` final = 20, nenhuma ação perdida.

**Tela (jsdom, `tests/demandas_check.js`):**
- `fetch` falhando 2 vezes mostra a faixa. Espera cresce. "Tentar agora" chama na hora. Voltar esconde a faixa e
  chama `refresh()`.
- Com `data-offline`, os botões de escrita ficam desabilitados e a gaveta abre.
- 401 no meio do formulário: rascunho recuperado ao reabrir e apagado depois de enviar com sucesso.
- `localStorage` que lança exceção não quebra nada.

**Mutação:** `py -3 qa.py mutate servidor.py` (papel, host, origin, XFF) e `demandas/api.py` (sessões, `cid`).
Mutante sobrevivente em `papel_do_pedido` bloqueia a entrega.

**Scripts `.bat`:** teste manual roteirizado (tarefa criada, reinício do PC, processo morto pelo Gerenciador de
Tarefas volta em cerca de 5 s, 10 quedas seguidas param o laço).

## 8. Fases e esforço estimado

| Fase | Entrega | Esforço (dev) | Fecha porta? |
|---|---|---|---|
| 0a | No-break, BIOS, energia, IP fixo, roteiro do PC reserva | 0,5 dia + compra | Não |
| 0b | `servidor-sempre.bat`, tarefa "ao iniciar", `iniciar.bat` que detecta o servidor ligado | 1-2 dias | Não |
| 0c | Faixa de conexão, só leitura, rascunho, `cid`, sessão de pessoa persistida, `inicio` no `/api/rev` | 3-4 dias | Não |
| 0d | Seção Servidor em ⚙ Configurações (`/api/servidor`) | 2 dias | Não |
| 1 | Interface `Banco` + `BancoJson`, `tenant` implícito "padrão", lock e cache por tenant, `papel_do_pedido` único, configuração por `DEMANDAS_MODO` | 5-8 dias | **É ela que abre as portas** |
| 2 | Modo hospedado (Host, Origin https, cookie Secure, XFF, bind local, sem `maquina`), sessão de empresa + código, senha para ADM, limitação de taxa, Caddy, systemd, backup fora, `/saude` | 2-3 semanas | Não |
| 3a | `BancoSqlite` + importador, ainda empresa única | 1-2 semanas | Não |
| 3b | Multiempresa: subdomínio, contas, convites, papéis, testes de isolamento | 3-4 semanas | Não |
| 3c | Cobrança, LGPD (termos, DPA, exportar e excluir), anexos em objetos, monitoramento | 3-5 semanas | Não |

**O que fazer agora para não reescrever depois:**
1. Nenhum código novo chama `ds.load()` ou `ds.commit()` direto fora de um ponto central. Novas rotas (avisos,
   e-mail, calendário) passam pelo mesmo `handle` e recebem `ctx`.
2. Pôr `ctx["tenant"] = "padrao"` já, mesmo sem uso, e repassar para o store.
3. Não acrescentar mais nenhuma decisão baseada em `_remote()` ou `papel == "maquina"` nos estudos 01, 02, 04
   e 05. Usar `pode(ctx, "configurar")`.
4. Ids e sequências continuam por documento (já são: `seq` em `demandas/demandas_store.py:57`). Não criar
   contador global.
5. Configurações novas (backup, e-mail, avisos) num arquivo por instalação, que vira linha por empresa depois,
   não em constantes.
6. Datas sempre em ms UTC (já são) e fuso por empresa numa configuração (estudo 05).

## 9. Ligações com os outros estudos

- **01 Backup:** o PC reserva é a restauração do backup. "Último backup" aparece na seção Servidor. O backup
  fora da VPS é o mesmo mecanismo apontando para armazenamento de objetos.
- **02 Avisos:** a thread de fundo para atrasos (em `main()`, `servidor.py:463-472`) precisa aguentar o laço de
  reinício e, no SaaS, percorrer os tenants. Avisos não devem disparar duas vezes depois de um reinício
  (`atraso_avisado` já existe).
- **04 E-mail:** convites e recuperação de senha da fase 2-3 dependem dele. Credenciais SMTP por instalação ou
  empresa, nunca no `demandas.json`.
- **05 Calendário:** turnos e feriados são configuração por empresa. No SaaS, fuso horário também.
- **Diálogo ⚙ Configurações:** a seção Servidor é a última do menu comum (Rede · Backup · E-mail · Avisos ·
  Servidor). Hospedado, Rede some e as outras seções viram área do administrador.

## 10. Mockups

- `docs/estudos/mockups/03-servidor-fora.html`: celular do operador (moldura de 390 px) e PC do escritório com a
  faixa "Sem conexão com a central, tentando de novo em 5 s", o botão "Tentar agora", "última atualização às
  14:32", os dados em modo só leitura (botões de ação desabilitados) e o aviso de rascunho guardado.
- `docs/estudos/mockups/03-login-hospedado.html`: entrada da versão hospedada. Passo 1, empresa (subdomínio ou
  código). Passo 2, o "Quem é você?" atual (setor, nome, código) ou usuário e senha para o administrador. As
  abas no topo alternam os passos.
- `docs/estudos/mockups/03-configuracoes-servidor.html`: seção Servidor do ⚙ Configurações, com saúde (ligado
  há, versão, disco, tamanho dos dados, último backup), "Iniciar com o Windows", "PC reserva" e endereços.

## Fontes externas (consultadas em 28/10/2026)

- DigitalOcean, preços de Droplets: https://www.digitalocean.com/pricing/droplets
- AWS Lightsail, preços: https://aws.amazon.com/lightsail/pricing/
- Hetzner Cloud Cost-Optimized: https://www.hetzner.com/cloud/cost-optimized/
- WinSW (MIT, 2.x estável, 3.x pré-lançamento): https://github.com/winsw/winsw
- NSSM: https://nssm.cc/download (respondeu 503; versão 2.24 de 2014 é conhecimento prévio, não confirmado)
- Domínio .com.br R$ 40/ano: https://www.homehost.com.br/blog/registro-de-dominios/quanto-custa-um-dominio e
  reajuste de 2017 em https://tiinside.com.br/02/09/2016/nic-br-anuncia-reajuste-para-registro-de-dominios-br-partir-do-ano-que-vem/
  (tabela oficial do Registro.br não abriu)
- Magalu Cloud: preço não confirmado.
