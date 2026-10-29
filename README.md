# Central de demandas

Programa local para pedir, aceitar e acompanhar demandas entre setores da fábrica: painel com mapa de setores,
solicitações em quadro e lista, gaveta com histórico, pausas, comentários e anexos, cronoanálise e administração de
setores e pessoas. Roda num computador da fábrica e atende celulares, tablets e outros computadores do mesmo Wi-Fi.

Só Python 3.10+ (biblioteca padrão). Nada para instalar além dele.

## Como usar
1. Dê dois cliques em `iniciar.bat`. O navegador abre em `http://127.0.0.1:8090`.
2. Neste computador você entra como **Escritório** (Administrador): em **Administração**, cadastre os setores e as
   pessoas (cada pessoa tem um código de 4 dígitos).
3. As pessoas entram em **Quem é você?** com setor, nome e código, e passam a pedir e atender demandas.
4. Para usar em outros aparelhos: clique em **⚙ Configurações** (canto inferior esquerdo), seção **Rede**, ligue o acesso pela rede e feche e
   abra o `iniciar.bat`. O painel mostra o endereço e dois PINs:
   - **PIN do escritório:** abre tudo, inclusive a Administração;
   - **PIN dos operadores:** abre só a tela de operador.
   O PIN é pedido uma vez por aparelho e vale por 30 dias. Gerar um PIN novo derruba quem entrou com o antigo.

**Não monte túnel nem proxy neste computador** (ngrok, Cloudflare Tunnel, IIS, nginx etc.). Todo pedido que chega
pelo próprio computador (`127.0.0.1`) entra como Escritório, sem PIN: com um túnel, qualquer visitante da internet
viraria administrador. Para outros aparelhos, use só o acesso pela rede com PIN.

Feche a janela preta do servidor para desligar.

### Ligar sozinho com o Windows (recomendado no PC da central)
1. Botão direito em `instalar-inicio.bat` → **Executar como administrador**. Ele pede a senha da sua conta uma vez
   e cria a tarefa agendada "Central de demandas": a Central liga quando o Windows liga, antes de alguém entrar, sem
   janela preta, e religa em 5 s se parar (10 quedas em 2 minutos: desiste e anota o motivo). Tudo fica anotado em
   `data/servidor.log`. Trocou a senha da conta? Rode o instalador de novo. Para desfazer: `remover-inicio.bat`.
2. Com a tarefa instalada, o `iniciar.bat` só abre o navegador.
3. No PC: **suspensão e hibernação desligadas** (Opções de energia), na BIOS **ligar ao voltar a energia**
   ("Restore on AC power loss = Power On"), **IP fixo** reservado no roteador e **no-break no PC e no roteador**.
   Um PC que "dorme", ou um roteador sem energia, deixa todos os aparelhos sem a Central.

## Dados
Ficam em `data/` (fora do Git):

| Arquivo | O que guarda |
|---|---|
| `demandas.json` | setores, pessoas, demandas abertas e recentes e notificações |
| `demandas-arquivo.json` | concluídas e canceladas antigas (arquivo morto) |
| `demandas-anexos/` | anexos (JPG, PNG, PDF; até 5 MB cada, 5 por demanda, 300 MB no total) |
| `rede.json`, `sessoes.json` | configuração do acesso pela rede e sessões dos aparelhos (só o hash) |

Toda gravação é atômica e guarda o arquivo anterior como `.bak`: se o principal corromper, a leitura volta ao
`.bak`.

**Backup automático:** com o programa aberto, todo dia às 03:00 (e ao ligar, se a última cópia tem mais de 20 h) ele grava
`backup/central-demandas_AAAAMMDD-HHMM_<tipo>.zip` ao lado de `data/`. Cada zip é conferido depois de gravado
(`manifesto.json` com o SHA-256 de cada arquivo) e guarda `demandas.json`, `demandas-arquivo.json` e os anexos
citados; **não** leva `rede.json` nem `sessoes.json`. Ficam 7 diárias, 4 semanais e 12 mensais, até 5 GB.
Horário, pasta, quantas cópias guardar e "Fazer backup agora" ficam em **⚙ Configurações → Backup** (só no computador
principal); se o backup falhar ou passar de 26 h, o Painel do ADM avisa. Configuração em `data/backup.json` e resultado
em `data/backup-estado.json`. O zip tem nomes, matrículas e os códigos
das pessoas (protegidos, mas quebráveis): guarde-o num lugar seguro e, em pen drive, use BitLocker To Go.

**Restaurar:** em **⚙ Configurações → Backup**, botão **Restaurar** na cópia e confirmação digitando RESTAURAR. Antes de
trocar, o programa faz uma cópia "antes de restaurar" do estado atual (dá para desfazer por ela); os números SOL-n não
se repetem e as pessoas nos aparelhos digitam o código de novo. Sem o programa: feche-o e descompacte o zip dentro de
`data/`.

## Aviso por e-mail
1. Em **Administração**, ponha o e-mail (opcional) das pessoas e dos setores que devem receber avisos. Só o
   escritório vê e edita esse campo.
2. Em **⚙ Configurações → E-mail** (só no computador principal): servidor SMTP, porta, segurança, usuário, senha e
   remetente. Peça os dados ao TI. Gmail e Google Workspace: use uma **senha de app**. Microsoft 365: a senha simples
   deixa de funcionar por padrão no fim de 2026 (o TI pode precisar liberar o "SMTP AUTH"). Use **Enviar teste**,
   ligue e salve.
3. Por padrão só "demanda criada" avisa (quem vai fazer; fila do setor: o e-mail do setor ou, sem ele, as pessoas do
   setor). Aceita, concluída, cobrada, atrasada, comentário e cancelada podem ser ligadas na mesma tela.

A tela nunca espera o envio: o e-mail entra numa fila (`data/email-fila.json`) e sai em até um minuto, com novas
tentativas (1, 5, 15, 60 e 180 min). Senha recusada para a fila até alguém clicar em **Retomar**. O resultado fica em
`data/email-log.json` e aparece na gaveta da demanda para o escritório. A senha fica em `data/email.json`, protegida
pelo Windows: só abre neste computador e com este usuário (num PC reserva, digite de novo). Todos os e-mails de uma
demanda ficam no mesmo fio, `[SOL-n] título`, e o botão "Abrir a demanda" só funciona dentro da rede da fábrica.

## Avisos na tela
Com a tela aberta, cada aviso novo toca um som, vibra (Android) e mostra o número na aba; com a aba escondida, o
título pisca. Cada pessoa escolhe em **Meus avisos** (pelo sino ou pelo nome no topo) o que avisa, o horário de
silêncio e se o urgente toca mesmo assim; som e vibração são escolhidos em cada aparelho. Os padrões para quem nunca
mexeu ficam em **⚙ Configurações → Avisos** (só no computador principal). Tudo fica em `data/avisos.json`, que entra
no backup. Avisos com o app fechado (push) dependem de HTTPS e ainda não existem.

Trazer dados de outra instalação: copie `demandas.json`, `demandas-arquivo.json` e `demandas-anexos/` para esta
`data/` com o programa fechado. O formato é o mesmo do módulo Demandas do CutFlow, de onde este programa saiu.

## Estrutura
| Caminho | Papel |
|---|---|
| `servidor.py` | servidor HTTP: página, arquivos do módulo, API, PIN, sessões e defesas (Host, Origin, CSP) |
| `store.py` | gravação segura dos JSON |
| `email_envio.py` | aviso por e-mail: configuração (senha protegida pelo Windows), fila, envio SMTP e registro |
| `demandas/` | o módulo: `api.py` (rotas, regras e permissões), `demandas_calc.py` (tempos e cronoanálise), `demandas_store.py` (dados e anexos), `demandas_backup.py` (backup automático), `demandas_avisos.py` (preferências de aviso), `demandas.js`/`.css` (tela), fontes, `CONTRATO.md` |
| `web/` | a página (`index.html`) e a casca (`app.js`: `api()`, avisos, atualização e o botão ⚙ Configurações) |
| `tests/` | testes Python e o teste de tela em jsdom |

Variáveis opcionais: `DEMANDAS_PORT` (porta, padrão 8090) e `DEMANDAS_DATA` (pasta de dados).

## Qualidade
Regra em [docs/QUALIDADE.md](docs/QUALIDADE.md). Ferramentas de desenvolvimento em `requirements-dev.txt`
(coverage, ruff, mutmut) e, para o teste de tela, `npm install jsdom` dentro de `tests/`.

```bash
py -3 qa.py all
```

```bash
py -3 qa.py mutate demandas/api.py
```
