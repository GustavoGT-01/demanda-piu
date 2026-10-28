# Estudo 01 · Backup automático

> Só estudo. Nenhuma linha do programa muda agora. Os mockups vão para aprovação do dono antes de qualquer
> implementação.

## 1. Resumo

- Uma thread daemon no servidor faz um `.zip` por dia (no horário escolhido) e também ao ligar, quando o último
  backup tem mais de 20 h. Faz outro antes de cada restauração.
- O zip leva `demandas.json`, `demandas-arquivo.json`, os anexos citados e um `manifesto.json` com o SHA-256 de
  cada arquivo. **Não leva `rede.json` (PIN em texto puro) nem `sessoes.json`.**
- Sempre grava numa pasta local fixa e, se configurado, copia o mesmo zip para um destino extra (pen drive, pasta
  de rede ou pasta do OneDrive/Google Drive). Retenção 7 diárias + 4 semanais + 12 mensais, com limite de espaço.
- Cada zip é verificado logo depois de gravado: `testzip`, leitura dos JSON e conferência dos hashes.
- Restaurar só no próprio PC, com cópia de segurança antes. O `rev` e o `seq` nunca voltam para trás. Aviso no
  Painel do ADM quando o backup falha ou passa de 26 h.

## 2. Como é hoje

- **Backup só manual**: "copie a pasta `data/` inteira com o programa fechado" (`README.md:33`). Com o programa
  aberto, a cópia pode pegar o momento em que o `demandas.json` não existe (ver abaixo).
- **Gravação**: `store.atomic_write` grava `.tmp` com fsync e faz dois renomes: o atual vira `.bak` e o `.tmp`
  vira o atual (`store.py:58-68`). **Entre os dois renomes o arquivo principal não existe** (`store.py:59-60`).
  A leitura cobre isso caindo para o `.bak` (`store.py:71-95`). Uma cópia feita fora do LOCK pode pegar esse
  momento.
- **Um lock só, em memória**: `demandas_store.LOCK` (`demandas/demandas_store.py:21`). Toda leitura e gravação
  do `api.py` acontece sob ele (`demandas/api.py:22`, `:848-856`).
- **Arquivo morto**: `_arquivar` grava `demandas-arquivo.json` *antes* do principal (`demandas_store.py:198-213`,
  linha 211). Por isso uma cópia consistente precisa pegar os dois sob o mesmo LOCK.
- **Anexos ficam fora do LOCK**:
  - `salvar_anexo` grava o arquivo com nome inédito sem o LOCK (`demandas_store.py:280-309`) e nunca sobrescreve
    (`_publica`, `:268-277`). O metadado entra depois, sob o LOCK (`api.py:773-796`).
  - Ao remover, o metadado sai sob o LOCK e o arquivo some **depois** de gravar, pelo callback `depois`
    (`api.py:543-554`, `:854-855`).
  - Resultado: **arquivo de anexo é imutável**. Há dois casos raros: arquivo órfão (enviado, ainda sem metadado)
    e metadado recém-removido cujo arquivo ainda existe por instantes.
- **Limites**: anexo até 5 MB (`demandas_store.py:24`), cota de 300 MB (`:26`). Até 5.000 demandas no principal e
  50.000 no arquivo morto (`:22-23`).
- **Versão do formato**: um arquivo com `v` maior que o do programa é recusado (`demandas_store.py:176-177`).
  Isso também protege a restauração de um zip vindo de uma versão mais nova.
- **Concorrência otimista**:
  - Cada registro guarda `_rv` = rev da gravação que o mudou (`api.py:95-100`).
  - A tela devolve o `_rv` que viu e o servidor recusa com 409 se mudou (`api.py:103-109`).
  - A gravação seguinte usa `rev + 1` (`api.py:755`, `demandas_store.py:218`).
  - **Consequência para a restauração**: se o `rev` voltar para trás, uma tela aberta pode ter um `_rv` antigo
    igual a um `_rv` novo e passar no conferido.
- **Tokens de pessoa** só em memória (`api.py:147-175`). Se a pessoa não existe mais, `_ator` responde 401
  "Identifique-se de novo." (`api.py:203-211`). Se ela existe com outro código, o token antigo continua valendo.
- **Arquivos fora das demandas**:
  - `rede.json` guarda os dois PINs **em texto puro** (`servidor.py:127-144`).
  - `sessoes.json` guarda só o sha256 do cookie (`servidor.py:169-171`). Quem lê o arquivo não consegue entrar
    com ele.
- **Pontos de encaixe**:
  - `main()` liga o servidor (`servidor.py:459-472`). A thread entra entre `api_mod()` (`:463`) e
    `serve_forever()` (`:472`).
  - A rota `/api/rede` já é o modelo de "só no computador principal": recusa quem vem da rede
    (`servidor.py:388-391`, `:432-441`).
  - Na tela, o botão ⚙ só aparece com `papel === 'maquina'` (`web/app.js:68`).
- **Atualização das telas**: `vigia()` pergunta `/api/rev` a cada 3 s e chama `refresh()` em **qualquer** mudança
  do rev, para cima ou para baixo (`web/app.js:27-36`). O `rev()` do servidor usa cache por mtime e tamanho
  (`servidor.py:90-107`), e os caches do banco também (`demandas_store.py:139-148`). Um arquivo restaurado
  invalida os três caches sozinho.
- **Painel do ADM**: o bloco "🚨 Atenção agora" usa `.dm-al` com `data-k` (`demandas.js:382-398`,
  `demandas.css:162-167`). Os alertas flutuantes usam `.dm-alert` (`demandas.js:224-238`, `demandas.css:346-353`).
  A vista do ADM já leva um dado de sistema, `anexos_uso` (`demandas_calc.py:150-166`, `api.py:734-735`): é o
  mesmo caminho para levar o estado do backup.

## 3. Opções comparadas

### 3a. Como copiar

| Opção | Prós | Contras | Custo | Esforço |
|---|---|---|---|---|
| **A. Thread daemon + `zipfile` (stdlib)** | Sem instalar nada. Consistente (lê sob o LOCK). Verifica e avisa na tela. | Só roda com o servidor ligado. | 0 | Médio |
| B. Agendador de Tarefas do Windows + script | Roda com o programa fechado. | Não enxerga o LOCK: volta ao problema dos dois renomes. Configuração fora do programa. A tela não sabe se falhou. | 0 | Médio |
| C. Histórico de Arquivos / OneDrive sincronizando `data/` direto | Zero código. | Copia arquivo pela metade ou no meio do renome. Sem verificação, sem retenção própria. O OneDrive pode travar o `.tmp` e o `os.replace` (PermissionError, `store.py:23-35`). | 0 | Baixo |
| D. Cópia "quente" sem zip (pasta datada) | Restauração manual fácil. | Milhares de arquivos soltos. Sem hash único, retenção trabalhosa. | 0 | Médio |

### 3b. Onde guardar

| Destino | Prós | Contras | Se sumir |
|---|---|---|---|
| **Pasta local** (`backup\` ao lado do programa) | Sempre disponível, rápida, sem configurar. Protege contra erro de uso e arquivo corrompido. | **Não protege contra o PC morrer**, disco queimar, roubo ou ransomware. | Não some. Disco cheio vira falha avisada. |
| Pen drive / HD externo | Barato. Fora do disco do PC. Dá para guardar longe. | Alguém tira e esquece. A letra muda (E:, F:). Se fica sempre plugado, o ransomware pega também. Perda do pen drive expõe dados (ver §6). | Destino "não encontrado": a cópia local segue. Aviso no painel em até 26 h. |
| Pasta de rede (UNC `\\SERVIDOR\backup`) | Outra máquina. Automático. | Depende de outro PC ligado e de credencial do Windows. O serviço pode rodar com outro usuário. Lento no Wi-Fi. | Igual ao pen drive. Tempo limite curto para não travar a thread. |
| Pasta sincronizada (OneDrive, Google Drive) | **Fora da fábrica** (cobre incêndio e roubo). Histórico de versões do provedor. | Plano grátis pequeno: OneDrive 5 GB, Google 15 GB divididos com Gmail e Fotos (fontes abaixo). Arquivo "só online" (Files On-Demand) some do disco até ser aberto. Sincroniza só com internet. Dados de pessoas saem para um provedor. | A pasta local do cliente existe sempre. O risco é **não sincronizar** sem ninguém ver. O programa não enxerga isso. |

Fontes consultadas em 2026-10-28 (não confirmei em página oficial da Microsoft nem do Google):
- OneDrive grátis com 5 GB e funcionamento do Files On-Demand:
  [cbackup.com](https://www.cbackup.com/articles/onedrive-files-on-demand-6688.html) e
  [Colorado State IT](https://cnsit.colostate.edu/kb/onedrive-files-on-demand).
- Google com 15 GB divididos entre Gmail, Drive e Fotos:
  [TechCrunch 2013](https://techcrunch.com/2013/05/13/google-unifies-its-free-storage-now-gives-you-15gb-for-drive-gmail-and-google-photos)
  e [Inbox Zero 2025](https://www.getinboxzero.com/blog/post/gmail-running-out-of-space).

### 3c. Retenção

| Opção | Prós | Contras |
|---|---|---|
| Últimas N cópias | Simples. | 30 cópias diárias cobrem só um mês. Um erro descoberto tarde já não tem volta. |
| **7 diárias + 4 semanais + 12 mensais (GFS)** | 23 cópias cobrem um ano. Erros antigos têm volta. | Regra um pouco mais longa (função pura, fácil de testar). |
| Sem apagar | Nada se perde. | Enche o pen drive. |

### 3d. Anexos dentro de cada zip ou num "depósito" comum

| Opção | Prós | Contras |
|---|---|---|
| **Cada zip completo** | Cada zip restaura sozinho e abre no Windows sem o programa. | 23 cópias × tamanho dos anexos. Com a cota cheia (300 MB) daria cerca de 7 GB. |
| Depósito comum `anexos/` no destino + zip só com JSON | Anexo é imutável e tem nome único: cada um é copiado uma vez só. | Restaurar depende do depósito. Apagar exige contar referências. Um depósito corrompido estraga todas as cópias. |

## 4. Recomendação

- **3a-A**: thread daemon com `zipfile`, lendo os JSON sob o LOCK.
- **Dois destinos**: a pasta local sempre e um destino extra opcional, que recebe uma cópia do mesmo zip já
  verificado. A pasta local resolve 90% dos casos (erro de uso, arquivo corrompido, restauração rápida). O
  destino extra é o que salva quando o PC morre.
- **GFS 7/4/12** com limite de espaço. Cópias manuais e as de "antes de restaurar" ficam fora da regra: guardar as
  últimas 5 de cada.
- **Zip completo** na fase 1. Mostrar o tamanho de cada cópia e avisar quando o limite está perto. O depósito
  comum só entra se o tamanho virar problema de verdade.

Por quê:
- É o único caminho que enxerga o LOCK, então a cópia nunca pega o meio de uma gravação.
- Não instala nada e segue a regra "só biblioteca padrão".
- A própria tela mostra se o backup está bom.

### Horário

- Padrão **12:00**, com a opção "também ao ligar o programa" ligada.
- Numa fábrica o PC pode ficar desligado de madrugada: um backup às 03:00 nunca rodaria.
- **Ao ligar**: se o último backup bom tem mais de 20 h, faz um 2 minutos depois do início, para não pesar a
  abertura.
- Perdeu o horário (PC desligado ou dormindo)? Na primeira verificação depois, faz o backup.

## 5. Como encaixa no código atual

### 5.1 Arquivos e funções

- **Novo `demandas/demandas_backup.py`** (fica no escopo crítico, `docs/QUALIDADE.md:32-34`):
  - `config()` / `salvar_config(body)` → `data/backup.json`.
  - `instantaneo()` → sob `ds.LOCK`, lê os **bytes** de `demandas.json` e `demandas-arquivo.json` e
    monta a lista de anexos citados (`d["anexos"][*].id` do principal e do arquivo morto). Solta o LOCK.
    - Lê bytes crus com `store._read_safe` para o caso "entre os renomes" e grava o JSON de novo. O texto vai
      igual ao do disco. O LOCK fica preso por milissegundos (dois `read`).
  - `gravar_zip(inst, pasta, tipo)`:
    - Fora do LOCK, cria `nome.zip.part` com os JSON em `ZIP_DEFLATED` e os anexos em `ZIP_STORED` (JPG, PNG e
      PDF já são comprimidos).
    - Anexo citado que sumiu entre o instantâneo e a cópia (removido nesse meio tempo) entra como `faltando` no
      manifesto. Não é falha.
    - Anexo órfão (arquivo sem metadado) não entra.
    - Grava `manifesto.json` por último. Faz fsync, verifica e renomeia para `.zip`.
  - `verificar(caminho)` → `testzip()` deve devolver `None`. Confere os nomes permitidos e os tamanhos máximos
    (contra zip bomb). Faz `json.loads` dos dois JSON, compara `v ≤ ds.V` e confere o sha256 de cada membro com
    o manifesto.
  - `reter(lista, agora, ret)` → **função pura** que devolve o que manter. Só apaga arquivos que batem com
    `^central-demandas_\d{8}-\d{4}_(auto|inicio|manual|antes-restaurar)\.zip$`. Nunca apaga a cópia verificada
    mais nova.
  - `estado()` → resumo para a tela e para a vista do ADM.
  - `restaurar(nome)` → ver 5.5.
  - `Agendador` → `threading.Thread(daemon=True)` com um `threading.Event`. Acorda a cada 60 s e decide com
    `deve_rodar(agora, cfg, estado)` (pura). Um `threading.Lock` próprio (`_BACKUP`), pego sem bloquear, impede
    duas cópias juntas.
- **`servidor.py`**:
  - Em `main()` (`:459-472`), depois de `api_mod()`: `backup_mod().iniciar()`.
  - Rotas `/api/backup*` no molde de `/api/rede`, recusando `_remote()` (`:388-391`).
  - Botão e diálogo: o "⚙ Rede" vira "⚙ Configurações" (padrão comum dos estudos).
- **`demandas/api.py`**:
  - `_vista_de` (`:734-735`) passa `backup=bk.resumo()` quando `ator is None` (ADM), como já faz com
    `anexos_uso`.
  - `restaurar` limpa `_TK` (`:147`) sob `_TK_LOCK`.
- **`demandas/demandas_calc.py`**: `vista(...)` (`:150-166`) ganha o parâmetro `backup` só para o ADM.
- **`demandas/demandas.js`**: `vPainel` (`:382`) mostra o aviso em cima dos KPIs quando `D.v.backup.alerta`.
  Mostra também um `toast` de "dados restaurados" quando chega `D.v.restaurado` novo.
- **`web/index.html` e `web/app.js`**: diálogo ⚙ Configurações com a seção Backup (`index.html:37-53` e
  `app.js:38-64` hoje).
- **`README.md:33`**: trocar a instrução manual pela nova.

### 5.2 Formato de dados novo

`data/backup.json` (configuração, só no PC; **não vai para o zip**):

```json
{
  "v": 1,
  "on": true,
  "hora": "12:00",
  "ao_ligar": true,
  "local": "C:\\CentralDemandas\\backup",
  "extra": "E:\\CentralDemandas-backup",
  "ret": {"diarias": 7, "semanais": 4, "mensais": 12, "manuais": 5},
  "limite_mb": 5000
}
```

`data/backup-estado.json` (o que aconteceu; reescrito com `atomic_write`):

```json
{
  "v": 1,
  "ultimo_ok": {"t": 1761645600000, "nome": "central-demandas_20261028-1200_auto.zip", "bytes": 48213990,
                "sha256": "9f2c…", "rev": 18342, "verificado": true, "extra": "ok"},
  "ultima_falha": {"t": 1761559200000, "destino": "extra", "erro": "Destino não encontrado: E:\\"},
  "falhas_seguidas": 0
}
```

`manifesto.json` dentro de cada zip:

```json
{
  "programa": "Central de demandas", "formato_backup": 1, "v_dados": 1,
  "criado": 1761645600000, "tipo": "auto", "rev": 18342, "maquina": "PCP-01",
  "arquivos": {
    "demandas.json": {"bytes": 8123456, "sha256": "…"},
    "demandas-arquivo.json": {"bytes": 21003311, "sha256": "…"},
    "demandas-anexos/a3f9c0d1e2b4a6f8.jpg": {"bytes": 412233, "sha256": "…"}
  },
  "contagem": {"demandas": 4211, "arquivo": 18877, "pessoas": 86, "setores": 8, "anexos": 214},
  "faltando": []
}
```

- Nome do arquivo: `central-demandas_AAAAMMDD-HHMM_<tipo>.zip`, com tipo `auto`, `inicio`, `manual` ou
  `antes-restaurar`.
- Dentro do zip os caminhos repetem os de `data/`. Assim dá para restaurar à mão, com o programa fechado, só
  descompactando.

### 5.3 Compatibilidade com o `demandas.json` atual

- Nenhum campo novo no `demandas.json`. O backup só **lê** o arquivo.
- O único campo novo no banco é `restaurado: {t, de}`, gravado na restauração para avisar as telas. É opcional, e
  `_normaliza` (`demandas_store.py:117-134`) hoje o descartaria. Ou entra na normalização, ou fica no
  `backup-estado.json` e vai para a vista por lá. **Recomendo o segundo**: o contrato dos dados não muda.
- Zip de versão mais nova (`v_dados > ds.V`) é recusado com a mesma frase de `demandas_store.py:177`.
- Zip de versão mais velha é restaurado como está. A migração existente (`_migra`, `:158-164`) roda na
  primeira leitura.

### 5.4 Rotas novas (todas só `papel == "maquina"`, 403 para qualquer outro)

| Rota | Faz |
|---|---|
| `GET /api/backup` | Configuração, estado, estado dos destinos e lista das cópias (nome, tipo, tamanho, hora, verificado). |
| `POST /api/backup` | Salva a configuração. Valida a hora `HH:MM`, a retenção 1–60 e o destino (ver §6). |
| `POST /api/backup/agora` | Faz uma cópia `manual`. 409 se já tem uma rodando. |
| `POST /api/backup/escolher` | Abre o seletor de pasta **no próprio PC** (`tkinter.filedialog.askdirectory` num subprocesso `py -3 -I -c …`, com tempo limite). Devolve o caminho. Sem tkinter, a tela só mostra o campo de texto. |
| `POST /api/backup/abrir` | `os.startfile(pasta)` da pasta escolhida (só as duas pastas configuradas, nunca um caminho vindo do pedido). |
| `POST /api/backup/restaurar` | `{nome, destino: "local"\|"extra", confirmo: "RESTAURAR"}`. |

- ADM pela rede (`completo`) e operador: **nenhuma** rota de backup.
- O ADM só **vê** o resumo no Painel, pela vista (`backup.alerta`, `backup.ultimo_ok_t`), sem caminhos de pasta.
- Teste rápido de ambiente: Python 3.14.6 com `zipfile`, `tkinter` e `os.listdrives` disponível neste PC (rodado
  em 2026-10-28). O `listdrives` serve para sugerir pen drives na tela.

### 5.5 Restaurar pela tela

Ordem (tudo sob `_BACKUP`; a gravação dos dados sob `ds.LOCK`):

1. **Verificar o zip escolhido** (`verificar`). Falhou → para, sem tocar em nada.
2. **Cópia `antes-restaurar`** do estado atual, gravada e verificada. Falhou → para.
3. Extrair para `data/.restaurar-tmp/`, só pelos nomes permitidos: nunca usar o caminho do membro como veio
   (zip slip). Conferir o hash de cada um.
4. Sob `ds.LOCK`:
   - copiar os anexos que faltam para `demandas-anexos/` (nomes únicos, `_publica` sem sobrescrever);
   - `atomic_write` do `demandas-arquivo.json` e depois do `demandas.json` (mesma ordem de `_arquivar`);
   - **`rev = max(rev_atual, rev_backup) + 1`**, para o rev nunca voltar (protege o `_rv`, `api.py:103-109`);
   - **`seq[k] = max(seq_atual[k], seq_backup[k])`**, para não reaproveitar um "SOL-n" que já foi impresso ou
     falado depois do backup;
   - limpar `_CACHE` e `_ARQ`.
5. Fora do LOCK: limpar `_TK` (todas as pessoas se identificam de novo) e apagar os anexos que o backup não cita.
   Eles estão no zip `antes-restaurar` e liberam a cota.
6. Gravar `restaurado` no estado e responder.

O que acontece com o resto:
- **Sessões do PIN** (`sessoes.json`): ficam como estão. Os aparelhos não precisam do PIN de novo.
- **Pessoas nos aparelhos**: voltam para "Quem é você?" (o token some). Quem não existe no backup não entra.
- **Telas abertas**:
  - o `vigia` vê o rev novo em até 3 s e recarrega (`web/app.js:33`);
  - gaveta aberta de uma demanda que não existe mais fecha com o aviso "Solicitação não encontrada";
  - formulário aberto devolve 409 ao salvar, porque o `_rv` não bate;
  - todas mostram o toast "Dados restaurados para 27/10 12:00".
- **Ações entre o backup e agora se perdem**. Por isso o modal mostra quantas demandas e eventos há a mais hoje,
  comparando as contagens do manifesto.

### 5.6 Avisar quando falha ou está velho

`resumo()` calcula `alerta` e a frase curta. Regras, nesta ordem:

| Situação | `alerta` | Texto no Painel |
|---|---|---|
| Backup desligado | `aviso` | "Backup automático desligado." |
| Nenhuma cópia local verificada há mais de 26 h | `grave` | "Último backup há N dias: <motivo da última falha>." |
| Destino extra configurado e sem cópia boa há mais de 26 h | `grave` | "Último backup há 3 dias: o destino (pen drive E:) não foi encontrado." A cópia local em dia não apaga o aviso, porque ela não protege se o PC quebrar. |
| Última verificação semanal achou cópia corrompida | `aviso` | "A cópia de 01/09 está com defeito." |
| Tudo ok | `null` | nada |

- **26 h** = um dia mais uma folga: um backup das 12:00 que atrasou por causa do PC desligado não dispara o aviso
  na mesma hora.
- **Onde aparece**:
  - faixa no topo do Painel do ADM, no estilo `.dm-al` (`demandas.css:162-167`);
  - alerta flutuante `.dm-alert` (`demandas.js:224-238`) uma vez por dia ao abrir a tela;
  - ponto vermelho no item "Backup" do ⚙ Configurações.
  - Operadores nunca veem.
- **ADM pela rede** (`completo`): vê o aviso sem caminho de pasta e sem os botões "Fazer backup agora" e "Abrir
  configurações", que só existem no PC.

## 6. Riscos e segurança

- **PIN em texto puro**: `rede.json` não vai para o zip (`servidor.py:127-144`).
  - Num PC novo, `net_config` cria PINs novos e os aparelhos digitam o PIN novo uma vez.
  - O manifesto guarda só `"rede_ligada": true/false` para lembrar o dono de religar.
- **Sessões**: `sessoes.json` não vai para o zip. Restaurar sessões reviveria acessos derrubados depois do backup
  (por exemplo depois de trocar o PIN, `servidor.py:152-160`).
- **Código de 4 dígitos é quebrável fora do programa**:
  - O zip leva `sal` e `hash` (pbkdf2 com 100 mil iterações, `api.py:40`, `:119`), necessários para restaurar.
    Só existem 10 mil códigos possíveis: quem pega o zip descobre todos em minutos num PC comum.
  - Hoje o bloqueio online é a defesa (`api.py:40`, comentário), e ele não vale fora do programa.
  - Medidas:
    - avisar na tela que o zip tem nomes, matrículas e códigos;
    - para pen drive, recomendar **BitLocker To Go** (o Windows 11 Pro deste PC tem);
    - o `zipfile` da stdlib **não grava zip com senha**, então criptografar exigiria código próprio (fora do
      escopo).
- **Destino escolhido**:
  - recusar caminho dentro de `data/` (o backup entraria no backup) e a raiz do disco do sistema;
  - criar só a subpasta `CentralDemandas-backup` quando a pasta mãe existe. **Nunca criar a letra do pen drive**:
    sem o pen drive, gravaria em outro lugar;
  - testar a gravação com um arquivo `.teste` antes de aceitar.
- **Apagar com segurança**: a retenção só apaga os nomes do padrão, só na pasta configurada, e nunca a cópia
  verificada mais nova. A pasta pode ser do usuário, com outros arquivos dentro.
- **Restauração destrutiva**:
  - só `maquina`;
  - confirmação digitando `RESTAURAR`;
  - cópia antes, verificada;
  - extração por lista branca de nomes;
  - limite de tamanho por membro (JSON ≤ 200 MB, anexo ≤ 5 MB) e no total (≤ cota + JSON).
- **Thread travada**: destino de rede lento pode prender a thread. Medidas:
  - não segura o LOCK durante a cópia;
  - tempo limite por arquivo no destino extra;
  - a pasta local é gravada antes, então nunca espera a rede.
- **Disco cheio**: `shutil.disk_usage` antes de gravar (precisa de 2× o tamanho estimado). Sem espaço → falha
  avisada, sem apagar dados.
- **OneDrive travando arquivo**: renomear `.part` para `.zip` pode dar PermissionError. Repetir como em
  `store._replace` (`store.py:23-35`).
- **Erro sem vazar caminho para a rede**: a vista do ADM leva só `alerta` e a frase curta. Caminhos aparecem só
  no diálogo do PC.

## 7. Testes que a implementação vai exigir (`docs/QUALIDADE.md`)

Todos com `DEMANDAS_DATA` apontando para uma pasta temporária e o relógio injetado (`agora`).

**Unitários (`tests/test_demandas_backup.py`)**
- `reter`:
  - 0, 1 e 400 cópias; limites 7/4/12;
  - virada de mês, ano e semana ISO;
  - duas cópias no mesmo dia (fica a mais nova);
  - manuais e antes-restaurar contadas à parte;
  - nunca apaga a verificada mais nova;
  - ignora nomes fora do padrão;
  - limite de espaço apaga das mais velhas, mas não abaixo de 1.
- `deve_rodar`:
  - antes, na hora e depois do horário; já rodou hoje;
  - PC desligado no horário;
  - ao ligar com o último backup de 19 h e de 21 h;
  - desligado (`on: false`).
- `salvar_config`: hora inválida (`24:00`, `7:5`, `""`, número), retenção 0/61/bool, destino dentro de `data/`,
  destino inexistente, tipos errados.
- `verificar`:
  - zip bom;
  - CRC quebrado (byte trocado) → `testzip` acusa;
  - JSON inválido;
  - `v` maior;
  - hash diferente do manifesto;
  - membro `../x`, `C:\x` e nome fora da lista;
  - membro grande demais;
  - manifesto ausente.
- `gravar_zip`:
  - anexo citado que sumiu → `faltando`, sem falhar;
  - órfão fica de fora;
  - `.part` some quando falha;
  - JSON comprimido e anexo `STORED`.
- Nomes e tipos de arquivo; `estado()` com e sem histórico; `alerta` com 25 h, 27 h, falha recente e destino
  ausente.

**Integração**
- Backup com gravações simultâneas: uma thread faz `commit` em laço (inclusive com `_arquivar` passando do teto)
  enquanto outra faz backups. Todo zip verifica, e o par principal/arquivo morto é coerente (nenhuma demanda nos
  dois, nenhuma em nenhum).
- Anexo enviado e removido durante o backup.
- Destinos:
  - extra ausente → a cópia local fica ok e `ultima_falha` registra o extra;
  - sem permissão;
  - disco cheio (`disk_usage` simulado).
- Restauração:
  - dados e anexos voltam;
  - rev maior que antes;
  - `seq` não diminui;
  - `_TK` vazio, e um tk antigo recebe 401;
  - a cópia `antes-restaurar` existe e verifica;
  - falha no meio (zip ruim, `antes-restaurar` sem espaço) deixa `data/` intacto, byte a byte.
- Rotas pelo servidor real (como em `tests/test_servidor.py`): `maquina` 200; `completo`, `operador` e sem
  sessão → 403/401; Host e Origin estranhos recusados; dois `agora` juntos → um 409.
- Thread: `iniciar()` com `Event` e relógio falso roda uma vez no horário e não duas.

**jsdom (`tests/demandas_check.js`)**
- Painel do ADM com `backup.alerta` mostra o aviso com o texto certo. Sem alerta, nada.
- Operador nunca vê o aviso.
- Diálogo ⚙ Configurações, seção Backup:
  - liga e desliga;
  - lista das cópias;
  - o botão Restaurar abre o modal;
  - "Restaurar" só habilita depois de digitar `RESTAURAR`.
- Toast "Dados restaurados" quando chega `restaurado` novo.

**Mutação**
- `py -3 qa.py mutate demandas/demandas_backup.py` e as rotas novas do `servidor.py`. Meta de 80%, e 90% em
  `reter`, `deve_rodar`, `verificar` e `restaurar` (operações destrutivas).

## 8. Fases e esforço estimado

| Fase | Entrega | Esforço |
|---|---|---|
| 1 | `demandas_backup.py`: instantâneo, zip, manifesto, verificar, reter, estado, agendador. Só a pasta local. Testes unitários e de integração. | 2–3 dias |
| 2 | Seção Backup do ⚙ Configurações (sem restaurar) e aviso no Painel do ADM. jsdom. | 2 dias |
| 3 | Destino extra: escolher pasta, estado do destino, abrir pasta, pen drives sugeridos. | 1–2 dias |
| 4 | Restaurar pela tela: modal, cópia antes, rev e seq, `_TK`. Testes de falha no meio. | 2 dias |
| 5 | Ligações: aviso pelo estudo 02, e-mail pelo 04, destino fora da fábrica pelo 03. | depende dos outros |

Cada fase fecha com `py -3 qa.py all`, a mutação do código alterado e o relatório de 10 itens.

## 9. Ligações com os outros estudos

- **02 Avisos**:
  - o alerta "backup velho ou falhou" é um tipo de aviso do sistema (não de demanda);
  - se o 02 criar avisos persistentes, notificação do navegador ou sino do ADM, o backup só publica o evento
    `backup_falhou` / `backup_velho` e o 02 decide como mostrar;
  - até lá, o aviso fica fixo no Painel.
- **03 Continuidade e hospedagem**:
  - o destino extra fora da máquina é o primeiro passo de continuidade;
  - hospedado, o backup roda igual no servidor, com o destino num disco ou bucket separado;
  - o formato do zip e o manifesto servem para migrar do PC da fábrica para a hospedagem (exportar no PC,
    restaurar no servidor);
  - em SaaS, o zip passa a ser por empresa.
- **04 E-mail**: com e-mail configurado, mandar um aviso ao ADM depois de 2 falhas seguidas ou 48 h sem backup.
  **Não anexar o zip ao e-mail** (dados pessoais e códigos quebráveis, ver §6).
- **05 Calendário**: se o 05 criar turnos e expediente, o horário padrão do backup pode seguir o fim do expediente.

## 10. Mockups

| Arquivo | Mostra |
|---|---|
| `mockups/01-configuracoes-backup.html` | Diálogo ⚙ Configurações com a seção **Backup** ativa: liga/desliga e horário, "também ao ligar", destino local e extra com "Escolher pasta" e o estado (pen drive E: não encontrado), retenção 7/4/12 e limite de espaço, último backup (tamanho, hora, verificado ✓), "Fazer backup agora" e "Abrir pasta", lista das cópias com "Restaurar", e o **modal de confirmação** da restauração com o que vai acontecer. |
| `mockups/01-aviso-backup.html` | Painel do ADM com a faixa de aviso "Último backup há 3 dias: o destino (pen drive E:) não foi encontrado", no estilo do "Atenção agora", mais o alerta flutuante equivalente. |

## Dúvidas para o dono

1. O PC da fábrica fica ligado 24 h ou é desligado à noite? Isso define o horário padrão (12:00 proposto).
2. Qual destino extra existe de verdade: pen drive, outro PC na rede ou conta OneDrive/Google da empresa?
3. Aceita que o zip leve nomes, matrículas e os hashes dos códigos de 4 dígitos (quebráveis se o zip vazar)? Ou
   prefere exigir BitLocker no pen drive?
4. Na restauração, as pessoas nos tablets devem digitar o código de novo (proposto) ou continuar identificadas?
