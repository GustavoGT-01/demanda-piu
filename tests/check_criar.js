const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// QA da "Nova solicitação" (formulário do ADM e da pessoa) contra o servidor REAL (servidor.py) com DEMANDAS_DATA temporário.
// rodar: node tests/check_criar.js   (jsdom em tests/node_modules; PYTHON=... troca o interpretador)
// Linhas: PASS/FAIL = regra da tela. KNOWN-BUG = bug CONFIRMADO e listado em docs/qa/criar.md: a linha diz se ainda
// reproduz; não reprova o check (quando o bug for corrigido a linha vira "NÃO REPRODUZ MAIS" e o caso sai da lista).
const REPO=path.resolve(__dirname,'..');
const base=fs.mkdtempSync(path.join(os.tmpdir(),'dem-qa-criar-')),data=path.join(base,'data');
fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,N=0,F=0,K=0;
const LOST={n:0};            // quantas respostas de demanda/criar a página "perde" (o servidor grava, a tela não recebe)
const CALLS=[];              // pedidos de demanda/criar que a página fez: {corpo, status}
function startServer(){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor;s=servidor.Server(('127.0.0.1',0),servidor.Handler);print(s.server_address[1],flush=True);s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='';p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+)\s/.exec(out);if(m&&!PORT){PORT=+m[1];res(p)}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ok=(c,m)=>{N++;console.log((c?'PASS ':'FAIL ')+m);if(!c){F++;process.exitCode=1}};
const known=(id,reproduz,m)=>{K++;console.log(reproduz?'KNOWN-BUG '+id+' (reproduz) '+m:'FIXED? '+id+' NÃO REPRODUZ MAIS: '+m)};
const direto=(rest,body)=>fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(async r=>{const t=await r.text();try{return JSON.parse(t)}catch(e){return {_status:r.status,_texto:t}}});
const disco=()=>JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8'));
const porTitulo=t=>disco().demandas.filter(d=>d.titulo===t);
const ndem=()=>disco().demandas.length;

// papel: finge o /api/eu de um aparelho da rede ('' = o do próprio PC: Escritório). O fetch da página registra os pedidos de criar.
async function boot(papel){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/',{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=async(u,o)=>{
      if(papel&&u==='/api/eu')return new Response(JSON.stringify({papel}),{headers:{'Content-Type':'application/json'}});
      const criar=String(u).includes('demanda/criar');
      const r=await fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);
      if(criar){
        const c={corpo:JSON.parse(o.body),status:r.status};CALLS.push(c);
        if(LOST.n>0){LOST.n--;c.perdida=true;throw new TypeError('Failed to fetch')}   // o servidor respondeu, a página não viu
      }
      return r;
    };
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
    w.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={}}resume(){this.state='running'}createOscillator(){return{type:'',frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
    Object.defineProperty(w.navigator,'wakeLock',{configurable:true,value:{request:async()=>({addEventListener(){},release:async()=>{}})}});
    Object.defineProperty(w.navigator,'vibrate',{configurable:true,value:()=>true});
  }});
  const w=dom.window;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  const d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const until=async(f,ms=6000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(40))try{if(f())return true}catch(e){}return false};
  const click=s=>{const el=typeof s==='string'?$(s):s;if(!el)throw new Error('não achei '+s);el.click();return el};
  const type=(s,v,ev='input')=>{const el=$(s);if(!el)throw new Error('não achei '+s);el.value=v;el.dispatchEvent(new w.Event(ev,{bubbles:true}))};
  const toast=()=>($('#dm-toast')||{}).textContent||'';
  const aberto=()=>$('#dm-modal').classList.contains('dm-on');
  const press=s=>$$(s).filter(b=>b.getAttribute('aria-pressed')==='true').map(b=>b.dataset.v||b.textContent);
  const rasc=(k)=>JSON.parse(w.localStorage.getItem(k||'dm-rascunho:adm')||'null');
  const erros=()=>$$('#dm-mbox .dm-fld.dm-err').map(f=>(f.querySelector('label,.dm-lbl')||{}).textContent);
  // Enviar: espera a resposta (ou a recusa da própria tela, sem pedido) e devolve o que mudou
  async function enviar(){
    const n=CALLS.length;click('[data-act=m-submit]');
    for(let t0=Date.now();Date.now()-t0<6000&&CALLS.length===n;await sleep(30)){}
    await sleep(CALLS.length>n?150:80);
    return {pediu:CALLS.length>n,chamada:CALLS[CALLS.length-1]};
  }
  return {w,d,$,$$,until,click,type,toast,aberto,press,rasc,erros,enviar};
}
async function entraAdm(T){
  ok(await T.until(()=>T.$('[data-act=lgk][data-v=adm]')),'computador principal tem a opção Administrador');
  T.click('[data-act=lgk][data-v=adm]');T.click('.dm-lgbtn');
  ok(await T.until(()=>T.$('#dm-login').hidden&&T.$('.dm-tab[data-v=painel]')),'Administrador entra como Escritório');
}
// preenche o mínimo válido; sobras entram em `o`
async function preenche(T,o={}){
  const f={titulo:'Pedido de teste',toS:'CNC',motivo:'Outro',...o};
  T.type('#dm-fm-title',f.titulo);
  if(f.desc!==undefined)T.type('#dm-fm-desc',f.desc);
  if(f.fromS)T.type('#dm-fm-fromS',f.fromS,'change');
  T.type('#dm-fm-toS',f.toS,'change');await sleep(30);
  if(f.toP)T.type('#dm-fm-toP',f.toP,'change');
  T.click('[data-act=m-reason][data-v="'+f.motivo+'"]');
  if(f.tipo)T.click('[data-act=m-type][data-v='+f.tipo+']');
  if(f.prio)T.click('[data-act=m-prio][data-v='+f.prio+']');
  if(f.est)T.click('[data-act=m-est][data-v="'+f.est+'"]');
  await sleep(20);
}
const abreForm=async T=>{T.click('.dm-hdnew');return T.until(()=>T.$('#dm-fm-title'))};
const fechaForm=async T=>{if(T.aberto())T.click('[data-act=mclose]');return T.until(()=>!T.aberto())};
// o "hoje HH:MM" / "dd/mm HH:MM" da tela para um instante (mesma conta do fDT)
const fmtTela=(w,ms)=>{const p=n=>String(n).padStart(2,'0'),d=new w.Date(ms),h=new w.Date();
  return (d.toDateString()===h.toDateString()?'hoje ':p(d.getDate())+'/'+p(d.getMonth()+1)+' ')+p(d.getHours())+':'+p(d.getMinutes())};

async function formularioDoAdm(){
  const T=await boot('');const {w,$,$$,until,click,type,toast,aberto,press,rasc,erros,enviar}=T;
  await entraAdm(T);
  // ---------------- estrutura do formulário
  ok(!!$('.dm-hdnew')&&/Nova solicitação/.test($('.dm-hdnew').textContent),'botão "＋ Nova solicitação" no cabeçalho');
  ok(await abreForm(T),'o botão abre o formulário');
  const tt=$('#dm-fm-title'),ds=$('#dm-fm-desc'),en=$('#dm-fm-estN');
  ok(tt.maxLength===140&&tt.type==='text','título: texto com maxlength 140');
  ok(ds.maxLength===2000&&ds.tagName==='TEXTAREA','descrição: textarea com maxlength 2000');
  ok(en.type==='number'&&en.min==='1'&&en.max==='43200','tempo personalizado: número de 1 a 43200');
  ok($$('[data-act=m-type]').length===5&&$$('[data-act=m-prio]').length===4&&$$('[data-act=m-reason]').length===8&&$$('[data-act=m-est]').length===5,'5 tipos, 4 prioridades, 8 motivos, 5 atalhos de tempo');
  ok(press('[data-act=m-type]').join()==='dem'&&press('[data-act=m-prio]').join()==='norm'&&press('[data-act=m-reason]').length===0&&press('[data-act=m-est]').join()==='60','padrão: Demanda, Normal, sem motivo, 1 h');
  ok($$('[data-act=m-est]').map(b=>b.textContent).join()==='30 min,1 h,2 h,4 h,8 h','atalhos de tempo: 30 min, 1 h, 2 h, 4 h, 8 h');
  ok(!!$('[data-act=mclose]')&&/Cancelar/.test($('[data-act=mclose]').textContent)&&/Enviar solicitação/.test($('[data-act=m-submit]').textContent),'botões Cancelar e Enviar solicitação');
  const opts=s=>$$(s+' option').map(o=>o.value);
  ok(opts('#dm-fm-fromS').join()==='PCP,CNC,ESP,ALM'&&$('#dm-fm-fromS').value==='PCP','solicitante (só o ADM): setores ativos, padrão PCP; o inativo (PIN) não aparece');
  ok(opts('#dm-fm-toS').join()===',PCP,CNC,ESP,ALM'&&$('#dm-fm-toS').value==='','setor responsável: "Selecione" + ativos, sem o inativo');
  ok($('#dm-fm-toP').disabled&&/Escolha o setor primeiro/.test($('#dm-fm-toP').textContent),'pessoa responsável desligada até escolher o setor');
  ok(/Prazo final: .* \(.* a partir de agora\)/.test($('#dm-fm-prev').textContent),'prévia do prazo mostra "Prazo final: ... a partir de agora": '+$('#dm-fm-prev').textContent);
  ok(!$('#dm-fm-rasc')&&erros().length===0,'formulário novo: sem rascunho recuperado e sem erro');
  // ---------------- botões de opção
  for(const t of ['alt','set','man','mat','dem']){click('[data-act=m-type][data-v='+t+']');ok(press('[data-act=m-type]').join()===t,'tipo '+t+' marcado (só ele)')}
  for(const p of ['low','high','urg','norm']){click('[data-act=m-prio][data-v='+p+']');ok(press('[data-act=m-prio]').join()===p,'prioridade '+p+' marcada (só ela)')}
  for(const m of ['30','60','120','240','480']){click('[data-act=m-est][data-v="'+m+'"]');ok(press('[data-act=m-est]').join()===m&&$('#dm-fm-estN').value===String(m>=60?m/60:m)&&$('#dm-fm-estU').value===(m>=60&&m%60===0?'h':'m'),'atalho '+m+' min marcado e o campo livre acompanha ('+$('#dm-fm-estN').value+' '+$('#dm-fm-estU').value+')')}
  // o foco: clicar numa opção redesenha o formulário e o foco volta para o título
  $('#dm-fm-desc').focus();click('[data-act=m-prio][data-v=low]');
  known('QA-C-08',w.document.activeElement.id==='dm-fm-title','quem está na Descrição e toca num botão de opção tem o foco levado de volta ao Título (o formulário é redesenhado e o openModal foca o primeiro campo): o que digitar depois vai para o título; no tablet abre o teclado');
  click('[data-act=m-prio][data-v=norm]');
  // setor, pessoa e a fila
  type('#dm-fm-toS','CNC','change');await sleep(30);
  ok(!$('#dm-fm-toP').disabled&&opts('#dm-fm-toP').join()===','+disco().pessoas.filter(p=>p.setor==='CNC').map(p=>p.id).join(),'escolher o setor libera as pessoas dele (e "qualquer pessoa" = fila)');
  ok(/Qualquer pessoa do setor/.test($('#dm-fm-toP').options[0].textContent),'primeira opção da pessoa: "— Qualquer pessoa do setor —"');
  const carlos=disco().pessoas.find(p=>p.nome==='Carlos').id;
  type('#dm-fm-toP',carlos,'change');ok($('#dm-fm-toP').value===carlos,'escolhe Carlos');
  type('#dm-fm-toS','ESP','change');await sleep(30);
  ok($('#dm-fm-toP').value===''&&opts('#dm-fm-toP').join()==='','trocar de setor zera a pessoa (ESP não tem ninguém: só a fila)');
  type('#dm-fm-toS','ALM','change');await sleep(30);
  ok(/ainda não tem usuários ativos/.test($('#dm-mbox').textContent),'setor sem usuários ativos: aviso "ficará aguardando"');
  type('#dm-fm-toS','','change');await sleep(30);
  ok($('#dm-fm-toP').disabled,'voltar para "Selecione" desliga a pessoa de novo');
  // ---------------- enviar vazio: um erro por campo, nada vai ao servidor
  const n0=ndem();
  let r=await enviar();
  ok(!r.pediu&&aberto()&&ndem()===n0,'enviar vazio: a tela recusa sozinha, o formulário fica aberto e nada é gravado');
  ok(erros().join('|')==='Título|Setor responsável|Motivo','erros marcados por campo: Título, Setor responsável e Motivo ('+erros().join('|')+')');
  ok(/5 a 140 caracteres/.test($('#dm-fm-title').closest('.dm-fld').querySelector('.dm-em').textContent)&&/Escolha o setor responsável/.test($('#dm-fm-toS').closest('.dm-fld').querySelector('.dm-em').textContent)&&/Selecione o motivo/.test($('.dm-opts [data-act=m-reason]').closest('.dm-fld').querySelector('.dm-em').textContent),'cada campo traz a sua mensagem (dm-em)');
  type('#dm-fm-title','abc');ok(erros().includes('Título'),'título com 3 letras: o erro continua enquanto digita');
  type('#dm-fm-title','abcde');ok(!erros().includes('Título'),'chegou a 5 letras: o erro do título some na hora');
  click('[data-act=m-reason][data-v="Retrabalho"]');ok(!erros().includes('Motivo')&&erros().includes('Setor responsável'),'escolher o motivo limpa só o erro do motivo');
  type('#dm-fm-toS','CNC','change');await sleep(30);ok(erros().length===0,'escolher o setor limpa o erro do setor');
  // ---------------- limites do título pela tela
  const tentaTitulo=async(t)=>{type('#dm-fm-title',t);return enviar()};
  r=await tentaTitulo('abcd');ok(!r.pediu&&erros().join()==='Título','título de 4 letras: recusa na tela');
  r=await tentaTitulo('   abcd   ');ok(!r.pediu&&erros().join()==='Título','4 letras com espaços nas pontas: ainda recusa');
  r=await tentaTitulo('x'.repeat(141));ok(!r.pediu&&erros().join()==='Título','título de 141 (colado por fora do maxlength): recusa na tela');
  r=await tentaTitulo('x'.repeat(140));ok(r.pediu&&r.chamada.status===200&&!aberto()&&porTitulo('x'.repeat(140)).length===1,'título de 140: grava ('+toast()+')');
  ok(/Solicitação enviada para/.test(toast()),'sucesso: aviso "✅ Solicitação enviada para ..." ('+toast()+')');
  ok(rasc()===null,'enviou: o rascunho do aparelho foi apagado');
  await abreForm(T);await preenche(T,{titulo:'abcde'});
  r=await enviar();ok(r.pediu&&r.chamada.status===200&&porTitulo('abcde').length===1,'título de 5 letras: grava');
  await abreForm(T);await preenche(T,{titulo:'   Com espaços   '});
  r=await enviar();ok(r.chamada.corpo.titulo==='Com espaços'&&porTitulo('Com espaços').length===1,'espaços das pontas saem antes de enviar');
  // ---------------- tempo estipulado: o campo livre
  const unidade=async u=>{type('#dm-fm-estU',u,'change');await sleep(30)};   // o campo abre em "1 horas" (60 min): a unidade vem antes do número
  const livre=async(v,u='m')=>{await unidade(u);type('#dm-fm-estN',v);return enviar()};
  await abreForm(T);await preenche(T,{titulo:'Tempo livre 01'});
  const prev0=()=>$('#dm-fm-prev').textContent;
  await unidade('m');type('#dm-fm-estN','90');ok(press('[data-act=m-est]').length===0&&/1h 30|1 h 30|1h30|90 min|1,5 h/.test(prev0()),'90 min digitados: nenhum atalho marcado e a prévia acompanha: '+prev0());
  r=await enviar();ok(r.chamada.corpo.est===90&&porTitulo('Tempo livre 01')[0].est===90,'90 min: grava est=90');
  const casos=[['43200','m',true,43200,'43200 min (30 dias): limite máximo'],['43201','m',false,0,'43201 min: um além do máximo'],['0','m',false,0,'0: inválido'],['','m',false,0,'vazio: inválido'],
    ['-5','m',false,0,'negativo'],['abc','m',false,0,'texto (o campo numérico ignora)'],['0.4','m',false,0,'0,4 min arredonda para 0'],['0.5','m',true,1,'0,5 min arredonda para 1'],['1','m',true,1,'1 min: limite mínimo'],
    ['1.5','h',true,90,'1,5 h = 90 min'],['720','h',true,43200,'720 h = 43200 min (máximo)'],['721','h',false,0,'721 h: um além do máximo'],['0.01','h',true,1,'0,01 h = 0,6 min arredonda para 1'],['2.4','m',true,2,'2,4 min arredonda para 2'],['89.6','m',true,90,'89,6 min arredonda para 90']];
  let i=2;
  for(const [v,u,vale,est,desc] of casos){
    await abreForm(T);await preenche(T,{titulo:'Tempo livre '+String(i).padStart(2,'0')});
    const antes=ndem();r=await livre(v,u);
    if(vale)ok(r.pediu&&r.chamada.status===200&&r.chamada.corpo.est===est&&ndem()===antes+1,'tempo livre '+desc+' → est='+est);
    else ok(!r.pediu&&aberto()&&erros().includes('Tempo estipulado para concluir')&&ndem()===antes,'tempo livre '+desc+' → recusado na tela, campo marcado');
    await fechaForm(T);i++;
  }
  // o campo marcado como erro não limpa enquanto digita um valor bom (só ao trocar de unidade ou clicar atalho)
  await abreForm(T);await preenche(T,{titulo:'Erro do tempo'});type('#dm-fm-estN','0');await enviar();
  ok(erros().includes('Tempo estipulado para concluir'),'(conferência: o tempo 0 marcou o campo)');
  type('#dm-fm-estN','45');
  known('QA-C-07',erros().includes('Tempo estipulado para concluir'),'depois do erro, digitar um tempo válido (45) não tira o vermelho do campo; só sai ao trocar a unidade ou clicar num atalho');
  click('[data-act=m-est][data-v="30"]');ok(!erros().includes('Tempo estipulado para concluir'),'clicar num atalho limpa o erro do tempo');
  type('#dm-fm-estN','45');
  known('QA-C-10',press('[data-act=m-est]').join()==='30'&&/45 min/.test($('#dm-fm-prev').textContent),'digitar 45 no campo livre com o atalho "30 min" marcado deixa o atalho marcado (o tempo valendo é 45 min: a prévia diz 45 min)');
  // trocar a unidade reinterpreta o número digitado
  type('#dm-fm-estN','90');type('#dm-fm-estU','h','change');await sleep(30);
  ok(/Prazo final/.test($('#dm-fm-prev').textContent)&&$('#dm-fm-estU').value==='h'&&$('#dm-fm-estN').value==='90','90 min trocados para "horas" passam a valer 90 h (5400 min) e o campo continua em 90 h');
  await fechaForm(T);
  // ---------------- tudo preenchido: o registro gravado
  await abreForm(T);
  await preenche(T,{titulo:'  Pedido completo da tela  ',desc:'linha 1\n\nlinha 3  ',fromS:'ESP',toS:'CNC',toP:carlos,motivo:'Retrabalho',tipo:'man',prio:'urg',est:'240'});
  const antesUrg=disco().notas.filter(n=>n.tipo==='urg').length;
  r=await enviar();
  const g=porTitulo('Pedido completo da tela')[0]||{};
  ok(r.pediu&&r.chamada.status===200&&!aberto(),'pedido completo: servidor aceitou e o formulário fechou');
  ok(g.tipo==='man'&&g.prio==='urg'&&g.motivo==='Retrabalho'&&g.est===240&&g.desc==='linha 1\n\nlinha 3'&&JSON.stringify(g.de)==='{"s":"ESP","p":null}'&&JSON.stringify(g.para)==='{"s":"CNC","p":"'+carlos+'"}'&&g.status==='new','registro gravado confere campo a campo: '+JSON.stringify({tipo:g.tipo,prio:g.prio,est:g.est,de:g.de,para:g.para}));
  ok(disco().notas.filter(n=>n.tipo==='urg').length===antesUrg+1&&g.eventos.map(e=>e.ev).join()==='created,assigned','urgente avisa o Escritório (nota urg); pessoa escolhida gera o evento "assigned"');
  ok(/Solicitação enviada para .*Corte CNC/.test(toast()),'o aviso nomeia o setor responsável: '+toast());
  ok(typeof r.chamada.corpo.cid==='string'&&/^[A-Za-z0-9_-]{8,64}$/.test(r.chamada.corpo.cid)&&disco().cids.some(c=>c[0]===r.chamada.corpo.cid&&c[1]===g.id),'o pedido levou um cid válido e o servidor o anotou');
  ok(!('de_s' in {})&&r.chamada.corpo.de_s==='ESP'&&r.chamada.corpo.para.p===carlos,'corpo enviado pelo ADM leva de_s e a pessoa');
  click('[data-act=tab][data-v=sol]');
  ok(await until(()=>$$('.dm-card').some(c=>c.querySelector('.dm-nm').textContent==='Pedido completo da tela')),'a solicitação nova aparece na lista do ADM');
  // fila: sem pessoa vai null
  await abreForm(T);await preenche(T,{titulo:'Pedido na fila do setor'});r=await enviar();
  ok(r.chamada.corpo.para.p===null&&porTitulo('Pedido na fila do setor')[0].para.p===null,'sem escolher pessoa: vai para a fila do setor (p=null)');
  // ---------------- clique duplo
  await abreForm(T);await preenche(T,{titulo:'Clique duplo'});
  const n1=ndem(),bt=$('[data-act=m-submit]');bt.click();bt.click();bt.click();
  await sleep(500);ok(ndem()===n1+1&&porTitulo('Clique duplo').length===1,'três cliques seguidos em Enviar: grava uma vez só ('+(ndem()-n1)+')');
  // ---------------- erros que só o servidor sabe
  await abreForm(T);await preenche(T,{titulo:'Descrição com tab',desc:'col1\tcol2'});
  const n2=ndem();r=await enviar();
  ok(r.pediu&&r.chamada.status===200&&ndem()===n2+1&&porTitulo('Descrição com tab').length===1&&porTitulo('Descrição com tab')[0].desc==='col1 col2','descrição com TAB colada: a tela troca o TAB por espaço e a solicitação é criada (QA-C-01)');
  await abreForm(T);await preenche(T,{titulo:'😀😀😀'});
  const n3=ndem();r=await enviar();
  ok(!r.pediu&&aberto()&&ndem()===n3&&erros().length>0,'título de 3 emojis (6 unidades no JS, 3 caracteres): a tela conta como o servidor, recusa e marca o campo (QA-C-02)');
  await fechaForm(T);
  await abreForm(T);await preenche(T,{titulo:'Com acentos ação 😀 ✓',desc:'Ação: 3×4 mm ✓ 😀 <b>x</b>'});r=await enviar();
  ok(r.chamada.status===200&&porTitulo('Com acentos ação 😀 ✓')[0].desc==='Ação: 3×4 mm ✓ 😀 <b>x</b>','acentos, emoji e HTML na descrição vão e voltam como texto');
  await abreForm(T);await preenche(T,{titulo:'Descrição vazia',desc:'   '});r=await enviar();
  ok(porTitulo('Descrição vazia')[0].desc==='Sem descrição adicional.','descrição só com espaços vira "Sem descrição adicional."');
  await abreForm(T);await preenche(T,{titulo:'Descrição 2000',desc:'d'.repeat(2000)});r=await enviar();
  ok(porTitulo('Descrição 2000')[0].desc.length===2000,'descrição de 2000: grava inteira');
  await abreForm(T);await preenche(T,{titulo:'Descrição 2001',desc:'d'.repeat(2001)});r=await enviar();
  ok(r.chamada.corpo.desc.length===2000&&porTitulo('Descrição 2001')[0].desc.length===2000,'descrição de 2001 (só por fora do maxlength): a tela corta em 2000 sem avisar');
  // Esc e Cancelar
  await abreForm(T);type('#dm-fm-title','Vai ficar de rascunho');
  w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  ok(await until(()=>!aberto()),'Esc fecha o formulário');
  ok(rasc()&&rasc().titulo==='Vai ficar de rascunho','…e o texto fica de rascunho');
  // ---------------- resposta perdida: o servidor grava, a tela não vê, e reenviar não duplica
  await abreForm(T);
  ok($('#dm-fm-rasc')&&$('#dm-fm-title').value==='Vai ficar de rascunho','reabrir traz o rascunho de volta');
  await preenche(T,{titulo:'Resposta perdida'});
  const cid1=rasc().cid;LOST.n=1;const n4=ndem();
  r=await enviar();
  ok(r.chamada.perdida&&ndem()===n4+1&&aberto()&&/Sem resposta do servidor|servidor está desligado/.test(toast()),'resposta perdida: o servidor gravou, a tela avisa que não houve resposta e o formulário fica aberto ('+toast()+')');
  ok(!$('[data-act=m-submit]').disabled&&rasc()&&rasc().cid===cid1,'o botão Enviar volta a funcionar e o rascunho mantém a mesma chave');
  r=await enviar();
  ok(r.chamada.corpo.cid===cid1&&r.chamada.status===200&&ndem()===n4+1&&porTitulo('Resposta perdida').length===1&&!aberto(),'reenviar com a mesma chave NÃO duplica (1 só no servidor) e fecha o formulário');
  ok(rasc()===null,'depois do reenvio bem-sucedido o rascunho sai');
  // ---------------- rascunho: guardar, recuperar, descartar, expirar
  await abreForm(T);
  ok(!$('#dm-fm-rasc')&&rasc()===null,'formulário novo depois de enviar: sem rascunho');
  type('#dm-fm-title','Rascunho completo');type('#dm-fm-desc','texto do rascunho');type('#dm-fm-fromS','CNC','change');type('#dm-fm-toS','ESP','change');await sleep(30);
  click('[data-act=m-reason][data-v="Quebra de máquina"]');click('[data-act=m-type][data-v=alt]');click('[data-act=m-prio][data-v=high]');click('[data-act=m-est][data-v="120"]');
  let rs=rasc();
  ok(rs&&rs.titulo==='Rascunho completo'&&rs.desc==='texto do rascunho'&&rs.fromS==='CNC'&&rs.toS==='ESP'&&rs.motivo==='Quebra de máquina'&&rs.tipo==='alt'&&rs.prio==='high'&&rs.est===120&&!('tk' in rs),'rascunho guarda título, descrição, setores, motivo, tipo, prioridade e tempo (sem tk)');
  await fechaForm(T);await abreForm(T);
  ok($('#dm-fm-rasc')&&/Rascunho recuperado de \d\d\/\d\d \d\d:\d\d/.test($('#dm-fm-rasc').textContent),'reabrir mostra "Rascunho recuperado de dd/mm hh:mm"');
  ok($('#dm-fm-title').value==='Rascunho completo'&&$('#dm-fm-desc').value==='texto do rascunho'&&$('#dm-fm-fromS').value==='CNC'&&$('#dm-fm-toS').value==='ESP'&&press('[data-act=m-reason]').join()==='Quebra de máquina'&&press('[data-act=m-type]').join()==='alt'&&press('[data-act=m-prio]').join()==='high'&&press('[data-act=m-est]').join()==='120','recuperou todos os campos');
  ok(rasc().cid===rs.cid,'a chave do pedido é a mesma do rascunho');
  // rascunho só com espaços não vale
  type('#dm-fm-title','   ');type('#dm-fm-desc','  ');ok(rasc()===null,'título e descrição só com espaços: o rascunho é apagado');
  type('#dm-fm-title','Rascunho completo');
  click('[data-act=m-draft-x]');await sleep(30);
  ok(!$('#dm-fm-rasc')&&$('#dm-fm-title').value===''&&$('#dm-fm-desc').value===''&&rasc()===null&&press('[data-act=m-reason]').length===0,'Descartar: formulário em branco e rascunho apagado');
  await fechaForm(T);
  // expira em 24 h (limite)
  const guarda=(extra)=>w.localStorage.setItem('dm-rascunho:adm',JSON.stringify({t:Date.now(),cid:'chave-rasc-0001',tipo:'dem',titulo:'Rascunho antigo',desc:'',fromS:'PCP',toS:'CNC',toP:'',motivo:'Outro',prio:'norm',est:60,...extra}));
  guarda({t:Date.now()-24*3600000+60000});await abreForm(T);
  ok($('#dm-fm-rasc')&&$('#dm-fm-title').value==='Rascunho antigo','rascunho de 23 h 59 min ainda volta');
  await fechaForm(T);
  guarda({t:Date.now()-24*3600000-1000});await abreForm(T);
  ok(!$('#dm-fm-rasc')&&$('#dm-fm-title').value==='','rascunho de 24 h e 1 s não volta');
  await fechaForm(T);
  // o que veio do aparelho passa pelas mesmas listas da tela
  guarda({tipo:'xx',titulo:'T'.repeat(200),desc:'D'.repeat(2500),fromS:'ZZ',toS:'PIN',toP:'p99',motivo:'Inventado',prio:'max',est:99999,cid:'curto'});await abreForm(T);
  ok($('#dm-fm-title').value.length===140&&$('#dm-fm-desc').value.length===2000&&press('[data-act=m-type]').join()==='dem'&&press('[data-act=m-prio]').join()==='norm'&&press('[data-act=m-reason]').length===0&&$('#dm-fm-fromS').value==='PCP'&&$('#dm-fm-toS').value===''&&press('[data-act=m-est]').join()==='60','rascunho adulterado: título cortado em 140, descrição em 2000, tipo/prioridade/motivo/setores/tempo voltam ao padrão');
  ok(rasc().cid!=='curto'&&/^[A-Za-z0-9_-]{8,64}$/.test(rasc().cid),'chave inválida no rascunho é trocada por uma nova válida');
  await fechaForm(T);
  guarda({est:0});await abreForm(T);ok(press('[data-act=m-est]').join()==='60','est=0 no rascunho: volta para 1 h');await fechaForm(T);
  guarda({est:43200});await abreForm(T);ok($('#dm-fm-estN').value==='720'&&$('#dm-fm-estU').value==='h','est=43200 no rascunho: aceito (720 h)');await fechaForm(T);
  guarda({est:43201});await abreForm(T);ok(press('[data-act=m-est]').join()==='60','est=43201 no rascunho: volta para 1 h');await fechaForm(T);
  guarda({anexos:2});await abreForm(T);ok(/refaça os anexos/.test($('#dm-fm-rasc').textContent),'rascunho que tinha anexos avisa "refaça os anexos"');await fechaForm(T);
  w.localStorage.setItem('dm-rascunho:adm','{isso não é json');await abreForm(T);ok(!$('#dm-fm-rasc')&&$('#dm-fm-title').value==='','rascunho corrompido (JSON ruim) é ignorado sem erro');await fechaForm(T);
  w.localStorage.setItem('dm-rascunho:adm','[1,2]');await abreForm(T);ok(!$('#dm-fm-rasc'),'rascunho que não é objeto é ignorado');await fechaForm(T);
  // reabrir um rascunho renova as 24 h
  guarda({t:Date.now()-23*3600000});await abreForm(T);
  const t1=rasc().t;known('QA-C-03',Date.now()-t1<60000,'abrir o formulário regrava o rascunho com a hora de agora: um rascunho recuperado a 23 h ganha mais 24 h (a validade vira "24 h desde a última abertura")');
  ok($('#dm-fm-rasc')&&/Rascunho recuperado de/.test($('#dm-fm-rasc').textContent),'(conferência: o rascunho de 23 h voltou)');
  click('[data-act=m-draft-x]');await fechaForm(T);
  // ---------------- horário de serviço ligado: a prévia contra o prazo que o servidor grava
  const ag=(await direto('vista',{})).agenda;
  const lig=await direto('agenda/salvar',{agenda:{...ag,ativa:true}});
  ok(lig.agenda&&lig.agenda.ativa===true,'(preparo) horário de serviço ligado pelo ADM');
  await T.until(()=>T.w.document.getElementById('dmboard')); await sleep(2500);   // a tela pega a agenda no próximo /api/rev
  await abreForm(T);await preenche(T,{titulo:'Com horário ligado',est:'480'});
  type('#dm-fm-estN','43200');type('#dm-fm-estU','m','change');await sleep(30);
  const prev=$('#dm-fm-prev').textContent;
  r=await enviar();
  const hs=porTitulo('Com horário ligado')[0]||{};
  ok(r.chamada.status===200&&hs.agenda_v>=1&&hs.prazo_em>0,'com o horário ligado o servidor grava prazo_em e agenda_v ('+hs.agenda_v+')');
  ok(hs.prazo_em>hs.criado+43200*60000,'o prazo útil de 43200 min cai depois do prazo corrido (só os turnos contam)');
  known('QA-C-06',prev.indexOf(fmtTela(w,hs.prazo_em))<0&&prev.indexOf(fmtTela(w,hs.criado+43200*60000))>=0,'a prévia diz "'+prev.replace(/\s+/g,' ')+'" (tempo corrido), mas o servidor gravou o prazo de '+fmtTela(w,hs.prazo_em)+' (só dentro dos turnos)');
  await direto('agenda/salvar',{agenda:{...(await direto('vista',{})).agenda,ativa:false}});
  // ---------------- salvaguardas da tela do ADM
  w.close();
}

async function formularioDaPessoa(){
  const T=await boot('operador');const {w,$,$$,until,click,type,toast,aberto,press,rasc,erros,enviar}=T;
  ok(await until(()=>!$('#dm-login').hidden&&$('#dm-login .dm-lgcard')),'aparelho de operador abre em "Quem é você?"');
  ok($('.dm-hdnew').hidden===true||getComputedStyle(w.document.querySelector('.dm-hdnew')).display==='none'||$('.dm-hdnew').hidden,'sem identificação o botão "Nova solicitação" fica escondido');
  const entra=async(sigla,nome,cod)=>{
    ok(await until(()=>$('[data-act=lgs][data-v='+sigla+']')),'tela de entrada lista o setor '+sigla);
    click('[data-act=lgs][data-v='+sigla+']');await until(()=>$('.dm-lguser'));
    click($$('.dm-lguser').find(b=>b.textContent.includes(nome)));
    type('#dm-lg-code',cod);click('.dm-lgbtn');
    return until(()=>$('#dm-login').hidden&&new RegExp('Olá, '+nome).test($('#dmboard').textContent));
  };
  ok(await entra('PCP','Helena','1111'),'Helena entra com o código');
  ok(await abreForm(T),'pessoa abre o formulário');
  ok(!$('#dm-fm-fromS')&&$('.dm-fixed')&&/PCP/.test($('.dm-fixed').textContent)&&/Helena/.test($('.dm-fixed').textContent),'pessoa não escolhe o solicitante: aparece fixo "PCP Helena"');
  ok(!$('#dm-fm-rasc'),'sem rascunho de outra pessoa (o do ADM é outro: dm-rascunho:adm)');
  await preenche(T,{titulo:'Pedido da Helena',toS:'CNC',motivo:'Falta de material',prio:'urg'});
  const hel=disco().pessoas.find(p=>p.nome==='Helena').id;
  ok(w.localStorage.getItem('dm-rascunho:'+hel)&&JSON.parse(w.localStorage.getItem('dm-rascunho:'+hel)).titulo==='Pedido da Helena'&&!w.localStorage.getItem('dm-rascunho:adm'),'rascunho da pessoa fica na chave dm-rascunho:<id dela>');
  ok(!/"tk"/.test(w.localStorage.getItem('dm-rascunho:'+hel)),'o rascunho nunca guarda o tk');
  const antesUrg=disco().notas.filter(n=>n.tipo==='urg').length;
  let r=await enviar();
  const g=porTitulo('Pedido da Helena')[0]||{};
  ok(r.pediu&&r.chamada.status===200&&!('de_s' in r.chamada.corpo)&&typeof r.chamada.corpo.tk==='string','pessoa envia com o tk e sem de_s');
  ok(JSON.stringify(g.de)==='{"s":"PCP","p":"'+hel+'"}'&&g.eventos[0].quem==='Helena','solicitante gravado é ela mesma');
  ok(disco().notas.filter(n=>n.tipo==='urg').length===antesUrg+1&&disco().notas.some(n=>n.tipo==='urg'&&n.quem==='Helena'),'urgente da pessoa avisa o Escritório com o nome dela');
  ok(await until(()=>$$('.dm-ocard h3').some(h=>h.textContent==='Pedido da Helena')),'depois de enviar a tela vai para Enviadas e mostra o pedido');
  ok(w.localStorage.getItem('dm-rascunho:'+hel)===null,'rascunho da pessoa apagado depois de enviar');
  // o pedido sem setor etc.: mesma validação
  await abreForm(T);let e=await enviar();ok(!e.pediu&&erros().join('|')==='Título|Setor responsável|Motivo','pessoa enviando vazio: mesmos três erros, sem pedido');
  // pessoa com tk caído no meio do formulário: volta ao "Quem é você?" e o rascunho sobrevive
  type('#dm-fm-title','Rascunho que sobrevive ao login');type('#dm-fm-toS','ESP','change');await sleep(30);click('[data-act=m-reason][data-v="Outro"]');
  const cidAntes=rasc('dm-rascunho:'+hel).cid;
  const pessoaHel=disco().pessoas.find(p=>p.id===hel);
  await direto('pessoa/ativar',{id:hel,rev:pessoaHel._rv});   // desativa: o tk dela deixa de valer
  const n0=ndem();e=await enviar();
  ok(e.pediu&&e.chamada.status===401&&ndem()===n0,'pessoa desativada no meio do formulário: o servidor responde 401 e nada é gravado');
  ok(await until(()=>!$('#dm-login').hidden)&&!aberto(),'a tela volta ao "Quem é você?" (formulário fechado)');
  ok(JSON.parse(w.localStorage.getItem('dm-rascunho:'+hel)||'null')&&JSON.parse(w.localStorage.getItem('dm-rascunho:'+hel)).cid===cidAntes,'o rascunho continua no aparelho, com a mesma chave');
  await direto('pessoa/ativar',{id:hel,rev:disco().pessoas.find(p=>p.id===hel)._rv});   // reativa
  await sleep(200);
  ok(await entra('PCP','Helena','1111'),'Helena entra de novo');
  await abreForm(T);
  ok($('#dm-fm-rasc')&&$('#dm-fm-title').value==='Rascunho que sobrevive ao login'&&$('#dm-fm-toS').value==='ESP','depois do "Identifique-se de novo" o formulário traz o rascunho de volta');
  await fechaForm(T);
  // outra pessoa no mesmo aparelho não vê o rascunho da Helena
  click('#dm-uchip');await until(()=>$('[data-act=logout]'));
  if($('[data-act=logout]')){click('[data-act=logout]');await until(()=>!$('#dm-login').hidden);
    ok(await entra('CNC','Carlos','2222'),'Carlos entra no mesmo aparelho');
    await abreForm(T);ok(!$('#dm-fm-rasc')&&$('#dm-fm-title').value==='','outra pessoa no mesmo aparelho NÃO vê o rascunho da Helena');
    ok(/CNC/.test($('.dm-fixed').textContent)&&/Carlos/.test($('.dm-fixed').textContent),'o solicitante fixo agora é Carlos (CNC)');
    await fechaForm(T);
  }else ok(false,'não achei o botão Sair para trocar de pessoa');
  w.close();
}

(async()=>{
  const srv=await startServer();
  try{
    // cenário: PCP (Helena), CNC (Carlos, Bruno), ESP, ALM (ninguém) e PIN (inativo)
    for(const [id,nome] of [['PCP','Planejamento'],['CNC','Corte CNC'],['ESP','Espumação'],['ALM','Almoxarifado'],['PIN','Pintura']])
      await direto('setor/salvar',{modo:'novo',id,nome,icone:'⚙️',cor:'#3B82F6',rev:0});
    for(const [nome,setor,codigo] of [['Helena','PCP','1111'],['Carlos','CNC','2222'],['Bruno','CNC','3333']])
      await direto('pessoa/salvar',{modo:'novo',nome,setor,codigo,rev:0});
    await direto('setor/ativar',{id:'PIN',rev:disco().setores.find(s=>s.id==='PIN')._rv});
    ok(disco().setores.find(s=>s.id==='PIN').ativo===false,'(preparo) setor PIN inativo');
    await formularioDoAdm();
    await formularioDaPessoa();
  }finally{killTree(srv);
    try{fs.rmSync(base,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+base)}}
  console.log('\n[qa criar jsdom] casos: '+N+'  passou: '+(N-F)+'  falhou: '+F+'  bugs conhecidos checados: '+K);
  console.log(process.exitCode?'houve falhas':'tudo certo');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());
