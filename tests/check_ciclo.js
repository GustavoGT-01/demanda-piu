const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// QA do ciclo da solicitação na TELA (sessão C): cartões e gaveta por papel e situação, botões que existem / não existem,
// modais de pausa, conclusão, repasse e cancelamento (limites e texto), estender, prioridade, cobrar, comentar e anexos,
// contra o servidor REAL (servidor.py) com DEMANDAS_DATA temporário. Complementa tests/test_qa_ciclo.py (a API).
// rodar: node tests/check_ciclo.js   (PYTHON=... troca o interpretador; E2E_VERBOSE=1 mostra o stderr do servidor)
// Bug confirmado: bug(cond, msg) imprime KNOWN-BUG enquanto a regra certa falha e não reprova; quando passa, avisa para tirar a marca.
const REPO=path.resolve(__dirname,'..');
const base=fs.mkdtempSync(path.join(os.tmpdir(),'dem-ciclo-')),data=path.join(base,'data');
fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,casos=0,falhas=0,bugs=0;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ok=(c,m)=>{casos++;console.log((c?'PASS ':'FAIL ')+m);if(!c){falhas++;process.exitCode=1}};
const bug=(c,m)=>{casos++;if(c)console.log('PASS (known-bug já corrigido: tirar a marca) '+m);else{bugs++;console.log('KNOWN-BUG '+m)}};
function startServer(){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor;s=servidor.Server(('127.0.0.1',0),servidor.Handler);print(s.server_address[1],flush=True);s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='';p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+)\s/.exec(out);if(m&&!PORT){PORT=+m[1];res(p)}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}
// pedido direto ao servidor, como outro aparelho: devolve {s: status HTTP, j: corpo}
const diretoS=async(rest,body)=>{const r=await fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const t=await r.text();let j;try{j=JSON.parse(t)}catch(e){j=t}return{s:r.status,j}};
const direto=async(rest,body)=>(await diretoS(rest,body)).j;
async function boot(papel){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/',{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>papel&&u==='/api/eu'?Promise.resolve(new Response(JSON.stringify({papel}),{headers:{'Content-Type':'application/json'}})):fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
    w.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={}}resume(){this.state='running'}
      createOscillator(){return{type:'',frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
    Object.defineProperty(w.navigator,'vibrate',{configurable:true,value:()=>true});
    w.URL.createObjectURL=()=>'blob:qa';w.URL.revokeObjectURL=()=>{};
  }});
  const w=dom.window;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  return w;
}
// uma "tela": atalhos sobre uma janela já aberta
function tela(w){
  const d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const until=async(f,ms=6000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(40))try{if(f())return true}catch(e){}return false};
  const click=s=>{const el=typeof s==='string'?$(s):s;if(!el)throw new Error('não achei '+s);el.click();return el};
  const type=(s,v,ev='input')=>{const el=typeof s==='string'?$(s):s;if(!el)throw new Error('não achei '+s);el.value=v;el.dispatchEvent(new w.Event(ev,{bubbles:true}))};
  const toast=()=>($('#dm-toast')||{}).textContent||'';
  const log=[];let ult='';   // tudo o que o toast mostrou, na ordem (um aviso pode ser trocado por outro em poucos ms)
  new w.MutationObserver(()=>{const x=toast();if(x&&x!==ult){ult=x;log.push(x)}}).observe(d.body,{subtree:true,childList:true,characterData:true});
  const modal=()=>$('#dm-modal').classList.contains('dm-on');
  const gaveta=()=>$('#dm-drawer').classList.contains('dm-on');
  const acts=sel=>$$(sel+' [data-act]').map(b=>b.dataset.act);
  // fecha qualquer modal/gaveta antes do próximo passo
  const limpa=async()=>{if(modal())click('[data-act=mclose]');if(gaveta())click('#dm-drawer [data-act=close]');await until(()=>!modal()&&!gaveta())};
  // o que o seletor de arquivos do navegador devolveria na próxima vez que a tela abrir um <input type=file>
  const escolhe=fs=>{w.__arquivos=fs.map(f=>new w.File([f.bytes],f.nome,f.tipo===undefined?{}:{type:f.tipo}))};
  if(!w.__pickPatch){w.__pickPatch=1;const orig=w.HTMLInputElement.prototype.click;
    w.HTMLInputElement.prototype.click=function(){if(this.type==='file'&&w.__arquivos){const f=w.__arquivos;w.__arquivos=null;Object.defineProperty(this,'files',{value:f});this.dispatchEvent(new w.Event('change'))}else orig.call(this)}}
  return{w,d,$,$$,until,click,type,toast,log,modal,gaveta,acts,limpa,escolhe};
}
const vista=async()=>direto('vista',{});
const dem=async id=>(await vista()).demandas.find(x=>x.id===id);
const JPG=n=>{const b=new Uint8Array(Math.max(n,4));b.set([0xff,0xd8,0xff,0xe0]);return b};
const PDFB=new Uint8Array([...Buffer.from('%PDF-1.4\n')]),PNGB=new Uint8Array([0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a,1,2,3]);
async function operador(setor,nome,codigo){
  const w=await boot('operador'),t=tela(w);
  await t.until(()=>t.$('[data-act=lgs][data-v='+setor+']'));
  t.click('[data-act=lgs][data-v='+setor+']');await t.until(()=>t.$('.dm-lguser'));
  t.click(t.$$('.dm-lguser').find(b=>b.textContent.includes(nome)));
  t.type('#dm-lg-code',codigo);t.click('.dm-lgbtn');
  ok(await t.until(()=>t.$('.dm-ophead')&&new RegExp('Olá, '+nome).test(t.$('.dm-ophead h2').textContent)),nome+' entrou no aparelho de operador');
  return t;
}
async function escritorio(){
  const w=await boot(),t=tela(w);
  await t.until(()=>t.$('[data-act=lgk][data-v=adm]'));t.click('[data-act=lgk][data-v=adm]');t.click('.dm-lgbtn');
  ok(await t.until(()=>t.$('.dm-tab[data-v=painel]')),'Escritório entrou');
  return t;
}

(async()=>{
  const srv=await startServer();
  try{
    // ---------- cenário pelo próprio servidor ----------
    for(const [id,nome] of [['PCP','Planejamento'],['CNC','Corte CNC'],['ESP','Espumação']])
      await direto('setor/salvar',{modo:'novo',id,nome,icone:'⚙️',cor:'#3B82F6',rev:0});
    const pid={};
    for(const [nome,setor,cod] of [['Helena','PCP','1111'],['Carlos','CNC','2222'],['Bruno','CNC','3333'],['Fernanda','ESP','4444']]){
      const v=await direto('pessoa/salvar',{modo:'novo',nome,setor,codigo:cod,rev:0});pid[nome]=v.pessoas[v.pessoas.length-1].id}
    const tk={};for(const [nome,cod] of [['Helena','1111'],['Carlos','2222'],['Bruno','3333'],['Fernanda','4444']])tk[nome]=(await direto('entrar',{pessoa:pid[nome],codigo:cod})).tk;
    const novaPor=async(nome,titulo,para,extra={})=>{const v=await direto('demanda/criar',Object.assign({tk:tk[nome],titulo,tipo:'dem',motivo:'Outro',prio:'norm',est:60,para,desc:''},extra));
      return v.demandas.reduce((a,b)=>+b.id.slice(4)>+a.id.slice(4)?b:a).id};
    const pes=(nome,rest,corpo)=>diretoS(rest,Object.assign({tk:tk[nome]},corpo));
    const N1=await novaPor('Helena','Fila do setor',{s:'CNC',p:null});
    const ASG=await novaPor('Helena','Designada ao Carlos',{s:'CNC',p:pid.Carlos});
    const P1=await novaPor('Helena','Em andamento do Carlos',{s:'CNC',p:null});await pes('Carlos','demanda/aceitar',{id:P1});
    const Z1=await novaPor('Helena','Pausada do Carlos',{s:'CNC',p:null});await pes('Carlos','demanda/aceitar',{id:Z1});await pes('Carlos','demanda/pausar',{id:Z1,motivo:'Máquina parada'});
    const K1=await novaPor('Helena','Concluída',{s:'CNC',p:null});await pes('Carlos','demanda/aceitar',{id:K1});await pes('Carlos','demanda/concluir',{id:K1});
    const X1=await novaPor('Helena','Cancelada',{s:'CNC',p:null});await pes('Carlos','demanda/aceitar',{id:X1});await pes('Helena','demanda/cancelar',{id:X1,motivo:'duplicada'});
    const BP=await novaPor('Helena','Em andamento do Bruno',{s:'CNC',p:null});await pes('Bruno','demanda/aceitar',{id:BP});
    const ENV=await novaPor('Carlos','Pedido do Carlos para a Espumação',{s:'ESP',p:null});

    // ======================================================================================
    // 1. Carlos (CNC, operador): cartões, lock, modais
    // ======================================================================================
    let C=await operador('CNC','Carlos','2222');
    C.click('[data-act=opf][data-v=pend]');await C.until(()=>C.$('.dm-ocard'));
    const card=id=>C.$('.dm-ocard[data-id="'+id+'"]'),cb=id=>card(id)?[...card(id).querySelectorAll('.dm-obtns [data-act]')].map(b=>b.dataset.act):null;
    ok(JSON.stringify(cb(N1))==='["accept","reassign"]','fila do setor: Aceitar e Repassar '+JSON.stringify(cb(N1)));
    ok(JSON.stringify(cb(ASG))==='["accept","reassign"]','designada a mim e ainda aberta: Aceitar e Repassar '+JSON.stringify(cb(ASG)));
    ok(JSON.stringify(cb(P1))==='["pause","finish","reassign"]','minha em andamento: Pausar, Concluir, Repassar '+JSON.stringify(cb(P1)));
    ok(JSON.stringify(cb(Z1))==='["resume","finish"]','minha pausada: Retomar e Concluir (sem Repassar) '+JSON.stringify(cb(Z1)));
    ok(JSON.stringify(cb(BP))==='[]'&&/🔒 Em andamento com Bruno/.test(card(BP).textContent),'do Bruno em andamento: sem botão e "🔒 Em andamento com Bruno" '+JSON.stringify(cb(BP)));
    ok(/Só ele\(a\) pode pausar ou concluir/.test(card(BP).querySelector('.dm-lock').textContent),'a trava explica quem pode');
    ok(!card(K1)&&!card(X1),'concluída e cancelada não aparecem em "Fila do setor"');
    ok(!card(P1).querySelector('[data-act=nudge],[data-act=cancel],[data-act=extend]'),'Carlos (não pediu) não tem Cobrar/Cancelar/Estender nos cartões recebidos');
    ok(card(P1).querySelector('.dm-tg')&&/Minha/.test(card(P1).textContent)&&!/Minha/.test(card(BP).querySelector('.dm-oh').textContent),'etiqueta "Minha" só no cartão dele');
    C.click('[data-act=opf][data-v=done]');await C.until(()=>card(K1));
    ok(card(K1)&&card(X1)&&JSON.stringify(cb(K1))==='[]'&&JSON.stringify(cb(X1))==='[]','Concluídas: concluída e cancelada sem nenhum botão');
    C.click('[data-act=opf][data-v=pend]');await C.until(()=>card(N1));

    // aceitar pelo cartão; clique duplo não duplica (botão desabilita durante o pedido)
    const aceita=card(N1).querySelector('[data-act=accept]');aceita.click();aceita.click();
    ok(await C.until(()=>card(N1)&&card(N1).dataset.st!=='new'),'Aceitar e iniciar: cartão vira em andamento '+C.toast());
    ok(!C.gaveta(),'botão do cartão não abre a gaveta');
    let r=await dem(N1);
    ok(r.status==='prog'&&r.para.p===pid.Carlos&&r.eventos.filter(e=>e.ev==='started').length===1,'clique duplo gravou uma vez só: '+r.eventos.map(e=>e.ev));
    ok(JSON.stringify(cb(N1))==='["pause","finish","reassign"]','depois de aceitar: Pausar, Concluir, Repassar');
    // aceitar a designada: continua com ele, sem novo "assigned"
    C.click(card(ASG).querySelector('[data-act=accept]'));await C.until(()=>card(ASG).dataset.st==='prog');
    r=await dem(ASG);ok(r.eventos.map(e=>e.ev).join()==='created,assigned,started','designada: aceitar não repete o "assigned" '+r.eventos.map(e=>e.ev));

    // gaveta de uma minha: só as ações dele
    C.click(card(P1).querySelector('h3'));
    ok(await C.until(()=>C.gaveta()&&C.$('#dm-drawer h2')),'clicar no cartão abre a gaveta');
    ok(JSON.stringify(C.acts('#dm-drawer .dm-dact'))==='["pause","finish","reassign"]','gaveta do responsável: Pausar, Concluir, Repassar '+JSON.stringify(C.acts('#dm-drawer .dm-dact')));
    ok(!C.$('#dm-dr-prio')&&!C.$('[data-act=extend]'),'gaveta de operador não tem Prioridade nem Estender (só o Escritório)');
    ok(/Pausas|Histórico/.test(C.$('#dm-drawer').textContent)&&C.$$('#dm-drawer .dm-tl li').map(li=>li.dataset.ev).join()==='created,assigned,started','linha do tempo: criada, responsável, iniciada');

    // ---- modal de pausa: os 6 motivos, observação, limites
    C.click('#dm-drawer [data-act=pause]');await C.until(()=>C.$('[data-act=m-pause-ok]'));
    const radios=C.$$('input[name=dm-pr]');
    ok(radios.length===6&&radios.map(x=>x.value).join('|')==='Aguardando material|Aguardando outro setor|Máquina parada|Aguardando aprovação|Troca de turno ou intervalo|Informação incompleta','pausa: os 6 motivos, nesta ordem');
    ok(radios[0].checked&&radios.filter(x=>x.checked).length===1,'pausa: o primeiro vem marcado, um só');
    ok(C.$('#dm-pobs').maxLength===500&&/opcional/.test(C.$('label[for=dm-pobs]').textContent),'pausa: observação opcional com maxlength 500');
    ok(/A gerência será avisada/.test(C.$('#dm-mbox').textContent),'pausa: aviso de que a gerência é avisada');
    C.click('[data-act=mclose]');await C.until(()=>!C.modal());
    r=await dem(P1);ok(r.status==='prog'&&r.pausas.length===0,'Cancelar na pausa: nada gravado');
    C.click('#dm-drawer [data-act=pause]');await C.until(()=>C.$('[data-act=m-pause-ok]'));
    C.d.dispatchEvent(new C.w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    ok(await C.until(()=>!C.modal()&&C.gaveta()),'Esc fecha só o modal (a gaveta continua)');
    C.click('#dm-drawer [data-act=pause]');await C.until(()=>C.$('[data-act=m-pause-ok]'));
    C.click('#dm-modal');ok(await C.until(()=>!C.modal()),'clicar fora da caixa (no fundo) fecha o modal');
    const MOT=['Aguardando material','Aguardando outro setor','Máquina parada','Aguardando aprovação','Troca de turno ou intervalo','Informação incompleta'];
    for(let i=0;i<6;i++){
      C.click('#dm-drawer [data-act=pause]');await C.until(()=>C.$('[data-act=m-pause-ok]'));
      C.click(C.$$('input[name=dm-pr]')[i]);
      C.type('#dm-pobs',i===5?'a'.repeat(700):'linha 1\n   linha 2  \t fim ');
      C.click('[data-act=m-pause-ok]');
      ok(await C.until(()=>!C.modal()&&card(P1)&&card(P1).dataset.st==='pause'),'pausa com o motivo "'+MOT[i]+'" '+C.toast());
      r=await dem(P1);const pz=r.pausas[r.pausas.length-1];
      ok(pz.motivo===MOT[i]&&pz.fim===null,'  servidor gravou o motivo "'+MOT[i]+'" (aberta)');
      ok(i===5?pz.obs==='a'.repeat(500):pz.obs==='linha 1 linha 2 fim','  observação '+(i===5?'de 700 caracteres cortada em 500':'com quebra de linha e tabs vira uma linha só')+': '+pz.obs.length+' caracteres');
      await C.until(()=>JSON.stringify(C.acts('#dm-drawer .dm-dact'))==='["resume","finish","reassign"]');
      ok(JSON.stringify(C.acts('#dm-drawer .dm-dact'))==='["resume","finish","reassign"]','  pausada: a gaveta (diferente do cartão) mostra Retomar, Concluir e Repassar '+JSON.stringify(C.acts('#dm-drawer .dm-dact')));
      ok(/Pausas registradas/.test(C.$('#dm-drawer').textContent)&&C.$$('#dm-drawer .dm-pcard').length===i+1,'  "Pausas registradas" ganha o cartão '+(i+1));
      C.click('#dm-drawer [data-act=resume]');
      ok(await C.until(()=>card(P1).dataset.st==='prog'),'  Retomar volta para em andamento '+C.toast());
    }
    r=await dem(P1);ok(r.pausas.length===6&&r.pausas.every(p=>p.fim!==null),'6 pausas, todas fechadas');
    // pausa fica no cartão enquanto pausada
    C.click('#dm-drawer [data-act=pause]');await C.until(()=>C.$('[data-act=m-pause-ok]'));C.click('[data-act=m-pause-ok]');
    await C.until(()=>card(P1).dataset.st==='pause');
    ok(/Aguardando material/.test(card(P1).querySelector('.dm-pinfo').textContent),'cartão pausado mostra o motivo da pausa');
    C.click('#dm-drawer [data-act=resume]');await C.until(()=>card(P1).dataset.st==='prog');

    // ---- modal de concluir
    C.click('#dm-drawer [data-act=finish]');await C.until(()=>C.$('[data-act=m-finish-ok]'));
    ok(C.$('#dm-fnote').maxLength===500&&/opcional/.test(C.$('label[for=dm-fnote]').textContent)&&C.$$('#dm-mbox .dm-mets div').length===4,'concluir: observação opcional maxlength 500 e as 4 medidas');
    C.click('[data-act=mclose]');await C.until(()=>!C.modal());
    r=await dem(P1);ok(r.status==='prog','Cancelar na conclusão: nada muda');
    // ---- modal de repassar (do P1, com setor diferente)
    C.click('#dm-drawer [data-act=reassign]');await C.until(()=>C.$('#dm-ra-s'));
    ok(C.$$('#dm-ra-s option').map(o=>o.value).join()==='PCP,CNC,ESP'&&C.$('#dm-ra-s').value==='CNC','repassar: lista os setores ativos, começa no atual');
    ok(C.$('#dm-ra-p').value===pid.Carlos&&C.$$('#dm-ra-p option').map(o=>o.textContent).join('|').includes('Bruno'),'repassar: pessoa atual marcada, colegas do setor na lista');
    ok(C.$('#dm-ra-n').maxLength===500,'repassar: observação maxlength 500');
    C.type('#dm-ra-s','ESP','change');
    ok(C.$$('#dm-ra-p option').map(o=>o.textContent).join('|').includes('Fernanda')&&!C.$$('#dm-ra-p option').map(o=>o.textContent).join('|').includes('Bruno')&&C.$('#dm-ra-p').value==='','trocar o setor troca a lista de pessoas e volta para "fila"');
    ok(/volta para “Aberta” e o novo setor é avisado/.test(C.$('#dm-mbox').textContent),'repassar: avisa que muda para Aberta');
    C.click('[data-act=mclose]');await C.until(()=>!C.modal());
    r=await dem(P1);ok(r.para.s==='CNC'&&r.status==='prog','Cancelar no repasse: nada muda');
    C.click('#dm-drawer [data-act=reassign]');await C.until(()=>C.$('#dm-ra-s'));
    C.type('#dm-ra-s','ESP','change');C.type('#dm-ra-p',pid.Fernanda,'change');C.type('#dm-ra-n','melhor\n  com vocês');
    C.click('[data-act=m-ra-ok]');
    ok(await C.until(()=>!C.modal()&&!card(P1)),'repassar para a Espumação: some da lista do Carlos '+C.toast());
    r=await dem(P1);ok(r.status==='new'&&r.para.s==='ESP'&&r.para.p===pid.Fernanda&&r.iniciado===null,'repassada: aberta, destino Espumação · Fernanda');
    ok(r.eventos[r.eventos.length-1].nota==='Para ESP · Fernanda — melhor com vocês','nota do repasse sem quebra de linha: '+r.eventos[r.eventos.length-1].nota);
    await C.limpa();
    // concluir de verdade, pela gaveta, com observação longa
    C.click(card(N1).querySelector('h3'));await C.until(()=>C.gaveta());
    C.click('#dm-drawer [data-act=finish]');await C.until(()=>C.$('[data-act=m-finish-ok]'));
    C.type('#dm-fnote','z'.repeat(650));C.click('[data-act=m-finish-ok]');
    ok(await C.until(()=>!C.modal()&&/concluída/i.test(C.toast())),'concluir: confirma '+C.toast());
    r=await dem(N1);ok(r.status==='done'&&r.eventos[r.eventos.length-1].nota==='z'.repeat(500),'conclusão com 650 caracteres grava 500');
    ok(!C.$('#dm-drawer .dm-dact'),'concluída: a gaveta não tem mais ações');
    await C.limpa();
    // enviados: Cobrar e Cancelar (Carlos pediu ENV para a Espumação)
    C.click('[data-act=tab][data-v=sent]');await C.until(()=>card(ENV));
    ok(JSON.stringify(cb(ENV))==='["nudge","cancel"]','enviados: ativa tem Cobrar e Cancelar '+JSON.stringify(cb(ENV)));
    C.click(card(ENV).querySelector('[data-act=nudge]'));
    ok(await C.until(()=>/Cobrança enviada para Espumação/.test(C.toast())),'Cobrar: toast com o setor '+C.toast());
    r=await dem(ENV);ok(r.eventos[r.eventos.length-1].ev==='nudge'&&r.eventos[r.eventos.length-1].quem==='Carlos','Cobrar gravou o evento "nudge" do Carlos');
    C.click(card(ENV).querySelector('[data-act=cancel]'));await C.until(()=>C.$('[data-act=m-cn-ok]'));
    ok(C.$('#dm-cn').maxLength===500&&/Motivo do cancelamento/.test(C.$('#dm-mbox').textContent),'cancelar: motivo maxlength 500');
    C.click('[data-act=mclose]');await C.until(()=>!C.modal());r=await dem(ENV);ok(r.status==='new','Voltar no cancelamento: nada muda');
    C.click(card(ENV).querySelector('[data-act=cancel]'));await C.until(()=>C.$('[data-act=m-cn-ok]'));
    C.type('#dm-cn','não é\nmais   preciso');C.click('[data-act=m-cn-ok]');
    ok(await C.until(()=>!C.modal()&&/cancelada/i.test(C.toast())),'cancelar: confirma '+C.toast());
    r=await dem(ENV);ok(r.status==='canc'&&r.eventos[r.eventos.length-1].nota==='não é mais preciso','motivo gravado numa linha só: '+r.eventos[r.eventos.length-1].nota);
    C.click('[data-act=opf][data-v=done]');await C.until(()=>card(ENV));
    ok(card(ENV)&&JSON.stringify(cb(ENV))==='[]','cancelada vai para Concluídas, sem botões');
    // comentar (Carlos é do setor destino de BP)
    C.click('[data-act=tab][data-v=recv]');C.click('[data-act=opf][data-v=pend]');await C.until(()=>card(BP));
    C.click(card(BP).querySelector('h3'));await C.until(()=>C.gaveta());
    ok(!!C.$('#dm-cmt')&&C.$('#dm-cmt').maxLength===1000,'comentário: campo com maxlength 1000');
    ok(/Em andamento com <b>Bruno|Em andamento com Bruno/.test(C.$('#dm-drawer .dm-dact').textContent)&&!C.$('#dm-drawer [data-act=pause]'),'gaveta da demanda do Bruno: "🔒 Em andamento com Bruno", sem Pausar/Concluir');
    ok(!!C.$('#dm-drawer [data-act=reassign]')===false,'e sem Repassar (não é dele nem está aberta)');
    const n0=(await dem(BP)).comentarios.length;
    C.click('#dm-drawer [data-act=comment]');C.type('#dm-cmt','   ');C.click('#dm-drawer [data-act=comment]');await sleep(150);
    ok((await dem(BP)).comentarios.length===n0,'comentário vazio ou só espaços não é enviado');
    C.type('#dm-cmt','<b>oi</b> pelo botão');C.click('#dm-drawer [data-act=comment]');
    ok(await C.until(()=>/oi/.test(C.$('.dm-cmts').textContent)),'comentar pelo botão: aparece na gaveta '+C.toast());
    ok(C.$('#dm-cmt').value==='','o campo esvazia depois de enviar');
    ok(!C.$('.dm-cmts b')&&/<b>oi<\/b> pelo botão/.test(C.$('.dm-cmts').textContent),'HTML no comentário continua texto');
    C.type('#dm-cmt','pelo Enter');C.$('#dm-cmt').dispatchEvent(new C.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
    await C.until(()=>/pelo Enter/.test(C.$('.dm-cmts').textContent));
    ok(/pelo Enter/.test(C.$('.dm-cmts').textContent),'comentar com Enter');
    C.type('#dm-cmt','q'.repeat(1500));C.click('#dm-drawer [data-act=comment]');await sleep(600);
    const cs=(await dem(BP)).comentarios;ok(cs[cs.length-1].texto.length===1000,'comentário de 1500 caracteres sai cortado em 1000: '+cs[cs.length-1].texto.length);
    ok(cs.length===n0+3&&cs.every(c=>c.quem==='Carlos'||c.quem==='Bruno'),'3 comentários novos, todos do Carlos');
    await C.limpa();
    C.w.close();

    // ======================================================================================
    // 2. Helena (PCP, quem pediu): cobrar/cancelar, comentar, anexos
    // ======================================================================================
    const H=await operador('PCP','Helena','1111');
    const hc=id=>H.$('.dm-ocard[data-id="'+id+'"]'),hb=id=>hc(id)?[...hc(id).querySelectorAll('.dm-obtns [data-act]')].map(b=>b.dataset.act):null;
    H.click('[data-act=tab][data-v=sent]');await H.until(()=>H.$('.dm-ocard'));
    ok(H.$$('.dm-ocard').length>0&&H.$$('.dm-ocard').every(c=>/Para /.test(c.querySelector('.dm-route').textContent)),'"Enviadas": cartões mostram "Para <quem atende>"');
    const act1=[ASG,BP,Z1].filter(id=>hc(id));
    ok(act1.length===3&&act1.every(id=>JSON.stringify(hb(id))==='["nudge","cancel"]'),'Helena: toda enviada em aberto tem Cobrar e Cancelar (e nada de Aceitar/Pausar)');
    ok(!hc(P1)||JSON.stringify(hb(P1))==='["nudge","cancel"]','a repassada continua dela para cobrar');
    H.click('[data-act=opf][data-v=done]');await H.until(()=>hc(K1));
    ok(hc(K1)&&hc(X1)&&JSON.stringify(hb(K1))==='[]'&&JSON.stringify(hb(X1))==='[]','Helena: concluída e cancelada sem botão');
    // gaveta de uma dela: Cobrar e Cancelar; anexos
    H.click('[data-act=opf][data-v=pend]');await H.until(()=>hc(BP));
    H.click(hc(BP).querySelector('h3'));await H.until(()=>H.gaveta());
    ok(JSON.stringify(H.acts('#dm-drawer .dm-dact'))==='["nudge","cancel"]','gaveta de quem pediu: Cobrar e Cancelar '+JSON.stringify(H.acts('#dm-drawer .dm-dact')));
    ok(!H.$('#dm-drawer [data-act=accept],#dm-drawer [data-act=pause],#dm-drawer [data-act=finish],#dm-drawer [data-act=reassign]'),'quem pediu (de outro setor) não vê Aceitar/Pausar/Concluir/Repassar');
    ok(!H.$('#dm-dr-prio')&&!H.$('[data-act=extend]'),'e não vê Prioridade nem Estender');
    const anx=()=>H.$$('#dm-drawer .dm-file');
    ok(!!H.$('#dm-drawer [data-act=aadd]')&&/Nenhum anexo/.test(H.$('#dm-drawer .dm-files').textContent),'anexos: botão "＋ Adicionar" e "Nenhum anexo"');
    // --- seletor de arquivos: o que o cliente recusa antes de mandar
    const manda=async(fs)=>{H.escolhe(fs);H.click('#dm-drawer [data-act=aadd]');await sleep(500)};
    await manda([{nome:'virus.exe',bytes:JPG(10),tipo:'application/octet-stream'}]);
    ok(/Só JPG, PNG ou PDF: virus\.exe/.test(H.toast())&&anx().length===0,'cliente recusa extensão fora de JPG/PNG/PDF: '+H.toast());
    await manda([{nome:'foto.jpg',bytes:JPG(10),tipo:'image/gif'}]);
    ok(/Tipo não aceito: foto\.jpg/.test(H.toast())&&anx().length===0,'cliente recusa MIME que não é jpeg/png/pdf: '+H.toast());
    await manda([{nome:'vazio.jpg',bytes:new Uint8Array(0),tipo:'image/jpeg'}]);
    ok(/vazio\.jpg está vazio/.test(H.toast())&&anx().length===0,'cliente recusa arquivo vazio: '+H.toast());
    await manda([{nome:'grande.jpg',bytes:JPG(5*1024*1024+1),tipo:'image/jpeg'}]);
    ok(/grande\.jpg passa de 5 MB/.test(H.toast())&&anx().length===0,'cliente recusa 5 MB + 1 byte: '+H.toast());
    await manda([{nome:'falso.jpg',bytes:new Uint8Array([1,2,3,4,5]),tipo:'image/jpeg'}]);
    ok(/Tipo de arquivo não aceito/.test(H.toast())&&anx().length===0,'servidor recusa .jpg que não é JPG (assinatura) e a tela mostra a frase dele: '+H.toast());
    // --- aceitos
    await manda([{nome:'cinco.jpg',bytes:JPG(5*1024*1024),tipo:'image/jpeg'}]);
    ok(anx().length===1&&/📎 1 anexo\(s\) enviado\(s\)/.test(H.toast()),'5 MB exatos passam de ponta a ponta '+H.toast());
    await manda([{nome:'<b>nome</b>.PNG',bytes:PNGB,tipo:'image/png'},{nome:'doc.pdf',bytes:PDFB,tipo:'application/pdf'},{nome:'sem-tipo.jpeg',bytes:JPG(30)}]);
    ok(anx().length===4,'PNG (extensão maiúscula), PDF e JPEG sem MIME entram: '+anx().length);
    ok(!H.$('#dm-drawer .dm-files b')&&/&lt;b&gt;|<b>nome<\/b>\.PNG/.test(H.$('#dm-drawer .dm-files').innerHTML+H.$('#dm-drawer .dm-files').textContent),'nome do anexo com HTML aparece como texto');
    ok(/🖼️ cinco\.jpg/.test(anx()[0].textContent)&&/📄 doc\.pdf/.test(anx()[2].textContent),'ícone 🖼️ para imagem e 📄 para PDF');
    ok(!!H.$('#dm-drawer [data-act=aadd]'),'com 4 anexos ainda dá para adicionar');
    await manda([{nome:'a5.jpg',bytes:JPG(20),tipo:'image/jpeg'},{nome:'a6.jpg',bytes:JPG(20),tipo:'image/jpeg'},{nome:'a7.jpg',bytes:JPG(20),tipo:'image/jpeg'}]);
    ok(anx().length===5&&/1 anexo\(s\) enviado\(s\).*2 ficou\(aram\) de fora.*5/.test(H.toast()),'escolhendo 3 com só 1 vaga: entra 1 e o mesmo aviso diz que 2 ficaram de fora (QA-C-03): '+anx().length+' / "'+H.toast()+'"');
    ok(!H.$('#dm-drawer [data-act=aadd]'),'com 5 anexos o botão "Adicionar" some');
    r=await dem(BP);ok(r.anexos.length===5&&r.anexos.every(a=>a.por==='Helena'),'servidor: 5 anexos, todos da Helena');
    ok(r.eventos.filter(e=>e.ev==='attach').length===5,'um evento "attach" por anexo');
    // abrir imagem / PDF
    H.click(anx()[0].querySelector('[data-act=aopen]'));
    ok(await H.until(()=>H.$('#dm-vw-img')&&H.$('#dm-vw-t').textContent==='cinco.jpg'),'clicar na imagem abre o visualizador com o nome');
    ok(H.$('#dm-vw-img').getAttribute('src')==='blob:qa'&&!!H.$('#dm-vw-dl'),'visualizador tem a imagem e o link Baixar');
    H.click('#dm-modal [data-act=mclose]');await H.until(()=>!H.modal());
    H.click(anx()[2].querySelector('[data-act=aopen]'));
    ok(await H.until(()=>/doc\.pdf baixado/.test(H.toast())),'clicar no PDF baixa o arquivo: '+H.toast());
    // remover: ✕ só nos dela, com confirmação
    ok(anx().every(f=>f.querySelector('[data-act=adel]')),'Helena vê ✕ em todos (enviou todos)');
    H.click(anx()[4].querySelector('[data-act=adel]'));await H.until(()=>H.$('[data-act=cf-ok]'));
    ok(/Remover <b>a5\.jpg<\/b>|Remover a5\.jpg/.test(H.$('#dm-mbox').innerHTML)||/a5\.jpg/.test(H.$('#dm-mbox').textContent),'confirmação cita o anexo: '+H.$('#dm-mbox h2').textContent);
    H.click('[data-act=mclose]');await H.until(()=>!H.modal());ok(anx().length===5,'Voltar na confirmação: nada removido');
    H.click(anx()[4].querySelector('[data-act=adel]'));await H.until(()=>H.$('[data-act=cf-ok]'));H.click('[data-act=cf-ok]');
    ok(await H.until(()=>anx().length===4&&!H.modal()),'Remover anexo: some da gaveta '+H.toast());
    r=await dem(BP);ok(r.anexos.length===4,'servidor: 4 anexos');
    ok(!!H.$('#dm-drawer [data-act=aadd]'),'com vaga de novo, o botão "Adicionar" volta');
    // comentário de quem pediu → aparece para o outro lado
    H.type('#dm-cmt','da Helena');H.click('#dm-drawer [data-act=comment]');
    ok(await H.until(()=>/da Helena/.test(H.$('.dm-cmts').textContent)),'Helena comenta na demanda que pediu');
    // cobrar e cancelar pela gaveta
    H.click('#dm-drawer [data-act=nudge]');ok(await H.until(()=>/Cobrança enviada para Corte CNC/.test(H.toast())),'Cobrar pela gaveta: '+H.toast());
    await H.limpa();
    // ADM-only e demanda alheia: Fernanda não vê as demandas da CNC
    // cancelar uma ainda aberta pela gaveta
    H.click(hc(ASG).querySelector('h3'));await H.until(()=>H.gaveta());
    H.click('#dm-drawer [data-act=cancel]');await H.until(()=>H.$('[data-act=m-cn-ok]'));H.type('#dm-cn','Helena desistiu');H.click('[data-act=m-cn-ok]');
    ok(await H.until(()=>!H.modal()&&(H.$('.dm-pill[data-st=canc]')||/Cancelad/.test(H.$('#dm-drawer').textContent))),'Cancelar pela gaveta '+H.toast());
    r=await dem(ASG);ok(r.status==='canc'&&r.eventos[r.eventos.length-1].quem==='Helena','cancelada pela Helena');
    ok(!H.$('#dm-drawer .dm-dact'),'cancelada: a gaveta fecha as ações');
    ok(!H.$('#dm-drawer [data-act=aadd]'),'cancelada: não recebe anexo (botão some)');
    await H.limpa();
    // concluída ainda recebe anexo, mas não deixa remover
    H.click('[data-act=opf][data-v=done]');await H.until(()=>hc(K1));H.click(hc(K1).querySelector('h3'));await H.until(()=>H.gaveta());
    ok(!!H.$('#dm-drawer [data-act=aadd]'),'concluída: ainda dá para adicionar anexo (regra do contrato)');
    await manda([{nome:'depois.jpg',bytes:JPG(20),tipo:'image/jpeg'}]);
    ok(anx().length===1&&!anx()[0].querySelector('[data-act=adel]'),'concluída: anexo novo entra e não tem ✕ (só em demanda ativa)');
    await H.limpa();H.w.close();

    // ======================================================================================
    // 3. Fernanda (ESP): não vê o que não é dela; repassada chega na fila dela
    // ======================================================================================
    const F=await operador('ESP','Fernanda','4444');
    F.click('[data-act=opf][data-v=pend]');await F.until(()=>F.$('.dm-ocard'));
    const fc=id=>F.$('.dm-ocard[data-id="'+id+'"]');
    ok(!!fc(P1)&&JSON.stringify([...fc(P1).querySelectorAll('.dm-obtns [data-act]')].map(b=>b.dataset.act))==='["accept","reassign"]','a repassada chegou na Fernanda: Aceitar e Repassar');
    ok(!fc(BP)&&!fc(N1)&&!fc(K1),'Fernanda não vê demandas da CNC');
    F.click('[data-act=tab][data-v=sent]');ok(/Você ainda não enviou/.test(F.$('.dm-opwrap').textContent)||F.$$('.dm-ocard').length===0,'sem pedidos próprios: mensagem vazia');
    F.w.close();

    // ======================================================================================
    // 4. Escritório: gaveta com Cobrar, Reatribuir, +30 min, +1 h, Prioridade, Cancelar
    // ======================================================================================
    const A=await escritorio();
    A.click('[data-act=tab][data-v=sol]');await A.until(()=>A.$('[data-act=open]'));
    const abre=async id=>{await A.limpa();let el=A.$$('[data-act=open][data-id="'+id+'"]')[0];
      if(!el){A.click('[data-act=tab][data-v=sol]');A.click('[data-act=view][data-v=list]');A.type('#dm-fSt','','change');await A.until(()=>A.$('[data-act=open][data-id="'+id+'"]'));el=A.$('[data-act=open][data-id="'+id+'"]')}
      if(!el)throw new Error('sem '+id);A.click(el);await A.until(()=>A.gaveta()&&A.$('#dm-drawer h2'))};
    await abre(BP);
    ok(JSON.stringify(A.acts('#dm-drawer .dm-dact'))==='["nudge","reassign","extend","extend","cancel"]','Escritório, ativa: Cobrar, Reatribuir, +30 min, +1 h, Cancelar '+JSON.stringify(A.acts('#dm-drawer .dm-dact')));
    ok(!!A.$('#dm-dr-prio')&&A.$$('#dm-dr-prio option').map(o=>o.value).join()==='low,norm,high,urg'&&A.$('#dm-dr-prio').value==='norm','seletor de prioridade: 4 valores, atual marcado');
    ok(!A.$('#dm-drawer [data-act=accept],#dm-drawer [data-act=pause],#dm-drawer [data-act=resume],#dm-drawer [data-act=finish]'),'Escritório não tem Aceitar/Pausar/Retomar/Concluir (só o responsável)');
    ok(A.$$('#dm-drawer [data-act=extend]').map(b=>b.dataset.v).join()==='30,60','botões de estender: 30 e 60 minutos');
    const est0=(await dem(BP)).est;
    A.click(A.$$('#dm-drawer [data-act=extend]')[0]);await A.until(()=>/estendido em 30 min/.test(A.toast()));
    ok((await dem(BP)).est===est0+30,'+30 min soma 30: '+A.toast());
    A.click(A.$$('#dm-drawer [data-act=extend]')[1]);await A.until(()=>/estendido em 1h/.test(A.toast()));
    ok((await dem(BP)).est===est0+90,'+1 h soma 60: '+A.toast());
    ok(/Prazo ajustado/.test(A.$('#dm-drawer .dm-tl').textContent)&&/\+1h/.test(A.$('#dm-drawer .dm-tl').textContent),'linha do tempo registra "Prazo ajustado" com +30 min e +1h');
    A.type('#dm-dr-prio','urg','change');await A.until(()=>/Prioridade: Urgente/.test(A.toast()));
    ok((await dem(BP)).prio==='urg','mudar a prioridade para Urgente: '+A.toast());
    ok(/Prioridade alterada/.test(A.$('#dm-drawer .dm-tl').textContent)&&/Normal → Urgente/.test(A.$('#dm-drawer .dm-tl').textContent),'linha do tempo: Normal → Urgente');
    A.type('#dm-dr-prio','low','change');await A.until(()=>/Prioridade: Baixa/.test(A.toast()));ok((await dem(BP)).prio==='low','e para Baixa');
    // reatribuir pelo escritório (qualquer ativa, mesmo de quem está em andamento)
    A.click('#dm-drawer [data-act=reassign]');await A.until(()=>A.$('#dm-ra-s'));
    ok(/Reatribuir solicitação/.test(A.$('#dm-mbox h2').textContent),'Escritório: o modal se chama "Reatribuir" (a pessoa vê "Repassar")');
    A.type('#dm-ra-s','CNC','change');A.type('#dm-ra-p',pid.Carlos,'change');A.click('[data-act=m-ra-ok]');
    ok(await A.until(()=>!A.modal()),'reatribuir o que estava com o Bruno para o Carlos '+A.toast());
    r=await dem(BP);ok(r.para.p===pid.Carlos&&r.status==='prog','segue em andamento com o novo responsável (mesmo setor, outra pessoa)');
    // cobrar e cancelar pelo escritório
    A.click('#dm-drawer [data-act=nudge]');await A.until(()=>/Cobrança enviada/.test(A.toast()));
    r=await dem(BP);ok(r.eventos[r.eventos.length-1].ev==='nudge'&&r.eventos[r.eventos.length-1].quem==='Escritório','Cobrar pelo Escritório grava "nudge" do Escritório');
    // comentar como Escritório
    A.type('#dm-cmt','recado do escritório');A.click('#dm-drawer [data-act=comment]');
    ok(await A.until(()=>/recado do escritório/.test(A.$('.dm-cmts').textContent)),'Escritório comenta');
    // anexos do Escritório: apaga qualquer um (ele vê ✕ em todos)
    r=await dem(BP);const nAx=r.anexos.length;
    ok(nAx===4&&A.$$('#dm-drawer .dm-fx').length===4,'Escritório vê ✕ nos 4 anexos (inclusive os da Helena)');
    A.escolhe([{nome:'escritorio.pdf',bytes:PDFB,tipo:'application/pdf'}]);A.click('#dm-drawer [data-act=aadd]');
    ok(await A.until(()=>A.$$('#dm-drawer .dm-file').length===5),'Escritório anexa um PDF');
    r=await dem(BP);ok(r.anexos[4].por==='Escritório'&&r.anexos[4].tipo==='pdf','autor "Escritório" e tipo pdf');
    A.click(A.$$('#dm-drawer .dm-fx')[0]);await A.until(()=>A.$('[data-act=cf-ok]'));A.click('[data-act=cf-ok]');
    ok(await A.until(()=>A.$$('#dm-drawer .dm-file').length===4),'Escritório remove anexo da Helena '+A.toast());
    // cota na tela do Administrador
    await A.limpa();A.click('[data-act=tab][data-v=admin]');await A.until(()=>A.$('.dm-count'));
    const uso=(await vista()).anexos_uso.bytes;
    const mostrado=A.$('.dm-count').textContent;
    ok(/anexos .+ de 300,0 MB/.test(mostrado),'Administrador mostra "anexos X de 300,0 MB": '+mostrado);
    const fB=b=>b<1024?b+' B':b<1048576?Math.round(b/1024)+' KB':(b/1048576).toFixed(1).replace('.',',')+' MB';
    bug(mostrado.includes('anexos '+fB(uso)+' de'),'QA-C-02: logo depois de remover o anexo de 5 MB, o Administrador deveria mostrar "anexos '+fB(uso)+'" (servidor: '+uso+' B) e mostra "'+mostrado.replace(/^.*· /,'')+'"');
    A.click('[data-act=tab][data-v=sol]');
    // concluída e cancelada: gaveta sem ações do Escritório
    await abre(K1);ok(!A.$('#dm-drawer .dm-dact'),'concluída: sem ações para o Escritório');
    ok(!A.$('#dm-dr-prio')&&!A.$('[data-act=extend]'),'concluída: sem Prioridade/Estender');
    await abre(X1);ok(!A.$('#dm-drawer .dm-dact'),'cancelada: sem ações para o Escritório');
    ok(!A.$('#dm-drawer [data-act=aadd]'),'cancelada: sem "Adicionar" anexo');
    ok(A.$$('#dm-drawer .dm-tl li').map(li=>li.dataset.ev).join()==='created,assigned,started,canc','linha do tempo da cancelada: '+A.$$('#dm-drawer .dm-tl li').map(li=>li.dataset.ev));
    ok(/Cancelada/.test(A.$('#dm-drawer .dm-tl').textContent)&&/duplicada/.test(A.$('#dm-drawer .dm-tl').textContent),'cancelamento mostra quem e o motivo');
    // cancelar pelo escritório uma ativa (com motivo de 700 caracteres)
    await abre(Z1);
    A.click('#dm-drawer [data-act=cancel]');await A.until(()=>A.$('[data-act=m-cn-ok]'));A.type('#dm-cn','m'.repeat(700));A.click('[data-act=m-cn-ok]');
    ok(await A.until(()=>!A.modal()&&/cancelada/i.test(A.toast())),'Escritório cancela '+A.toast());
    r=await dem(Z1);ok(r.status==='canc'&&r.eventos[r.eventos.length-1].nota==='m'.repeat(500)&&r.pausas.every(p=>p.fim!==null),'cancelada com motivo cortado em 500 e a pausa fechada');
    ok(!A.$('#dm-drawer .dm-dact'),'depois de cancelar a gaveta perde as ações');

    // ---- "Ver como" (somente leitura): sem nenhum botão de ação
    await A.limpa();A.click('[data-act=tab][data-v=admin]');await A.until(()=>A.$('[data-act=admsub][data-v=users]'));A.click('[data-act=admsub][data-v=users]');
    await A.until(()=>A.$('[data-act=impersonate][data-v="'+pid.Carlos+'"]'));A.click('[data-act=impersonate][data-v="'+pid.Carlos+'"]');
    ok(await A.until(()=>A.$('.dm-ophead')&&/Carlos/.test(A.$('.dm-ophead h2').textContent)),'"Ver como" Carlos abre a tela de operador');
    A.click('[data-act=opf][data-v=pend]');await A.until(()=>A.$('.dm-ocard'));
    ok(A.$$('.dm-ocard').length>0&&A.$$('.dm-ocard .dm-obtns').length===0,'modo visualização: nenhum botão nos cartões ('+A.$$('.dm-ocard').length+' cartões)');
    ok(!A.$('.dm-opwrap [data-act=new]'),'modo visualização: a tela de operador não tem "＋ Nova solicitação" (o botão do cabeçalho é do Escritório)');
    A.click(A.$('.dm-ocard h3'));await A.until(()=>A.gaveta());
    ok(/Modo visualização: só leitura/.test(A.$('#dm-drawer .dm-dact').textContent)&&!A.$('#dm-cmt')&&!A.$('#dm-drawer [data-act=aadd]'),'gaveta em modo visualização: só leitura, sem comentar nem anexar');
    A.w.close();

    // ======================================================================================
    // 5. Erros do servidor chegando na tela e o limite de texto na ponta HTTP
    // ======================================================================================
    const Y=await novaPor('Helena','Para testar o texto cru',{s:'CNC',p:null});await pes('Carlos','demanda/aceitar',{id:Y});
    const sur=await pes('Carlos','demanda/pausar',{id:Y,motivo:'Máquina parada',obs:'a\ud83d'});
    bug(sur.s===400,'QA-C-01: observação com meio emoji (surrogate solto) deve dar 400, deu HTTP '+sur.s+' '+String(typeof sur.j==='string'?sur.j:JSON.stringify(sur.j)).slice(0,80));
    const st=await dem(Y);ok(st.status==='prog'&&st.pausas.length===0,'a falha não deixou a demanda pela metade (continua em andamento, sem pausa)');
    const vivo=await pes('Carlos','demanda/pausar',{id:Y,motivo:'Máquina parada',obs:'normal'});ok(vivo.s===200,'o servidor continua respondendo depois da falha');
    const rr=await Promise.all([pes('Bruno','demanda/aceitar',{id:await novaPor('Helena','Corrida do aceite',{s:'CNC',p:null})})]);
    ok(rr[0].s===200,'(conferência) aceite normal de outro pelo servidor');
    // corrida: dois operadores aceitam a mesma demanda ao mesmo tempo → um só vence
    const R=await novaPor('Helena','Corrida de verdade',{s:'CNC',p:null});
    const [c1,c2]=await Promise.all([pes('Carlos','demanda/aceitar',{id:R}),pes('Bruno','demanda/aceitar',{id:R})]);
    ok([c1.s,c2.s].sort().join()==='200,409','dois aceites simultâneos: um 200 e um 409 ('+c1.s+','+c2.s+')');
    ok((await dem(R)).eventos.filter(e=>e.ev==='started').length===1,'e um só "started" gravado');
  }finally{killTree(srv);
    try{fs.rmSync(base,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+base)}}
  console.log('casos: '+casos+' · falhas: '+falhas+' · bugs conhecidos ainda presentes: '+bugs);
  console.log(process.exitCode?'houve falhas':'tudo certo');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());
