# Plano de implementação: novas funções da Central de demandas

> Documento de continuidade, escrito em 28/10/2026, depois da aprovação dos mockups pelo dono. Serve para qualquer
> pessoa ou agente que retome o trabalho sem o histórico da conversa. **Leia este arquivo inteiro antes de mexer em
> código.**

## 1. Onde está cada coisa

| O quê | Onde |
|---|---|
| Regras do projeto (obrigatório) | `CLAUDE.md` e `docs/QUALIDADE.md` |
| Resumo dos estudos, decisões comuns e pendências | `docs/estudos/README.md` |
| Estudos detalhados (código atual com `arquivo:linha`, dados novos, rotas, testes exigidos, fases) | `docs/estudos/01-backup.md` … `05-calendario-cronograma.md` |
| Mockups **aprovados** (referência visual) | `docs/estudos/mockups/index.html` (abre no navegador, sem servidor) |
| Este plano | `docs/estudos/PLANO-IMPLEMENTACAO.md` |

Estado em 28/10/2026:
- Nada foi implementado. O último commit é `00adaca`.
- `docs/estudos/` e `brag-output/` não estão no Git. **`brag-output/` não deve ir para o Git** (decisão do dono).

## 2. Regras que valem para toda etapa

1. **Qualidade (`docs/QUALIDADE.md`).** Nenhuma etapa termina sem:
   - testes criados ou atualizados e executados;
   - `py -3 qa.py all` verde;
   - `py -3 qa.py mutate <arquivo>` do código alterado, com meta de 80% (90% em contas de tempo), analisando cada
     mutante sobrevivente;
   - relatório final de 10 itens (seção 14 de `docs/QUALIDADE.md`) com os números da execução atual.
2. **Só biblioteca padrão do Python.** Nada de dependência nova sem o dono aprovar. A única exceção prevista é
   `cryptography`, opcional, para o push do estudo 02, fase 6.
3. **Projeto independente.** Não importar nem ler nada de outro projeto (o CutFlow/NESTING-V2).
4. **Compatibilidade.** O `demandas.json` que já existe tem de continuar abrindo. Campos novos são opcionais.
   Mudança de formato passa pela migração com cópia `.v<n>.bak` que já existe em `demandas/demandas_store.py`.
5. **Git só local.** Uma etapa por branch ou commit. Não fazer push sem o dono pedir.
6. **Não encerrar processos que você não iniciou.** O servidor do dono roda na porta 8090. Para testar, use outra
   porta (`DEMANDAS_PORT`) e uma pasta de dados temporária (`DEMANDAS_DATA`).
7. **Visual.** Siga os mockups aprovados e use as classes e tokens `--dm-*` de `demandas/demandas.css`.
   - Ao implementar, unifique o estilo do diálogo ⚙ Configurações: os mockups das seções variam um pouco entre si.
   - Use como base `docs/estudos/mockups/00-configuracoes.html` e `03-configuracoes-servidor.html`.
8. Responder ao dono em **português do Brasil**.

## 3. Decisões de arquitetura já tomadas (comuns a todas as etapas)

- **Uma só thread de fundo** (daemon) em `servidor.py` `main()`, entre `api_mod()` e `serve_forever()`.
  - Acorda a cada 60 s e roda tarefas registradas: backup (01), checagem de atraso (02), fila de e-mail (04).
  - A falha de uma tarefa não derruba as outras.
  - Para teste, aceita relógio injetável.
- **Um só gancho de eventos.**
  - Os eventos são juntados sob o LOCK em `_evento` (`demandas/api.py`).
  - São despachados depois de gravar, pelo callback `depois` de `_gravar`, fora do LOCK.
  - Avisos, som e e-mail consomem esse mesmo despacho. Comentário precisa de gancho próprio em `_comentar`,
    porque hoje não gera evento.
- **Diálogo "⚙ Configurações"** substitui o "⚙ Rede" (`web/index.html`, `web/app.js`).
  - Seções: Rede · Backup · E-mail · Avisos · Servidor.
  - Autorização por uma função única, como `pode(ctx, "configurar")`, e não por `papel == "maquina"` espalhado.
    Isso prepara a hospedagem (estudo 03).
- **Configuração e estado em arquivos próprios em `data/`**, fora do `demandas.json`, porque `_normaliza`
  descarta chaves desconhecidas:
  - `backup.json` e `backup-estado.json`;
  - `email.json`, `email-fila.json` e `email-log.json`;
  - `avisos.json`.
  - Todos gravados com `store.atomic_write`.
- **Backup** não leva `rede.json` nem `sessoes.json`. A senha SMTP vai protegida por DPAPI.
- **E-mail da pessoa e do setor** aparece só na vista do ADM: a lista de pessoas também vai para os operadores.
- Preparar para hospedagem sem custo extra:
  - passar `ctx["tenant"] = "padrao"` nas rotas novas;
  - não criar contador global;
  - datas em ms UTC.

## 4. Ordem de implementação

Cada etapa vira uma entrega independente: código, testes, mutação, relatório e commit. **Antes de cada etapa, leia o
estudo correspondente inteiro**. Ele tem os detalhes, formatos JSON, rotas e a lista de testes.

### Etapa 0: consertos pequenos já identificados (≈ 0,5 dia)
- Rótulo "1 dia útil (8h)" → "8 h" em `demandas/demandas.js` (perto da linha 772): o prazo conta tempo corrido.
  Ver estudo 05, seção 1.
- Pôr no README um aviso de que não se deve montar túnel ou proxy no PC servidor. Ver estudo 03.

### Etapa 1: Backup (estudo 01, fases 1–4; ≈ 7–9 dias)
1. Módulo novo `demandas_backup.py` com:
   - instantâneo: JSON lido sob `demandas_store.LOCK`, anexos copiados fora do LOCK;
   - zip com `manifesto.json` (SHA-256);
   - verificação, retenção 7/4/12 com limite de espaço, `backup-estado.json`.
2. A **thread de fundo comum** em `servidor.py` (primeira tarefa: backup), mais a cópia ao ligar se a última tiver mais
   de 20 h.
3. Diálogo ⚙ Configurações com as seções **Rede** (migrada do ⚙ Rede) e **Backup**. Mockups `00-` e
   `01-configuracoes-backup.html`.
4. Aviso de backup velho ou com falha no Painel do ADM. Mockup `01-aviso-backup.html`.
5. Destino extra (pen drive, pasta de rede, OneDrive).
6. Restaurar pela tela:
   - fazer uma cópia antes;
   - `rev` = máximo + 1 e `seq` nunca menor que o atual;
   - limpar `_TK`;
   - confirmação digitando RESTAURAR.

### Etapa 2: Robustez local (estudo 03, fase 0; ≈ 7–9 dias)
1. `servidor-sempre.bat` com laço de reinício, mais tarefa agendada "ao iniciar o sistema" (`instalar-inicio.bat`).
   `iniciar.bat` detecta o servidor já ligado.
2. Faixa "Sem conexão com a central…" nos aparelhos: falha do polling em `web/app.js`, modo só leitura, "Tentar agora".
3. Rascunho do formulário que não se perde quando a resposta é 401 ou a conexão cai. Id do cliente (`cid`) para não
   duplicar uma solicitação.
4. Sessão da pessoa (`_TK`) persistida, para sobreviver a um reinício.
5. Seção **Servidor** nas Configurações (`/api/servidor`). Mockup `03-configuracoes-servidor.html`. Faixa
   `03-servidor-fora.html`.

### Etapa 3: E-mail (estudo 04, fases 1–4; ≈ 6–7 dias)
1. Campo opcional `email` em pessoa e setor: API, validação, modais `renderUF`/`renderSF`, vista só do ADM. Mockup
   `04-cadastro-email.html`.
2. Módulo `email_envio.py`:
   - configuração com senha em DPAPI;
   - montagem com `EmailMessage` (texto + HTML com escape), um fio por demanda (`Message-ID <SOL-n@…>`,
     `In-Reply-To`, `References`, assunto `[SOL-n] título`);
   - fila em disco, envio pela thread comum com espera crescente, `email-log.json`.
3. Primeiro só o evento "demanda criada". Fila do setor sem pessoa → e-mail do setor.
4. Seção **E-mail** nas Configurações, com "Enviar teste", estado da fila e registro. Mockup
   `04-configuracoes-email.html`.
5. Eventos opcionais (aceita, concluída, cobrança, atraso, comentário, cancelada), linhas ✉ na gaveta lidas do log,
   abrir `#SOL-n` pelo link.
- **Não** gravar "e-mail enviado" como evento da demanda. Isso mudaria o `rev` a cada envio e consumiria o teto
  de 500 eventos.

### Etapa 4: Avisos sem HTTPS (estudo 02, fases 1–5; ≈ 6–7 dias)
1. Nota por **pessoa** (`pid`) e "lida" por pessoa. Hoje, ler marca como lido para o setor inteiro. Nota antiga sem
   `pid` continua aparecendo.
2. Aviso de comentário.
3. Tarefa de atraso na thread comum, a cada minuto (`tick`).
4. Camada 1 na tela: som curto, título da aba piscando com o contador, vibração no Android, agrupamento, gaveta do
   sino nova. Mockups `02-central-avisos.html`, `02-celular-avisos.html` (a).
5. Preferências: `data/avisos.json`, rota `aviso/prefs`, tela "Meus avisos" e seção **Avisos** nas Configurações.
   Mockups `02-preferencias-avisos.html`, `02-configuracoes-avisos.html`.
6. Bônus no PC principal: Notification API e Wake Lock em `http://127.0.0.1`, que é contexto seguro.

### Etapa 5: Calendário e cronograma (estudo 05, fase 1; ≈ 5–7 dias; não muda dados)
1. Aba **Calendário** do ADM (mês, semana, dia), montada no navegador a partir da vista atual, que já traz o `prazo`.
   Mockups `05-calendario-mes.html`, `05-calendario-semana.html`.
2. Cronograma de vários dias como modo da Cronoanálise:
   - leitura nova `cronograma {de, ate, por}` no servidor, porque o `gantt` atual tem janela fixa de 13 h;
   - CSS com `--dm-gcols` no lugar das 13 colunas fixas.
   - Mockup `05-cronograma.html`.

### Depois (cada um precisa de um ok do dono antes)
- Estudo 05, fase 2: `inicio_plan` e `prazo_em` gravado (formato v2, migração), formulário com data e hora. Mockup
  `05-nova-solicitacao-data.html`. Fase 3: expediente e feriados, só se houver turnos fixos. Fase 4: `.ics`.
- Estudo 03, fase 1: armazenamento atrás de uma interface (`Banco`/`BancoJson`) com tenant implícito. **Obrigatória
  antes de qualquer hospedagem.**
- Estudo 03, fases 2–3: hospedagem (HTTPS com Caddy, login por pessoa, SQLite, multiempresa).
- Estudo 02, fase 6: Web Push com o app fechado, só com HTTPS. Estudo 05: feed `webcal://`.

## 5. Decisões pendentes do dono (perguntar quando a etapa chegar)

**Etapa 1 (backup)**: respondidas pelo dono em 28/10/2026
- PC ligado 24 h → horário padrão **03:00**. A cópia ao ligar (última com mais de 20 h) continua, como rede de
  segurança.
- Destino extra: **nenhum por enquanto**. Só a pasta local; o destino extra (fase 3) fica configurável, sem pressa.
- BitLocker: **só avisar na tela** que o zip tem nomes, matrículas e códigos, recomendando BitLocker To Go.
- Restaurar: **as pessoas se identificam de novo** (limpar `_TK`).

**Etapa 3 (e-mail)**
- Qual conta de envio (SMTP da empresa, Microsoft 365, Google Workspace ou Brevo/SES)?
- Quais eventos além de "criada" mandam e-mail? O solicitante recebe cópia?
- Fila do setor vai para o e-mail do setor ou para todas as pessoas?
- A descrição vai no e-mail?

**Etapa 4 (avisos)**
- No tablet compartilhado, o aviso é do setor ou da pessoa?
- O texto da demanda pode aparecer na tela bloqueada?

**Etapa 5 (calendário)**
- O cronograma fica dentro da Cronoanálise (proposto) ou numa aba própria?
- O operador ganha "Minha agenda de hoje"?

**Hospedagem**
- Uma empresa só ou SaaS?
- Código de 4 dígitos para operador e senha para ADM?
- Servidor no Brasil?

## 6. Como retomar (texto para colar no novo chat)

> Projeto em `C:\Users\Maria\Documents\PROJETOS\DEMANDA PIU` (Central de demandas). Leia `CLAUDE.md`,
> `docs/QUALIDADE.md`, `docs/estudos/PLANO-IMPLEMENTACAO.md` e `docs/estudos/README.md`. Os mockups em
> `docs/estudos/mockups/` estão aprovados. Comece pela **Etapa 0 e depois a Etapa 1 (Backup)**: leia
> `docs/estudos/01-backup.md` inteiro, faça um plano curto, me pergunte as decisões pendentes da etapa e implemente
> seguindo a regra de qualidade (testes, `py -3 qa.py all`, mutação e relatório de 10 itens). Não use a porta 8090
> para testes e não encerre processos que você não iniciou.
