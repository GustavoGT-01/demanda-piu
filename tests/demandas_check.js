const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// Central de demandas contra o servidor REAL (servidor.py) com DEMANDAS_DATA temporário.
// rodar: NODE_PATH=<pasta com jsdom>/node_modules node tests/demandas_check.js   (PYTHON=... troca o interpretador)
// Fluxo: ADM cria setores e pessoa, cria demanda (título com <img onerror>), mapa (ordem, idle/hasLate/pick, filtro),
// pessoa entra com o código, aceita (botão do cartão não abre a gaveta), pausa, retoma, conclui; mudança feita por outro
// aparelho aparece sozinha (/api/rev); aparelho de operador sem Administrador e sem o painel de rede.
const REPO=path.resolve(__dirname,'..');
const base=fs.mkdtempSync(path.join(os.tmpdir(),'dem-check-')),data=path.join(base,'data');   // o backup vai para <base>/backup
fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,FORA=false,REVS=0;   // FORA: o fetch da página falha como se a central tivesse caído; REVS conta /api/rev
function startServer(){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor;s=servidor.Server(('127.0.0.1',0),servidor.Handler);print(s.server_address[1],flush=True);s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='';p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+)\s/.exec(out);if(m&&!PORT){PORT=+m[1];res(p)}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
// servidor SMTP falso (o mínimo do protocolo), numa porta livre: o "Enviar teste" da tela manda para ele
const smtpLinhas=[];
const smtp=require('net').createServer(s=>{let dados=false,buf='';s.write('220 falso\r\n');s.on('data',d=>{buf+=d.toString('utf8');let i;
  while((i=buf.indexOf('\r\n'))>=0){const l=buf.slice(0,i);buf=buf.slice(i+2);
    if(dados){if(l==='.'){dados=false;s.write('250 ok\r\n')}else smtpLinhas.push(l);continue}
    const c=l.slice(0,4).toUpperCase();
    if(c==='EHLO'||c==='HELO')s.write('250 falso\r\n');else if(['MAIL','RCPT','RSET','NOOP'].includes(c))s.write('250 OK\r\n');
    else if(c==='DATA'){dados=true;s.write('354 manda\r\n')}else if(c==='QUIT')s.end('221 tchau\r\n');else s.write('502 x\r\n')}})});
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(!c)process.exitCode=1};
// papel: finge o /api/eu de um aparelho da rede (a trava do servidor tem teste próprio em tests/test_servidor.py)
async function boot(papel,hash=''){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/'+hash,{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>(u==='/api/rev'&&REVS++,0)||FORA&&String(u).startsWith('/api/')?Promise.reject(new TypeError('Failed to fetch')):papel&&u==='/api/eu'?Promise.resolve(new Response(JSON.stringify({papel}),{headers:{'Content-Type':'application/json'}}))
      :fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);   // jsdom não tem fetch: o do Node, com a origem do servidor
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
    // som e vibração falsos (contam o que tocou); __dt adianta o relógio da página
    w.__sons=[];w.__vib=[];w.__ctxs=[];w.__dt=0;const dn=w.Date.now;w.Date.now=()=>dn.call(w.Date)+w.__dt;
    w.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={};w.__ctxs.push(this)}resume(){this.state='running'}
      createOscillator(){const o={type:'',frequency:{},connect(){},start(){},stop(){}};w.__sons.push(o);return o}
      createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
    // aviso do sistema e tela acesa falsos: __perm é a resposta do navegador ao pedido de permissão
    w.__notifs=[];w.__pedidos=0;w.__perm='granted';w.__wl=[];
    w.Notification=class{constructor(t,o){this.title=t;this.body=o&&o.body;this.tag=o&&o.tag;this.fechada=false;w.__notifs.push(this)}close(){this.fechada=true}
      static get permission(){return w.__atual}static requestPermission(){w.__pedidos++;w.__atual=w.__perm;return Promise.resolve(w.__perm)}};
    w.__atual='default';
    Object.defineProperty(w.navigator,'wakeLock',{configurable:true,value:{request:async()=>{const l={soltou:false,ls:[],addEventListener(e,f){l.ls.push(f)},release:async()=>{l.soltou=true;l.ls.forEach(f=>f())}};w.__wl.push(l);return l}}});
    Object.defineProperty(w.navigator,'vibrate',{configurable:true,value:p=>{w.__vib.push(p);return true}});
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
  ok($('#cx-cfg').hidden,'sem o botão ⚙ Configurações');
  ok(!w.__ctxs.length,'(conferência: nenhum som preparado antes de tocar na tela)');
  d.dispatchEvent(new w.Event('pointerdown'));
  ok(w.__ctxs.length===1&&w.__ctxs[0].state==='running','o primeiro toque na tela libera o som');
  w.NestLocal.views.demandas.config('backup');await sleep(300);
  ok(!$('.dm-cfg'),'nem pela função: o diálogo não abre fora do computador principal');
  ok(await until(()=>$('[data-act=lgs][data-v=CNC]')),'a lista de setores chega na tela de entrada');
  $('[data-act=lgs][data-v=CNC]').click();await until(()=>$('.dm-lguser'));
  $$('.dm-lguser').find(b=>b.textContent.includes('Carlos')).click();
  const cod=$('#dm-lg-code');cod.value='1234';cod.dispatchEvent(new w.Event('input',{bubbles:true}));$('.dm-lgbtn').click();
  ok(await until(()=>$('#dm-login').hidden&&/Olá, Carlos/.test($('#dmboard').textContent)),'Carlos entra com o código dele');
  const pub=await fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/vista',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.text());
  ok(/corte@empresa/.test(pub),'(conferência: o ADM pelo próprio PC recebe os e-mails)');
  ok(!/@empresa\.com/.test(d.documentElement.innerHTML),'aparelho de operador: nenhum e-mail na tela');
  // aparelho com armazenamento bloqueado: o formulário funciona, só não guarda rascunho
  const erros=[];w.addEventListener('error',e=>erros.push(e.message));
  Object.defineProperty(w,'localStorage',{configurable:true,get(){throw new Error('armazenamento bloqueado')}});
  $('.dm-hdnew').click();await until(()=>$('#dm-fm-title'));
  const tt=$('#dm-fm-title');tt.value='Sem armazenamento';tt.dispatchEvent(new w.Event('input',{bubbles:true}));
  $('[data-act=mclose]').click();await sleep(30);$('.dm-hdnew').click();
  ok(await until(()=>$('#dm-fm-title')&&$('#dm-fm-title').value===''&&!$('#dm-fm-rasc'))&&!erros.length,'localStorage que lança erro não quebra o formulário '+erros.join(' | '));
  $('[data-act=mclose]').click();
  w.close();
}
// Camada 1 dos avisos (Carlos, CNC, com a tela aberta): som, vibração, título da aba e a gaveta do sino.
async function avisosDaTela(w,until,click){
  const d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const badge=()=>$('#dm-badge').hidden?0:+$('#dm-badge').textContent;
  const idDe=async t=>{const j=await direto('vista',{});return(j.demandas||(j.v||{}).demandas||[]).find(x=>x.titulo===t)};
  const pede=(titulo,prio='high')=>direto('demanda/criar',{titulo,tipo:'mat',motivo:'Falta de material',prio,est:60,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
  ok(await until(()=>w.__sons.length===2&&w.__vib.length===1),'aviso novo toca (2 notas) e vibra: '+w.__sons.length+' / '+JSON.stringify(w.__vib));
  ok(JSON.stringify(w.__vib[0])==='[200,100,200]','vibração normal [200,100,200]');
  ok(w.__sons.map(o=>o.frequency.value).join()==='880,660','som padrão: o bipe duplo curto');
  ok(badge()>0&&d.title==='('+badge()+') Central de demandas','título da aba com o número de não lidos: '+d.title);
  const P=(await idDe('Pedido feito em outro aparelho')).id,b0=badge();
  await direto('demanda/comentar',{id:P,texto:'Tem pressa'});
  ok(await until(()=>badge()===b0+1)&&w.__sons.length===2&&w.__vib.length===1,'segundo aviso da mesma demanda em 10 min: só o contador sobe');
  await pede('Urgente de outro aparelho','urg');
  ok(await until(()=>w.__vib.length===2)&&JSON.stringify(w.__vib[1])==='[200,100,200,100,200]','urgente vibra mais forte: '+JSON.stringify(w.__vib[1]));
  ok(w.__sons.length===2,'mas não toca de novo antes de 20 s: '+w.__sons.length);
  const U=(await idDe('Urgente de outro aparelho')).id;
  w.__dt=25000;w.localStorage.setItem('dm-avisos-aparelho',JSON.stringify({som:'desligado',vibrar:false}));
  let b1=badge();await pede('Terceiro pedido');
  ok(await until(()=>badge()===b1+1)&&w.__sons.length===2&&w.__vib.length===2,'aparelho com som e vibração desligados fica quieto');
  w.localStorage.setItem('dm-avisos-aparelho',JSON.stringify({som:'sino'}));
  b1=badge();await pede('Quarto pedido');
  ok(await until(()=>w.__sons.length===5)&&w.__vib.length===3,'passados 20 s, toca de novo: '+w.__sons.length);
  ok(w.__sons.slice(2).map(o=>o.frequency.value).join()==='1318,1046,784','o aparelho escolheu o sino: três notas descendo');
  w.localStorage.removeItem('dm-avisos-aparelho');
  const Q=(await idDe('Quarto pedido')).id;await direto('demanda/prioridade',{id:Q,prio:'urg'});
  ok(await until(()=>w.__vib.length===4)&&JSON.stringify(w.__vib[3])==='[200,100,200,100,200]','urgente fura o agrupamento da mesma demanda: '+JSON.stringify(w.__vib[3]));
  // aba escondida: o título pisca com o aviso e para quando a pessoa volta
  Object.defineProperty(d,'hidden',{configurable:true,get:()=>true});
  await pede('Quinto pedido');
  ok(await until(()=>/^\(\d+\) 📥 Nova solicitação · SOL-\d+$/.test(d.title),10000),'aba escondida: o título mostra o aviso: '+d.title);
  ok(await until(()=>/^\(\d+\) Central de demandas$/.test(d.title),3000),'e alterna com o normal (pisca)');
  Object.defineProperty(d,'hidden',{configurable:true,get:()=>false});d.dispatchEvent(new w.Event('visibilitychange'));
  await sleep(1300);
  ok(d.title==='('+badge()+') Central de demandas','voltou para a aba: para de piscar: '+d.title);
  // a gaveta do sino
  click('#dm-bell');
  ok(await until(()=>$('#dm-notif').classList.contains('dm-on')&&$('#dm-notif h2').textContent==='Avisos'),'o sino abre "Avisos"');
  ok(new RegExp('^'+badge()+' não lidos · só os seus e os da fila do ').test($('#dm-nf-sub').textContent),'subtítulo com o número e de quem são: '+$('#dm-nf-sub').textContent);
  const al=$$('.dm-alert').find(a=>/Quinto pedido/.test(a.textContent)),u0=badge();
  ok(al,'(conferência: o alerta do quinto pedido está na tela)');click(al.querySelector('[data-act=ax]'));
  ok(await until(()=>badge()===u0-1&&$('#dm-nf-sub').textContent.startsWith((u0-1)+' ')),'dispensar um alerta com a gaveta aberta atualiza a gaveta: '+$('#dm-nf-sub').textContent);
  ok($$('#dm-notif .dm-secx').map(e=>e.textContent).join()==='Agora','agrupado por período: '+$$('#dm-notif .dm-secx').map(e=>e.textContent).join());
  const gP=()=>$('#dm-notif [data-grupo="'+P+'"]');
  ok(gP()&&gP().querySelector('.dm-nfcnt').textContent==='2'&&/Mais 1 aviso desta demanda/.test(gP().textContent)&&/“Tem pressa”/.test(gP().textContent),'dois avisos da mesma demanda num cartão só, o comentário entre aspas');
  ok($$('#dm-notif [data-grupo]').length===6,'um cartão por demanda: '+$$('#dm-notif [data-grupo]').length);
  click('[data-act=nf][data-v=urg]');
  ok($$('#dm-notif [data-grupo]').map(g=>g.dataset.grupo).sort().join()===[U,Q].sort().join(),'filtro Urgentes: só as urgentes');
  ok($('[data-act=nf][data-v=urg]').getAttribute('aria-pressed')==='true','o filtro escolhido fica marcado');
  click('#dm-notif [data-grupo="'+U+'"] [data-act=accept]');
  ok(await until(()=>!$('#dm-notif [data-grupo="'+U+'"] [data-act=accept]')),'"Aceitar e iniciar" direto da gaveta');
  ok((await idDe('Urgente de outro aparelho')).status==='prog','a urgente ficou em andamento');
  ok(!$('#dm-drawer').classList.contains('dm-on'),'aceitar pela gaveta não abre a demanda');
  click('[data-act=nf][data-v=nao]');
  ok($$('#dm-notif [data-grupo]').length&&$$('#dm-notif [data-grupo]').every(g=>g.classList.contains('dm-new')),'filtro Não lidos: só os novos');
  click('[data-act=nf][data-v=todos]');
  const b2=badge();click(gP().querySelector('[data-act=noteopen]'));
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&badge()===b2-2),'"Ver solicitação" abre e marca os 2 avisos da demanda como lidos: '+b2+' → '+badge());
  click('#dm-drawer [data-act=close]');click('#dm-bell');
  ok(await until(()=>gP()&&!gP().classList.contains('dm-new')),'o cartão dela deixa de ser novo');
  ok($('[data-act=nfantigos]'),'mostra os últimos 7 dias, com "ver mais antigos"');
  w.__dt=8*86400000;click('[data-act=nf][data-v=todos]');   // 8 dias depois: tudo ficou antigo
  ok(!$$('#dm-notif [data-grupo]').length&&/Nenhum aviso\./.test($('#dm-notif').textContent),'aviso com mais de 7 dias sai da lista');
  click('[data-act=nfantigos]');
  ok(!$('[data-act=nfantigos]')&&$$('#dm-notif [data-grupo]').length===6,'"ver mais antigos" mostra tudo');
  w.__dt=25000;
  click('#dm-notif [data-act=noteall]');
  ok(await until(()=>badge()===0&&!$('#dm-notif .dm-new')&&d.title==='Central de demandas'),'"Marcar todos como lidos": sino e título zeram: '+d.title);
  click('[data-act=nf][data-v=nao]');
  ok(/Nada novo/.test($('#dm-notif').textContent),'Não lidos vazio: "Nada novo."');
  click('[data-act=nf][data-v=todos]');click('#dm-notif [data-act=close]');
}
// "Meus avisos" (Carlos): evento desligado fica só no sino, silêncio com os limites exatos (relógio da página posto em
// horários escolhidos), urgente fura o silêncio, som e vibração do aparelho, voltar ao padrão.
async function prefsDaTela(w,until,click){
  const d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const badge=()=>$('#dm-badge').hidden?0:+$('#dm-badge').textContent,toast=()=>($('#dm-toast')||{}).textContent||'';
  const av=()=>{try{return JSON.parse(fs.readFileSync(path.join(data,'avisos.json'),'utf8'))}catch(e){return{}}};
  const ap=()=>w.localStorage.getItem('dm-avisos-aparelho');
  const carlos=JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8')).pessoas.find(p=>p.nome==='Carlos').id;
  const set=(id,v)=>{const el=$('#dm-pf-'+id);if(typeof v==='boolean')el.checked=v;else el.value=v};
  const abre=async()=>{click('#dm-bell');await until(()=>$('#dm-notif [data-act=prefs]'));click('#dm-notif [data-act=prefs]');
    return until(()=>$('#dm-mbox h2')&&$('#dm-mbox h2').textContent==='Meus avisos')};
  const salva=async()=>{click('[data-act=pf-salvar]');return until(()=>/Avisos salvos/.test(toast())&&!$('#dm-modal').classList.contains('dm-on'))};
  // o relógio da página (só ele) num horário do dia escolhido, sempre para a frente
  const dia0=new Date();dia0.setHours(0,0,0,0);
  const hora=(dia,hh,mm,ss)=>{const real=w.Date.now()-w.__dt;w.__dt=dia0.getTime()+(dia+2)*86400000+((hh*60+mm)*60+ss)*1000-real};
  const ouve=async(titulo,prio='high',pessoa=null)=>{const b=badge(),s0=w.__sons.length,v0=w.__vib.length;
    await direto('demanda/criar',{titulo,tipo:'mat',motivo:'Falta de material',prio,est:60,para:{s:'CNC',p:pessoa},desc:'',de_s:'PCP'});
    const chegou=await until(()=>badge()===b+1);await sleep(100);return{chegou,sons:w.__sons.length-s0,vib:w.__vib.slice(v0)}};
  ok(await abre()&&!$('#dm-notif').classList.contains('dm-on'),'"⚙ Meus avisos" na gaveta abre a tela (e fecha a gaveta)');
  ok($$('[id^=dm-pf-ev-]').length===9&&$$('[id^=dm-pf-ev-]').every(c=>c.checked),'nove eventos, todos ligados no padrão');
  ok(/fila do Corte CNC/.test($('#dm-pf-ev-fila').closest('label').textContent),'"Demanda nova na fila do Corte CNC"');
  ok(!$('#dm-pf-sil').checked&&$('#dm-pf-ini').value==='22:00'&&$('#dm-pf-fim').value==='06:00'&&$('#dm-pf-urg').checked,'silêncio desligado no padrão; urgente fura ligado');
  click('[data-act=pf-turno][data-v=C]');
  ok($('#dm-pf-ini').value==='06:00'&&$('#dm-pf-fim').value==='22:00'&&$('#dm-pf-sil').checked&&$('[data-act=pf-turno][data-v=C]').getAttribute('aria-pressed')==='true'&&$('[data-act=pf-turno][data-v=A]').getAttribute('aria-pressed')==='false',
    'Turno C (22–06): silêncio das 06:00 às 22:00, ligado');
  let s0=w.__sons.length;set('som','sino');click('[data-act=pf-teste]');
  ok(w.__sons.slice(s0).map(o=>o.frequency.value).join()==='1318,1046,784','"▶ Testar" toca o som escolhido');
  s0=w.__sons.length;set('som','desligado');click('[data-act=pf-teste]');
  ok(w.__sons.length===s0&&/som está desligado/.test(toast()),'"▶ Testar" com o som desligado avisa');
  set('ev-fila',false);set('ini','22:00');set('fim','06:00');set('som','sino');set('vib',false);
  ok(await salva(),'Salvar fecha e avisa');
  ok(JSON.stringify(av().pessoas[carlos])==='{"eventos":{"fila":false},"silencio":{"ligado":true}}','no servidor só as diferenças: '+JSON.stringify(av().pessoas));
  ok(ap()==='{"som":"sino","vibrar":false}','som e vibração ficam no aparelho: '+ap());
  hora(0,12,0,0);
  let r=await ouve('Fila desligada');
  ok(r.chegou&&!r.sons&&!r.vib.length&&!$$('.dm-alert').some(a=>/Fila desligada/.test(a.textContent)),'evento desligado: fica só no sino, sem banner e sem som');
  hora(0,12,1,0);r=await ouve('Escolheram o Carlos','high',carlos);
  ok(r.chegou&&r.sons===3&&$$('.dm-alert').some(a=>/Escolheram o Carlos/.test(a.textContent)),'fila desligada não cala a demanda escolhida para ele '+JSON.stringify(r));
  click('#dm-uchip');await until(()=>$('#dm-mbox [data-act=prefs]'));click('#dm-mbox [data-act=prefs]');
  ok(await until(()=>$('#dm-pf-ev-fila')&&!$('#dm-pf-ev-fila').checked&&$('#dm-pf-sil').checked),'pelo "quem é você" também abre, com o que foi salvo');
  set('ev-fila',true);set('vib',true);
  ok(await salva()&&ap()==='{"som":"sino"}','vibração igual ao padrão sai do aparelho: '+ap());
  hora(0,21,59,30);r=await ouve('Antes do silêncio');
  ok(r.chegou&&r.sons===3&&r.vib.length===1,'21:59: toca e vibra '+JSON.stringify(r));
  hora(0,22,0,10);r=await ouve('Começo do silêncio');
  ok(r.chegou&&!r.sons&&!r.vib.length,'22:00 em ponto: silêncio '+JSON.stringify(r));
  ok($$('.dm-alert').some(a=>/Começo do silêncio/.test(a.textContent)),'no silêncio a tela aberta ainda mostra o banner');
  hora(1,5,59,30);r=await ouve('Fim do silêncio');
  ok(r.chegou&&!r.sons&&!r.vib.length,'05:59 do dia seguinte: ainda silêncio (atravessa a meia-noite) '+JSON.stringify(r));
  hora(1,6,0,10);r=await ouve('Depois do silêncio');
  ok(r.chegou&&r.sons===3&&r.vib.length===1,'06:00: acabou o silêncio '+JSON.stringify(r));
  hora(1,23,0,0);r=await ouve('Urgente no silêncio','urg');
  ok(r.chegou&&r.sons===3&&JSON.stringify(r.vib)==='[[200,100,200,100,200]]','urgente toca mesmo no silêncio '+JSON.stringify(r));
  ok(await abre(),'abre de novo');set('urg',false);ok(await salva(),'salva sem o urgente furar');
  hora(1,23,30,0);r=await ouve('Urgente calado','urg');
  ok(r.chegou&&!r.sons&&!r.vib.length,'"Urgente toca mesmo no silêncio" desligado: o urgente também fica quieto '+JSON.stringify(r));
  ok(await abre(),'abre de novo');click('[data-act=pf-turno][data-v=C]');set('urg',true);ok(await salva(),'salva o Turno C (silêncio das 06 às 22)');
  hora(2,6,0,0);r=await ouve('Começo do dia calado');
  ok(r.chegou&&!r.sons,'silêncio de dia (sem atravessar a meia-noite): 06:00 em ponto já é silêncio '+JSON.stringify(r));
  hora(2,21,59,0);r=await ouve('Fim do dia calado');
  ok(r.chegou&&!r.sons,'21:59: ainda silêncio '+JSON.stringify(r));
  hora(2,22,0,0);r=await ouve('Fim do turno');
  ok(r.chegou&&r.sons===3,'22:00 em ponto: toca '+JSON.stringify(r));
  ok(await abre(),'abre de novo');set('ini','12:30');set('fim','12:45');ok(await salva(),'salva o silêncio das 12:30 às 12:45');
  hora(3,12,35,0);r=await ouve('Meio do almoço');
  ok(r.chegou&&!r.sons,'12:35: silêncio (os minutos contam) '+JSON.stringify(r));
  ok(await abre(),'abre de novo');set('ini','13:10');set('fim','13:10');ok(await salva(),'salva início igual ao fim');
  hora(3,13,10,0);r=await ouve('Início igual ao fim');
  ok(r.chegou&&r.sons===3,'início igual ao fim: não há silêncio '+JSON.stringify(r));
  ok(await abre(),'abre para voltar ao padrão');set('sil',false);set('jun',false);ok(await salva(),'salva sem silêncio e sem juntar');
  ok(ap()==='{"som":"sino","juntar":false}','não juntar fica no aparelho: '+ap());
  hora(4,10,0,0);r=await ouve('Sem juntar');
  const J=(await direto('vista',{})).demandas.find(x=>x.titulo==='Sem juntar').id;
  hora(4,10,0,30);const b=badge(),s1=w.__sons.length;await direto('demanda/comentar',{id:J,texto:'Mais um'});
  ok(r.sons===3&&await until(()=>badge()===b+1)&&await until(()=>w.__sons.length===s1+3),'sem juntar: o segundo aviso da mesma demanda toca de novo');
  ok(await abre(),'abre mais uma vez');click('[data-act=pf-padrao]');
  ok(await until(()=>/de volta ao padrão/.test(toast())),'"Voltar ao padrão" avisa');
  ok(!(carlos in (av().pessoas||{}))&&ap()===null,'e apaga as diferenças no servidor e no aparelho');
  w.__dt=25000;
}
// Só no PC principal (127.0.0.1): aviso do Windows com o título da demanda (aba escondida) e tela acesa.
async function sistemaDaTela(w,until,click){
  const d=w.document,$=s=>d.querySelector(s),toast=()=>($('#dm-toast')||{}).textContent||'';
  const ap=()=>w.localStorage.getItem('dm-avisos-aparelho');
  const abre=async()=>{click('#dm-bell');await until(()=>$('#dm-notif [data-act=prefs]'));click('#dm-notif [data-act=prefs]');return until(()=>$('#dm-pf-sis'))};
  const salva=()=>{click('[data-act=pf-salvar]');return until(()=>/Avisos salvos|não permitiu/.test(toast())&&!$('#dm-modal').classList.contains('dm-on'))};
  const escondida=v=>{Object.defineProperty(d,'hidden',{configurable:true,get:()=>v});d.dispatchEvent(new w.Event('visibilitychange'))};
  const ouve=async t=>{const n0=w.__notifs.length;await direto('demanda/criar',{titulo:t,tipo:'mat',motivo:'Falta de material',prio:'norm',est:60,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
    await until(()=>[...d.querySelectorAll('.dm-alert')].some(a=>a.textContent.includes(t))||w.__notifs.length>n0,10000);await sleep(150);return w.__notifs.length-n0};
  w.__dt=25000;
  ok(await abre()&&!$('#dm-pf-sis').checked&&!$('#dm-pf-tela').checked&&/O navegador pergunta ao salvar/.test($('#dm-pf-sis').closest('label').textContent),'no PC principal: aviso do Windows e tela acesa, desligados, antes de pedir a permissão');
  ok(w.__pedidos===0,'abrir a tela não pede permissão');
  $('#dm-pf-sis').checked=true;ok(await salva(),'salva ligando o aviso do Windows');
  ok(w.__pedidos===1&&ap()==='{"sistema":true}','a permissão é pedida no Salvar e a escolha fica no aparelho: '+w.__pedidos+' '+ap());
  escondida(false);ok(await ouve('Com a aba à vista')===0,'aba à vista: sem aviso do Windows (já há banner)');
  escondida(true);
  ok(await ouve('Com a aba atrás')===1,'aba escondida: um aviso do Windows');
  const n=w.__notifs[w.__notifs.length-1];
  ok(/^Nova solicitação · SOL-\d+$/.test(n.title)&&n.body==='Com a aba atrás'&&n.tag===n.title.split(' · ')[1],'mostra o título da demanda: '+n.title+' / '+n.body+' / '+n.tag);
  escondida(false);n.onclick();
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&$('#dm-drawer h2').textContent==='Com a aba atrás')&&n.fechada,'clicar no aviso abre a demanda e fecha o aviso');
  click('#dm-drawer [data-act=close]');
  w.__atual='denied';escondida(true);
  ok(await ouve('Permissão negada')===0,'permissão retirada no navegador: nada aparece');
  escondida(false);
  ok(await abre()&&/bloqueou/.test($('#dm-pf-sis').closest('label').textContent),'a tela explica o bloqueio');
  $('#dm-pf-sis').checked=false;ok(await salva()&&ap()===null,'desligar tira do aparelho: '+ap());
  w.__atual='granted';escondida(true);
  ok(await ouve('Permitido mas desligado')===0,'permissão do navegador sem a escolha do aparelho: nada aparece');
  escondida(false);w.__atual='denied';
  ok(await abre(),'abre');$('#dm-pf-sis').checked=true;ok(await salva()&&/não permitiu/.test(toast())||ap()===null,'ligar com o navegador bloqueando: avisa e não guarda '+ap());
  ok(ap()===null,'e não guarda a escolha');
  w.__atual='default';w.__perm='denied';
  ok(await abre(),'abre');$('#dm-pf-sis').checked=true;await salva();
  ok(w.__pedidos===2&&ap()===null&&w.__atual==='denied','o pedido negado pelo usuário também não guarda: pedidos='+w.__pedidos);
  // tela acesa
  ok(await abre(),'abre');$('#dm-pf-tela').checked=true;ok(await salva(),'liga a tela acesa');
  ok(await until(()=>w.__wl.length===1&&!w.__wl[0].soltou)&&ap()==='{"tela":true}','pede a tela acesa e guarda a escolha: '+w.__wl.length);
  escondida(true);ok(await until(()=>w.__wl.length===1),'(conferência) escondida não pede de novo');
  escondida(false);ok(await until(()=>w.__wl.length===2&&!w.__wl[1].soltou),'ao voltar para a aba, pede de novo (o navegador solta ao esconder)');
  await sleep(50);w.__wl[1].release();await sleep(50);escondida(false);ok(await until(()=>w.__wl.length===3),'se o navegador soltar, a próxima volta pede de novo '+w.__wl.map(l=>l.soltou).join());
  ok(await abre(),'abre');$('#dm-pf-tela').checked=false;await salva();
  ok(await until(()=>w.__wl[2].soltou)&&ap()===null,'desligar solta a tela acesa');
  ok(await abre(),'abre');$('#dm-pf-tela').checked=true;await salva();ok(await until(()=>w.__wl.length===4&&!w.__wl[3].soltou),'liga de novo');
  ok(await abre(),'abre');click('[data-act=pf-padrao]');
  ok(await until(()=>w.__wl[3].soltou)&&ap()===null,'"Voltar ao padrão" também solta a tela acesa');
  Object.defineProperty(w.navigator,'wakeLock',{configurable:true,value:{request:async()=>{throw new Error('bateria fraca')}}});
  w.localStorage.setItem('dm-avisos-aparelho','{"tela":true}');const e0=[];w.addEventListener('error',e=>e0.push(e));escondida(true);escondida(false);await sleep(100);
  ok(!e0.length,'o navegador recusando a tela acesa não quebra nada');
  w.localStorage.removeItem('dm-avisos-aparelho');
}
// ⚙ Configurações · Avisos (PC principal) e o "Meus avisos" do Escritório, separado dos padrões.
// Cronoanálise: a janela de 13 h continua como era, e os modos novos (Dia, Semana, Mês) pedem a rota
// cronograma. É aqui que a fronteira de dia, semana e mês é conferida, porque ela é calculada no
// navegador, com o fuso do aparelho.
async function cronogramaDaTela(){
  const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
  const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();
  await until(()=>$('.dm-tab[data-v=painel]'));
  $('.dm-tab[data-v=crono]').click();
  ok(await until(()=>$('.dm-gtrack')||$('.dm-empty')),'Cronoanálise abre');
  // 13 h: sem --dm-gcols no estilo, então o fundo cai no 13 do fallback do CSS — o desenho de sempre
  ok($$('[data-act=crwin]').length===4&&$('[data-act=crwin][data-v="13h"]').getAttribute('aria-pressed')==='true','abre em 13 h, com quatro janelas');
  ok(!$('[data-act=crby]')&&!$('.cr-scroll'),'em 13 h não há agrupamento nem rolagem horizontal');
  const t13=$('.dm-gtrack');
  ok(t13&&!t13.getAttribute('style'),'13 h não emite --dm-gcols: o fundo usa o 13 do fallback');
  // o título do painel do cronograma, não o do primeiro painel da tela
  const ph=()=>{const p=$$('.dm-panel').find(x=>x.querySelector('.cr-tools'));return p?p.querySelector('.dm-ph h3').textContent:''};
  ok(/últimas 10h \+ próximas 3h/.test(ph()),'título da janela de hoje: '+ph());
  // Semana: 7 colunas, eixo com os sete dias e um "hoje", faixa de fim de semana e o plano
  $('[data-act=crwin][data-v=semana]').click();
  ok(await until(()=>$('.cr-scroll')&&$('.cr-axis')),'Semana monta o cronograma multidia');
  ok($$('.cr-axis .cr-d').length===7,'eixo da semana tem sete dias, tem '+$$('.cr-axis .cr-d').length);
  ok($$('.cr-axis .cr-today').length===1,'exatamente um dia marcado como hoje');
  ok($$('.cr-ticks span').length>0,'faixa de horas 06/12/18 presente');
  const tS=$('.dm-gtrack');
  ok(tS&&tS.style.getPropertyValue('--dm-gcols')==='7','na semana a trilha emite --dm-gcols:7, veio "'+(tS&&tS.style.getPropertyValue('--dm-gcols'))+'"');
  ok($$('.cr-we').length>0,'fim de semana hachurado');
  ok($$('.cr-plan').length>0,'barra do plano (criado → prazo) aparece');
  const plano=$('.cr-plan'),espera=$('.dm-gs.dm-wait');
  ok(plano&&espera&&plano.style.left===espera.style.left,'o plano começa no mesmo ponto da espera ('+(plano&&plano.style.left)+' vs '+(espera&&espera.style.left)+')');
  ok($$('.cr-grp').length>0,'linhas agrupadas por setor');
  ok($('[data-act=crby][data-v=setor]').getAttribute('aria-pressed')==='true','agrupamento começa por setor');
  // Mês: tantas colunas quantos dias tem o mês corrente
  $('[data-act=crwin][data-v=mes]').click();
  const dias=new Date(new Date().getFullYear(),new Date().getMonth()+1,0).getDate();
  ok(await until(()=>$('.dm-gtrack')&&$('.dm-gtrack').style.getPropertyValue('--dm-gcols')===String(dias)),'no mês a trilha emite --dm-gcols:'+dias);
  ok($$('.cr-axis .cr-d').length===dias,'eixo do mês tem '+dias+' dias, tem '+$$('.cr-axis .cr-d').length);
  // Dia: 24 colunas
  $('[data-act=crwin][data-v=dia]').click();
  ok(await until(()=>$('.dm-gtrack')&&$('.dm-gtrack').style.getPropertyValue('--dm-gcols')==='24'),'no dia a trilha emite --dm-gcols:24');
  // Por pessoa: muda os grupos
  const porSetor=$$('.cr-grp').length;
  $('[data-act=crby][data-v=pessoa]').click();
  ok(await until(()=>$('[data-act=crby][data-v=pessoa]').getAttribute('aria-pressed')==='true'&&$$('.cr-grp').length>0),'Por pessoa reagrupa ('+porSetor+' grupos por setor)');
  // ‹ e › deslocam a janela, e o botão do meio volta para hoje
  $('[data-act=crwin][data-v=semana]').click();
  ok(await until(()=>$('.cr-axis')),'volta para Semana');
  const t0=ph();
  ok(/^Cronograma · /.test(t0),'título do cronograma diz a janela: '+t0);
  $('[data-act=crnav][data-v="-1"]').click();
  ok(await until(()=>ph()!==t0&&/^Cronograma · /.test(ph())),'‹ muda a janela: '+ph());
  ok($$('.cr-axis .cr-today').length===0,'na semana passada nenhum dia é hoje');
  $('[data-act=crnav][data-v="0"]').click();
  ok(await until(()=>ph()===t0),'o botão do meio volta para esta semana');
  // voltar para 13 h restaura o painel antigo
  $('[data-act=crwin][data-v="13h"]').click();
  ok(await until(()=>!$('.cr-scroll')&&$('.dm-gtrack')&&!$('.dm-gtrack').getAttribute('style')),'voltar para 13 h restaura o painel de sempre');
  ok(/últimas 10h \+ próximas 3h/.test(ph()),'e o título volta a ser o de hoje');
  w.close();
}

async function avisosDaCentral(){
  const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
  const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const toast=()=>($('#dm-toast')||{}).textContent||'',av=()=>JSON.parse(fs.readFileSync(path.join(data,'avisos.json'),'utf8'));
  await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();
  await until(()=>$('.dm-tab[data-v=painel]'));
  w.NestLocal.views.demandas.config('avisos');
  ok(await until(()=>$('#dm-av-som')&&$('.dm-cfgnav [aria-current=page]').textContent==='🔔 Avisos'),'seção 🔔 Avisos nas Configurações');
  ok($$('.dm-avq:not(.dm-cfgth)').length===9&&$$('[id^=dm-av-ev-]').every(c=>c.checked),'"Quem recebe o quê": nove eventos, ligados');
  ok($('#dm-av-som').value==='curto'&&$('#dm-av-jun').value==='10'&&$('#dm-av-vib').value==='1'&&$('#dm-av-urg').value==='1'&&!$('#dm-av-sil').checked,'padrões: curto, 10 min, vibração, urgente fura, sem silêncio');
  $('#dm-av-som').value='sino';$('#dm-av-jun').value='0';$('#dm-av-vib').value='0';$('#dm-av-urg').value='0';$('#dm-av-ev-late').checked=false;
  $('#dm-av-sil').checked=true;$('#dm-av-ini').value='23:00';$('#dm-av-fim').value='05:00';
  $('[data-act=av-salvar]').click();
  ok(await until(()=>/Padrões dos avisos salvos/.test(toast())),'Salvar padrões '+toast());
  const p=av().padrao;
  ok(p.som==='sino'&&p.agrupar_min===0&&p.vibrar===false&&p.urgente_fura===false&&p.eventos.late===false&&p.eventos.new===true&&JSON.stringify(p.silencio)==='{"ligado":true,"ini":"23:00","fim":"05:00"}','gravado em data/avisos.json: '+JSON.stringify(p));
  ok($('#dm-av-som').value==='sino'&&$('#dm-av-jun').value==='0'&&!$('#dm-av-ev-late').checked,'a seção mostra o que foi salvo');
  // o Escritório não mexeu nos seus: o silêncio novo (23–05, urgente respeita) já vale nesta tela
  const tk=(await direto('entrar',{pessoa:JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8')).pessoas.find(p=>p.nome==='Carlos').id,codigo:'1234'})).tk;
  const urgente=async(win,titulo)=>{const s0=win.__sons.length;   // o sino do Escritório já passa de 99: espera o banner
    await direto('demanda/criar',{tk,titulo,tipo:'mat',motivo:'Falta de material',prio:'urg',est:60,para:{s:'PCP',p:null},desc:''});
    const chegou=await until(()=>[...win.document.querySelectorAll('.dm-alert')].some(a=>a.textContent.includes(titulo)),10000);
    await sleep(100);return chegou?win.__sons.length-s0:'não chegou'};
  const dia=new Date();dia.setHours(0,0,0,0);
  const hora=(win,hh,mm)=>{win.__dt=dia.getTime()+86400000+(hh*60+mm)*60000-(win.Date.now()-win.__dt)};
  hora(w,23,30);
  ok(await urgente(w,'Urgente da madrugada')===0,'padrão novo da central vale na hora para quem não mexeu (silêncio, urgente respeita)');
  hora(w,12,0);
  ok(await urgente(w,'Urgente do meio-dia')===3,'(conferência: fora do silêncio o urgente toca)');
  const w2=await boot(),$2=s=>w2.document.querySelector(s);
  await until(()=>$2('[data-act=lgk][data-v=adm]'));$2('[data-act=lgk][data-v=adm]').click();$2('.dm-lgbtn').click();
  await until(()=>$2('.dm-tab[data-v=painel]'));await sleep(500);
  hora(w2,23,40);
  ok(await urgente(w2,'Urgente na outra tela')===0,'tela aberta depois: já entra com as preferências do servidor');
  w2.close();
  $('#dm-av-ini').value='';$('[data-act=av-salvar]').click();
  ok(await until(()=>/Horário de silêncio inválido/.test(toast())),'hora vazia: o servidor recusa '+toast());
  $('[data-act=cfg-sec][data-v=email]').click();
  ok(await until(()=>$('.dm-cfgnav [aria-current=page]').textContent.includes('E-mail')),'"Abrir" leva à seção E-mail');
  $('[data-act=mclose]').click();
  $('#dm-uchip').click();await until(()=>$('#dm-mbox [data-act=prefs]'));$('#dm-mbox [data-act=prefs]').click();
  ok(await until(()=>$('#dm-pf-ev-new')),'o Escritório tem o seu "Meus avisos"');
  ok(!$('#dm-pf-ev-fila')&&$$('[id^=dm-pf-ev-]').length===8,'sem a fila (o Escritório não tem fila)');
  ok(!$('#dm-pf-ev-late').checked&&$('#dm-pf-sil').checked&&$('#dm-pf-ini').value==='23:00'&&$('#dm-pf-som').value==='sino'&&!$('#dm-pf-vib').checked&&!$('#dm-pf-jun').checked,'quem não mexeu recebe os padrões novos');
  ok(/não juntar/.test($('#dm-pf-jun').closest('label').textContent),'"não juntar" da central aparece na tela');
  $('#dm-pf-ev-pause').checked=false;$('[data-act=pf-salvar]').click();
  ok(await until(()=>/Avisos salvos/.test(toast())),'o Escritório salva os seus');
  ok(JSON.stringify(av().pessoas.adm)==='{"eventos":{"pause":false}}'&&av().padrao.eventos.pause===true,'os do Escritório ficam separados dos padrões: '+JSON.stringify(av().pessoas));
  ok(w.localStorage.getItem('dm-avisos-aparelho')===null,'aparelho igual ao padrão da central: nada guardado');
  $('#dm-uchip').click();await until(()=>$('#dm-mbox [data-act=prefs]'));$('#dm-mbox [data-act=prefs]').click();
  await until(()=>$('#dm-pf-ev-new'));$('#dm-pf-ev-new').checked=false;$('[data-act=pf-salvar]').click();
  await until(()=>!$('#dm-modal').classList.contains('dm-on'));
  hora(w,12,5);const s0=w.__sons.length;
  await direto('demanda/criar',{tk,titulo:'Urgente com nova desligada',tipo:'mat',motivo:'Falta de material',prio:'urg',est:60,para:{s:'PCP',p:null},desc:''});
  const naGaveta=async()=>{$('#dm-bell').click();await sleep(100);const ok1=/Urgente com nova desligada/.test($('#dm-notif').textContent);$('#dm-notif [data-act=close]').click();return ok1};
  let chegou=false;for(let i=0;i<20&&!chegou;i++){await sleep(500);chegou=await naGaveta()}
  const semBanner=!$$('.dm-alert').some(a=>/Urgente com nova desligada/.test(a.textContent));
  ok(chegou&&w.__sons.length===s0&&semBanner,'"Demanda nova" desligado no Escritório: o urgente fica só no sino '+JSON.stringify({chegou,sons:w.__sons.length-s0,semBanner}));
  w.close();
}
// O link do e-mail (…/#SOL-1001) abre a demanda depois de entrar; o ADM vê as linhas ✉ do registro de envio.
async function linkDoEmail(){
  fs.writeFileSync(path.join(data,'email-log.json'),JSON.stringify({v:1,itens:[{t:Date.now(),dem:'SOL-1001',ev:'created',para:['corte@empresa.com'],status:'ok',tent:1,erro:''}]}));
  const w=await boot(undefined,'#SOL-1001'),d=w.document,$=s=>d.querySelector(s);
  const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
  await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&/SOL-1001/.test($('#dm-drawer .dm-hsub').textContent)),'o link #SOL-1001 abre a gaveta da demanda');
  ok(w.location.hash==='','o # sai do endereço (recarregar não reabre)');
  const mail=$('#dm-drawer .dm-tl li[data-ev=email]');
  ok(mail&&/✉ E-mail enviado/.test(mail.textContent)&&/corte@empresa\.com/.test(mail.textContent)&&/criada/.test(mail.textContent),'histórico do ADM mostra o e-mail enviado: '+(mail&&mail.textContent));
  $('#dm-drawer [data-act=close]').click();await sleep(30);
  w.location.hash='#SOL-1001';
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')),'mudar o # com a tela aberta também abre');
  $('#dm-drawer [data-act=close]').click();
  w.location.hash='#SOL-9999';
  ok(await until(()=>/não encontrada/.test(($('#dm-toast')||{}).textContent||'')),'demanda que não existe: avisa');
  w.close();
}
// Restaurar pela tela a cópia feita no começo (antes dos setores): confirmação, RESTAURAR digitado, dados voltam.
async function restaurarPelaTela(){
  const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
  const outra=await boot(),o=s=>outra.document.querySelector(s);   // outra tela de ADM aberta durante a restauração
  await until(()=>o('[data-act=lgk][data-v=adm]'));o('[data-act=lgk][data-v=adm]').click();o('.dm-lgbtn').click();
  await until(()=>o('.dm-tab[data-v=painel]'));
  const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const toast=()=>($('#dm-toast')||{}).textContent||'';
  await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();
  await until(()=>$('.dm-tab[data-v=painel]'));
  w.NestLocal.views.demandas.config('backup');
  ok(await until(()=>$$('[data-act=bk-rest]').length===1),'a cópia aparece com o botão Restaurar');
  $('[data-act=bk-rest]').click();
  ok(await until(()=>$('#dm-rs-c')&&/Vai se perder/.test($('#dm-rs-perde').textContent)),'confirmação mostra o que vai se perder');
  const seq=JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8')).seq.demanda;
  ok($('#dm-rs-prox').textContent==='SOL-'+(seq+1),'próximo número continua do maior já usado: '+$('#dm-rs-prox').textContent+' (esperado SOL-'+(seq+1)+')');
  ok($('#dm-rs-ok').disabled,'"Restaurar" começa desligado');
  const c=$('#dm-rs-c');c.value='restaura';c.dispatchEvent(new w.Event('input',{bubbles:true}));
  ok($('#dm-rs-ok').disabled,'texto incompleto não liga o botão');
  c.value=' restaurar ';c.dispatchEvent(new w.Event('input',{bubbles:true}));
  ok(!$('#dm-rs-ok').disabled,'RESTAURAR digitado liga o botão');
  $('[data-act=bk-rest-x]').click();
  ok(await until(()=>$$('[data-act=bk-rest]').length===1&&!$('#dm-rs-c')),'Cancelar volta para a lista sem mudar nada');
  $('[data-act=bk-rest]').click();await until(()=>$('#dm-rs-c'));
  $('#dm-rs-c').value='RESTAURAR';$('#dm-rs-c').dispatchEvent(new w.Event('input',{bubbles:true}));$('#dm-rs-ok').click();
  ok(await until(()=>/Dados restaurados/.test(toast())&&$$('.dm-cfgtipo[data-t=antes-restaurar]').length===1,10000),'restaura e guarda a cópia "antes de restaurar" '+toast());
  $('[data-act=mclose]').click();
  ok(await until(()=>$('.dm-mapsum')&&/^0 setores/.test($('.dm-mapsum').textContent.trim())),'os setores criados depois da cópia sumiram');
  const pub=await fetch('http://127.0.0.1:'+PORT+'/api/local/demandas').then(r=>r.json());
  ok(pub.setores.length===0&&pub.demandas.length===0,'servidor confirma: dados da cópia');
  ok(await until(()=>/Dados restaurados para/.test((o('#dm-toast')||{}).textContent||''),10000),'a outra tela aberta avisa sozinha: '+((o('#dm-toast')||{}).textContent||''));
  w.close();outra.close();
}
(async()=>{
  await new Promise(r=>smtp.listen(0,'127.0.0.1',r));smtp.unref();
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
    ok(await until(()=>!$('#cx-cfg').hidden),'computador principal tem o botão ⚙ Configurações');
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
    // backup: aviso no Painel e ⚙ Configurações (Rede e Backup)
    ok(await until(()=>$('#dm-bkav')&&/Nenhum backup feito ainda/.test($('#dm-bkav').textContent)),'Painel do ADM avisa: nenhum backup feito');
    ok(await until(()=>$('.dm-alert[data-k=backup]')),'alerta flutuante do backup aparece');
    click('.dm-alert[data-k=backup] [data-act=ax]');
    click('#cx-cfg');
    ok(await until(()=>$('.dm-cfg')&&$('#dm-cfg-on')),'⚙ Configurações abre na seção Rede');
    ok(!$('#dm-cfg-on').checked&&!$('#dm-cfg-pin'),'rede desligada: sem PINs');
    click('#dm-cfg-on');
    ok(await until(()=>$('#dm-cfg-pin')&&/^\d{6}$/.test($('#dm-cfg-pin').textContent)&&/para ligar o acesso/.test(($('#dm-cfg-msg')||{}).textContent)),'ligar a rede mostra os PINs e pede para reiniciar');
    const pin0=$('#dm-cfg-pin').textContent;w.confirm=()=>true;
    click('[data-act=cfg-pin][data-v=pin]');
    ok(await until(()=>$('#dm-cfg-pin')&&$('#dm-cfg-pin').textContent!==pin0),'gerar PIN do escritório novo');
    click('#dm-cfg-on');ok(await until(()=>!$('#dm-cfg-pin')),'desligar a rede de novo');
    click('[data-act=cfg-sec][data-v=backup]');
    ok(await until(()=>$('#dm-bk-hora')&&$('#dm-bk-hora').value==='03:00'&&$('[data-act=cfg-sec][data-v=backup] .dm-cfgdot')),'seção Backup: 03:00 e ponto vermelho no menu');
    ok(/Nenhum backup feito ainda/.test($('#dm-bk-ult').textContent)&&/Nenhuma cópia/.test($('.dm-cfgbody').textContent),'sem cópias ainda');
    ok($('#dm-bk-pasta').textContent===path.join(base,'backup'),'pasta padrão ao lado de data/: '+$('#dm-bk-pasta').textContent);
    type('#dm-bk-hora','');click('[data-act=bk-salvar]');
    ok(await until(()=>/Horário inválido/.test(toast())),'horário inválido: mensagem do servidor '+toast());
    type('#dm-bk-hora','12:30');type('#dm-bk-diarias','3');click('[data-act=bk-salvar]');
    ok(await until(()=>/salva/.test(toast())&&$('#dm-bk-hora').value==='12:30'&&$('#dm-bk-diarias').value==='3'),'salvar a configuração '+toast());
    click('[data-act=bk-agora]');
    ok(await until(()=>$$('.dm-cfgcp:not(.dm-cfgth)').length===1&&/Verificado/.test($('#dm-bk-ult').textContent),8000),'fazer backup agora: a cópia aparece verificada '+toast());
    ok(!$('[data-act=cfg-sec][data-v=backup] .dm-cfgdot')&&fs.readdirSync(path.join(base,'backup')).length===1,'o ponto vermelho some e o zip está na pasta');
    click('[data-act=cfg-sec][data-v=servidor]');
    ok(await until(()=>$('#dm-sv-ok')&&/Funcionando/.test($('#dm-sv-ok').textContent),8000),'seção Servidor: funcionando');
    ok(/1\.0\.0/.test($('.dm-cfgbody').textContent)&&/Último backup/.test($('.dm-cfgbody').textContent)&&/1 cópias guardadas/.test($('.dm-cfgbody').textContent),'versão e último backup na saúde');
    ok(/Instalado|Não instalado|Não deu para verificar/.test($('#dm-sv-tarefa').textContent)&&/instalar-inicio\.bat|remover-inicio\.bat/.test($('.dm-cfgbody').textContent),'iniciar com o Windows: estado e o que fazer: '+$('#dm-sv-tarefa').textContent);
    ok(/http:\/\/127\.0\.0\.1:\d+/.test($('.dm-svaddr').textContent)&&/acesso pela rede desligado/.test($('.dm-svaddr').textContent),'endereços: este PC e rede desligada');
    // seção E-mail: conta de envio, teste de verdade (servidor SMTP falso), salvar
    click('[data-act=cfg-sec][data-v=email]');
    ok(await until(()=>$('#dm-ml-host')&&!$('#dm-ml-on').checked&&$('#dm-ml-ev-created').checked&&!$('#dm-ml-ev-done').checked),'seção E-mail: desligado, só "criada" marcado');
    ok(/^http:\/\/127\.0\.0\.1:\d+$/.test($('#dm-ml-link').placeholder),'sugere o endereço do link: '+$('#dm-ml-link').placeholder);
    type('#dm-ml-host','127.0.0.1');type('#dm-ml-porta',String(smtp.address().port));type('#dm-ml-seg','nenhuma','change');
    type('#dm-ml-usu','');type('#dm-ml-rem','Central <central@empresa.com>');type('#dm-ml-para','ana@empresa.com');
    click('[data-act=ml-teste]');
    ok(await until(()=>$('#dm-ml-res')&&/^✔ Enviado para ana@empresa\.com/.test($('#dm-ml-res').textContent),10000),'Enviar teste: '+(($('#dm-ml-res')||{}).textContent||toast()));
    ok(smtpLinhas.some(l=>l==='Subject: Teste da Central de demandas'),'o servidor de e-mail recebeu o teste');
    type('#dm-ml-senha','senha-secreta-1');click('#dm-ml-on');click('[data-act=ml-salvar]');
    ok(await until(()=>/e-mail salva/.test(toast())&&$('#dm-ml-on').checked&&$('#dm-ml-host').value==='127.0.0.1'),'salvar liga o e-mail '+toast());
    ok($('#dm-ml-senha').value===''&&/digite para trocar/.test($('#dm-ml-senha').placeholder)&&!/senha-secreta-1/.test(d.documentElement.innerHTML),'a senha não volta para a tela');
    ok($('#dm-ml-num')&&/Pendentes0/.test($('#dm-ml-num').textContent.replace(/\s/g,'')),'fila vazia');
    $('#dm-ml-num').dataset.velho='1';   // some quando a tela redesenha com a resposta do servidor
    click('#dm-ml-ev-done');click('[data-act=ml-salvar]');
    ok(await until(()=>$('#dm-ml-num')&&!$('#dm-ml-num').dataset.velho&&$('#dm-ml-ev-done').checked&&!$('#dm-ml-ev-started').checked&&$('#dm-ml-ev-created').checked&&/digite para trocar/.test($('#dm-ml-senha').placeholder)),'salvar de novo sem digitar a senha: os eventos mudam e a senha guardada fica');
    click('#dm-ml-ev-done');click('[data-act=ml-salvar]');await until(()=>!$('#dm-ml-ev-done').checked);
    click('[data-act=mclose]');
    ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')&&$('.dm-kpis')&&!$('#dm-bkav')),'fecha e o aviso do Painel some');
    // setores
    const novoSetor=async(nome,sig)=>{click('[data-act=tab][data-v=admin]');await until(()=>$('[data-act=newsector]'));click('[data-act=newsector]');type('#dm-sf-name',nome);type('#dm-sf-id',sig);click('[data-act=sf-save]');return until(()=>!$('#dm-modal').classList.contains('dm-on')&&$$('.dm-scard').some(c=>c.textContent.includes(nome)))};
    ok(await novoSetor('Planejamento','PCP'),'cria setor PCP '+toast());
    ok(await novoSetor('Corte CNC','CNC'),'cria setor CNC '+toast());
    ok(await novoSetor('Almoxarifado','ALM'),'cria setor ALM (fica sem demanda) '+toast());
    // pessoa
    click('[data-act=newuser]');type('#dm-uf-name','Carlos');type('#dm-uf-sec','CNC','change');await sleep(50);type('#dm-uf-code','1234');
    type('#dm-uf-email','carlos@');click('[data-act=uf-save]');await sleep(50);
    ok($('#dm-modal').classList.contains('dm-on')&&$('#dm-uf-email').closest('.dm-fld').classList.contains('dm-err'),'e-mail inválido: o campo avisa e nada é enviado');
    type('#dm-uf-email',' Carlos.Souza@Empresa.com ');click('[data-act=uf-save]');
    ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')&&/Carlos/.test(toast())),'cria pessoa Carlos (CNC) com código '+toast());
    const carlosDisco=JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8')).pessoas.find(p=>p.nome==='Carlos');
    ok(carlosDisco.email==='carlos.souza@empresa.com','e-mail gravado em minúsculas: '+carlosDisco.email);
    click('[data-act=tab][data-v=admin]');await until(()=>$('[data-act=editsector][data-v=CNC]'));click('[data-act=editsector][data-v=CNC]');
    ok(await until(()=>$('#dm-sf-email')&&$('#dm-sf-email').value===''),'setor sem e-mail: campo vazio');
    type('#dm-sf-email','corte@empresa.com');click('[data-act=sf-save]');
    ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')),'setor salvo com e-mail');
    click('[data-act=editsector][data-v=CNC]');
    ok(await until(()=>$('#dm-sf-email')&&$('#dm-sf-email').value==='corte@empresa.com'),'o ADM vê o e-mail do setor ao editar');
    click('[data-act=mclose]');
    // demanda com tentativa de XSS no título
    const XSS='<img src=x onerror="window.__xss=1"> Corte de chapas';
    // rascunho: fechar o formulário não perde o texto; Descartar limpa
    click('.dm-hdnew');await until(()=>$('#dm-fm-title'));
    ok(!$('#dm-fm-rasc'),'formulário novo, sem rascunho');
    type('#dm-fm-title','Rascunho que não pode sumir');type('#dm-fm-toS','CNC','change');await sleep(30);type('#dm-fm-desc','detalhe');
    click('[data-act=mclose]');await until(()=>!$('#dm-modal').classList.contains('dm-on'));
    const rasc=JSON.parse(w.localStorage.getItem('dm-rascunho:adm')||'{}');
    ok(rasc.titulo==='Rascunho que não pode sumir'&&rasc.desc==='detalhe'&&rasc.toS==='CNC'&&typeof rasc.cid==='string'&&/^[A-Za-z0-9_-]{8,64}$/.test(rasc.cid)&&!('tk' in rasc),'rascunho guardado no aparelho (até o último campo digitado), com a chave do pedido e sem tk');
    click('.dm-hdnew');await until(()=>$('#dm-fm-title'));
    ok($('#dm-fm-rasc')&&$('#dm-fm-title').value==='Rascunho que não pode sumir'&&$('#dm-fm-desc').value==='detalhe'&&$('#dm-fm-toS').value==='CNC','reabrir recupera o rascunho');
    click('[data-act=m-draft-x]');await sleep(30);
    ok(!$('#dm-fm-rasc')&&$('#dm-fm-title').value===''&&w.localStorage.getItem('dm-rascunho:adm')===null,'Descartar limpa o formulário e o aparelho');
    w.localStorage.setItem('dm-rascunho:adm',JSON.stringify({t:Date.now()-25*3600000,titulo:'velho'}));
    click('[data-act=mclose]');await sleep(30);click('.dm-hdnew');await until(()=>$('#dm-fm-title'));
    ok(!$('#dm-fm-rasc')&&$('#dm-fm-title').value==='','rascunho de mais de 24 h não volta');
    ok($('[data-act=m-est][data-v="480"]').textContent==='8 h','atalho de 480 min diz "8 h": o prazo conta tempo corrido, não dia útil');
    type('#dm-fm-title',XSS);type('#dm-fm-fromS','PCP','change');type('#dm-fm-toS','CNC','change');await sleep(50);
    click('[data-act=m-reason]');await sleep(30);click('[data-act=m-est][data-v="30"]');await sleep(30);
    const cidEnviado=JSON.parse(w.localStorage.getItem('dm-rascunho:adm')||'{}').cid;
    click('[data-act=m-submit]');
    ok(await until(()=>!$('#dm-modal').classList.contains('dm-on')),'demanda criada '+toast());
    const cids=JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8')).cids||[];
    ok(typeof cidEnviado==='string'&&cids.length===1&&cids[0][0]===cidEnviado,'o pedido levou a mesma chave do rascunho: reenviar não duplica');
    const filaMail=JSON.parse(fs.readFileSync(path.join(data,'email-fila.json'),'utf8')).itens;
    ok(filaMail.length===1&&filaMail[0].ev==='created'&&filaMail[0].para.join()==='corte@empresa.com','a demanda nova entrou na fila de e-mail para o e-mail do setor');
    ok(w.localStorage.getItem('dm-rascunho:adm')===null,'enviada com sucesso: o rascunho sai do aparelho');
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
    // central fora do ar: faixa, só leitura, "Tentar agora" com espera crescente, e a volta
    const faixa=()=>(($('.dm-conn b')||{}).textContent||'');
    FORA=true;
    ok(await until(()=>/Sem conexão com a central/.test(faixa()),15000),'2 falhas seguidas: faixa "Sem conexão" '+faixa());
    ok($('#dmboard').hasAttribute('data-offline')&&/tentando de novo em [1-5] s|tentando agora/.test(faixa())&&/Última atualização às \d\d:\d\d/.test($('.dm-conn').textContent),'só leitura, espera curta e hora da última atualização: '+faixa());
    click(oc().querySelector('[data-act=accept]'));await sleep(30);
    ok(/tente quando ela voltar/.test(toast())&&st()==='new','aceitar não sai sem conexão '+toast());
    click('.dm-hdnew');await until(()=>$('#dm-fm-title'));click('[data-act=m-submit]');await sleep(30);
    ok(/rascunho fica guardado/.test(toast())&&$('#dm-modal').classList.contains('dm-on'),'abrir o formulário pode; enviar não, e o rascunho fica');
    click('[data-act=mclose]');
    click('[data-act=conn-retry]');
    ok(await until(()=>/tentando de novo em (6|7|8|9|10) s/.test(faixa())),'"Tentar agora" pergunta na hora e a espera cresce: '+faixa());
    const n1=+(/em (\d+) s/.exec(faixa())||[])[1];await sleep(2200);const n2=+(/em (\d+) s/.exec(faixa())||[])[1];
    ok(n2<n1,'a contagem da faixa anda sozinha: '+n1+' → '+n2);
    const r0=REVS;w.NestLocal.tentarAgora();w.NestLocal.tentarAgora();w.NestLocal.tentarAgora();await sleep(50);
    ok(REVS-r0===1,'"Tentar agora" repetido não abre perguntas em paralelo: '+(REVS-r0));
    FORA=false;click('[data-act=conn-retry]');
    ok(await until(()=>!$('.dm-conn')&&!$('#dmboard').hasAttribute('data-offline')&&/Conexão restabelecida/.test(toast())),'voltou: a faixa some e avisa '+toast());
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
    await avisosDaTela(w,until,click);
    await prefsDaTela(w,until,click);
    await sistemaDaTela(w,until,click);
    w.close();
    await aparelhoOperador();
    await linkDoEmail();
    await cronogramaDaTela();
    await avisosDaCentral();
    await restaurarPelaTela();
  }finally{killTree(srv);   // no Windows o servidor recém-morto ainda pode segurar arquivos: tenta de novo e não reprova por isso
    try{fs.rmSync(base,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+base)}}
  console.log(process.exitCode?'houve falhas':'tudo certo');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());   // janela jsdom aberta não pode prender o processo
