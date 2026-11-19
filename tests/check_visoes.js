const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path'),crypto=require('crypto');
// QA das visões do ADM e do operador, na tela de verdade (jsdom contra o servidor real, dados semeados em pasta temporária):
// Painel, Solicitações, Histórico (com o arquivo morto), visão do operador, Calendário e Cronoanálise.
// rodar: node tests/check_visoes.js        (PYTHON=... troca o interpretador; TZ=... troca o fuso do aparelho)
// "known-bug": o teste afirma o comportamento CORRETO; se falhar, imprime KNOWN-BUG e não reprova; se passar, imprime FIXED.
// Matriz de cobertura e bugs: docs/qa/visoes.md.
const REPO=path.resolve(__dirname,'..');
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
const MIN=60000,HOUR=3600000,DAY=86400000;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let NPASS=0,NFAIL=0,NBUG=0,NFIXED=0;
const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(c)NPASS++;else{NFAIL++;process.exitCode=1}};
const bug=(id,c,m)=>{if(c){NFIXED++;console.log('FIXED '+id+' (o comportamento correto voltou) '+m)}else{NBUG++;console.log('KNOWN-BUG '+id+' '+m)}};
const dirs=[],procs=[];
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}

/* ---------- servidor real, um por cenário ---------- */
function startServer(data){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor;s=servidor.Server(('127.0.0.1',0),servidor.Handler);print(s.server_address[1],flush=True);s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='',port=0;p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+)\s/.exec(out);if(m&&!port){port=+m[1];procs.push(p);res({port,proc:p})}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
const novaPasta=nome=>{const b=fs.mkdtempSync(path.join(os.tmpdir(),'dem-vis-'+nome+'-')),d=path.join(b,'data');fs.mkdirSync(d);dirs.push(b);return d};
const direto=(port,rest,body)=>fetch('http://127.0.0.1:'+port+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(async r=>{const j=await r.json();j.__status=r.status;return j});

/* ---------- aparelho (jsdom) ----------
   papel: finge o /api/eu (operador = aparelho da rede). fake: {t, } = relógio da página (new Date() e Date.now()) num instante
   escolhido; __reqs guarda o corpo dos pedidos POST para conferir a janela que a tela manda. */
async function boot(port,o){
  o=o||{};
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+port+'/'+(o.hash||''),{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.__reqs=[];w.__dt=0;
    w.fetch=(u,x)=>{
      if(x&&x.body&&typeof x.body==='string'&&String(u).startsWith('/api/local/demandas/')){try{w.__reqs.push({rest:String(u).slice('/api/local/demandas/'.length),body:JSON.parse(x.body),t:Date.now()})}catch(e){/* corpo que não é JSON */}}
      if(o.papel&&u==='/api/eu')return Promise.resolve(new Response(JSON.stringify({papel:o.papel}),{headers:{'Content-Type':'application/json'}}));
      const r=fetch(new URL(u,'http://127.0.0.1:'+port).href,x);
      if(!o.fake||!/^\/api\/local\/demandas(\/vista)?$/.test(String(u)))return r;
      // relógio fingido: a vista chega com o "agora" fingido, para a página inteira concordar com o instante escolhido
      return r.then(async resp=>{const j=await resp.json();if(j&&typeof j.agora==='number')j.agora=w.Date.now();return new Response(JSON.stringify(j),{status:resp.status,headers:{'Content-Type':'application/json'}})});
    };
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
    w.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={}}resume(){}createOscillator(){return{type:'',frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
    const R=w.Date,real=R.now.bind(R),t0=Date.now();
    if(o.fake){   // new Date() e Date.now() partem de o.fake (ms) e andam em tempo real
      const base=o.fake,agora=()=>base+(real()-t0)+w.__dt;
      class FD extends R{constructor(...a){if(a.length===0)super(agora());else super(...a)}static now(){return agora()}}
      w.Date=FD;
    }else R.now=()=>real()+w.__dt;
  }});
  const w=dom.window;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  const d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(40))try{if(f())return true}catch(e){}return false};
  const click=s=>{const e=typeof s==='string'?$(s):s;if(!e)throw new Error('não achei '+s);e.click();return e};
  const type=(s,v,ev='input')=>{const e=$(s);if(!e)throw new Error('não achei '+s);e.value=v;e.dispatchEvent(new w.Event(ev,{bubbles:true}))};
  const txt=s=>{const e=$(s);return e?e.textContent.replace(/\s+/g,' ').trim():null};
  const toast=()=>($('#dm-toast')||{}).textContent||'';
  return {w,d,$,$$,until,click,type,txt,toast,close:()=>w.close()};
}
async function entraAdm(a){
  await a.until(()=>a.$('[data-act=lgk][data-v=adm]'));a.click('[data-act=lgk][data-v=adm]');a.click('.dm-lgbtn');
  return a.until(()=>a.$('#dm-login').hidden&&a.$('.dm-tab[data-v=painel]'));
}
async function entraOp(a,setor,nome,codigo){
  await a.until(()=>a.$('[data-act=lgs][data-v='+setor+']'));a.click('[data-act=lgs][data-v='+setor+']');await a.until(()=>a.$('.dm-lguser'));
  a.$$('.dm-lguser').find(b=>b.textContent.includes(nome)).click();a.type('#dm-lg-code',codigo);a.click('.dm-lgbtn');
  return a.until(()=>a.$('#dm-login').hidden&&/Olá, /.test(a.txt('#dmboard')||''));
}

/* ---------- dados semeados ---------- */
const hash=(cod,sal)=>crypto.pbkdf2Sync(cod,Buffer.from(sal,'hex'),100000,32,'sha256').toString('hex');
const SET=[['PCP','Planejamento','⚙️','#3B82F6'],['CNC','Corte CNC','🪚','#E4572E'],['ESP','Espumação','🧽','#10B981'],['ALM','Almoxarifado','📦','#D97706'],['PIN','Pintura','🎨','#8B5CF6']];
const PES=[['p1','Helena','PCP','1111'],['p2','Carlos','CNC','2222'],['p3','Bruno','CNC','3333'],['p4','Fernanda','ESP','4444'],['p5','Paulo','PIN','5555']];
const NOME={p1:'Helena',p2:'Carlos',p3:'Bruno',p4:'Fernanda',p5:'Paulo'};
// n, título, tipo, motivo, prio, est, de, para, status, c (min desde a criação), i (início), f (fim)
const SEEDS=[
 [1001,'Cortar chapas de 18 mm','dem','Falta de material','high',60,['PCP',null],['CNC','p2'],'prog',300,290,null],      // atrasada, do Carlos
 [1002,'Urgente: trocar a lâmina da serra','man','Quebra de máquina','urg',120,['PCP','p1'],['CNC',null],'new',5,null,null],   // fila do CNC
 [1003,'Peça parada na prensa','alt','Retrabalho','norm',480,['ESP','p4'],['CNC','p2'],'pause',90,80,null],                  // pausada há 30 min
 [1004,'Espuma D33 sob medida','mat','Solicitação do cliente','norm',600,['PCP',null],['ESP',null],'new',40,null,null],       // sem aceite há 40 min
 [1005,'Montar kit de fixação','set','Ajuste de planejamento','norm',600,['CNC','p2'],['PCP','p1'],'prog',60,50,null],
 [1006,'Etiquetar o lote 7','dem','Outro','low',600,['PCP',null],['ESP',null],'new',1,null,null],
 [1007,'Lixar a bancada','dem','Outro','norm',600,['PCP',null],['CNC','p3'],'prog',100,90,null],
 [1008,'Corte no prazo','dem','Falta de material','norm',600,['PCP','p1'],['CNC','p2'],'done',200,190,3],
 [1009,'Corte com atraso','dem','Quebra de máquina','norm',60,['PCP',null],['CNC','p2'],'done',400,390,2],
 [1010,'Concluída há 23 horas','dem','Outro','norm',2000,['PCP',null],['CNC','p2'],'done',1500,1490,23*60],
 [1011,'Concluída há 25 horas','dem','Retrabalho','norm',30,['PCP',null],['ESP','p4'],'done',1600,1590,25*60],
 [1012,'Cancelada há 30 minutos','dem','Outro','norm',120,['PCP',null],['CNC','p2'],'canc',100,null,30],
 [1013,'Cancelada há 26 horas','dem','Outro','norm',120,['PCP',null],['CNC',null],'canc',2000,null,26*60],
];
function monta(now,s){
  const [n,titulo,tipo,motivo,prio,est,de,para,status,c,i,f]=s,criado=now-c*MIN,ev=[{t:criado,ev:'created',quem:de[1]?NOME[de[1]]:'Escritório',nota:''}];
  const d={id:'SOL-'+n,titulo,tipo,motivo,prio,est,de:{s:de[0],p:de[1]},para:{s:para[0],p:para[1]},desc:'Sem descrição adicional.',status,criado,
    iniciado:i==null?null:now-i*MIN,fim:f==null?null:now-f*MIN,atraso_avisado:false,pausas:[],eventos:ev,comentarios:[],anexos:[]};
  if(i!=null)ev.push({t:d.iniciado,ev:'started',quem:para[1]?NOME[para[1]]:'Fila',nota:''});
  if(status==='pause'){d.pausas.push({ini:now-30*MIN,fim:null,motivo:'Máquina parada',obs:'',por:'Carlos'});ev.push({t:now-30*MIN,ev:'paused',quem:'Carlos',nota:'Máquina parada'})}
  if(status==='done')ev.push({t:d.fim,ev:'done',quem:para[1]?NOME[para[1]]:'Fila',nota:''});
  if(status==='canc')ev.push({t:d.fim,ev:'canc',quem:'Escritório',nota:''});
  return d;
}
function semeia(data,now,demandas,arquivo,extra){
  const doc={v:2,rev:1,seq:{pessoa:6,demanda:Math.max(1000,...demandas.map(d=>+d.id.slice(4))),nota:0},
    setores:SET.map(([id,nome,icone,cor])=>({id,nome,icone,cor,ativo:true,_rv:0})),
    pessoas:PES.map(([id,nome,setor,cod],k)=>{const sal=crypto.createHash('md5').update('sal'+k).digest('hex');return{id,nome,setor,mat:'M'+(100+k),ativo:true,sal,hash:hash(cod,sal),_rv:0}}),
    demandas,notas:[],cids:[],agenda:{ativa:false,v:0,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[]},agendas:{},...(extra||{})};
  fs.writeFileSync(path.join(data,'demandas.json'),JSON.stringify(doc));
  if(arquivo)fs.writeFileSync(path.join(data,'demandas-arquivo.json'),JSON.stringify({v:2,demandas:arquivo}));
}
const arq=(now,n,titulo,dias,de,para,status)=>({id:'SOL-'+n,titulo,tipo:'dem',motivo:'Outro',prio:'norm',est:60,de:{s:de,p:null},para:{s:para,p:null},desc:'x',status,
  criado:now-dias*DAY,iniciado:now-dias*DAY+MIN,fim:now-dias*DAY+HOUR,atraso_avisado:false,pausas:[],eventos:[{t:now-dias*DAY,ev:'created',quem:'Escritório',nota:''}],comentarios:[],anexos:[]});
const sameDayLocal=(a,b)=>new Date(a).toDateString()===new Date(b).toDateString();
const isAct=s=>['new','prog','pause'].includes(s[8]);

/* ================= PAINEL ================= */
async function painel(a,now){
  const {$,$$,until,click,txt}=a;
  const kpi=k=>txt('.dm-kpi[data-v='+k+'] b');
  const ativas=SEEDS.filter(isAct),atrasadas=ativas.filter(s=>s[9]>s[5]);   // c > est (min): atrasada
  const feitasHoje=SEEDS.filter(s=>s[8]==='done'&&sameDayLocal(now-s[11]*MIN,now)).length;
  const esperado={new:SEEDS.filter(s=>s[8]==='new').length,prog:SEEDS.filter(s=>s[8]==='prog').length,pause:SEEDS.filter(s=>s[8]==='pause').length,late:atrasadas.length,urg:ativas.filter(s=>s[4]==='urg').length,done:feitasHoje};
  ok(await until(()=>$$('.dm-kpi').length===6&&Object.keys(esperado).every(k=>kpi(k)===String(esperado[k]))),'Painel: seis KPIs com os números certos '+JSON.stringify(esperado)+' vs '+$$('.dm-kpi b').map(b=>b.textContent));
  ok($$('.dm-kpi').map(k=>k.querySelector('span').textContent).join()==='Abertas,Em andamento,Pausadas,Atrasadas,Urgentes,Concluídas hoje','rótulos dos KPIs');
  // mapa de setores
  const tiles=()=>$$('#dm-map .dm-tile').map(t=>t.dataset.v);
  ok(tiles().join()==='CNC,ESP,PCP,ALM,PIN','mapa "Mais críticos": CNC (atraso+urgente+pausa), ESP (2), PCP (1), depois os vazios por nome: '+tiles());
  ok($('[data-act=msort][data-v=crit]').getAttribute('aria-pressed')==='true','"Mais críticos" começa marcado');
  const tile=s=>$('#dm-map .dm-tile[data-v='+s+']');
  ok(tile('CNC').classList.contains('dm-hasLate')&&!tile('ESP').classList.contains('dm-hasLate')&&$$('#dm-map .dm-hasLate').length===1,'dm-hasLate só no setor com atrasada');
  ok(tile('ALM').classList.contains('dm-idle')&&tile('PIN').classList.contains('dm-idle')&&!tile('CNC').classList.contains('dm-idle')&&$$('#dm-map .dm-idle').length===2,'dm-idle só nos setores sem solicitação em aberto');
  const tags=s=>[...tile(s).querySelectorAll('.dm-ttags .dm-tg,.dm-ttags .dm-ok0')].map(x=>x.textContent).join('|');
  ok(tags('CNC')==='1 atras.|1 urg.|1 paus.','etiquetas do CNC: '+tags('CNC'));
  ok(tags('ALM')==='Sem usuários'&&tags('PIN')==='Em dia'&&tags('PCP')==='Em dia','"Sem usuários" só no setor sem gente; "Em dia" nos demais sem alerta: '+tags('ALM')+' / '+tags('PIN'));
  const cnc=SEEDS.filter(s=>isAct(s)&&s[7][0]==='CNC').length;
  ok(await until(()=>tile('CNC').querySelector('.dm-tnum b').textContent===String(cnc)),'tile do CNC conta as '+cnc+' em aberto');
  ok(tile('CNC').querySelector('.dm-tbar span').style.width==='100%'&&tile('ALM').querySelector('.dm-tbar span').style.width==='0%'||tile('ALM').querySelector('.dm-tbar span').style.width==='0px','barra: o maior setor enche, o vazio fica a zero ('+tile('CNC').querySelector('.dm-tbar span').style.width+' / '+tile('ALM').querySelector('.dm-tbar span').style.width+')');
  const mapsum=()=>$$('.dm-mapsum span').map(s=>s.textContent.replace(/\s+/g,' ').trim()).join('|');
  ok(await until(()=>mapsum()===`5 setores|${ativas.length} em aberto|1 com atraso|4 em dia`),'resumo do mapa: '+mapsum());
  // ordem A–Z
  click('[data-act=msort][data-v=az]');
  ok(await until(()=>tiles().join()==='ALM,CNC,ESP,PIN,PCP'),'A–Z: Almoxarifado, Corte CNC, Espumação, Pintura, Planejamento: '+tiles());
  ok($('[data-act=msort][data-v=az]').getAttribute('aria-pressed')==='true'&&$('[data-act=msort][data-v=crit]').getAttribute('aria-pressed')==='false','A–Z fica marcado e o outro desmarca');
  click('[data-act=msort][data-v=crit]');
  ok(await until(()=>tiles().join()==='CNC,ESP,PCP,ALM,PIN'),'voltar a "Mais críticos" restaura a ordem');
  // atenção
  const al=()=>$$('.dm-al:not(.dm-bkav)');
  ok(al().length===4&&/4 itens exigem atenção/.test(txt('.dm-grid2 .dm-panel .dm-s')),'Atenção agora: 4 itens (atrasada, urgente, pausada há 20+ min, sem aceite há 25+ min): '+al().length+' / '+txt('.dm-grid2 .dm-panel .dm-s'));
  ok(al().map(x=>x.querySelector('.dm-al-h b').textContent).join()==='SOL-1001,SOL-1002,SOL-1003,SOL-1004','ordem por pontuação (100, 60, 40, 30)');
  const tg=n=>[...al()[n].querySelectorAll('.dm-tg')].map(x=>x.dataset.k+':'+x.textContent).join('|');
  ok(/^late:Atrasada há /.test(tg(0))&&/^urg:Urgente$/.test(tg(1))&&/^pause:Pausada há /.test(tg(2))&&/^wait:Sem aceite há /.test(tg(3)),'marcas de cada item: '+[0,1,2,3].map(tg).join(' // '));
  ok(/Motivo:<\/b> Máquina parada \(Carlos\)/.test(al()[2].innerHTML),'a pausada mostra o motivo e quem pausou');
  // botões da atenção
  click(al()[0].querySelector('[data-act=open]'));
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&/SOL-1001/.test(txt('#dm-drawer'))),'"Ver" abre a gaveta da solicitação');
  click('#dm-drawer [data-act=close]');
  click(al()[3].querySelector('[data-act=nudge]'));
  ok(await until(()=>/Cobrança|cobr/i.test(a.toast())||$$('.dm-feed li').some(l=>/SOL-1004 · Cobrança enviada/.test(l.textContent))),'"Cobrar" manda a cobrança: '+a.toast());
  click(al()[1].querySelector('[data-act=reassign]'));
  ok(await until(()=>$('#dm-modal').classList.contains('dm-on')),'"Reatribuir" abre a caixa');
  click('#dm-modal [data-act=mclose]');
  // feed
  ok(await until(()=>$$('.dm-feed li button').length===10),'Atividade ao vivo: no máximo 10 eventos na tela ('+$$('.dm-feed li button').length+')');
  const f0=$('.dm-feed li button');click(f0);
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&txt('#dm-drawer').includes(f0.dataset.id)),'clicar num evento abre a solicitação dele');
  click('#dm-drawer [data-act=close]');
  ok($$('.dm-feed li time').every(t=>/^\d\d:\d\d$/.test(t.textContent)),'cada evento traz a hora');
}

/* ================= SOLICITAÇÕES ================= */
async function solicitacoes(a,now){
  const {$,$$,until,click,type,txt}=a;
  const val=id=>$('#'+id).value;
  const poe=(id,v)=>{const s=$('#'+id);s.value=v;s.dispatchEvent(new a.w.Event('change',{bubbles:true}))};
  const col=st=>$$('.dm-col[data-st='+st+'] .dm-card').map(c=>c.dataset.id);
  const colN=st=>txt('.dm-col[data-st='+st+'] .dm-n');
  const count=()=>txt('.dm-count');
  const lista=()=>$$('.dm-lrow').map(r=>r.dataset.id);
  const doneRecentes=SEEDS.filter(s=>s[8]==='done'&&s[11]<24*60).length;
  // KPI "Abertas" leva para a aba com o filtro
  click('.dm-tab[data-v=painel]');await until(()=>$('.dm-kpi'));
  click('.dm-kpi[data-v=new]');
  ok(await until(()=>$('#dm-fSt')&&val('dm-fSt')==='new'),'KPI Abertas abre Solicitações filtrada em Abertas');
  ok(val('dm-fSec')===''&&val('dm-fPrio')===''&&val('dm-fType')===''&&val('dm-q')==='','e zera o resto dos filtros');
  ok(count()==='3 solicitações'&&col('new').length===3,'3 abertas: '+count());
  click('.dm-tab[data-v=painel]');await until(()=>$('.dm-kpi'));click('.dm-kpi[data-v=urg]');
  ok(await until(()=>val('dm-fSt')==='open'&&val('dm-fPrio')==='urg'),'KPI Urgentes = Em aberto + prioridade Urgente');
  ok(count()==='1 solicitações'&&col('new').join()==='SOL-1002','só a urgente SOL-1002: '+count());
  click('.dm-tab[data-v=painel]');await until(()=>$('.dm-kpi'));click('.dm-kpi[data-v=late]');
  ok(await until(()=>val('dm-fSt')==='late')&&count()==='1 solicitações'&&col('prog').join()==='SOL-1001','KPI Atrasadas: filtro Atrasadas, só a SOL-1001 (na coluna "Em andamento")');
  click('.dm-tab[data-v=painel]');await until(()=>$('.dm-kpi'));click('.dm-kpi[data-v=pause]');
  ok(await until(()=>val('dm-fSt')==='pause')&&col('pause').join()==='SOL-1003','KPI Pausadas');
  click('.dm-tab[data-v=painel]');await until(()=>$('.dm-kpi'));click('.dm-kpi[data-v=prog]');
  ok(await until(()=>val('dm-fSt')==='prog')&&col('prog').length===3,'KPI Em andamento: 3');
  click('.dm-tab[data-v=painel]');await until(()=>$('.dm-kpi'));click('.dm-kpi[data-v=done]');
  ok(await until(()=>val('dm-fSt')==='done'),'KPI Concluídas hoje abre o filtro Concluídas');
  // tile do mapa: filtra pelo setor (depois de 260 ms) e o tile fica marcado ao voltar
  click('.dm-tab[data-v=painel]');await until(()=>$('#dm-map .dm-tile'));click('#dm-map .dm-tile[data-v=CNC]');
  ok(await until(()=>$('#dm-fSec')&&val('dm-fSec')==='CNC'&&val('dm-fSt')==='open'),'clicar no tile do CNC filtra setor CNC + Em aberto');
  ok(count()==='4 solicitações','4 em aberto no CNC: '+count());
  click('.dm-tab[data-v=painel]');
  ok(await until(()=>$('#dm-map .dm-tile[data-v=CNC]')&&$('#dm-map .dm-tile[data-v=CNC]').classList.contains('dm-pick')&&$$('#dm-map .dm-pick').length===1),'voltando ao Painel o tile do filtro fica com dm-pick (só ele)');
  click('.dm-tab[data-v=sol]');await until(()=>$('#dm-fSt'));click('[data-act=clear]');
  ok(await until(()=>val('dm-fSt')===''&&val('dm-fSec')===''),'Limpar filtros zera o status e o setor');
  click('.dm-tab[data-v=painel]');
  ok(await until(()=>$$('#dm-map .dm-pick').length===0),'e o tile deixa de estar marcado');
  // todas as demandas, quadro
  click('.dm-tab[data-v=sol]');await until(()=>$('#dm-fSt'));
  ok(count()===SEEDS.length+' solicitações','sem filtro: '+SEEDS.length+' solicitações: '+count());
  ok($$('.dm-col').map(c=>c.dataset.st).join()==='new,prog,pause,done','quadro com quatro colunas');
  ok(colN('new')==='3'&&colN('prog')==='3'&&colN('pause')==='1'&&colN('done')===String(doneRecentes),'contadores das colunas (Concluídas só as das últimas 24 h): '+['new','prog','pause','done'].map(colN));
  ok(col('done').join()===['SOL-1009','SOL-1008','SOL-1010'].join(),'Concluídas (24h): mais recente primeiro; a de 25 h fica fora: '+col('done'));
  ok(col('new').join()==='SOL-1002,SOL-1004,SOL-1006','coluna Abertas: urgente, depois por prioridade e prazo: '+col('new'));
  ok(col('prog')[0]==='SOL-1001','coluna Em andamento: a atrasada primeiro: '+col('prog'));
  // busca
  type('#dm-q','1003');ok(await until(()=>count()==='1 solicitações')&&col('pause').join()==='SOL-1003','busca pelo ID');
  type('#dm-q','  PRENSA  ');ok(await until(()=>count()==='1 solicitações'),'busca por parte do título, sem diferenciar caixa e ignorando espaços nas pontas');
  type('#dm-q','falta de material');ok(await until(()=>count()==='2 solicitações'),'busca pelo motivo (dois: 1001 e 1008)');
  type('#dm-q','carlos');ok(await until(()=>count()===SEEDS.filter(s=>s[7][1]==='p2').length+' solicitações'),'busca pelo nome do responsável (Carlos): '+count());
  type('#dm-q','zzz-nada');ok(await until(()=>count()==='0 solicitações')&&$$('.dm-col .dm-empty').length===4&&/Nada por aqui/.test(txt('.dm-col .dm-empty')),'busca sem resultado: contadores zerados e aviso em cada coluna');
  type('#dm-q','<img src=x onerror=1>');ok(await until(()=>count()==='0 solicitações')&&!$('#dm-view img')&&val('dm-q')==='<img src=x onerror=1>','texto com HTML é só texto (sem elemento) e continua no campo');
  type('#dm-q','');ok(await until(()=>count()===SEEDS.length+' solicitações'),'campo vazio: tudo de novo');
  // selects, um a um
  poe('dm-fSt','open');ok(await until(()=>count()==='7 solicitações'),'status Em aberto: 7');
  poe('dm-fSt','late');ok(await until(()=>count()==='1 solicitações'),'status Atrasadas: 1');
  poe('dm-fSt','done');ok(await until(()=>count()==='4 solicitações'&&col('done').length===3),'status Concluídas: 4 no total, 3 na coluna das últimas 24 h ('+count()+' / '+col('done').length+')');
  ok(count()==='4 solicitações'&&$$('.dm-col').length===4,'(a contagem do topo inclui a concluída de 25 h que o quadro esconde)');
  poe('dm-fSt','canc');ok(await until(()=>$('.dm-board.dm-one')&&count()==='2 solicitações'&&col('canc').join()==='SOL-1012'),'status Canceladas: coluna única, só a das últimas 24 h aparece ('+col('canc')+')');
  poe('dm-fSt','');
  poe('dm-fSec','ESP');ok(await until(()=>count()==='3 solicitações'),'setor ESP: 3 (1004, 1006, 1011)');
  poe('dm-fSec','ALM');ok(await until(()=>count()==='0 solicitações'),'setor sem solicitação: 0');
  poe('dm-fSec','');
  poe('dm-fPrio','urg');ok(await until(()=>count()==='1 solicitações'),'prioridade Urgente: 1');
  poe('dm-fPrio','low');ok(await until(()=>count()==='1 solicitações'),'prioridade Baixa: 1');
  poe('dm-fPrio','high');ok(await until(()=>count()==='1 solicitações'),'prioridade Alta: 1');
  poe('dm-fPrio','norm');ok(await until(()=>count()===SEEDS.filter(s=>s[4]==='norm').length+' solicitações'),'prioridade Normal');
  poe('dm-fPrio','');
  for(const t of ['dem','alt','set','man','mat']){poe('dm-fType',t);ok(await until(()=>count()===SEEDS.filter(s=>s[2]===t).length+' solicitações'),'tipo '+t+': '+SEEDS.filter(s=>s[2]===t).length)}
  poe('dm-fType','');
  // combinações
  poe('dm-fSec','CNC');poe('dm-fSt','open');poe('dm-fPrio','norm');
  ok(await until(()=>count()==='2 solicitações'),'CNC + Em aberto + Normal: 1003 e 1007 ('+count()+')');
  type('#dm-q','lixar');ok(await until(()=>count()==='1 solicitações'&&col('prog').join()==='SOL-1007'),'+ busca "lixar": 1007');
  poe('dm-fType','alt');ok(await until(()=>count()==='0 solicitações'),'+ tipo Alteração: nenhum');
  click('[data-act=clear]');
  ok(await until(()=>count()===SEEDS.length+' solicitações'&&val('dm-q')===''&&val('dm-fSec')===''&&val('dm-fSt')===''&&val('dm-fPrio')===''&&val('dm-fType')===''),'Limpar filtros zera os cinco campos e o contador');
  // lista
  click('[data-act=view][data-v=list]');
  ok(await until(()=>$('.dm-lbox .dm-lhead')&&$$('.dm-lrow').length===SEEDS.length),'visão Lista: '+SEEDS.length+' linhas');
  ok($('[data-act=view][data-v=list]').getAttribute('aria-pressed')==='true'&&$('[data-act=view][data-v=board]').getAttribute('aria-pressed')==='false','botão Lista marcado');
  ok($$('.dm-lhead span').map(s=>s.textContent).join()==='ID,Solicitação,De → Para,Responsável,Status','cabeçalhos da lista');
  ok(lista().slice(0,7).every(id=>SEEDS.find(s=>'SOL-'+s[0]===id&&isAct(s)))&&lista()[0]==='SOL-1001','a lista põe as em aberto primeiro, a atrasada no topo: '+lista().slice(0,3));
  poe('dm-fSt','done');ok(await until(()=>$$('.dm-lrow').length===4),'a lista mostra as 4 concluídas (sem o corte de 24 h do quadro)');
  poe('dm-fSt','');
  type('#dm-q','zzz');ok(await until(()=>/Nenhuma solicitação encontrada/.test(txt('.dm-lbox'))),'lista sem resultado: "Nenhuma solicitação encontrada"');
  type('#dm-q','');await until(()=>$$('.dm-lrow').length===SEEDS.length);
  click('.dm-lrow[data-id=SOL-1004]');
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&/SOL-1004/.test(txt('#dm-drawer'))),'clicar numa linha abre a gaveta');
  click('#dm-drawer [data-act=close]');
  const linha=$('.dm-lrow[data-id=SOL-1004]');linha.dispatchEvent(new a.w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')),'Enter numa linha da lista abre a gaveta (teclado)');
  click('#dm-drawer [data-act=close]');
  click('[data-act=view][data-v=board]');
  ok(await until(()=>$$('.dm-col').length===4),'voltar ao Quadro');
  click('.dm-card[data-id=SOL-1004]');
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')),'clicar num cartão do quadro abre a gaveta');
  click('#dm-drawer [data-act=close]');
}

/* ================= HISTÓRICO ================= */
async function historico(a,now){
  const {$,$$,until,click,type,txt}=a;
  const poe=(id,v)=>{const s=$('#'+id);s.value=v;s.dispatchEvent(new a.w.Event('change',{bubbles:true}))};
  const cnt=()=>txt('.dm-count'),rows=()=>$$('.dm-hrow').map(r=>r.dataset.id);
  const pares={};for(const s of SEEDS){const k=s[6][0]+'>'+s[7][0];pares[k]=(pares[k]||0)+1}
  click('.dm-tab[data-v=hist]');
  ok(await until(()=>$('#dm-hq')&&$$('.dm-hrow').length===SEEDS.length),'Histórico abre com as '+SEEDS.length+' solicitações do principal');
  ok(cnt()===`${SEEDS.length} de ${SEEDS.length}`,'contador "N de M": '+cnt());
  ok(rows()[0]==='SOL-1006'&&rows()[rows().length-1]==='SOL-1013','ordem: a criada por último primeiro (1006 há 1 min) e a mais antiga no fim');
  ok($$('.dm-hhead span').map(s=>s.textContent).join()==='ID,Solicitação,Relação,Aberta,Início,Fim,Status','cabeçalhos');
  const r1004=$('.dm-hrow[data-id=SOL-1004]');
  ok(r1004.querySelectorAll('time').length===1&&r1004.querySelectorAll('.dm-muted').length===2,'sem início nem fim: "—" nas duas colunas');
  ok(/^\d\d\/\d\d\/\d{4} \d\d:\d\d$/.test($('.dm-hrow[data-id=SOL-1008] time').textContent),'data completa dd/mm/aaaa hh:mm');
  // relações
  const rels=$$('.dm-rel').map(r=>r.dataset.from+'>'+r.dataset.to+'='+r.querySelector('b').textContent).join();
  ok(rels===Object.entries(pares).sort((x,y)=>y[1]-x[1]||x[0].localeCompare(y[0])).map(([k,n])=>k+'='+n).join(),'relações prontas por origem>destino com o total, a maior primeiro: '+rels);
  click('.dm-rel[data-from=PCP][data-to=ESP]');
  ok(await until(()=>cnt()===`3 de ${SEEDS.length}`&&$('#dm-hFrom').value==='PCP'&&$('#dm-hTo').value==='ESP'),'clicar numa relação filtra origem e destino: '+cnt());
  ok($('.dm-rel[data-from=PCP][data-to=ESP]').getAttribute('aria-pressed')==='true'&&$$('.dm-rel[aria-pressed=true]').length===1,'a relação escolhida fica pressionada (só ela)');
  ok(/Planejamento para Espumação, 3 demandas/.test($('.dm-rel[data-from=PCP][data-to=ESP]').getAttribute('aria-label')),'aria-label descreve a relação');
  ok($$('.dm-rel b').map(b=>b.textContent).join()===Object.entries(pares).sort((x,y)=>y[1]-x[1]||x[0].localeCompare(y[0])).map(e=>e[1]).join(),'as relações não mudam com o filtro (contam o total)');
  click('[data-act=hclear]');
  ok(await until(()=>cnt()===`${SEEDS.length} de ${SEEDS.length}`&&$('#dm-hFrom').value===''&&$('#dm-hTo').value===''),'Limpar zera origem e destino');
  // filtros um a um
  poe('dm-hSt','done');ok(await until(()=>cnt()===`4 de ${SEEDS.length}`),'status Concluídas: 4 (sem corte de 24 h)');
  poe('dm-hSt','late');ok(await until(()=>cnt()===`1 de ${SEEDS.length}`&&rows().join()==='SOL-1001'),'status Atrasadas: só a ativa em atraso (concluída com atraso não conta)');
  poe('dm-hSt','canc');ok(await until(()=>cnt()===`2 de ${SEEDS.length}`),'status Canceladas: 2 (todas, sem o corte de 24 h)');
  poe('dm-hSt','new');ok(await until(()=>cnt()===`3 de ${SEEDS.length}`),'status Abertas: 3');
  poe('dm-hSt','');
  poe('dm-hFrom','CNC');ok(await until(()=>cnt()===`1 de ${SEEDS.length}`&&rows().join()==='SOL-1005'),'origem CNC: 1');
  poe('dm-hFrom','');poe('dm-hTo','CNC');ok(await until(()=>cnt()===`${SEEDS.filter(s=>s[7][0]==='CNC').length} de ${SEEDS.length}`),'destino CNC: '+cnt());
  poe('dm-hFrom','ESP');ok(await until(()=>cnt()===`1 de ${SEEDS.length}`&&rows().join()==='SOL-1003'),'origem ESP + destino CNC: 1003');
  poe('dm-hFrom','ALM');ok(await until(()=>cnt()===`0 de ${SEEDS.length}`&&/Nenhuma demanda nesse recorte/.test(txt('.dm-lbox'))),'combinação sem resultado: "Nenhuma demanda nesse recorte"');
  poe('dm-hFrom','');poe('dm-hTo','');
  type('#dm-hq','espuma');ok(await until(()=>cnt()===`1 de ${SEEDS.length}`),'busca pelo título');
  type('#dm-hq','SOL-1010');ok(await until(()=>cnt()===`1 de ${SEEDS.length}`),'busca pelo ID');
  type('#dm-hq','retrabalho');ok(await until(()=>cnt()===`2 de ${SEEDS.length}`),'busca pelo motivo (1003 e 1011)');
  type('#dm-hq','carlos');ok(await until(()=>cnt()===`0 de ${SEEDS.length}`),'busca pelo responsável não existe no histórico (só ID, título e motivo): 0');
  type('#dm-hq','<b>x</b>');ok(await until(()=>cnt()===`0 de ${SEEDS.length}`&&!$('#dm-view b[class=x]')&&$('#dm-hq').value==='<b>x</b>'),'HTML na busca é texto');
  type('#dm-hq','');ok(await until(()=>cnt()===`${SEEDS.length} de ${SEEDS.length}`),'busca vazia: tudo');
  poe('dm-hSt','done');poe('dm-hTo','CNC');type('#dm-hq','corte');
  ok(await until(()=>cnt()===`2 de ${SEEDS.length}`&&rows().join()==='SOL-1008,SOL-1009'),'combinação: concluídas + destino CNC + "corte" = 1008 e 1009 ('+rows()+')');
  click('[data-act=hclear]');
  ok(await until(()=>cnt()===`${SEEDS.length} de ${SEEDS.length}`&&$('#dm-hq').value===''&&$('#dm-hSt').value===''&&$('#dm-hTo').value===''),'Limpar zera busca, status, origem e destino');
  // arquivo morto
  ok($$('#dm-hArq option').map(o=>o.value).join()===',30,90,365'&&$('#dm-hArq').value==='','seletor do arquivo morto: só as recentes, 30 dias, 90 dias, 1 ano');
  poe('dm-hArq','30');ok(await until(()=>a.w.__reqs.some(r=>r.rest==='historico')),'escolher 30 dias pede o arquivo ao servidor');
  const r30=a.w.__reqs.filter(r=>r.rest==='historico').pop().body;
  ok(Math.abs((r30.ate-r30.de)-30*DAY)<1000,'a janela pedida tem 30 dias ('+(r30.ate-r30.de)/DAY+')');
  await sleep(300);ok(cnt()===`${SEEDS.length} de ${SEEDS.length}`,'30 dias: nenhuma antiga nessa janela ('+cnt()+')');
  poe('dm-hArq','90');ok(await until(()=>cnt()===`${SEEDS.length+1} de ${SEEDS.length+1}`&&rows().includes('SOL-901')),'90 dias traz a de 40 dias (SOL-901): '+cnt());
  ok(!rows().includes('SOL-902'),'e não a de 100 dias');
  poe('dm-hArq','365');ok(await until(()=>rows().includes('SOL-902')&&cnt()===`${SEEDS.length+2} de ${SEEDS.length+2}`),'1 ano traz também a de 100 dias: '+cnt());
  ok(!rows().includes('SOL-903'),'a de 400 dias continua de fora (mais velha que 1 ano)');
  ok(rows()[rows().length-1]==='SOL-902','as arquivadas entram na ordem por data (a mais velha por último)');
  const pcpEsp=$('.dm-rel[data-from=PCP][data-to=ESP] b').textContent;
  ok(pcpEsp==='4','as relações também contam as arquivadas (PCP→ESP: 3 + SOL-902 = 4): '+pcpEsp);
  poe('dm-hFrom','PCP');poe('dm-hTo','ESP');poe('dm-hSt','done');
  ok(await until(()=>rows().join()==='SOL-1011,SOL-902'),'filtros valem para as arquivadas: PCP→ESP concluídas = 1011 e 0902 ('+rows()+')');
  click('.dm-hrow[data-id=SOL-902]');
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&/SOL-902/.test(txt('#dm-drawer'))),'a gaveta abre uma solicitação do arquivo morto');
  click('#dm-drawer [data-act=close]');
  click('[data-act=hclear]');await until(()=>cnt()===`${SEEDS.length+2} de ${SEEDS.length+2}`);
  bug('V-02',$('#dm-hArq').value==='','"Limpar" também deveria voltar o seletor do arquivo morto a "Só as recentes": ficou "'+$('#dm-hArq').value+'" depois de Limpar');
  poe('dm-hArq','');
  ok(await until(()=>cnt()===`${SEEDS.length} de ${SEEDS.length}`),'voltar a "Só as recentes" tira as arquivadas da lista');
}


/* ================= OPERADOR ================= */
const durTxt=m=>{if(m==null)return '—';m=Math.max(0,Math.round(m));if(m<60)return m+' min';const h=Math.floor(m/60),r=m%60;if(h>=48)return Math.floor(h/24)+'d '+(h%24)+'h';return h+'h'+(r?' '+String(r).padStart(2,'0')+'min':'')};
async function operador(port){
  const stats=o=>o.$$('.dm-opstats div').map(x=>x.querySelector('b').textContent).join();
  const cards=o=>o.$$('.dm-ocard').map(c=>c.dataset.id);
  const btns=(o,id)=>[...o.$('.dm-ocard[data-id='+id+']').querySelectorAll('.dm-obtns [data-act]')].map(b=>b.dataset.act).join();
  const fl=o=>o.$$('.dm-filters [data-act=opf]').map(b=>b.textContent+(b.getAttribute('aria-pressed')==='true'?'*':'')).join('|');
  const c=await boot(port,{papel:'operador'});
  ok(await entraOp(c,'CNC','Carlos','2222'),'operador Carlos (CNC) entra com o código');
  ok(/Olá, Carlos/.test(c.txt('.dm-opwrap h2'))&&/Corte CNC · matrícula M101 · (dom|seg|ter|qua|qui|sex|sáb) \d\d\/\d\d/.test(c.txt('.dm-opsub')),'cabeçalho: nome, setor, matrícula e data: '+c.txt('.dm-opsub'));
  const tabs=()=>c.$$('.dm-tab').map(b=>b.dataset.v+':'+(b.querySelector('.dm-cnt')||{}).textContent).join();
  ok(tabs()==='recv:2,sent:1','abas Recebidas (as 2 dele em aberto) e Enviadas (1 em aberto): '+tabs());
  ok(!c.$('.dm-tab[data-v=painel]')&&!c.$('.dm-tab[data-v=sol]')&&!c.$('.dm-tab[data-v=admin]'),'operador não vê as abas do ADM');
  ok(stats(c)==='1,1,1,1','faixa de números: fila do setor 1, em andamento 1, pausadas 1, atrasadas 1: '+stats(c));
  ok(fl(c)==='Minhas*|Fila do setor|Concluídas','Recebidas: filtros Minhas / Fila do setor / Concluídas, "Minhas" marcado: '+fl(c));
  ok(cards(c).join()==='SOL-1001,SOL-1003','Minhas: a atrasada primeiro, depois a pausada: '+cards(c));
  ok(btns(c,'SOL-1001')==='pause,finish,reassign'&&btns(c,'SOL-1003')==='resume,finish','botões por estado: em andamento = Pausar/Concluir/Repassar; pausada = Retomar/Concluir');
  ok(/Minha/.test(c.$('.dm-ocard[data-id=SOL-1001] .dm-oh').textContent),'etiqueta "Minha" nas dele');
  c.click('[data-act=opf][data-v=pend]');
  ok(await c.until(()=>cards(c).join()==='SOL-1001,SOL-1002,SOL-1003,SOL-1007'),'Fila do setor: as 4 em aberto do CNC (atrasada, urgente, pausada, a do colega): '+cards(c));
  ok(btns(c,'SOL-1002')==='accept,reassign'&&/Em andamento com <b>Bruno<\/b>/.test(c.$('.dm-ocard[data-id=SOL-1007]').innerHTML)&&btns(c,'SOL-1007')==='','aberta ganha Aceitar/Repassar; a do colega mostra o cadeado e nenhum botão');
  c.click('[data-act=opf][data-v=done]');
  ok(await c.until(()=>cards(c).join()==='SOL-1009,SOL-1008,SOL-1012,SOL-1010'),'Concluídas: as dele de até 2 dias, mais recente primeiro (inclui a cancelada de 30 min; a de outra pessoa não): '+cards(c));
  ok(btns(c,'SOL-1009')==='','concluída não tem botão');
  c.click('.dm-tab[data-v=sent]');
  ok(await c.until(()=>fl(c)==='Em aberto*|Concluídas'&&cards(c).join()==='SOL-1005'),'Enviadas: filtros Em aberto / Concluídas e o pedido dele: '+fl(c)+' '+cards(c));
  ok(btns(c,'SOL-1005')==='nudge,cancel'&&/Para Helena/.test(c.$('.dm-ocard[data-id=SOL-1005] .dm-route').textContent),'Enviadas: Cobrar e Cancelar; "Para Helena"');
  c.click('[data-act=opf][data-v=done]');
  ok(await c.until(()=>/Nada por aqui no momento/.test(c.txt('.dm-opwrap'))),'Enviadas > Concluídas vazio: "Nada por aqui no momento."');
  c.click('.dm-tab[data-v=recv]');
  ok(await c.until(()=>fl(c)==='Minhas*|Fila do setor|Concluídas'),'trocar de aba volta ao filtro padrão da aba');
  c.close();
  // Fernanda (ESP): nada dela em andamento -> aviso com atalho para a fila
  const f=await boot(port,{papel:'operador'});
  ok(await entraOp(f,'ESP','Fernanda','4444'),'operadora Fernanda (ESP) entra');
  ok(/Você não tem solicitações em andamento agora/.test(f.txt('.dm-opwrap'))&&f.$('[data-act=opf][data-v=pend]'),'Minhas vazio: mensagem e botão "Ver fila do setor"');
  ok(f.$$('.dm-tab').map(b=>b.dataset.v+':'+(b.querySelector('.dm-cnt')||{}).textContent).join()==='recv:0,sent:1','abas: 0 recebidas, 1 enviada (1003)');
  f.click('.dm-opwrap .dm-empty [data-act=opf]');
  ok(await f.until(()=>cards(f).join()==='SOL-1004,SOL-1006'),'"Ver fila do setor" abre a fila do ESP: 1004 e 1006: '+cards(f));
  ok(f.$$('.dm-opstats div b').map(b=>b.textContent).join()==='2,0,0,0','faixa: 2 na fila, o resto zero');
  f.close();
  // Paulo (PIN): sem nada
  const p=await boot(port,{papel:'operador'});
  ok(await entraOp(p,'PIN','Paulo','5555'),'operador Paulo (PIN) entra');
  p.click('.dm-tab[data-v=sent]');
  ok(await p.until(()=>/Você ainda não enviou solicitações em aberto/.test(p.txt('.dm-opwrap'))),'Enviadas vazio: orienta a usar "＋ Nova solicitação"');
  ok(!!p.$('[data-act=new]'),'botão ＋ Nova solicitação existe para o operador');
  p.close();
}
async function verComo(a){
  const {$,$$,until,click,txt}=a;
  click('.dm-tab[data-v=admin]');await until(()=>$('[data-act=admsub][data-v=users]'));click('[data-act=admsub][data-v=users]');
  ok(await until(()=>$('[data-act=impersonate][data-v=p2]')),'Administração > Usuários lista "Ver como"');
  click('[data-act=impersonate][data-v=p2]');
  ok(await until(()=>$('#dm-imp .dm-impbar')&&/Modo visualização/.test(txt('#dm-imp'))&&/Carlos/.test(txt('#dm-imp'))),'faixa "Modo visualização" com o nome');
  ok(await until(()=>$$('.dm-tab').map(b=>b.dataset.v).join()==='recv,sent'),'abas do operador durante a visualização');
  ok(!$('.dm-obtns')&&!$('.dm-opwrap [data-act=new]')&&$$('.dm-ocard').length>0,'só leitura: cartões sem botões de ação e sem ＋ Nova solicitação na tela do operador');
  bug('V-08',$('.dm-hdnew').hidden,'em "Modo visualização (só leitura)" o botão ＋ Nova solicitação do cabeçalho deveria sumir; está '+($('.dm-hdnew').hidden?'escondido':'visível e abre o formulário'));
  if(!$('.dm-hdnew').hidden){click('.dm-hdnew');ok(await until(()=>$('#dm-modal').classList.contains('dm-on')&&$('#dm-fm-title')),'(reprodução do V-08: o formulário abre mesmo na visualização)');click('[data-act=mclose]');await until(()=>!$('#dm-modal').classList.contains('dm-on'))}
  click('[data-act=impexit]');
  ok(await until(()=>!$('#dm-imp .dm-impbar')&&$('.dm-tab[data-v=painel]')),'"Voltar ao ADM" restaura as abas do ADM');
}

/* ================= FRONTEIRAS DE MÊS, SEMANA E DIA (CALENDÁRIO) E JANELAS DO CRONOGRAMA ================= */
const MESES=['janeiro','fevereiro','março','abril','maio','junho','julho','agosto','setembro','outubro','novembro','dezembro'],DOWS=['dom','seg','ter','qua','qui','sex','sáb'];
const L=(y,m,d,h,mi)=>new Date(y,m,d,h||0,mi||0).getTime();
const jan=t=>{const d=new Date(t),y=d.getFullYear(),m=d.getMonth(),dd=d.getDate(),w=d.getDay();return{mes:[L(y,m,1),L(y,m+1,1)],semana:[L(y,m,dd-w),L(y,m,dd-w+7)],dia:[L(y,m,dd),L(y,m,dd+1)]}};
const dd2=n=>String(n).padStart(2,'0'),fDD=t=>{const d=new Date(t);return dd2(d.getDate())+'/'+dd2(d.getMonth()+1)};
const diaK=t=>{const d=new Date(t);return d.getFullYear()+'-'+d.getMonth()+'-'+d.getDate()};
const feita=(n,titulo,fim,extra)=>({id:'SOL-'+n,titulo,tipo:'dem',motivo:'Outro',prio:'norm',est:600,de:{s:'PCP',p:null},para:{s:'CNC',p:null},desc:'x',status:'done',criado:fim-2*HOUR,iniciado:fim-HOUR,fim,
  atraso_avisado:false,pausas:[],eventos:[{t:fim-2*HOUR,ev:'created',quem:'Escritório',nota:''}],comentarios:[],anexos:[],...(extra||{})});
const ativaC=(n,titulo,prazo)=>({id:'SOL-'+n,titulo,tipo:'dem',motivo:'Outro',prio:'norm',est:60,de:{s:'PCP',p:null},para:{s:'CNC',p:null},desc:'x',status:'prog',criado:prazo-HOUR,iniciado:prazo-HOUR+MIN,fim:null,prazo_em:prazo,
  atraso_avisado:false,pausas:[],eventos:[{t:prazo-HOUR,ev:'created',quem:'Escritório',nota:''}],comentarios:[],anexos:[]});
async function fronteiras(tz,y,m,d,rot){
  process.env.TZ=tz;
  const fake=L(y,m-1,d,12),J=jan(fake),real=Date.now();
  const alvo=[['M0',J.mes[0]],['M1',J.mes[0]-1],['M2',J.mes[1]-1],['M3',J.mes[1]],['W0',J.semana[0]],['W1',J.semana[0]-1],['W2',J.semana[1]-1],['W3',J.semana[1]],['D0',J.dia[0]],['D1',J.dia[0]-1],['D2',J.dia[1]-1],['D3',J.dia[1]]];
  const dems=alvo.map(([tag,t],i)=>feita(3001+i,tag,t));
  for(let i=0;i<5;i++)dems.push(feita(3101+i,'C'+i,J.dia[0]+10*HOUR+i*MIN));
  dems.push(ativaC(3201,'ATR',J.dia[0]+9*HOUR));
  const itens=dems.map(x=>({titulo:x.titulo,t:x.status==='done'?x.fim:x.prazo_em,ativa:x.status!=='done'}));
  const dir=novaPasta('F');semeia(dir,real,dems);const S=await startServer(dir);
  const R=rot+' ['+tz+' '+y+'-'+dd2(m)+'-'+dd2(d)+'] ';
  try{
    const a=await boot(S.port,{fake});
    if(!await entraAdm(a)){ok(false,R+'Administrador não entrou');a.close();return}
    const {$,$$,until,click,txt}=a;
    const horasDia0=Math.round((J.dia[1]-J.dia[0])/HOUR),chk=(c,m)=>horasDia0===25?bug('V-07',c,m+' [dia de 25 h: a lateral e a visão Dia usam inicio+24 h e perdem a última hora]'):ok(c,m),bugNd=(id,c,m)=>new Date(fake).getDay()===0?ok(true,m+' (domingo: o primeiro dia da semana é hoje)'):bug(id,c,m);
    const dentro=w=>itens.filter(x=>x.t>=w[0]&&x.t<w[1]);
    const tem=(w,tag)=>dentro(w).some(x=>x.titulo===tag);
    click('.dm-tab[data-v=cal]');
    ok(await until(()=>$('.cal-grid')),R+'Calendário abre no mês');
    // ----- mês
    const cells=()=>$$('.cal-day');
    const ini=J.mes[0],primeiro=new Date(ini).getDay(),diasMes=Math.round((J.mes[1]-J.mes[0])/DAY);
    ok(txt('.cal-tit')===MESES[new Date(fake).getMonth()]+' de '+y,R+'título do mês: '+txt('.cal-tit'));
    ok(cells().length===42&&cells().slice(0,primeiro).every(c=>c.classList.contains('cal-out'))&&!cells()[primeiro].classList.contains('cal-out'),R+'42 células; as '+primeiro+' antes do dia 1 são do mês anterior');
    const noMes=cells().filter(c=>!c.classList.contains('cal-out'));
    ok(noMes.length===new Date(y,m,0).getDate(),R+'o mês tem '+new Date(y,m,0).getDate()+' dias na grade: '+noMes.length);
    ok(cells().filter(c=>c.classList.contains('cal-today')).length===1&&cells().find(c=>c.classList.contains('cal-today')).querySelector('.cal-dn').textContent===String(d),R+'hoje marcado no dia '+d);
    ok(cells().filter(c=>c.classList.contains('cal-we')).length===12&&cells().filter(c=>c.classList.contains('cal-we')).every(c=>[0,6].includes(new Date(+c.dataset.v).getDay())),R+'12 células de fim de semana, todas sáb/dom');
    const porDia={};for(const x of dentro(J.mes))porDia[diaK(x.t)]=(porDia[diaK(x.t)]||0)+1;
    const bateCont=cells().every(c=>{const k=+c.dataset.v,n=(porDia[diaK(k)]||0),dentroDoMes=k>=J.mes[0]&&k<J.mes[1],esp=dentroDoMes?n:0,s=c.querySelector('.dm-s');return (s?+s.textContent:0)===esp&&c.querySelectorAll('.cal-chip').length===Math.min(3,esp)});
    ok(bateCont,R+'cada célula conta os itens do dia dela (fim da concluída, prazo da ativa); fora do mês nada aparece');
    ok(tem(J.mes,'M0')&&!tem(J.mes,'M1')&&tem(J.mes,'M2')&&!tem(J.mes,'M3'),R+'(oráculo) 1º ms do mês entra, o último ms do mês anterior não; último ms do mês entra, o 1º do seguinte não');
    const celM0=cells().find(c=>+c.dataset.v===J.mes[0]),celM2=cells().find(c=>+c.dataset.v===L(y,m-1,diasMes));
    ok(celM0&&celM0.querySelector('.cal-chip span')&&[...celM0.querySelectorAll('.cal-chip span')].some(s=>s.textContent==='M0')||(celM0&&+celM0.querySelector('.dm-s').textContent>3),R+'o item do 1º ms do mês está na célula do dia 1');
    ok(celM2&&+celM2.querySelector('.dm-s').textContent===(porDia[diaK(L(y,m-1,diasMes))]||0),R+'o item do último ms do mês está na célula do último dia');
    // "+ n mais" e lateral do dia
    const hoje=cells().find(c=>c.classList.contains('cal-today')),nHoje=porDia[diaK(J.dia[0])]||0;
    ok(nHoje>3&&hoje.querySelector('.cal-more')&&hoje.querySelector('.cal-more').textContent==='+ '+(nHoje-3)+' mais',R+'"+ n mais" no dia cheio: '+(hoje.querySelector('.cal-more')||{}).textContent+' (esperado + '+(nHoje-3)+' mais)');
    ok(/Clique num dia para ver/.test(txt('.cal-side')),R+'sem dia escolhido, a lateral orienta');
    click(hoje.querySelector('.cal-more'));
    chk(await until(()=>$('.cal-day.cal-sel')&&$$('.cal-list .dm-card').length===nHoje),R+'"+ n mais" seleciona o dia e a lateral lista os '+nHoje+' itens: '+$$('.cal-list .dm-card').length);
    chk(/solicitaç/.test(txt('.cal-side .dm-ph .dm-s'))&&$$('.cal-dens span').length===4&&$$('.cal-dens b').map(b=>+b.textContent).reduce((x,y2)=>x+y2,0)===nHoje,R+'a lateral tem as quatro faixas e somam '+nHoje);
    ok($$('.cal-dens .cal-pk').length===1,R+'uma faixa de pico destacada');
    // resumo
    const sum=$$('.cal-sum span').map(s=>s.textContent);
    const nAtr=itens.filter(x=>x.ativa&&x.t>=J.mes[0]&&x.t<J.mes[1]&&x.t<Math.max(real,fake)).length;
    ok(sum[0]===dentro(J.mes).length+' no período'&&sum[1]===nAtr+' atrasada'+(nAtr===1?'':'s')&&sum[2]===(itens.some(x=>!x.ativa&&x.t>=J.mes[0]&&x.t<J.mes[1])?'100% no prazo':'— no prazo'),R+'resumo: '+sum.join(' | '));
    // navegação ‹ › e "Este mês"
    const t0=txt('.cal-tit');
    for(let k=1;k<=13;k++){click('[data-act=calnav][data-v="-1"]');const dd=new Date(y,m-1-k,1);if(!await until(()=>txt('.cal-tit')===MESES[dd.getMonth()]+' de '+dd.getFullYear())){ok(false,R+'‹ '+k+' vezes: título '+txt('.cal-tit')+' (esperado '+MESES[dd.getMonth()]+' de '+dd.getFullYear()+')');break}if(k===13)ok(true,R+'‹ 13 vezes recua um ano e um mês sem pular nem repetir mês')}
    ok($$('.cal-day').length===42&&$$('.cal-today').length===0,R+'no passado: 42 células, nenhum "hoje"');
    const hs=a.w.__reqs.filter(r=>r.rest==='historico');
    const ant=jan(L(y,m-1-13,15));
    ok(hs.length>0&&hs[hs.length-1].body.ate===ant.mes[1]&&hs[hs.length-1].body.de===ant.mes[0]-31*DAY,R+'mês passado pede o arquivo morto com 31 dias de folga antes: '+JSON.stringify(hs[hs.length-1]&&hs[hs.length-1].body));
    click('[data-act=calnav][data-v="0"]');ok(await until(()=>txt('.cal-tit')===t0),R+'"Este mês" volta');
    const nh=a.w.__reqs.filter(r=>r.rest==='historico').length;
    for(let k=1;k<=13;k++){click('[data-act=calnav][data-v="1"]');const dd=new Date(y,m-1+k,1);if(!await until(()=>txt('.cal-tit')===MESES[dd.getMonth()]+' de '+dd.getFullYear())){ok(false,R+'› '+k+': título '+txt('.cal-tit'));break}if(k===13)ok(true,R+'› 13 vezes avança sem pular mês')}
    ok(a.w.__reqs.filter(r=>r.rest==='historico').length===nh,R+'meses futuros não pedem o arquivo morto');
    click('[data-act=calnav][data-v="0"]');await until(()=>txt('.cal-tit')===t0);
    // ----- semana
    click('[data-act=calmode][data-v=semana]');
    ok(await until(()=>$('.cal-week')&&$$('.cal-col').length===7),R+'Semana: sete colunas');
    ok(txt('.cal-tit')===fDD(J.semana[0])+' a '+fDD(J.semana[1]-1),R+'título da semana: '+txt('.cal-tit')+' (esperado '+fDD(J.semana[0])+' a '+fDD(J.semana[1]-1)+')');
    ok($$('.cal-wh span:not(.cal-tcol)').map(s=>s.textContent.replace(/\s+/g,' ')).join()===[0,1,2,3,4,5,6].map(i=>{const t=L(y,m-1,d-new Date(fake).getDay()+i);return DOWS[new Date(t).getDay()]+' '+fDD(t)}).join(),R+'cabeçalho: dom a sáb com a data de cada um: '+$$('.cal-wh span:not(.cal-tcol)').map(s=>s.textContent).join());
    const blocos=()=>$$('.cal-blk').map(b=>b.querySelector('.cal-bn').textContent).sort().join();
    const esperadoS=dentro(J.semana).map(x=>x.titulo).sort().join();
    ok(blocos()===esperadoS,R+'a semana mostra só o que cai entre dom 00:00 (incluído) e o dom seguinte 00:00 (excluído): '+blocos()+' vs '+esperadoS);
    ok(tem(J.semana,'W0')&&!tem(J.semana,'W1')&&tem(J.semana,'W2')&&!tem(J.semana,'W3'),R+'(oráculo) fronteiras da semana');
    ok($$('.cal-col.cal-today').length===1&&$$('.cal-col').findIndex(c=>c.classList.contains('cal-today'))===new Date(fake).getDay(),R+'a coluna de hoje é a do dia da semana certo');
    ok($$('.cal-now').length===0||$$('.cal-now').length===1,R+'linha do agora, no máximo uma');
    const lat=txt('.cal-side .dm-ph h3');
    bugNd('V-03',lat===DOWS[new Date(fake).getDay()]+', '+fDD(fake),R+'na Semana a lateral deveria abrir no dia de hoje (ou no escolhido); mostra "'+lat+'"');
    click('[data-act=calmode][data-v=dia]');
    ok(await until(()=>$('.cal-week')&&$$('.cal-col').length===1),R+'Dia: uma coluna');
    ok(txt('.cal-tit')===DOWS[new Date(fake).getDay()]+', '+fDD(fake),R+'título do dia: '+txt('.cal-tit'));
    chk(blocos()===dentro(J.dia).map(x=>x.titulo).sort().join()&&tem(J.dia,'D0')&&!tem(J.dia,'D1')&&tem(J.dia,'D2')&&!tem(J.dia,'D3'),R+'o dia vai de 00:00 (incluído) a 00:00 do seguinte (excluído): '+blocos());
    chk($$('.cal-list .dm-card').length===dentro(J.dia).length&&txt('.cal-side .dm-ph h3')===DOWS[new Date(fake).getDay()]+', '+fDD(fake),R+'lateral do dia lista os '+dentro(J.dia).length+' itens');
    ok($$('.cal-blk.cal-cut').length>=2,R+'o item das 00:00 e o das 23:59 saem da faixa 6h–22h e vêm marcados como cortados: '+$$('.cal-blk.cal-cut').length);
    click('[data-act=calnav][data-v="-1"]');
    ok(await until(()=>txt('.cal-tit')===DOWS[new Date(L(y,m-1,d-1)).getDay()]+', '+fDD(L(y,m-1,d-1))),R+'‹ no Dia recua um dia: '+txt('.cal-tit'));
    ok(blocos()===dentro([J.dia[0]-DAY>L(y,m-1,d-1)?J.dia[0]-DAY:L(y,m-1,d-1),J.dia[0]]).map(x=>x.titulo).sort().join(),R+'o dia anterior mostra o que cabe nele (D1 = último ms de ontem): '+blocos());
    click('[data-act=calnav][data-v="0"]');await until(()=>txt('.cal-tit')===DOWS[new Date(fake).getDay()]+', '+fDD(fake));
    click('[data-act=calmode][data-v=mes]');await until(()=>$('.cal-grid'));
    // ----- Cronoanálise: as janelas do cronograma
    click('.dm-tab[data-v=crono]');
    ok(await until(()=>$('[data-act=crwin]')),R+'Cronoanálise abre');
    const pedido=()=>a.w.__reqs.filter(r=>r.rest==='cronograma').pop();
    const cr=async(modo,win,dias,rotulo)=>{
      const n0=a.w.__reqs.filter(r=>r.rest==='cronograma').length;
      click('[data-act=crwin][data-v='+modo+']');
      const pediu=await until(()=>a.w.__reqs.filter(r=>r.rest==='cronograma').length>n0);
      const b=pedido()&&pedido().body;
      ok(pediu&&b&&b.de===win[0]&&b.ate===win[1],R+rotulo+': a janela pedida é a local ('+(b&&fDD(b.de))+' a '+(b&&fDD(b.ate))+')');
      return b;
    };
    const bS=await cr('semana',J.semana,7,'Semana');
    ok(await until(()=>$$('.cr-axis .cr-d').length===7),R+'eixo da semana: 7 dias');
    await until(()=>$$('.dm-grow').length>0);
    const gnow=$$('.dm-gnow').map(e=>e.style.left);
    bug('V-05',gnow.length===0||gnow.every(l=>l!=='100%'&&l!=='0%'),R+'o instante atual está fora da janela mostrada; a linha "Agora" não deveria ser desenhada (a tela a cola na borda: '+[...new Set(gnow)].join('/')+')');
    ok(bS&&bS.ate-bS.de===(Math.round((J.semana[1]-J.semana[0])/HOUR))*HOUR,R+'(a janela da semana tem '+Math.round((bS.ate-bS.de)/HOUR)+' h)');
    const bM=await cr('mes',J.mes,diasMes,'Mês');
    const horasMes=Math.round((J.mes[1]-J.mes[0])/HOUR);
    if(horasMes>31*24){
      bug('V-01',await until(()=>$$('.cr-axis .cr-d').length===diasMes,3000),R+'no mês de '+diasMes+' dias com '+horasMes+' h (horário de verão acaba nele) o servidor recusa a janela ("Período de até 31 dias") e a tela fica em "Carregando o cronograma…": '+txt('.cr-scroll, .dm-loading')+' | '+a.toast());
    }else{
      ok(await until(()=>$$('.cr-axis .cr-d').length===diasMes),R+'eixo do mês: '+diasMes+' dias');
      ok(!/Período|⚠/.test(a.toast()),R+'janela do mês aceita pelo servidor ('+horasMes+' h)');
    }
    const bD=await cr('dia',J.dia,1,'Dia');
    const horasDia=Math.round((J.dia[1]-J.dia[0])/HOUR);
    if(horasMes<=31*24)await until(()=>$('.dm-gtrack'));
    if(horasDia!==24){
      await until(()=>$('.dm-gtrack'));
      bug('V-04',$('.dm-gtrack')&&$('.dm-gtrack').style.getPropertyValue('--dm-gcols')===String(horasDia),R+'dia de '+horasDia+' h (mudança de horário): a grade do dia usa '+($('.dm-gtrack')&&$('.dm-gtrack').style.getPropertyValue('--dm-gcols'))+' colunas e deveria usar '+horasDia);
    }else ok(await until(()=>$('.dm-gtrack')&&$('.dm-gtrack').style.getPropertyValue('--dm-gcols')==='24'),R+'dia de 24 h: 24 colunas');
    a.close();
  }finally{killTree(S.proc)}
}

/* ================= CALENDÁRIO: SOMBREADO E FILTRO DE SETOR ================= */
async function calendarioHorario(a,port){
  const {$,$$,until,click,txt}=a;
  const poeSec=v=>{const s=a.d.getElementById('dm-calSec');s.value=v;s.dispatchEvent(new a.w.Event('change',{bubbles:true}))};
  const v0=await direto(port,'vista',{});
  const hoje=new Date(),isoDia=t=>{const d=new Date(t);return d.getFullYear()+'-'+dd2(d.getMonth()+1)+'-'+dd2(d.getDate())};
  const quarta=L(hoje.getFullYear(),hoje.getMonth(),hoje.getDate()-hoje.getDay()+3);
  const salva=async ag=>{const v=(await direto(port,'vista',{})).agenda.v;const r=await direto(port,'agenda/salvar',{agenda:{ativa:true,v,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[],...ag}});await a.w.NestLocal.views.demandas.refresh();return r};
  click('.dm-tab[data-v=cal]');await until(()=>$('.cal-grid'));
  click('[data-act=calmode][data-v=semana]');await until(()=>$('.cal-week'));
  ok($$('.cal-off').length===14&&/O horário de serviço está desligado: a faixa sombreada é só uma referência \(07h às 17h\)/.test(txt('.cal-week .dm-note')),'horário desligado: referência fixa 07h–17h (2 faixas por coluna) e a nota explica');
  ok(v0.agenda.ativa===false,'(conferência: horário desligado na vista)');
  const r=await salva({});ok(r.__status===200,'liguei o horário (seg–sex, 07–12 e 13–17)');
  ok(await until(()=>$$('.cal-off').length===17&&/A faixa sombreada é fora do horário de serviço/.test(txt('.cal-week .dm-note'))),'horário ligado: 17 faixas (dom e sáb inteiros = 1 cada; seg–sex = antes, almoço e depois = 3 cada): '+$$('.cal-off').length);
  const nota=txt('.cal-week .dm-note');
  await salva({feriados:[{data:isoDia(quarta),nome:'Feriado de teste',setores:[]}]});
  ok(await until(()=>$$('.cal-off').length===15),'feriado na quarta desta semana: a coluna dela vira uma faixa só (17 - 3 + 1 = 15): '+$$('.cal-off').length);
  await salva({feriados:[{data:isoDia(quarta),nome:'Feriado só do ESP',setores:['ESP']}]});
  ok(await until(()=>$$('.cal-off').length===17),'feriado de outro setor não sombreia a visão geral');
  poeSec('ESP');ok(await until(()=>$$('.cal-off').length===15),'filtro ESP: o feriado do ESP entra no sombreado dele (15)');
  await salva({setores:{ESP:{dias:[1,2],turnos:[['08:00','12:00']]}},feriados:[]});
  ok(await until(()=>$$('.cal-off').length===9),'filtro ESP com horário próprio (seg e ter 08–12): 2×2 + 5 = 9 faixas: '+$$('.cal-off').length);
  poeSec('CNC');ok(await until(()=>$$('.cal-off').length===17),'filtro CNC (sem horário próprio) volta ao padrão: 17');
  poeSec('');
  ok($('#dm-calSec').value==='','filtro de setor volta a "Todos"');
  click('[data-act=calmode][data-v=mes]');await until(()=>$('.cal-grid'));
  ok(!$('.cal-off'),'visão Mês não tem sombreado');
  ok(nota.length>0,'(nota da semana lida)');
  const v=(await direto(port,'vista',{})).agenda.v;await direto(port,'agenda/salvar',{agenda:{ativa:false,v,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[]}});await a.w.NestLocal.views.demandas.refresh();
  click('[data-act=calmode][data-v=semana]');
  ok(await until(()=>$$('.cal-off').length===14),'desligar o horário volta à referência fixa (14)');
  click('[data-act=calmode][data-v=mes]');
}

/* ================= CRONOANÁLISE ================= */
async function cronoanalise(a,port,now){
  const {$,$$,until,click,txt}=a;
  const ck=()=>$$('.dm-ck').map(x=>x.querySelector('b').textContent),sub=()=>$$('.dm-ck').map(x=>x.querySelector('small').textContent);
  const per=()=>$$('[data-act=period]').map(b=>b.textContent+(b.getAttribute('aria-pressed')==='true'?'*':'')).join();
  const doApi=async dias=>direto(port,'crono',{dias});
  const doDom=(k)=>[String(k.abertas),String(k.concluidas),k.pct_prazo==null?'—':k.pct_prazo+'%',durTxt(k.espera),durTxt(k.execucao),durTxt(k.pausado)];
  click('.dm-tab[data-v=crono]');
  ok(await until(()=>$('[data-act=period]')&&$$('.dm-ck').length===6),'Cronoanálise abre com seis KPIs');
  ok(per()==='Hoje,7 dias*,30 dias','períodos Hoje / 7 dias / 30 dias, com 7 dias marcado: '+per());
  ok($$('.dm-ck').map(x=>x.querySelector('span').textContent.replace(/^\S+ /,'')).join()==='Solicitações,Concluídas,Cumprimento do prazo,Espera média,Execução média,Tempo em pausa','rótulos dos KPIs');
  // 7 dias: números calculados à mão a partir dos dados semeados
  ok(ck().join()==='13,4,50%,10 min,3h 14min,0 min','7 dias: 13 abertas, 4 concluídas, 50% no prazo, espera 10 min, execução 3h 14min, pausa 0 min: '+ck());
  ok(sub().join()==='abertas no período,de 13 abertas,2 de 4 no prazo,até alguém iniciar,estimado 11h 13min,média por solicitação','subtítulos dos KPIs: '+sub());
  const rows=()=>$$('.dm-crow').map(r=>[...r.children].filter(c=>!c.classList.contains('dm-cbar')).map(c=>c.textContent.replace(/\s+/g,' ').trim()).join('|'));
  ok(rows().join('//')==='ESPEspumação|1|10 min|1h 30min|30 min|0%//CNCCorte CNC|3|10 min|3h 48min|14h 47min|67%','tabela por setor, pior cumprimento primeiro: '+rows().join('//'));
  ok($$('.dm-crow .dm-stack').length===2&&$$('.dm-crow .dm-est').length===2,'cada setor tem a barra empilhada e o traço do estimado');
  const ins=$$('.dm-ins').map(x=>x.textContent.replace(/\s+/g,' ').trim());
  ok(ins.length===4&&/Maior espera para iniciar.*Corte CNC leva em média 10 min/.test(ins[0])&&/Menor cumprimento de prazo.*Corte CNC cumpre apenas 67% dos prazos/.test(ins[1])&&/Execução vs\. estimado.*executa em 26% do tempo estimado/.test(ins[2])&&/Motivo mais comum.*Outro: 5 solicitações \(38%\)/.test(ins[3]),'quatro insights (setor com 3+ concluídas, mais o motivo): '+ins.join(' // '));
  ok($$('.dm-par').map(p=>p.querySelector('.dm-pl').textContent+'='+p.querySelector('b').textContent+'/'+p.querySelector('small').textContent).join()==='Outro=5/38%,Falta de material=2/54%,Quebra de máquina=2/69%,Retrabalho=2/85%,Ajuste de planejamento=1/92%,Solicitação do cliente=1/100%','motivos em Pareto (acumulado sobre as 13 abertas): '+$$('.dm-par').map(p=>p.querySelector('.dm-pl').textContent+'='+p.querySelector('b').textContent+'/'+p.querySelector('small').textContent));
  ok($$('.dm-rk').map(r=>r.textContent.replace(/\s+/g,' ').trim()).join('//').replace(/CNC|ESP/g,'').replace(/\s+/g,' ')==='1º C Carlos 67% // 2º F Fernanda 0%'.replace(/\s+/g,' ')||$$('.dm-rk').length===2,'ranking: Carlos (3, 67%) antes de Fernanda (1, 0%): '+$$('.dm-rk').map(r=>r.textContent.replace(/\s+/g,' ').trim()).join(' // '));
  ok($$('.dm-rk')[0].textContent.includes('Carlos')&&/^1º/.test($$('.dm-rk')[0].textContent)&&$$('.dm-rk')[1].textContent.includes('Fernanda'),'ordem do ranking');
  // 13 h
  ok($('[data-act=crwin][data-v="13h"]').getAttribute('aria-pressed')==='true','linha do tempo abre em 13 h');
  const linhas=()=>$$('.dm-grow').map(g=>g.dataset.id);
  ok([...linhas()].sort().join()==='SOL-1001,SOL-1002,SOL-1003,SOL-1004,SOL-1005,SOL-1006,SOL-1007,SOL-1008,SOL-1009'&&linhas().join()==='SOL-1009,SOL-1001,SOL-1008,SOL-1007,SOL-1003,SOL-1005,SOL-1004,SOL-1002,SOL-1006','13 h: as 7 em aberto e as 2 concluídas nas últimas 10 h, por data de criação: '+linhas());
  ok(!$('.hs-fora')&&!$('.cr-off')&&!$$('.dm-legend').some(l=>/Fora do horário de serviço/.test(l.textContent)),'horário desligado: sem aviso, sem sombreado, sem legenda');
  ok($$('.dm-gnow').length===9&&$$('.dm-gd').length>0,'linha do agora em cada linha e marcas de prazo dentro da janela');
  // períodos: a tela mostra o que a rota devolve
  for(const [dias,rot] of [[1,'Hoje'],[30,'30 dias'],[7,'7 dias']]){
    const j=await doApi(dias);
    click('[data-act=period][data-v="'+dias+'"]');
    ok(await until(()=>per().includes(rot+'*')&&ck().join()===doDom(j.kpis).join()),rot+': os seis KPIs da tela são os da rota: '+ck()+' vs '+doDom(j.kpis));
    if(dias===1)ok(+ck()[0]<=13&&+ck()[0]===SEEDS.filter(s=>now-s[9]*MIN>=j.desde).length,'Hoje conta só as criadas desde a meia-noite local ('+ck()[0]+')');
    if(dias===30)ok(ck().join()==='13,4,50%,10 min,3h 14min,0 min','30 dias = 7 dias (tudo foi criado nas últimas 36 h; o arquivo de 40 dias fica fora)');
  }
  // janelas multidia
  const dEsp=SEEDS.map(s=>({id:'SOL-'+s[0],setor:s[7][0],pes:s[7][1],ativa:isAct(s),feita:s[8]==='done',criado:now-s[9]*MIN,fim:s[11]==null?null:now-s[11]*MIN,prazo:now-s[9]*MIN+s[5]*MIN}));
  const incl=(w,agora)=>dEsp.filter(d=>(d.ativa||d.feita)&&((d.prazo>=w[0]&&d.prazo<=w[1])||(d.criado<w[1]&&(d.fim==null?agora:d.fim)>w[0])));
  const grupos=(lista,por)=>{const m={};for(const d of lista){const k=por==='pessoa'?d.pes:d.setor;(m[k]=m[k]||[]).push(d)}
    return Object.entries(m).map(([k,l])=>({k,n:l.length,at:l.filter(x=>x.ativa).length})).sort((x,y)=>y.at-x.at||y.n-x.n||String(x.k).localeCompare(String(y.k)))};
  const J=jan(Date.now()),agora=Date.now();
  click('[data-act=crwin][data-v=semana]');
  ok(await until(()=>$('.cr-axis')&&$$('.dm-grow').length>0),'Semana monta');
  const esp=incl(J.semana,agora);
  ok(linhas().sort().join()===esp.map(d=>d.id).sort().join(),'Semana: entram as ativas e as concluídas que cruzam a janela (canceladas não): '+linhas().length+' linhas');
  ok(!linhas().includes('SOL-1012')&&!linhas().includes('SOL-1013'),'canceladas ficam fora');
  const gl=()=>$$('.cr-grp .dm-glab').map(g=>g.querySelector('b').textContent+':'+g.querySelector('.dm-gt').textContent);
  const gs=grupos(esp,'setor');
  ok(gl().join()===gs.map(g=>SET.find(s=>s[0]===g.k)[1]+':'+g.n+' '+(g.n===1?'solicitação':'solicitações')+' · '+g.at+' ativa'+(g.at===1?'':'s')).join(),'grupos por setor: ativas desc, n desc, sigla; com "n solicitações · k ativas": '+gl());
  ok($$('.dm-gtrack').length>0&&$$('.cr-we').length===2*$$('.dm-gtrack').length,'Semana: sábado e domingo hachurados em cada linha ('+$$('.cr-we').length+' faixas em '+$$('.dm-gtrack').length+' linhas)');
  ok($$('.cr-axis .cr-d').map(s=>s.textContent.replace(/\s+/g,' ')).join()===[0,1,2,3,4,5,6].map(i=>{const t=L(new Date().getFullYear(),new Date().getMonth(),new Date().getDate()-new Date().getDay()+i);return DOWS[new Date(t).getDay()]+' '+fDD(t)}).join(),'eixo com os sete dias (dom a sáb)');
  click('[data-act=crby][data-v=pessoa]');
  ok(await until(()=>$('[data-act=crby][data-v=pessoa]').getAttribute('aria-pressed')==='true'&&/Fila do setor/.test(txt('.cr-scroll'))),'Por pessoa: a fila sem responsável é um grupo "Fila do setor"');
  const gp=grupos(esp,'pessoa');
  ok($$('.cr-grp').length===gp.length,'um grupo por responsável + a fila: '+$$('.cr-grp').length+' esperado '+gp.length);
  click('[data-act=crby][data-v=setor]');await until(()=>$('[data-act=crby][data-v=setor]').getAttribute('aria-pressed')==='true');
  click('[data-act=crnav][data-v="-1"]');
  ok(await until(()=>$$('.cr-axis .cr-today').length===0&&!$('.dm-loading')),'‹ na Semana: a semana passada não tem "hoje"');
  click('[data-act=crnav][data-v="1"]');
  ok(await until(()=>$$('.cr-axis .cr-today').length===1),'› volta à semana de hoje');
  click('[data-act=crnav][data-v="0"]');
  // mês: 28, 29, 30 e 31 dias, nenhuma recusada pelo servidor
  click('[data-act=crwin][data-v=mes]');
  const R=a.w.__reqs;let semErro=true;const vistos=new Set();
  for(let k=0;k<=16;k++){
    const hoje=new Date(),alvo=new Date(hoje.getFullYear(),hoje.getMonth()+k,1),dias=new Date(alvo.getFullYear(),alvo.getMonth()+1,0).getDate();
    if(k>0)click('[data-act=crnav][data-v="1"]');
    const carregou=await until(()=>$$('.cr-axis .cr-d').length===dias&&/Cronograma · /.test(txt('.dm-panel:has(.cr-tools) .dm-ph h3')));
    vistos.add(dias);if(!carregou||/Período|⚠/.test(a.toast())){semErro=false;ok(false,'mês +'+k+' ('+dias+' dias): não carregou '+a.toast());break}
  }
  ok(semErro&&[...vistos].sort().join()==='28,29,30,31','navegar 17 meses para a frente (inclui fev/2028 bissexto): janelas de 28, 29, 30 e 31 dias aceitas: '+[...vistos].sort());
  const pm=R.filter(r=>r.rest==='cronograma').map(r=>(r.body.ate-r.body.de)/DAY);
  ok(Math.max(...pm)<=31,'nenhuma janela pedida passa de 31 dias: máx '+Math.max(...pm));
  click('[data-act=crnav][data-v="0"]');
  ok(await until(()=>$$('.cr-axis .cr-today').length===1),'"Este mês" volta ao mês de hoje');
  ok(await until(()=>$$('.dm-gtrack').length>0)&&$$('.cr-we').length===$$('.dm-gtrack').length*(()=>{const d=new Date(),n=new Date(d.getFullYear(),d.getMonth()+1,0).getDate();let c=0;for(let i=1;i<=n;i++)if([0,6].includes(new Date(d.getFullYear(),d.getMonth(),i).getDay()))c++;return c})(),'Mês: um hachurado por sábado/domingo em cada linha');
  click('[data-act=crwin][data-v=dia]');
  ok(await until(()=>/Cronograma · \d\d\/\d\d$/.test(txt('.dm-panel:has(.cr-tools) .dm-ph h3'))&&$('.dm-gtrack')&&$$('.cr-axis .cr-d').length===0),'Dia: título com a data e eixo de horas');
  click('[data-act=crwin][data-v="13h"]');await until(()=>!$('.cr-scroll'));
  // horário de serviço: aviso e sombreado
  const ag=async(extra)=>{const v=(await direto(port,'vista',{})).agenda.v;const r=await direto(port,'agenda/salvar',{agenda:{ativa:true,v,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[],...extra}});await a.w.NestLocal.views.demandas.refresh();return r};
  const hojeISO=new Date().getDay()||7,semHoje=[1,2,3,4,5,6,7].filter(x=>x!==hojeISO);
  await ag({padrao:{dias:semHoje,turnos:[['07:00','17:00']]}});
  ok(await until(()=>$('.hs-fora')&&/Fora do horário de serviço: os prazos e as contagens estão parados/.test(txt('.hs-fora'))),'horário ligado e fechado agora: aviso "Fora do horário de serviço"');
  ok(await until(()=>$$('.dm-grow .cr-off').length>0&&$$('.dm-legend').some(l=>/Fora do horário de serviço/.test(l.textContent))),'13 h: faixas cr-off e item na legenda');
  await ag({padrao:{dias:semHoje,turnos:[['07:00','17:00']]},setores:{ESP:{dias:[1,2,3,4,5,6,7],turnos:[['00:00','23:59']]}}});
  const larg=id=>[...$('.dm-grow[data-id='+id+'] .cr-off')?$$('.dm-grow[data-id='+id+'] .cr-off'):[]].reduce((t,e)=>t+parseFloat(e.style.width),0);
  ok(await until(()=>larg('SOL-1004')>=0&&$$('.dm-grow[data-id=SOL-1001] .cr-off').length>0&&larg('SOL-1001')>larg('SOL-1004')+5),'sombreado por setor: o CNC (fechado hoje) tem faixa larga; o ESP (horário próprio quase 24 h) quase nada: '+larg('SOL-1001').toFixed(1)+'% vs '+larg('SOL-1004').toFixed(1)+'%');
  await ag({padrao:{dias:[1,2,3,4,5,6,7],turnos:[['00:00','23:59']]}});
  ok(await until(()=>!$('.hs-fora')),'horário ligado e aberto agora: sem o aviso');
  const v=(await direto(port,'vista',{})).agenda.v;await direto(port,'agenda/salvar',{agenda:{ativa:false,v,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[]}});await a.w.NestLocal.views.demandas.refresh();
  ok(await until(()=>!$('.hs-fora')&&!$('.cr-off')),'desligar o horário tira o aviso e o sombreado');
  // clicar numa linha abre a solicitação
  click('.dm-grow[data-id=SOL-1004]');
  ok(await until(()=>$('#dm-drawer').classList.contains('dm-on')&&/SOL-1004/.test(txt('#dm-drawer'))),'clicar numa linha da linha do tempo abre a solicitação');
  click('#dm-drawer [data-act=close]');
}

/* ================= VOLUMES (tetos de linhas) ================= */
async function volumes(port,now){
  const a=await boot(port);
  ok(await entraAdm(a),'[volumes] Administrador entra');
  const {$,$$,until,click,txt}=a;
  const poe=(id,v)=>{const s=$('#'+id);s.value=v;s.dispatchEvent(new a.w.Event('change',{bubbles:true}))};
  ok(await until(()=>txt('.dm-kpi[data-v=new] b')==='130'&&txt('.dm-kpi[data-v=urg] b')==='10'),'[volumes] KPIs: 130 abertas, 10 urgentes: '+txt('.dm-kpi[data-v=new] b'));
  ok($$('.dm-al:not(.dm-bkav)').length===7&&/120 itens exigem atenção/.test(txt('.dm-grid2 .dm-panel .dm-s')),'[volumes] Atenção mostra no máximo 7 de 120 (10 urgentes + 110 sem aceite há 25+ min): '+$$('.dm-al:not(.dm-bkav)').length+' / '+txt('.dm-grid2 .dm-panel .dm-s'));
  ok($$('.dm-feed li').length===10,'[volumes] Atividade ao vivo: 10 eventos de 14: '+$$('.dm-feed li').length);
  ok(await until(()=>txt('#dm-map .dm-tile[data-v=CNC] .dm-tnum b')==='130'),'[volumes] tile do CNC: 130');
  click('.dm-tab[data-v=sol]');await until(()=>$('#dm-fSt'));
  ok(txt('.dm-count')==='450 solicitações'&&txt('.dm-col[data-st=new] .dm-n')==='130'&&$$('.dm-col[data-st=new] .dm-card').length===60,'[volumes] quadro: a coluna Abertas conta 130 e mostra 60 cartões: '+$$('.dm-col[data-st=new] .dm-card').length);
  click('[data-act=view][data-v=list]');await until(()=>$$('.dm-lrow').length>0);
  ok($$('.dm-lrow').length===90,'[volumes] lista: no máximo 90 linhas: '+$$('.dm-lrow').length);
  click('.dm-tab[data-v=hist]');await until(()=>$('#dm-hq'));
  ok($$('.dm-hrow').length===400&&txt('.dm-count')==='450 de 450','[volumes] histórico: 400 linhas e o contador diz "450 de 450": '+$$('.dm-hrow').length+' / '+txt('.dm-count'));
  poe('dm-hSt','done');ok(await until(()=>txt('.dm-count')==='320 de 450'&&$$('.dm-hrow').length===320),'[volumes] filtrando concluídas: 320');
  poe('dm-hSt','');
  click('.dm-tab[data-v=crono]');await until(()=>$('[data-act=crwin]'));
  for(const modo of ['semana','dia','mes']){
    click('[data-act=crwin][data-v='+modo+']');
    ok(await until(()=>$$('.dm-grow').length===120),'[volumes] '+modo+': o servidor corta em 120 linhas: '+$$('.dm-grow').length);
    ok(/Muitas solicitações nesta janela: mostrando as 120 mais urgentes/.test(txt('.cr-scroll')+txt('.dm-panel:has(.cr-tools)')),'[volumes] '+modo+': aviso de corte');
    const ids=$$('.dm-grow').map(g=>g.dataset.id);
    ok(Array.from({length:10},(_,i)=>'SOL-'+(2001+i)).every(id=>ids.includes(id)),'[volumes] '+modo+': as 10 urgentes ficam dentro do corte');
    const ativas=ids.filter(id=>+id.slice(4)<3001).length;
    bug('V-06',ativas===120,'[volumes] '+modo+': com 130 em aberto e 120 vagas, o corte deveria ficar só com solicitações em aberto; entraram '+(120-ativas)+' concluídas (o corte usa o "prazo mais perto" também para as concluídas)');
  }
  click('[data-act=crby][data-v=pessoa]');
  ok(await until(()=>$$('.dm-grow').length===120&&/Fila do setor/.test(txt('.cr-scroll'))),'[volumes] Por pessoa também corta em 120');
  a.close();
}

/* ================= TELA SEM DADOS ================= */
async function vazio(port){
  const a=await boot(port);
  ok(await entraAdm(a),'[vazio] Administrador entra numa base vazia');
  const {$,$$,until,click,txt}=a;
  ok(await until(()=>$$('.dm-kpi b').length===6&&$$('.dm-kpi b').every(b=>b.textContent==='0')),'[vazio] Painel: seis KPIs em zero');
  ok(/Nenhum setor ativo\. Cadastre em Administração\./.test(txt('#dm-map'))&&/Nada crítico no momento/.test(txt('.dm-grid2'))&&/Sem eventos ainda/.test(txt('.dm-feed')),'[vazio] Painel: mapa, atenção e feed vazios com aviso');
  ok(/0 setores/.test(txt('.dm-mapsum')),'[vazio] resumo do mapa: 0 setores');
  click('.dm-tab[data-v=sol]');ok(await until(()=>txt('.dm-count')==='0 solicitações'&&$$('.dm-col .dm-empty').length===4),'[vazio] Solicitações: 0 e aviso nas 4 colunas');
  click('[data-act=view][data-v=list]');ok(await until(()=>/Nenhuma solicitação encontrada/.test(txt('.dm-lbox'))),'[vazio] lista vazia');
  ok($$('#dm-fSec option').length===1&&$$('#dm-fSt option').length===8,'[vazio] filtro de setor só com "Todos"');
  click('.dm-tab[data-v=hist]');ok(await until(()=>txt('.dm-count')==='0 de 0'&&/Nenhuma relação registrada/.test(txt('.dm-rels'))&&/Nenhuma demanda nesse recorte/.test(txt('.dm-lbox'))),'[vazio] Histórico: "0 de 0", sem relações, sem demandas');
  a.d.getElementById('dm-hArq').value='365';a.d.getElementById('dm-hArq').dispatchEvent(new a.w.Event('change',{bubbles:true}));
  ok(await until(()=>a.w.__reqs.some(r=>r.rest==='historico'))&&txt('.dm-count')==='0 de 0','[vazio] arquivo morto vazio: continua "0 de 0"');
  click('.dm-tab[data-v=cal]');ok(await until(()=>$('.cal-grid')),'[vazio] Calendário abre');
  ok($$('.cal-sum span').map(s=>s.textContent).join()==='0 no período,0 atrasadas,— no prazo'&&$$('.cal-chip').length===0,'[vazio] resumo: 0 no período, 0 atrasadas, "— no prazo"');
  click('[data-act=calmode][data-v=dia]');ok(await until(()=>/Nada neste dia/.test(txt('.cal-side'))&&/0 solicitações/.test(txt('.cal-side'))),'[vazio] Dia: "Nada neste dia." e 0 solicitações');
  click('[data-act=calmode][data-v=mes]');
  click('.dm-tab[data-v=crono]');ok(await until(()=>$$('.dm-ck').length===6),'[vazio] Cronoanálise abre');
  ok($$('.dm-ck b').map(b=>b.textContent).join()==='0,0,—,—,—,—','[vazio] KPIs: 0, 0, "—" (sem divisão por zero), médias "—": '+$$('.dm-ck b').map(b=>b.textContent));
  ok(!$('.dm-ins')&&/Sem solicitações concluídas neste período/.test(txt('.dm-crow, .dm-panel'))&&$$('.dm-panel .dm-empty').length>=3,'[vazio] sem insights e com os avisos "Sem ..."');
  ok(/Sem solicitações no intervalo/.test(txt('.dm-panel:has(.cr-tools)')),'[vazio] 13 h: "Sem solicitações no intervalo."');
  for(const m of ['dia','semana','mes']){click('[data-act=crwin][data-v='+m+']');ok(await until(()=>$('.cr-scroll')&&/Sem solicitações no intervalo/.test(txt('.cr-scroll'))),'[vazio] '+m+': sem linhas, com aviso')}
  for(const p of [1,30,7]){click('[data-act=period][data-v="'+p+'"]');ok(await until(()=>$('[data-act=period][data-v="'+p+'"]').getAttribute('aria-pressed')==='true'&&$$('.dm-ck').length===6),'[vazio] período '+p+' carrega')}
  a.close();
}

/* ================= EXECUÇÃO ================= */
(async()=>{
  const now=Date.now();
  const dA=novaPasta('A');
  semeia(dA,now,SEEDS.map(s=>monta(now,s)),[arq(now,901,'Arquivo 40 dias',40,'PCP','CNC','done'),arq(now,902,'Arquivo 100 dias',100,'PCP','ESP','done'),arq(now,903,'Arquivo 400 dias',400,'CNC','PCP','done')]);
  const A=await startServer(dA);
  try{
    const adm=await boot(A.port);
    ok(await entraAdm(adm),'Administrador entra');
    await painel(adm,now);
    await solicitacoes(adm,now);
    await historico(adm,now);
    await verComo(adm);
    await operador(A.port);
    await calendarioHorario(adm,A.port);
    await cronoanalise(adm,A.port,now);
    adm.close();
    // volumes: 130 abertas + 320 concluídas, para os tetos (60 cartões, 90 linhas, 400 linhas, 120 do cronograma, 7 da atenção, 10 do feed)
    const dB=novaPasta('B'),B=[];
    for(let i=0;i<130;i++)B.push([2001+i,'Pedido em massa '+(i+1),'dem','Outro',i<10?'urg':'norm',600,['PCP',null],['CNC',null],'new',5+i,null,null]);
    for(let i=0;i<320;i++)B.push([3001+i,'Concluída antiga '+(i+1),'dem','Outro','norm',600,['PCP',null],['ESP',null],'done',4000+i,3990+i,3000+i]);
    semeia(dB,now,B.map(s=>monta(now,s)));
    const SB=await startServer(dB);await volumes(SB.port,now);killTree(SB.proc);
    // base vazia
    const SC=await startServer(novaPasta('C'));await vazio(SC.port);killTree(SC.proc);
    // fronteiras de mês, semana e dia em vários fusos (o aparelho e o servidor usam o fuso do computador)
    const tz0=process.env.TZ;
    for(const [tz,y,m,d] of [['America/Sao_Paulo',2026,3,18],['America/Sao_Paulo',2026,2,1],['America/Sao_Paulo',2028,2,29],['America/New_York',2026,3,8],['Europe/Berlin',2026,10,25],['Pacific/Auckland',2026,4,5]])
      await fronteiras(tz,y,m,d,'[fuso]');
    if(tz0===undefined)delete process.env.TZ;else process.env.TZ=tz0;
  }catch(e){console.log('FAIL exceção: '+(e&&e.stack||e));process.exitCode=1}
  finally{procs.forEach(killTree);setTimeout(()=>{dirs.forEach(d=>{try{fs.rmSync(d,{recursive:true,force:true})}catch(e){/* temporário */}});
    console.log(`\nRESUMO: ${NPASS} passaram, ${NFAIL} falharam, ${NBUG} bugs conhecidos reproduzidos, ${NFIXED} bugs conhecidos que passaram`);process.exit(process.exitCode||0)},300)}
})();
