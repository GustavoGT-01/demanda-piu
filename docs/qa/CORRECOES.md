# Bateria QA: o que foi corrigido e o que ficou

Sete sessões de teste (`docs/qa/<área>.md`) acharam cerca de 45 pontos. Em 18/11/2026 foram corrigidos os abaixo.
Os testes que antes marcavam o defeito (`expectedFailure`, `known-bug`) viraram testes normais.

## Corrigidos

| Origem | O que era | Correção |
|---|---|---|
| ADM-01 | excluir setor deixava horário e feriado órfãos e travava o Expediente | `_setor_apagar` tira o setor da agenda (nova versão) |
| ADM-02, avisos B2 | `^…$` + `match` aceitava quebra de linha no fim (código, HH:MM, datas, siglas) | `fullmatch` |
| ADM-03 | CONTRATO prometia o campo `abertas` | CONTRATO descreve a frase |
| ADM-04 | nome de feriado aceitava caractere de controle | recusa controles |
| ADM-05 | feriado com vários setores aparecia como um | o seletor mostra "CNC, PCP" |
| ADM-06 | conflito 409 nunca disparava nos modais Setor e Usuário | `rev` guardado ao abrir o modal |
| ADM-07 | Expediente voltava ao "Horário padrão" depois de salvar | o setor em edição é mantido |
| ADM-08 | formulário do Expediente ficava velho e "sujo" quando outro aparelho salvava | compara com o que recebeu |
| ADM-09 | erro de sigla, nome e código não sumia ao corrigir | some ao ficar válido |
| ciclo C-01 | meio emoji dava HTTP 500 | 400 (recusa) e a tela remove o meio emoji |
| ciclo C-02 | total de anexos desatualizado ao remover | `anexos_uso` refeito depois de apagar o arquivo |
| ciclo C-03 | aviso de limite de anexos sumia na hora | o mesmo aviso diz quantos ficaram de fora |
| criar C-01 | descrição com tab: erro sem campo marcado | a tela troca o tab por espaço |
| criar C-02 | título curto com emoji passava na tela | conta caracteres como o servidor |
| criar C-03 | rascunho ganhava 24 h a cada abertura | só renova se o conteúdo mudar |
| criar C-04 | título só de caracteres invisíveis | recusado |
| criar C-05 | "Prioridade inválido." | "inválida" |
| criar C-06 | prévia do prazo ignorava o horário de serviço | prévia em tempo útil (`hsSoma`) |
| criar C-07, C-10 | vermelho e atalho marcados depois de digitar outro tempo | atualizados na hora |
| criar C-08 | tocar numa opção levava o foco ao Título | o foco volta para onde estava |
| tempo B1 | reatribuir entre setores deixava prazo e medida em grades diferentes | a grade fica presa ao setor da criação (`agenda_s`) |
| tempo B2 | `calc.atencao` contava o atraso em tempo corrido | tempo útil |
| tempo B3 | a poda de 50 versões apagava versão em uso | nunca apaga versão de demanda ativa |
| tempo B4 | concluída fora do expediente: "no prazo" no cartão e "atrasou" no KPI | `atrasou_concluida` usa o atraso útil |
| tempo B5 | "Faltam 0 min" numa atrasada | "Atrasada há …" |
| visões V-03 | Semana: a lateral mostrava sempre o domingo | mostra hoje; o cabeçalho do dia é clicável |
| visões V-05 | linha "Agora" colada na borda de janela passada | só aparece se o instante está na janela |
| visões V-06 | o teto de 120 linhas dava vaga a concluídas antigas | as em aberto entram primeiro |
| visões V-08, acesso B1 | "Ver como" deixava "＋ Nova solicitação" ativo | botão escondido e ação bloqueada |
| acesso B2 | lista de pessoas da entrada ficava velha | atualizada ao perder a sessão e quando o cadastro muda |
| acesso B3 | "Ver como" gravava ao abrir cartão e em "marcar todos" | não grava |
| visões V-09 | CONTRATO dizia janela invertida é ordenada, a rota recusava | a rota ordena |
| avisos B1, B4 | JSON muito aninhado e pasta de backup com caractere nulo derrubavam a conexão | 400 |
| avisos B3 | título com U+2028/U+0085 nunca gerava e-mail | título recusa esses separadores |
| avisos B5 | campo "e-mail para teste" sem rótulo acessível | `aria-label` |

## Não corrigidos (decisão ou risco baixo)

- **V-01, V-04, V-07** (só fuso com horário de verão: mês de 31 dias com 745 h, dia de 23/25 h): o Brasil não tem
  horário de verão desde 2019. Os testes seguem marcados `known-bug` em `check_visoes.js`.
- **V-02** ("Limpar" do Histórico não volta o seletor do arquivo morto): pode ser intencional; decidir com o dono.
- **criar C-09** (unidade do tempo em linha própria no modal estreito): visual, sem teste.
- Observações dos relatórios (sem veredito de bug): "Sair" lembrar o último usuário, reativar setor ressuscitar token,
  e-mail frouxo, e outras listadas em cada `docs/qa/<área>.md`.
