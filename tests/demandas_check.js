const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// Central de demandas contra o servidor REAL (servidor.py) com DEMANDAS_DATA temporário.
// rodar: NODE_PATH=<pasta com jsdom>/node_modules node tests/demandas_check.js   (PYTHON=... troca o interpretador)
// Fluxo: ADM cria setores e pessoa, cria demanda (título com <img onerror>), mapa (ordem, idle/hasLate/pick, filtro),
// pessoa entra com o código, aceita (botão do cartão não abre a gaveta), pausa, retoma, conclui; mudança feita por outro
// aparelho aparece sozinha (/api/rev); aparelho de operador sem Administrador e sem o painel de rede.
const REPO=path.resolve(__dirname,'..');
const data=fs.mkdtempSync(path.join(os.tmpdir(),'dem-check-'));
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0;
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
// papel: finge o /api/eu de um aparelho da rede (a trava do servidor tem teste próprio em tests/test_servidor.py)
async function boot(papel){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/',{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>papel&&u==='/api/eu'?Promise.resolve(new Response(JSON.stringify({papel}),{headers:{'Content-Type':'application/json'}}))
      :fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);   // jsdom não tem fetch: o do Node, com a origem do servidor
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
  }});
  const w=dom.window;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  return w;
}
// pedido direto ao servidor, como se fosse outro aparelho (o do próprio PC: Escritório)
const direto=(rest,body)=>fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
// Aparelho de operador (PIN dos operadores): só operador, sem Administrador e sem o painel de rede.
async function aparelhoOperador(){
  const w=await boot('operador'),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
  ok(await until(()=>!$('#dm-login').hidden&&$('#dm-login .dm-lgcard')),'aparelho de operador abre em "Quem é você?"');
  const semAdm=()=>!$('[data-act=lgk][data-v=adm]')&&!/Administrador/.test($('#dm-login').textContent);
  ok(semAdm(),'sem a opção Administrador'+(semAdm()?'':' (ainda aparece: '+$('#dm-login').textContent.slice(0,120)+')'));
  ok($('#cx-rede').hidden,'sem o botão ⚙ Rede');
  ok(await until(()=>$('[data-act=lgs][data-v=CNC]')),'a lista de setores chega na tela de entrada');
  $('[data-act=lgs][data-v=CNC]').click();await until(()=>$('.dm-lguser'));
  $$('.dm-lguser').find(b=>b.textContent.includes('Carlos')).click();
  const cod=$('#dm-lg-code');cod.value='1234';cod.dispatchEvent(new w.Event('input',{bubbles:true}));$('.dm-lgbtn').click();
  ok(await until(()=>$('#dm-login').hidden&&/Olá, Carlos/.test($('#dmboard').textContent)),'Carlos entra com o código dele');
  w.close();
}
(async()=>{
  const srv=await startServer();
  try{
    const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
    const until=async(f,ms=5000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
    const click=s=>{const el=typeof s==='string'?$(s):s;if(!el)throw new Error('não achei '+s);el.click();return el};
    const type=(s,v,ev='input')=>{const el=$(s);if(!el)throw new Error('não achei '+s);el.value=v;el.dispatchEvent(new w.Event(ev,{bubbles:true}))};
    const toast=()=>($('#dm-toast')||{}).textContent||'';
    const css=fs.readFileSync(path.join(REPO,'demandas/demandas.css'),'utf8');
    ok(!!w.NestLocal.views.demandas,'módulo registrou NestLocal.views.demandas');
    ok(!$('.nav')&&!!d.getElementById('dm-i-painel'),'página própria: sem menu de outro programa, ícones do módulo carregados');
    ok(await until(()=>!$('#cx-rede').hidden),'computador principal tem o botão ⚙ Rede');
    // regra de escopo do CSS: todo seletor sob #dmboard ou main[data-view="demandas"]
    const sels=css.replace(/\/\*[\s\S]*?\*\//g,'').replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g,'').replace(/@media[^{]+\{/g,'').match(/[^{}]+(?=\{)/g).flatMap(s=>s.split(',')).map(s=>s.trim()).filter(Boolean);
    const solto=sels.filter(s=>!/^(#dmboard|main\[data-view="demandas"\])/.test(s));
    ok(sels.length>100&&!solto.length,'CSS: '+sels.length+' seletores, todos com escopo '+solto.slice(0,5).join(' | '));
    ok(!/@keyframes (?!dm-)/.test(css),'keyframes com prefixo dm-');
    ok(await until(()=>!$('#dm-login').hidden&&$('#dm-login .dm-lgcard')),'abre em "Quem é você?"');
    ok(w.getComputedStyle($('#dmboard')).display==='flex','#dmboard aparece na tela Demandas');
    // ADM (computador principal: papel maquina); a opção só aparece depois que o /api/eu responde
    ok(await until(()=>$('[data-act=lgk][data-v=adm]')),'computador principal tem a opção Administrador');
    click('[data-act=lgk][data-v=adm]');click('.dm-lgbtn');
    ok(await until(()=>$('#dm-login').hidden&&$('.dm-tab[data-v=painel]')),'Administrador entra como Escritório '+toast());
    // setores
    const novoSetor=async(nome,sig)=>{click('[data-act=tab][data-v=admin]');await until(()=>$('[data-act=newsector]'));click('[data-act=newsector]');type('#dm-sf-name',nome);type('#dm-sf-id',sig);click('[data-act=sf-save]');return until(()=>!$('#dm-modal').classList.contains('dm-on')&&$$('.dm-scard').some(c=>c.textContent.includes(nome)))};
    ok(await novoSetor('Planejamento','PCP'),'cria setor PCP '+toast());
    ok(await novoSetor('Corte CNC','CNC'),'cria setor CNC '+toast());
    ok(await novoSetor('Almoxarifado','ALM'),'cria setor ALM (fica sem demanda) '+toast());
    // pessoa
    click('[data-act=newuser]');type('#dm-uf-name','Carlos');type('#dm-uf-sec','CNC','change');await sleep(50);type('#dm-uf-code','1234');click('[data-act=uf-save]');
    ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')&&/Carlos/.test(toast())),'cria pessoa Carlos (CNC) com código '+toast());
    // demanda com tentativa de XSS no título
    const XSS='<img src=x onerror="window.__xss=1"> Corte de chapas';
    click('.dm-hdnew');await until(()=>$('#dm-fm-title'));
    type('#dm-fm-title',XSS);type('#dm-fm-fromS','PCP','change');type('#dm-fm-toS','CNC','change');await sleep(50);
    click('[data-act=m-reason]');await sleep(30);click('[data-act=m-est][data-v="30"]');await sleep(30);click('[data-act=m-submit]');
    ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')),'demanda criada '+toast());
    click('[data-act=tab][data-v=sol]');
    ok(await until(()=>$$('.dm-card').some(c=>c.querySelector('.dm-nm').textContent===XSS)),'título aparece como texto');
    ok(!$('#dmboard img')&&w.__xss===undefined,'o <img onerror> não virou elemento nem rodou');
    // mapa de setores
    click('[data-act=tab][data-v=painel]');await until(()=>$$('.dm-tile').length===3);
    const ordem=()=>$$('.dm-tile').map(t=>t.dataset.v);
    ok(ordem()[0]==='CNC','"Mais críticos": CNC (com demanda) primeiro: '+ordem());
    click('[data-act=msort][data-v=az]');await sleep(50);
    ok(ordem().join()==='ALM,CNC,PCP','A–Z pelo nome: '+ordem());
    ok($('.dm-tile[data-v=ALM]').classList.contains('dm-idle')&&!$('.dm-tile[data-v=CNC]').classList.contains('dm-idle'),'setor sem demanda tem dm-idle');
    ok(!$('.dm-tile[data-v=CNC]').classList.contains('dm-hasLate'),'sem atraso: sem dm-hasLate');
    const realNow=w.Date.now.bind(w.Date);w.Date.now=()=>realNow()+2*3600000;   // 2 h depois: a demanda de 30 min passa do prazo
    click('[data-act=tab][data-v=sol]');click('[data-act=tab][data-v=painel]');
    // o número do KPI entra pela contagem animada (começa em 0): espera ela terminar
    ok(await until(()=>$('.dm-tile[data-v=CNC]').classList.contains('dm-hasLate')&&$('.dm-kpi[data-v=late] b').textContent==='1',3000),'prazo estourado: dm-hasLate e KPI Atrasadas');
    w.Date.now=realNow;
    click('.dm-tile[data-v=CNC]');
    ok($('.dm-tile[data-v=CNC]').classList.contains('dm-pick'),'clique no setor marca dm-pick');
    ok(await until(()=>$('#dm-fSec')&&$('#dm-fSec').value==='CNC'),'vai para Solicitações filtrado por CNC');
    ok($$('.dm-card').length>=1&&$$('.dm-card').every(c=>[...c.querySelectorAll('.dm-abbr')].some(a=>a.textContent==='CNC')),'só cartões do CNC');
    // pessoa entra com o código
    click('#dm-uchip');await until(()=>$('#dm-mbox [data-act=lgk]'));
    click('[data-act=lgk][data-v=op]');click('[data-act=lgs][data-v=CNC]');
    await until(()=>$('.dm-lguser'));click('.dm-lguser');
    type('#dm-lg-code','9999');click('#dm-lgform [type=submit]');
    ok(await until(()=>$('#dm-lg-fld.dm-err')),'código errado: mensagem do servidor no campo: '+(($('#dm-lg-fld .dm-em')||{}).textContent||''));
    type('#dm-lg-code','1234');click('#dm-lgform [type=submit]');
    ok(await until(()=>$('.dm-ophead')&&/Carlos/.test($('.dm-ophead h2').textContent)),'Carlos entra pelo código');
    click('[data-act=opf][data-v=pend]');await until(()=>$('.dm-ocard'));
    const oc=()=>$('.dm-ocard'),st=()=>oc()&&oc().dataset.st;
    click(oc().querySelector('[data-act=accept]'));
    await sleep(30);ok(!$('#dm-drawer').classList.contains('dm-on'),'botão do cartão não abre a gaveta');
    ok(await until(()=>st()==='prog'||st()==='late'),'aceitar: em andamento '+toast());
    click(oc().querySelector('h3'));
    ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')),'clique no cartão abre a gaveta');
    ok($('#dm-drawer h2').textContent===XSS,'gaveta mostra o título escapado');
    click('#dm-drawer [data-act=pause]');await until(()=>$('[data-act=m-pause-ok]'));click('[data-act=m-pause-ok]');
    ok(await until(()=>oc()&&oc().dataset.st==='pause'),'pausar '+toast());
    click('#dm-drawer [data-act=resume]');ok(await until(()=>oc()&&oc().dataset.st!=='pause'),'retomar');
    click('#dm-drawer [data-act=finish]');await until(()=>$('[data-act=m-finish-ok]'));click('[data-act=m-finish-ok]');
    ok(await until(()=>/concluída/i.test(toast())),'concluir '+toast());
    click('#dm-drawer [data-act=close]');click('[data-act=opf][data-v=done]');
    ok(await until(()=>oc()&&oc().dataset.st==='done'),'aparece em Concluídas');
    // outro aparelho cria uma demanda: a tela atualiza sozinha pelo /api/rev, sem recarregar
    await direto('demanda/criar',{titulo:'Pedido feito em outro aparelho',tipo:'mat',motivo:'Falta de material',prio:'high',est:60,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
    click('[data-act=opf][data-v=pend]');
    ok(await until(()=>$$('.dm-ocard h3').some(h=>h.textContent==='Pedido feito em outro aparelho'),8000),'mudança de outro aparelho aparece sozinha');
    w.close();
    await aparelhoOperador();
  }finally{killTree(srv);   // no Windows o servidor recém-morto ainda pode segurar arquivos: tenta de novo e não reprova por isso
    try{fs.rmSync(data,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+data)}}
  console.log(process.exitCode?'houve falhas':'tudo certo');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());   // janela jsdom aberta não pode prender o processo
