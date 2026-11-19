const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// QA sessão G (transversal) contra o servidor REAL com DEMANDAS_DATA temporário: XSS em todo campo de texto exibido,
// "Sem conexão" do Escritório, aria/foco por teclado, link #SOL-n malicioso, localStorage estragado e aviso do Windows
// fora do computador principal. Complementa tests/demandas_check.js (não repete o que ele confere).
// rodar: node tests/check_robustez.js      (PYTHON=... troca o interpretador)
// "KNOWN-BUG": defeito confirmado, listado em docs/qa/avisos.md; não reprova a execução.
const REPO=path.resolve(__dirname,'..');
const base=fs.mkdtempSync(path.join(os.tmpdir(),'dem-robustez-')),data=path.join(base,'data');
fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,FORA=false;
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
const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(!c)process.exitCode=1};
const kb=(c,m)=>console.log(c?'PASS '+m:'KNOWN-BUG '+m);
const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
async function boot(hash=''){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/'+hash,{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>FORA&&String(u).startsWith('/api/')?Promise.reject(new TypeError('Failed to fetch')):fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.__erros=[];w.addEventListener('error',e=>{w.__erros.push(e.message);console.log('PAGE ERROR',e.message)});
    w.__sons=[];w.__vib=[];w.__dt=0;const dn=w.Date.now;w.Date.now=()=>dn.call(w.Date)+w.__dt;
    w.AudioContext=class{constructor(){this.state='running';this.currentTime=0;this.destination={}}resume(){}
      createOscillator(){const o={type:'',frequency:{},connect(){},start(){},stop(){}};w.__sons.push(o);return o}
      createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
    w.__notifs=[];w.__wl=[];
    w.Notification=class{constructor(t,o){this.title=t;this.body=o&&o.body;w.__notifs.push(this)}close(){}static get permission(){return'granted'}static requestPermission(){return Promise.resolve('granted')}};
    Object.defineProperty(w.navigator,'wakeLock',{configurable:true,value:{request:async()=>{const l={release:async()=>{},addEventListener(){}};w.__wl.push(l);return l}}});
    Object.defineProperty(w.navigator,'vibrate',{configurable:true,value:p=>{w.__vib.push(p);return true}});
  }});
  const w=dom.window;w.__dom=dom;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  return w;
}
const direto=(rest,body)=>fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(async r=>{const t=await r.text();try{return JSON.parse(t)}catch(e){throw new Error(rest+' '+r.status+' '+t)}});
const sistema=(rest,body)=>fetch('http://127.0.0.1:'+PORT+'/api/'+rest,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined}).then(r=>r.json());

// Marcas de ataque: uma por tipo de contexto (texto, atributo com aspas duplas, atributo com aspas simples, tag que fecha script)
const P1='<img src=x onerror=window.__xss=1>',P2='"><svg onload=window.__xss=2>',P3="' onmouseover='window.__xss=3",P4='</script><b id=xssb>x</b>';
const JPG='/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAAAP/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==';
// o que não pode existir em lugar nenhum da página: elemento com atributo on*, <b id=xssb>, <img src=x> e a marca de execução
function limpo(w,onde){
  const d=w.document,ons=[...d.querySelectorAll('*')].filter(e=>[...e.attributes].some(a=>/^on/i.test(a.name)));
  const cheio=w.__xss===undefined&&!ons.length&&!d.getElementById('xssb')&&!d.querySelector('img[src="x"]');
  ok(cheio,'sem XSS em '+onde+(cheio?'':' (xss='+w.__xss+', on*='+ons.map(e=>e.tagName).join()+')'));
}
function semNome(w){   // botões e campos sem nome acessível na tela de agora
  const d=w.document,out=[];
  for(const b of d.querySelectorAll('button')){if(b.hidden||b.closest('[hidden]'))continue;if(!(b.textContent.trim()||b.getAttribute('aria-label')||b.title))out.push('button.'+b.className+'[data-act='+b.dataset.act+']')}
  for(const i of d.querySelectorAll('input,select,textarea')){if(i.type==='hidden'||i.closest('[hidden]'))continue;
    const lab=i.getAttribute('aria-label')||(i.id&&d.querySelector('label[for="'+i.id+'"]'))||i.closest('label');if(!lab)out.push(i.tagName.toLowerCase()+'#'+i.id)}
  return out;
}

async function semear(){
  const j=await sistema('rede');void j;
  const setor=(id,nome)=>direto('setor/salvar',{modo:'novo',id,nome,icone:'🗂️',cor:'#6366F1',rev:0});
  await setor('PCP',P1.slice(0,40));await setor('CNC',P2.slice(0,40));
  const pes=async(nome,setor,cod)=>(await direto('pessoa/salvar',{modo:'novo',nome,setor,codigo:cod,rev:0})).pessoas.slice(-1)[0].id;
  const h=await pes(P3.slice(0,60),'PCP','1111'),c=await pes(P2.slice(0,60),'CNC','2222');
  const tkH=(await direto('entrar',{pessoa:h,codigo:'1111'})).tk,tkC=(await direto('entrar',{pessoa:c,codigo:'2222'})).tk;
  const nova=(t,extra)=>direto('demanda/criar',{tk:tkH,titulo:t,tipo:'mat',motivo:'Falta de material',prio:'high',est:60,para:{s:'CNC',p:c},desc:P2+' '+P4,...extra});
  const v=await nova(P1+' corte');const D1=v.demandas.slice(-1)[0].id;
  await direto('demanda/aceitar',{tk:tkC,id:D1});
  await direto('demanda/pausar',{tk:tkC,id:D1,motivo:'Máquina parada',obs:P2});
  await direto('demanda/retomar',{tk:tkC,id:D1});
  await direto('demanda/comentar',{tk:tkH,id:D1,texto:P1+P3+P4});
  await direto('anexo/enviar',{tk:tkH,id:D1,nome:P1,dados:JPG});
  await direto('demanda/concluir',{tk:tkC,id:D1,nota:P3});
  const D2=(await nova(P2+' cancelar')).demandas.slice(-1)[0].id;
  await direto('demanda/cancelar',{tk:tkH,id:D2,motivo:P1});
  const D3=(await nova(P3+' aberta')).demandas.slice(-1)[0].id;
  await direto('demanda/reatribuir',{tk:tkC,id:D3,s:'CNC',p:null,nota:P2});
  const ag=(await direto('vista',{})).agenda;
  await direto('agenda/salvar',{agenda:{...ag,feriados:[{data:'2026-12-25',nome:P1,setores:[]},{data:'2026-12-26',nome:P2.slice(0,60),setores:['CNC']}]}});
  return {h,c,D1,D2,D3};
}
async function entraAdm(w){const $=s=>w.document.querySelector(s);await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();return until(()=>$('.dm-tab[data-v=painel]'))}

// 1. XSS: cada campo de texto aparece como texto em todas as telas, gaveta, sino, configurações e modo visualização
async function xssEmTudo(ids){
  const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)],click=s=>$(s).click();
  await until(()=>$('[data-act=lgk][data-v=adm]'));
  limpo(w,'a tela "Quem é você?" (nomes de pessoas e setores)');
  ok(await entraAdm(w),'Escritório entra');
  limpo(w,'Painel');
  for(const [aba,rotulo] of [['sol','Solicitações'],['hist','Histórico'],['cal','Calendário'],['crono','Cronoanálise'],['admin','Administração'],['painel','Painel']]){
    click('[data-act=tab][data-v='+aba+']');await sleep(400);
    limpo(w,rotulo);
    ok($$('[data-act=tab]').filter(b=>b.getAttribute('aria-pressed')==='true').length===1&&$('[data-act=tab][data-v='+aba+']').getAttribute('aria-pressed')==='true','aria-pressed: só a aba "'+rotulo+'" está marcada');
  }
  click('[data-act=tab][data-v=sol]');await sleep(300);
  ok($$('.dm-nm').some(x=>x.textContent===P1+' corte'),'o título com <img onerror> aparece como TEXTO nos cartões');
  ok(!$('#dmboard img'),'nenhum <img> nasceu do título');
  for(const id of [ids.D1,ids.D2,ids.D3]){
    const card=$$('.dm-card').find(c=>c.textContent.includes(id));
    if(!card){if(id===ids.D2){console.log('INFO '+id+' (cancelada) não está na lista padrão de Solicitações');continue}ok(false,'cartão de '+id+' na lista');continue}
    card.click();
    ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&$('#dm-drawer').textContent.includes(id)),'gaveta de '+id+' abre');
    await sleep(150);limpo(w,'gaveta de '+id+' (título, descrição, comentário, pausa, nota, anexo)');
    if(id===ids.D1){
      const t=$('#dm-drawer').textContent;
      ok(t.includes(P1)&&t.includes(P3)&&t.includes(P4),'gaveta mostra comentário, nota e anexo como texto literal');
      ok(/Máquina parada/.test(t)&&t.includes(P2),'gaveta mostra a observação da pausa como texto');
    }
    kb(d.activeElement===$('#dm-drawer .dm-x'),'foco vai para o botão Fechar ao abrir a gaveta');
    const sn=semNome(w);ok(!sn.length,'gaveta: todo botão e campo tem nome acessível '+sn.join(' | '));
    d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    ok(await until(()=>!$('#dm-drawer').classList.contains('dm-on')),'Esc fecha a gaveta');
  }
  // sino
  click('#dm-bell');ok(await until(()=>$('#dm-notif').classList.contains('dm-on')),'sino abre');await sleep(100);
  limpo(w,'gaveta do sino');
  ok($$('#dm-notif [data-act=nf]').filter(b=>b.getAttribute('aria-pressed')==='true').length===1,'sino: um filtro marcado (aria-pressed)');
  click('#dm-notif [data-act=nf][data-v=urg]');await sleep(100);
  ok($('#dm-notif [data-act=nf][data-v=urg]').getAttribute('aria-pressed')==='true'&&$('#dm-notif [data-act=nf][data-v=todos]').getAttribute('aria-pressed')==='false','sino: aria-pressed troca com o filtro');
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  ok(await until(()=>!$('#dm-notif').classList.contains('dm-on')),'Esc fecha o sino');
  // configurações: cada seção
  for(const sec of ['rede','backup','email','avisos','servidor']){
    w.NestLocal.views.demandas.config(sec);
    ok(await until(()=>$('.dm-cfg')&&$('.dm-cfgnav [aria-current=page]')&&$('.dm-cfgnav [aria-current=page]').dataset.v===sec),'Configurações · '+sec);
    await sleep(300);limpo(w,'Configurações · '+sec);
    const sn=semNome(w);kb(!sn.length,'Configurações · '+sec+': todo botão e campo tem nome acessível '+sn.join(' | '));
  }
  ok($('#dm-mbox').getAttribute('role')==='dialog'&&$('#dm-mbox').getAttribute('aria-modal')==='true'&&d.getElementById($('#dm-mbox').getAttribute('aria-labelledby')),'Configurações: role=dialog, aria-modal e aria-labelledby apontando para um título que existe');
  d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')),'Esc fecha as Configurações');
  // horário de serviço (feriados com nome de ataque)
  click('[data-act=tab][data-v=admin]');await sleep(300);
  const bh=$$('[data-act]').find(b=>/horario|hor/.test(b.dataset.act));
  if(bh){bh.click();await sleep(400);limpo(w,'Horário de serviço (nome de feriado)');ok($('#dm-mbox')&&$('#dm-mbox').textContent.includes(P1),'nome do feriado aparece como texto');d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await sleep(100)}
  else console.log('INFO botão do horário de serviço não achado pela busca genérica (coberto em demandas_check.js)');
  // modo visualização: "Ver como" cada pessoa
  click('[data-act=tab][data-v=admin]');await sleep(300);
  for(const b of $$('[data-act=impersonate]')){
    b.click();await sleep(500);limpo(w,'modo visualização como '+b.dataset.v);
    ok(/Modo visualização/.test(($('#dm-imp')||{}).textContent||''),'faixa do modo visualização para '+b.dataset.v);
    const out=$('[data-act=impexit]');if(out)out.click();await sleep(300);click('[data-act=tab][data-v=admin]');await sleep(200);
  }
  // Meus avisos, quem é você
  click('#dm-uchip');await until(()=>$('#dm-mbox [data-act=prefs]'));limpo(w,'"Quem é você" aberto');
  $('#dm-mbox [data-act=prefs]').click();ok(await until(()=>$('#dm-pf-som')),'Meus avisos abre');
  limpo(w,'Meus avisos');
  const sn=semNome(w);ok(!sn.length,'Meus avisos: todo botão e campo tem nome acessível '+sn.join(' | '));
  ok(d.getElementById($('#dm-mbox').getAttribute('aria-labelledby'))!==null||$('#dm-mbox h2'),'Meus avisos tem título');
  ok($$('[data-act=pf-turno]').every(b=>b.hasAttribute('aria-pressed')),'botões de turno têm aria-pressed');
  click('[data-act=pf-turno][data-v=B]');
  ok($('[data-act=pf-turno][data-v=B]').getAttribute('aria-pressed')==='true'&&$$('[data-act=pf-turno]').filter(b=>b.getAttribute('aria-pressed')==='true').length===1,'turno: aria-pressed troca para o escolhido');
  kb(modalFoco(w),'foco entra no diálogo aberto');
  click('[data-act=mclose]');
  ok(w.__erros.length===0,'nenhum erro de página durante a varredura: '+w.__erros.join(' | '));
  w.close();
}
const modalFoco=w=>w.document.getElementById('dm-modal').contains(w.document.activeElement);

// 2. o Escritório sem conexão: faixa, só leitura, voltar
async function offlineDoEscritorio(){
  const w=await boot(),d=w.document,$=s=>d.querySelector(s),click=s=>$(s).click();
  await entraAdm(w);
  const toast=()=>($('#dm-toast')||{}).textContent||'';
  w.NestLocal.views.demandas.config('backup');await until(()=>$('[data-act=bk-agora]'));
  FORA=true;
  ok(await until(()=>$('.dm-conn')&&/Sem conexão com a central/.test($('.dm-conn').textContent),15000),'Escritório: faixa "Sem conexão" aparece');
  ok($('.dm-conn').getAttribute('role')==='status','faixa de conexão é role=status');
  click('[data-act=bk-agora]');await sleep(500);
  ok(!/Backup feito|Cópia feita/i.test(toast())&&!w.__erros.length,'"Fazer backup agora" sem conexão não finge que fez '+toast());
  const antes=$('#dm-bk-hora')&&$('#dm-bk-hora').value;
  ok(!$('#dm-modal').classList.contains('dm-on')||$('.dm-cfg'),'a janela de Configurações continua aberta, com o que foi digitado: '+antes);
  FORA=false;click('[data-act=conn-retry]');
  ok(await until(()=>!$('.dm-conn')&&/Conexão restabelecida/.test(toast())),'volta: faixa some e avisa '+toast());
  click('[data-act=bk-agora]');
  ok(await until(()=>/Verificado/.test(($('#dm-bk-ult')||{}).textContent||''),10000),'depois de voltar, o backup funciona e fica verificado');
  ok(w.__erros.length===0,'sem erro de página: '+w.__erros.join(' | '));
  w.close();
}

// 3. link #SOL-n malicioso ou estranho
async function linkEstranho(ids){
  for(const hash of ['#SOL-9999','#SOL-12345678901','#sol-1','#SOL-1"><svg onload=window.__xss=8>','#SOL-<img src=x onerror=window.__xss=9>','#SOL-','#','#%00','#SOL-1%0A']){
    const w=await boot(hash),d=w.document;
    await entraAdm(w);await sleep(500);
    limpo(w,'link '+hash.slice(0,30));
    ok(!w.__erros.length,'link '+hash.slice(0,30)+': nenhum erro de página '+w.__erros.join('|'));
    ok(!d.getElementById('dm-drawer').classList.contains('dm-on')||/SOL-\d{1,9}/.test(d.getElementById('dm-drawer').textContent),'link '+hash.slice(0,30)+': só abre gaveta de demanda de verdade');
    w.close();
  }
  const w=await boot('#'+ids.D1),d=w.document;await entraAdm(w);
  ok(await until(()=>d.getElementById('dm-drawer').classList.contains('dm-on')&&d.getElementById('dm-drawer').textContent.includes(ids.D1)),'link válido #'+ids.D1+' abre a gaveta');
  w.close();
}

// 4. localStorage estragado
async function armazenamentoEstragado(){
  const w=await boot(),d=w.document,$=s=>d.querySelector(s);
  await entraAdm(w);await sleep(800);d.dispatchEvent(new w.Event('pointerdown'));
  const badge=()=>$('#dm-badge').hidden?0:+$('#dm-badge').textContent.replace('+','');
  const pede=t=>direto('demanda/criar',{titulo:t,tipo:'mat',motivo:'Falta de material',prio:'urg',est:60,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
  for(const lixo of ['[]','"x"','null','5','{x','{"som":"zzz","vibrar":"nao","juntar":5,"sistema":"sim"}','{"som":{"a":1}}']){
    w.localStorage.setItem('dm-avisos-aparelho',lixo);w.__dt+=25000;
    const b0=badge();
    await pede('Aviso com armazenamento '+lixo.slice(0,8));
    const chegou=await until(()=>badge()>b0);await sleep(150);
    ok(chegou&&!w.__erros.length,'localStorage '+JSON.stringify(lixo).slice(0,30)+': o aviso chega e nada quebra '+w.__erros.join('|'));
  }
  w.localStorage.removeItem('dm-avisos-aparelho');
  for(const lixo of ['{x','[]','"x"','null','{"t":"x","titulo":5,"desc":[]}','{"t":'+Date.now()+',"titulo":"<img src=x onerror=window.__xss=4>","desc":"d","toS":"CNC"}']){
    w.localStorage.setItem('dm-rascunho:adm',lixo);
    $('.dm-hdnew').click();
    ok(await until(()=>$('#dm-fm-title')),'rascunho '+lixo.slice(0,24)+': o formulário abre');
    limpo(w,'rascunho '+lixo.slice(0,24));
    $('[data-act=mclose]').click();await sleep(60);
  }
  ok(!w.__erros.length,'sem erro de página: '+w.__erros.join('|'));
  w.close();
}

// 5. aviso do Windows e tela acesa só no computador principal
async function foraDoComputadorPrincipal(){
  const w=await boot(),d=w.document,$=s=>d.querySelector(s);
  await entraAdm(w);await sleep(500);
  w.__dom.reconfigure({url:'http://192.168.0.9:8090/'});   // o mesmo que abrir pelo celular da rede
  w.localStorage.setItem('dm-avisos-aparelho','{"sistema":true,"tela":true}');
  Object.defineProperty(d,'hidden',{configurable:true,get:()=>true});d.dispatchEvent(new w.Event('visibilitychange'));
  const n0=w.__notifs.length,l0=w.__wl.length;w.__dt+=25000;
  await direto('demanda/criar',{titulo:'Aviso fora do PC',tipo:'mat',motivo:'Falta de material',prio:'norm',est:60,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
  await sleep(1500);
  ok(w.__notifs.length===n0,'fora do 127.0.0.1: nenhum aviso do Windows, mesmo com a escolha guardada');
  ok(w.__wl.length===l0,'fora do 127.0.0.1: não pede tela acesa');
  Object.defineProperty(d,'hidden',{configurable:true,get:()=>false});
  w.NestLocal.views.demandas.config('avisos');
  $('#dm-uchip').click;
  $('[data-act=mclose]')&&$('[data-act=mclose]').click();await sleep(100);
  $('#dm-uchip').click();await until(()=>$('#dm-mbox [data-act=prefs]'));$('#dm-mbox [data-act=prefs]').click();
  ok(await until(()=>$('#dm-pf-som')),'Meus avisos abre fora do PC');
  ok(!$('#dm-pf-sis')&&!$('#dm-pf-tela')&&/só no computador principal/.test($('#dm-mbox').textContent),'e explica que aviso do Windows e tela acesa são só do computador principal');
  ok(/HTTPS/.test($('#dm-mbox').textContent)&&/192\.168\.0\.9/.test($('#dm-mbox').textContent),'e mostra o endereço atual, sem HTML (origem escapada)');
  w.close();
}

(async()=>{
  const srv=await startServer();
  try{
    const ids=await semear();
    console.log('INFO dados semeados: '+JSON.stringify(ids));
    await xssEmTudo(ids);
    await linkEstranho(ids);
    await armazenamentoEstragado();
    await foraDoComputadorPrincipal();
    await offlineDoEscritorio();
  }finally{killTree(srv);
    try{fs.rmSync(base,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+base)}}
  console.log(process.exitCode?'houve falhas':'tudo certo');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());
