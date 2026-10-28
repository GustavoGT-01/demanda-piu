# Estudos de melhorias da Central de demandas

> Só estudo e mockups, feitos em 28/10/2026. **Nenhuma linha do programa mudou.** Nada será implementado antes
> de os mockups serem aprovados.

Os estudos partiram da comparação com o Trello e tratam dos pontos fracos apontados lá: backup, avisos, PC servidor
desligado e hospedagem. Também cobrem os dois pedidos novos: e-mail e calendário. Cada tema foi estudado por um
agente separado, que começou do zero, leu o código e pesquisou na web as fontes externas, com data. Depois, as
citações foram conferidas por amostra contra o código e a coerência entre os estudos foi revisada.

**Mockups:** abra [`mockups/index.html`](mockups/index.html) no navegador. Eles foram aprovados pelo dono em 28/10/2026.

**Implementação:** siga [`PLANO-IMPLEMENTACAO.md`](PLANO-IMPLEMENTACAO.md), que traz a ordem, as regras e o texto
para retomar em outro chat.

## Os estudos

| # | Tema | Recomendação curta | Esforço com testes |
|---|---|---|---|
| [01](01-backup.md) | Backup automático | Zip diário e na hora de ligar, verificado com manifesto SHA-256. Fica numa pasta local e é copiado para um destino extra opcional. Retenção de 7 diárias, 4 semanais e 12 mensais. Restaurar só no PC principal, sempre com uma cópia antes. | 7–9 dias |
| [02](02-avisos.md) | Avisos | Já, em http: som, título da aba piscando e vibração no Android. No servidor: aviso por pessoa, aviso de comentário e checagem de atraso a cada minuto. Push com o app fechado só depois do HTTPS. | 6–7 dias + 3–4 (push) |
| [03](03-continuidade-hospedagem.md) | PC desligado e hospedagem | Fase 0: no-break, iniciar com o Windows, religar sozinho, reconexão sem perder o que foi digitado. Fase 1: guardar os dados atrás de uma interface com uma empresa implícita. Isso deixa abertos os caminhos de empresa única e de SaaS. | 0: 7–9 dias · 1: 5–8 dias · hospedar: semanas |
| [04](04-email.md) | E-mail | Fila em disco e envio em segundo plano com `smtplib`, só biblioteca padrão. Campo `email` em pessoa e setor. Um fio por demanda (`[SOL-n]`). Começa só com "demanda criada". | 6–7 dias |
| [05](05-calendario-cronograma.md) | Calendário e cronograma | Viável. Fase 1 sem mudar os dados: aba Calendário e cronograma de vários dias na Cronoanálise. Depois vêm `prazo_em` e `inicio_plan`, e só se fizer falta, expediente e feriados. | 5–7 dias (fase 1) |

## Ordem recomendada

1. **Backup (01).** Protege tudo o que vem depois e cria a **thread de fundo** que 02 e 04 reaproveitam.
2. **Robustez local (03, fase 0)** com a **seção Servidor**. É a resposta imediata ao "PC desligou".
3. **E-mail (04).** Pedido direto do dono e independente de HTTPS.
4. **Avisos em http (02, fases 1–5).** Reaproveita o gancho de eventos do e-mail e o timer de atraso.
5. **Calendário (05, fase 1).** Não muda dados, então pode entrar em paralelo a qualquer item acima.
6. **Camada de dados com empresa implícita (03, fase 1).** Antes de qualquer hospedagem.
7. **Hospedagem (03, fases 2–3)** e então o **push** (02, fase 6) e o **feed de calendário** (05, fase 4).

## Decisões comuns (valem para todos os estudos)

- **Uma só thread de fundo** no servidor (`main()`, entre `api_mod()` e `serve_forever()`, `servidor.py:463-472`).
  Ela acorda a cada minuto e faz três coisas:
  - backup no horário marcado (01);
  - checagem de atraso, que hoje só é detectado quando alguém grava (02);
  - fila de e-mail (04).
  Uma exceção em uma das tarefas não derruba as outras.
- **Um só gancho de eventos.** Os eventos são juntados sob o LOCK em `_evento` e despachados depois de gravar, no
  callback `depois` de `_gravar` (`demandas/api.py:753-759`). Esse despacho alimenta avisos na tela, som e
  e-mail.
- **Configurações num diálogo só**, "⚙ Configurações", que é a evolução do "⚙ Rede", com as seções Rede · Backup ·
  E-mail · Avisos · Servidor. Ele aparece só no PC principal. O estudo 03 recomenda decidir com `pode(ctx,
  "configurar")` e não com `papel == "maquina"`, para não travar a hospedagem.
- **Arquivos novos em `data/`, um por assunto.** Ficam fora do `demandas.json`, porque `_normaliza` descarta chaves
  desconhecidas (`demandas/demandas_store.py:117-134`):
  - `backup.json` e `backup-estado.json`;
  - `email.json`, `email-fila.json` e `email-log.json`;
  - `avisos.json`.
- **O que entra no backup.** Não entram `rede.json` (PIN em texto puro) nem `sessoes.json`. A senha SMTP de
  `email.json` é protegida pelo Windows (DPAPI) e só abre no mesmo PC. Num PC reserva, ela precisa ser digitada
  de novo.
- **E-mail e telefone só na vista do ADM.** A lista de pessoas também vai para os operadores.

## Achados que valem mesmo sem implementar nada

- **Proxy ou túnel no próprio PC transforma todo visitante em administrador.** Todo pedido chega de 127.0.0.1 e
  ganha o papel `maquina`, sem PIN (`servidor.py:283-285`). Hoje ninguém usa túnel, mas não monte um. (03)
- **O atalho "1 dia útil (8h)" conta tempo corrido** (`demandas.js:772` × `demandas_calc.py:39-40`). Um pedido
  criado às 16:00 vira "atrasado" de madrugada. Conserto barato: rotular "8 h". (05)
- **Ler um aviso marca como lido para o setor inteiro** (`demandas/api.py:563-580`), e comentário não gera aviso.
  (02)
- **Quando o servidor reinicia, quem estava preenchendo um formulário perde o texto.** O `tk` da pessoa vive só na
  memória (`demandas/api.py:147`). (03)
- **Copiar `data/` com o programa aberto pode pegar o instante sem o `demandas.json`.** Isso acontece entre os dois
  renomes de `atomic_write` (`store.py:58-68`). O README já manda copiar com o programa fechado. (01)

## Decisões que só o dono pode tomar

**Hospedagem (03)**
- Empresa única pela internet ou SaaS com várias empresas? Isso só muda as fases 2 e 3.
- Na versão hospedada: código de 4 dígitos para operadores e senha para ADM? Servidor no Brasil?

**Backup (01)**
- O PC fica ligado 24 h?
- Qual destino extra existe de verdade: pen drive, outro PC ou OneDrive/Google da empresa?
- O zip leva nomes e hashes dos códigos. Exigir BitLocker no pen drive?

**E-mail (04)**
- Qual conta de envio: SMTP da empresa, Microsoft 365, Google Workspace ou Brevo/SES?
- Quais eventos além de "criada" mandam e-mail? O solicitante recebe cópia?
- Fila do setor: mandar para o e-mail do setor ou para todas as pessoas?
- A descrição vai no e-mail?

**Avisos (02)**
- Aceitar a dependência opcional `cryptography` para o push quando houver HTTPS?
- O texto da demanda pode aparecer na tela bloqueada?
- No tablet compartilhado, o aviso é do setor ou da pessoa?

**Calendário (05)**
- Os setores têm turnos fixos? Isso decide a fase 3.
- Uma demanda agendada pode ser aceita antes da hora?
- O cronograma fica dentro da Cronoanálise ou numa aba própria?
- O operador ganha "Minha agenda de hoje"?

## Limitações deste estudo

- Os mockups são telas estáticas. Os dados são fictícios e os botões não fazem nada, exceto o menu de
  Configurações, que navega entre as seções. Pequenas diferenças de estilo entre as seções de Configurações vêm de
  agentes diferentes e serão unificadas na implementação.
- Preços e regras de provedores (VPS, e-mail, navegadores) mudam com o tempo. Cada estudo traz a fonte e a data da
  consulta, e alguns itens estão marcados como "não confirmado".
- Os esforços são estimativas para uma pessoa e incluem os testes exigidos por `docs/QUALIDADE.md`.
