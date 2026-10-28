# Estudo 05 · Calendário e cronograma

> Só estudo. Nenhuma linha do programa muda agora. Consulta feita em 28/10/2026.

## 1. Resumo

- **É viável.** A fase 1 não muda o formato dos dados. Calendário e cronograma multidia saem do que a vista já entrega (`prazo`, `segs`).
- Calendário faz sentido para **PCP e gestão (ADM)**. Para o operador, basta uma faixa "Minha agenda de hoje" dentro de "Recebidas". Um calendário mensal não ajuda quem faz tarefas de 30 min a 8 h.
- **Achado importante:** o atalho "1 dia útil (8h)" do formulário promete dia útil, mas o prazo conta em tempo corrido. Um pedido criado às 16:00 vence à meia-noite e vira "atrasada" durante a noite, com evento e aviso.
- Ordem recomendada: (1) calendário derivado + cronograma multidia; (2) `inicio_plan` + `prazo_em` congelado (formato v2); (3) expediente e feriados; (4) `.ics` por demanda e, quando houver hospedagem, o feed.
- Arrastar para reagendar fica para depois da fase 2, só para o ADM. Feed `webcal://` no Google só funciona com o servidor na internet.

## 2. Como é hoje

**Prazo e atraso**
- Prazo = `criado + est·60000`, em tempo corrido: `demandas/demandas_calc.py:39-40`. Não existe data planejada, turno nem feriado.
- Atrasada = ativa e `agora > prazo`: `demandas_calc.py:84-85`. Concluída com atraso: `demandas_calc.py:88-89`. O valor não é gravado, é recalculado.
- SLA = `total / est · 100`, com total em tempo corrido desde a criação: `demandas_calc.py:96-100`.
- O evento "late" só é gravado quando alguém grava alguma coisa, pela função `marcar_atrasos`: `demandas/api.py:286-297`. É chamada em `_gravar`: `api.py:753-759`.
- `estender` soma minutos em `est` (até 30 dias). Se o novo prazo ficar no futuro, zera `atraso_avisado`: `api.py:471-482`.
- `est` vai de 1 a 43200 minutos (`EST_MAX`, `api.py:37`) e é validado em `_criar` (`api.py:326`). O normalizador usa 60 como padrão: `demandas/demandas_store.py:100`.

**Cronoanálise e Gantt**
- `crono` aceita só `dias` ∈ {1, 7, 30}: `api.py:726-731`. Sempre devolve `gantt(...)`: `demandas_calc.py:280-281`.
- `gantt` usa a janela fixa `agora-10h … agora+3h`. Mostra as 14 ativas mais urgentes e as 4 concluídas mais recentes: `demandas_calc.py:284-294`. Os trechos de espera, execução e pausa vêm de `segs`: `demandas_calc.py:210-229`.
- Na tela, `gantt(g)` está em `demandas/demandas.js:479-495`. O eixo marca uma hora sim, outra não (`h % 2 === 0`). O "agora" é deduzido como `fim - 3h` (`NOWg`, `:481`).
- No CSS, a grade da trilha é `background-size: calc(100% / 13)`, ou seja, 13 colunas de 1 h: `demandas/demandas.css:387`. Também em `demandas.css`: rótulo de 240 px (`:382`), eixo com `margin-left:250px` (`:380`), barras `.dm-gs` (`:388-391`), prazo `.dm-gd` (`:392-393`) e agora `.dm-gnow` (`:394`).
- `inicio_do_dia` usa o fuso do PC servidor: `demandas_calc.py:232-234`.

**Formulário e tela**
- O "Tempo estipulado" do formulário (`renderForm`, `demandas.js:757-777`) tem atalhos de 30 min, 1 h, 2 h, 4 h e "1 dia útil (8h)" (`:772`). O campo personalizado aceita de 1 a 43200 min (`:773`). A prévia é `prevTxt`: "Prazo final: … (x a partir de agora)" (`:778`).
- A gaveta mostra "Prazo: <data>" e "Faltam/Atrasada há" (`renderDrawer`, `demandas.js:637-660`, linha `:648`). O ADM tem os botões +30 min e +1 h (`actionsHtml`, `:621`).
- Abas do ADM: Painel, Solicitações, Histórico, Cronoanálise, Administração (`renderTabs`, `demandas.js:338-345`). A view é escolhida em `renderView` (`:946-956`).
- A vista do ADM já traz **todas** as demandas do arquivo principal, com `prazo` calculado (`calc.vista`, `demandas_calc.py:150-166`, e `publica`, `:109-114`). As do arquivo morto saem pela leitura `historico` `{de, ate}`, filtrada por `criado` (`api.py:720-723`).

**Dados e versão**
- O formato tem versão `V = 1` (`demandas_store.py:20`). Arquivo antigo é migrado em `_migra`: guarda `demandas.json.v<n>.bak` e grava o novo (`demandas_store.py:158-164`). Arquivo de versão maior é recusado (`:176-177`).
- `_demanda` normaliza campos conhecidos e **mantém** chaves desconhecidas: `demandas_store.py:95-110`.

**Para quem é a demanda.** São tarefas curtas de chão de fábrica, de minutos a horas. A média estimada aparece na cronoanálise (`kpis.estimado`).
- **ADM / PCP:** um calendário responde "o que vence quando, e onde acumula". Serve para planejar a carga da semana e conversar com o cliente.
- **Operador:** um calendário mensal é ruído. Ele precisa saber "o que é meu hoje e até que horas", e isso a lista ordenada por `sortAtt` (`demandas.js:108`) já quase dá. No máximo, uma faixa "Minha agenda de hoje".

## 3. Opções comparadas

| # | Opção | Prós | Contras | Esforço | Impacto |
|---|---|---|---|---|---|
| 1 | Calendário de prazos derivado (mês/semana/dia) | Nenhuma mudança de dados. 100% front-end com a vista atual. Mostra a concentração de prazos por dia e setor. | Posiciona só pelo prazo e pela conclusão. Não existe "início planejado". Demandas de minutos viram bloquinhos finos na semana. | P (2–3 d) | Médio para o ADM |
| 2 | Campos `inicio_plan` e `prazo_em` | Permite agendar ("começar amanhã 7h") e prometer data e hora fixas. Prepara a fase 3. | Formato v2, migração e mudança em `prazo()`, `espera_ms`, `estender` e fila do operador. | M (4–6 d) | Alto para o PCP |
| 3 | Expediente, turnos e feriados por setor | Corrige o "1 dia útil (8h)". Fim dos atrasos noturnos falsos. | Todas as métricas mudam. Exige configuração e um calendário de feriados. Risco de reescrever atrasos passados (mitigado congelando `prazo_em`). | G (6–10 d) | Alto, mas só se houver turno fixo |
| 4 | Cronograma multidia (Gantt por setor ou pessoa) | Reaproveita `segs`. Mostra plano × real. É a visão que o PCP já usa no papel. | Leitura nova no servidor e CSS sem as 13 colunas fixas. Fica denso com mais de 60 linhas. | M (3–4 d) | Alto para o ADM |
| 5a | `.ics` por demanda (baixar) | Simples: um texto RFC 5545. Combina com o e-mail do estudo 04. | Cópia estática: se o prazo muda, o evento no Outlook fica velho. | P (1 d) | Baixo |
| 5b | Feed `webcal://` por setor | Agenda do setor sempre no Outlook ou no Google. | Precisa de token na URL (o cliente de calendário não faz login). O Google exige servidor na internet e atualiza devagar (até ~12 h). | M (3 d) + hospedagem | Baixo hoje |
| 6 | Arrastar para reagendar (ADM) | Rápido para o PCP. | Arraste no celular é ruim, arrasto sem querer muda prazos, e falta um evento novo. Só faz sentido depois da opção 2. | M (3 d) | Médio |

## 4. Recomendação

1. **Fase 1, sem mudar dados:**
   - aba **Calendário** do ADM (mês, semana e dia) derivada de `prazo` e `fim`;
   - **cronograma multidia** como modo dentro da Cronoanálise;
   - já trocar o rótulo "1 dia útil (8h)" por "8 h" e dizer na prévia que o tempo é corrido. É honesto e custa uma linha.
2. **Fase 2:**
   - `inicio_plan` opcional;
   - `prazo_em` gravado e **congelado** no criar, no estender e no reagendar;
   - no formulário, "Prazo em data e hora" e "Agendar início";
   - formato v2.
3. **Fase 3:** expediente e feriados, só se o dono confirmar turnos fixos por setor. O `prazo_em` congelado da fase 2 garante que os atrasos passados não mudem.
4. **Fase 4:** `.ics` por demanda, junto com o e-mail do estudo 04. O feed `webcal://` só depois da hospedagem do estudo 03.

**Por quê:** a fase 1 entrega a visão que o PCP quer, com risco quase zero. O formato de dados só muda quando houver um pedido real de agendamento.

## 5. Como encaixa no código atual

### Fase 1: calendário derivado + cronograma

**Calendário (só front-end)**
- `demandas.js`:
  - em `renderTabs` (`:342`), entra `['cal', 'Calendário', '']` entre Histórico e Cronoanálise;
  - em `renderView` (`:952`), entra `D.tab === 'cal' ? vCal()`;
  - em `symbols` (`:1236`), um ícone novo `dm-i-cal`.
- Estado novo em `D` (`:26`): `cal: {modo: 'mes'|'semana'|'dia', ref: <ms>, sec: '', dia: <ms>}`.
- A função `vCal()` agrupa `reqs()` por dia local do prazo. Ativas usam `prazo`; concluídas usam `fim`, com um marcador de prazo. Reaproveita `dispSt`, `lateNow`, `chip`, `pill` e `card` no painel lateral. O clique no chip usa `data-act="open"`, a gaveta que já existe.
- Meses passados com demandas no arquivo morto chamam a leitura `historico` com `{de, ate}` do mês (já existe, `api.py:720`). Um porém: ela filtra por `criado`, então uma demanda criada no mês anterior com prazo no mês pedido escapa. Para resolver, aumentar a janela em `EST_MAX` (30 dias) para trás e filtrar no cliente.
- Na semana, a altura do bloco vai de `criado` (ou `iniciado`) até `prazo`. Faixa de 6h a 22h, como no mockup.

**Cronograma (servidor + front-end)**
- `demandas_calc.py`: generalizar `gantt(demandas, agora, ini=None, fim=None, por=None, limite=None)`.
  - Com `ini`/`fim` omitidos, mantém a janela atual de 13 h e os testes antigos continuam válidos.
  - Com `por="setor"|"pessoa"`, devolve `grupos: [{chave, linhas: [...]}]`.
  - A escolha das linhas passa a ser "ativa, ou com algum `seg` dentro da janela, ou com prazo dentro da janela".
  - Cada linha ganha `plano: {a: criado, b: prazo}`, a barra fina de plano sob a real.
- `api.py`: leitura nova `cronograma`, só ADM (`_so_adm`).
  - Body: `{de, ate, por}`, com `ate - de` ≤ 31 dias e `por` ∈ {setor, pessoa}.
  - Usa `_todas(doc)`, como `_crono`.
  - Entra em `LEITURAS` (`api.py:750`).
  - A rota não precisa entrar em `OPERADOR_RE` (`servidor.py:63-65`).
- `demandas.js`: `gantt(g)` passa a receber `{ini, fim, agora, escala}`.
  - O eixo é gerado por escala: `dia` = marca a cada 2 h; `semana` = rótulo de data por dia e marcas a cada 6 h; `mes` = rótulo por dia.
  - `NOWg` vem de `g.agora`, e não mais de `fim - 3h`.
  - Linhas de grupo (`.dm-ggrp`) com o chip do setor.
- `demandas.css`:
  - a trilha deixa de usar `calc(100% / 13)` fixo (`:387`) e passa a receber a variável `--dm-gcols` por inline style (`style="--dm-gcols:7"`), com `background-size: calc(100% / var(--dm-gcols, 13))`; o padrão 13 mantém a tela atual;
  - classes novas `.dm-ggrp`, `.dm-gplan`, `.dm-gday` (faixa do fim de semana) e `.dm-gaxis2` (eixo de duas linhas: data em cima, hora embaixo).
- A Cronoanálise ganha o seletor "Linha do tempo: 13 h | Dia | Semana | Mês". Nos três últimos, a tela chama `cronograma` e não usa `c.gantt`.

### Fase 2: `inicio_plan` e `prazo_em`

**Regra de compatibilidade.** `est` continua sendo a fonte do **tempo de trabalho**. `prazo_em` é o **resultado congelado**, calculado pelo servidor:

```
base     = max(criado, inicio_plan or criado)
prazo_em = base + est·60000                  (fase 2: corrido)
prazo_em = soma_util(base, est, expediente)  (fase 3: útil)
prazo(d) = d.get("prazo_em") or d["criado"] + d["est"]·60000
```

- Quando o usuário escolhe "Prazo em data e hora", o servidor faz o caminho inverso: `est = ceil((prazo_em - base) / 60000)` (corrido na fase 2, minutos úteis na fase 3). O resultado precisa ficar em 1..`EST_MAX`. Assim `est`, `sla` e a cronoanálise continuam fazendo sentido.
- O prazo só é recalculado em `criar`, `estender` e `reagendar`. Mudar o expediente depois **não** mexe em prazo gravado.

**Exemplo de demanda v2:**
```json
{"id": "SOL-1043", "titulo": "Soldar suporte do eixo 2", "est": 240,
 "criado": 1793174400000, "inicio_plan": 1793260800000, "prazo_em": 1793275200000,
 "status": "new", "de": {"s": "PCP", "p": null}, "para": {"s": "SOLDA", "p": null}}
```

**Migração v1 → v2** (`demandas_store.py`):
- `V = 2`. `_migra` já guarda `demandas.json.v1.bak`. O comentário "v0 -> v1: só ganha o número" (`:162`) passa a ter um passo por versão.
- v1→v2 grava `prazo_em = criado + est·60000` em todas as demandas, inclusive no arquivo morto, para congelar o passado. `inicio_plan` fica ausente.
- `_demanda` normaliza `prazo_em` e `inicio_plan` como `_int(…, None)`.
- **Por que subir a versão:** sem isso, um programa antigo leria o arquivo, ignoraria `inicio_plan` e calcularia prazos errados sem avisar. Com `V = 2`, ele recusa (`:176-177`).

**Impactos**
- `estender` (`api.py:471`): soma em `est` e recalcula `prazo_em` a partir da mesma base. Na fase 3, a soma é em tempo útil a partir do prazo atual (`prazo_em + minutos úteis`), para "+1 h" significar uma hora de trabalho.
- `atrasada`, `atrasou_concluida` e `chave_atencao` já usam `prazo()`, então não mudam.
- `espera_ms` (`demandas_calc.py:66-67`) passa a contar a partir de `base`. Quem agendou para amanhã não está "esperando" hoje.
- `total_ms` e o SLA também partem de `base`.
- O `segs` ganha um trecho `{"k": "plan", a: criado, b: inicio_plan}`, desenhado em cinza claro.
- Em `atencao` (`demandas_calc.py:181-205`), a regra "sem aceite há 25 min" passa a contar de `base`.
- **Fila do operador** com `inicio_plan` no futuro: aparece em "Fila do setor" com a etiqueta "Agendada · seg 07:00", desbotada e sem o botão Aceitar antes da hora? **Decisão do dono.** A sugestão é permitir aceitar antes (adiantar é bom) e só ordenar depois das que já valem.
- Rota nova `demanda/reagendar`, só ADM: `{id, inicio_plan?, prazo_em?}`. Gera o evento `deadline` com a nota "Reagendada: seg 03/11 07:00 → ter 04/11 07:00". Não precisa de tipo novo de evento, `EVL` já tem "Prazo ajustado".
- `demanda/criar` aceita `inicio_plan?` e `prazo_em?` (mutuamente exclusivo com `est`). Atualizar a tabela em `CONTRATO.md` e `OPERADOR_RE` não muda.

### Fase 3: expediente, turnos e feriados

**Configuração** em `doc["agenda"]`, editada só pelo ADM (aba Administração, sub-aba "Expediente"):
```json
{"agenda": {"padrao": {"turnos": [["07:00","12:00"],["13:00","17:00"]], "dias": [1,2,3,4,5]},
            "setores": {"SOLDA": {"turnos": [["06:00","14:00"],["14:00","22:00"]], "dias": [1,2,3,4,5,6]}},
            "feriados": ["2026-11-02", "2026-11-15", "2026-11-20", "2026-12-25"]}}
```

**Cálculo**
- Funções puras novas em `demandas_calc.py`: `soma_util(ini, minutos, agenda, setor)` e `util_entre(a, b, agenda, setor)`. São percursos dia a dia pelos turnos, com limite de 400 dias.
- O fuso é o do servidor (`datetime` local). Se o sistema for SaaS (estudo 03), o fuso vira campo da empresa.

**Métricas**
- `atrasada` não muda, porque compara com `prazo_em`.
- Todas as durações (`espera`, `execucao`, `pausado`, `total`, `sla`) passariam a ter duas versões, corrida e útil. A proposta é a cronoanálise mostrar a **útil** só para demandas com `agenda_v` (marca gravada na criação) e manter a corrida para as antigas. Sem isso, os números históricos mudam quando se edita um feriado.

**Risco de "atrasos passados mudarem":** eliminado pelo `prazo_em` congelado. Só as métricas de duração útil dependem da configuração atual. Por isso convém gravar `agenda_v` (a versão da configuração) na demanda e guardar as versões anteriores da agenda.

**Vale a pena?** Só se:
- houver turnos fixos e respeitados;
- houver queixa real de atraso noturno ou de fim de semana.

Até lá, a correção barata do rótulo "1 dia útil (8h)" e a opção de prazo em data e hora (fase 2) resolvem a maior parte dos casos.

### Fase 4: `.ics`

**`.ics` por demanda**
- GET `/api/local/demandas/ics/<id>`, com a mesma sessão de quem vê a demanda (`calc.ve`).
- Devolve `text/calendar` com `VEVENT`:
  - `UID: SOL-1043@<instalação>`;
  - `DTSTART: inicio_plan ou criado`;
  - `DTEND: prazo`;
  - `SUMMARY: [SOLDA] Soldar suporte`;
  - `SEQUENCE`: o `_rv` da demanda.
- Não precisa de biblioteca: é texto RFC 5545 com dobra de linha em 75 octetos e escape de `,;\`.
- Para o operador, a rota entra em `OPERADOR_RE`.

**Feed por setor** (`webcal://host:8090/feed/<setor>.ics?k=<token>`)
- O cliente de calendário não faz login nem guarda cookie. Hoje, quem vem da rede sem sessão recebe 401 (`servidor.py:279-296`).
- O feed precisa então de um token aleatório por setor, guardado com hash em `rede.json`, revogável no diálogo de Configurações, só leitura, só demandas ativas e dos últimos 7 dias.
- Rota pública fora de `_auth_ok`, como exceção explícita.

**Fatos externos** (consultados em 28/10/2026):
- **Google Agenda:** "Adicionar por URL" exige um calendário público. A busca é feita pelos servidores do Google, então uma URL de rede local ou `127.0.0.1` não funciona. Fonte: [Google Agenda: assinar o calendário de outra pessoa](https://support.google.com/calendar/answer/37100) ("only add a calendar with a link if … public"). A busca pelo lado do Google e o fato de `localhost` não funcionar são dedução minha, não confirmada pelo Google.
- **Intervalo de atualização no Google:** a doc oficial não diz. Fornecedores relatam que leva até cerca de 12 h e que o Google ignora `REFRESH-INTERVAL`/`X-PUBLISHED-TTL`. Fontes: [Cheqroom: how often does Google update its calendar feeds](https://knowledge.cheqroom.com/helpcenter/how-often-does-google-update-its-calendar-feeds) e [nocal.app](https://nocal.app/help/google-calendar/subscribe-to-ical-feed). **Não confirmado oficialmente.**
- **Outlook clássico (desktop):** quem baixa a assinatura é o próprio Outlook, no PC, "at the publisher's recommended interval". Ele aceita URL `webcal://` e a doc cita calendário publicado "on an internal server". Fonte: [Microsoft Learn: Configure Internet Calendars in Outlook 2007](https://learn.microsoft.com/en-us/previous-versions/office/office-2007-resource-kit/cc179094(v=office.12)). É uma doc antiga, de 2007. Não achei doc atual. Relatos de 2023–2026 dizem que o intervalo real não segue as dicas do feed: [Microsoft Q&A](https://learn.microsoft.com/en-us/answers/questions/5956480/classic-outlook-internet-calendar-subscription-not).
- **O novo Outlook e o Outlook.com:** pelos relatos, a assinatura é sincronizada pela nuvem da Microsoft, o que exigiria servidor na internet como no Google. **Não confirmado em doc oficial.**
- **Conclusão:** na rede da fábrica, só o Outlook clássico, num PC da mesma rede, assinaria o feed. Isso também exige o acesso pela rede ligado (`NET_ON`) e o IP fixo do servidor.

### Fase 5 (opcional): arrastar para reagendar
- Só ADM, só na visão Semana e no Cronograma, só depois da fase 2. Ao soltar, abre o `modalConfirm` (`demandas.js:715`): "Mover prazo de SOL-1043 de qui 29/10 16:00 para sex 30/10 10:00?". Depois chama `demanda/reagendar`.
- Sem `modalConfirm`, um arrasto acidental muda o prazo sem ninguém perceber.
- **Avaliação:** vale pouco. Os botões +30 min e +1 h e o campo "Reagendar" na gaveta cobrem o caso com menos risco. Fica para depois.

### Onde entra na tela
- **ADM:** aba nova **Calendário** (ícone de calendário), entre Histórico e Cronoanálise. Tem os modos Mês, Semana e Dia, o filtro de setor e o painel lateral do dia.
- **Cronograma:** como **modo da Cronoanálise**, no painel "Linha do tempo", e não como aba própria. Usa os mesmos dados e as mesmas cores, sem criar mais uma aba. Se o PCP usar muito, pode virar aba na fase 2.
- **Operador:** sem aba nova. Em "Recebidas", uma faixa compacta "Minha agenda de hoje" no topo, com as ativas dele ordenadas por prazo e a hora de cada uma. Só se o dono quiser, na fase 2 (quando houver `inicio_plan`).

## 6. Riscos e segurança

- **Fuso e horário de verão:** todo cálculo de dia usa o fuso local do servidor (`demandas_calc.py:232-234`) e o do navegador na tela. Numa fábrica só, os dois coincidem. No SaaS, precisa de fuso por empresa.
- **Desempenho:**
  - O calendário do mês percorre até 5000 demandas no cliente: barato.
  - O cronograma de 31 dias com `_todas` lê também o arquivo morto, com até 50000 registros, porque `load_arquivo` usa cache. É preciso limitar as linhas, por exemplo a 300, e informar "e mais N".
- **Feed com token na URL:**
  - O token aparece no histórico e nos logs de quem assina. Por isso: só leitura, por setor, revogável, sem nomes de pessoas no evento, só sigla do setor e título.
  - Em `http` puro, o token trafega em claro na rede local. Na internet, só com HTTPS (estudo 03).
- **Fase 3:** se uma configuração mal feita deixar a agenda sem turnos, `soma_util` nunca termina. Por isso o limite de 400 dias e a validação "pelo menos um turno de pelo menos 15 min por semana".
- **Reagendar:** só o ADM, com o evento `deadline` gravado. Mover o prazo zera `atraso_avisado` se ele ficar no futuro, como já faz `estender`.
- **Migração v2:** é irreversível sem o `.v1.bak`. Testar em cópia, e o README precisa avisar.

## 7. Testes exigidos (docs/QUALIDADE.md)

**Unitários**, em `tests/test_demandas_calc.py`, meta de 90% (cálculo de tempo):
- Fase 1: `gantt` com `ini`/`fim`/`por`.
  - Janela padrão inalterada (regressão).
  - Escolha de linhas por sobreposição, inclusive no limite exato `seg.b == ini`.
  - Agrupamento por setor e por pessoa, incluindo `para.p = None` como "Fila".
  - Limite de linhas e o campo `plano`.
- Fase 2:
  - `prazo()` com e sem `prazo_em`;
  - `espera_ms` com `inicio_plan` no futuro e no passado;
  - conversão inversa `prazo_em → est` (arredondamento para cima, limites 1 e 43200, prazo no passado recusado).
- Fase 3: `soma_util` e `util_entre`.
  - Início fora do turno, na virada do almoço, sexta 16:30 + 60 min, feriado na segunda, turno que cruza a meia-noite.
  - Horário de verão (simulado com fuso fixo), agenda vazia recusada e limite de 400 dias.

**Integração**, em `tests/test_demandas_api.py`:
- `cronograma`:
  - só ADM (operador recebe 403);
  - validação de `de`/`ate` (inverso, mais de 31 dias, tipos errados, `bool`);
  - `por` inválido;
  - inclui o arquivo morto.
- `criar` com `inicio_plan` ou `prazo_em`: exclusão mútua com `est`, valores fora do limite.
- `reagendar`:
  - só ADM;
  - em demanda encerrada, recusado;
  - evento `deadline` gravado;
  - `atraso_avisado` zerado.
- `estender` com `prazo_em`.
- Migração v1→v2 em `tests/test_demandas_store.py`:
  - cria o `.v1.bak`;
  - preenche `prazo_em` = valor antigo;
  - recusa v3;
  - a segunda carga não migra de novo.
- `.ics`:
  - conteúdo RFC 5545 (CRLF, dobra em 75 octetos, escape);
  - operador não baixa demanda que não vê;
  - token do feed errado ou revogado devolve 401.

**jsdom**, em `tests/demandas_check.js`:
- A aba Calendário aparece só para o ADM.
- No mês, os chips caem no dia certo, aparece "+N", a atrasada tem a classe de destaque e o filtro de setor funciona.
- O clique no dia abre o painel. O clique no chip abre a gaveta.
- Alternância Mês/Semana/Dia.
- Cronograma com escala Semana: eixo de 7 dias e `--dm-gcols:7`.
- Formulário: a prévia "Prazo final" com prazo em data e hora e o aviso "fora do expediente" (fase 3).

**Mutação:** `py -3 qa.py mutate demandas/demandas_calc.py --funcoes gantt,prazo,espera_ms,soma_util,util_entre`, com `api.py` (`_cronograma`, `_reagendar`, `_criar`, `_estender`) e `demandas_store.py` (`_migra`, `_demanda`). Meta: 90% no cálculo de tempo, 80% no resto.

## 8. Fases e esforço estimado

| Fase | Entrega | Muda dados? | Esforço (com testes) |
|---|---|---|---|
| 1 | Aba Calendário (mês, semana, dia) + cronograma multidia na Cronoanálise + rótulo "8 h" honesto | Não | 5–7 dias |
| 2 | `inicio_plan`, `prazo_em` congelado, formulário com data e hora, `reagendar`, formato v2 | Sim (v2) | 4–6 dias |
| 3 | Expediente, turnos e feriados por setor; métricas úteis | Sim (`agenda`) | 6–10 dias |
| 4 | `.ics` por demanda (+ anexo no e-mail do estudo 04); feed só com hospedagem | Não / token | 1 d + 3 d |
| 5 | Arrastar para reagendar (opcional) | Não | 3 dias |

## 9. Ligações com os outros estudos

- **01 Backup:** a migração v2 gera `demandas.json.v1.bak`, que entra na rotina de backup. A configuração `agenda` vive em `demandas.json` e já vai no backup.
- **02 Avisos:** hoje o atraso só é detectado quando alguém grava (`api.py:286`). Uma thread de fundo (estudo 02) poderia avisar "vence em 30 min" e "agendada começa agora", usando os mesmos `prazo()` e `inicio_plan`.
- **03 Continuidade e hospedagem:** o feed `webcal://` para o Google e o novo Outlook depende do servidor na internet, com HTTPS. No SaaS, o fuso e os feriados passam a ser por empresa.
- **04 E-mail:** o convite `.ics` (`METHOD:REQUEST`) vai anexo ao e-mail "nova solicitação" ou "prazo ajustado". Usa o mesmo gerador `.ics` da fase 4 e o mesmo `UID`, com `SEQUENCE` = `_rv`, para o Outlook atualizar o evento em vez de duplicar. Precisa de e-mail no setor ou na pessoa, campo que hoje não existe.
- **Configurações:** este estudo não cria seção nova no diálogo comum. O token do feed (fase 4) ficaria na seção **Servidor**. O expediente fica na Administração do ADM, porque é regra do negócio, não do PC.

## 10. Mockups

Todos em `docs/estudos/mockups/`, HTML estático com o CSS real do programa.

| Arquivo | Mostra |
|---|---|
| `05-calendario-mes.html` | Aba Calendário do ADM em outubro/2026. Chips por status, atrasadas pulsando, "+N", feriado de 12/10, filtro de setor, Mês/Semana/Dia e painel lateral com o dia 29/10 selecionado. |
| `05-calendario-semana.html` | Semana de 26/10 a 01/11, das 6h às 22h. Demandas como blocos do início ao prazo, linha de "agora" na quarta 28/10 às 10:40 e faixa fora do expediente sombreada (prévia da fase 3). |
| `05-cronograma.html` | Modo cronograma da Cronoanálise: escala de 7 dias e linhas agrupadas por setor (CORTE, SOLDA, PINTURA, MONTAGEM, EXPEDIÇÃO). Barras de espera, execução e pausa com as cores reais de `.dm-gs`, barra fina de plano, marcador de prazo e de agora. |
| `05-nova-solicitacao-data.html` | Formulário "Nova solicitação" real, com os modos "Tempo estipulado", "Prazo em data e hora" e "Agendar início", a prévia "Prazo final: sex 30/10 16:00" e o aviso de fora do expediente. |

Observação: o exemplo do pedido dizia "qui 30/10". Em 2026, 30/10 cai numa sexta, e os mockups usam "sex 30/10".
