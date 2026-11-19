const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// QA das regras de tempo na tela (sessão E): paridade JS×Python com tests/vetores_qa.json e o cronômetro, o "Faltam /
// Atrasada há", a barra de SLA e a atenção do ADM contra o servidor REAL (servidor.py) com relógio falso e pasta temporária.
// rodar: node tests/check_tempo.js   (PYTHON=... troca o interpretador; jsdom vem de tests/node_modules)
// Casos que expõem bug confirmado saem como "KNOWN-BUG" e não reprovam; se passarem, saem como "FIXED?" (tirar a marca).
const REPO=path.resolve(__dirname,'..');
const FILHO=process.argv[2]==='--paridade';
const base=FILHO?'':fs.mkdtempSync(path.join(os.tmpdir(),'tempo-check-')),data=path.join(base,'data'),CLK=path.join(base,'relogio.txt');
if(!FILHO)fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,FALHAS=0,BUGS=0,PASSOU=0;
const MIN=60000,HORA=3600000;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(c)PASSOU++;else{FALHAS++;process.exitCode=1}};
const bug=(c,m)=>{if(c){console.log('FIXED? '+m+' (o bug parece corrigido: tirar a marca known-bug)');PASSOU++}else{console.log('KNOWN-BUG '+m);BUGS++}};
const at=(y,mo,d,h=0,mi=0,s=0,ms=0)=>new Date(y,mo-1,d,h,mi,s,ms).getTime();   // instante local, como o servidor e a tela veem
const setClock=t=>fs.writeFileSync(CLK,String(t));
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}
// servidor real com o relógio da API lendo um arquivo: o teste decide que horas são (o tick de fundo não roda aqui)
function startServer(){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor;m=servidor.api_mod();m._agora=lambda:int(open(${JSON.stringify(CLK)}).read());s=servidor.Server(('127.0.0.1',0),servidor.Handler);print(s.server_address[1],flush=True);s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='';p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+)\s/.exec(out);if(m&&!PORT){PORT=+m[1];res(p)}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
const direto=(rest,body)=>fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
// a página com Date.now congelado em w.__T: o "agora" da tela = agora do servidor + (w.__T − w.__T da hora da vista)
async function boot(){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/',{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
    w.__T=Date.now();w.Date.now=()=>w.__T;
  }});
  const w=dom.window;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  return w;
}
const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};

/* ---------- 1. paridade JS × Python: tests/vetores_qa.json ---------- */
// Cada TZ roda num processo filho com a TZ no ambiente (trocar process.env.TZ no meio do caminho não volta ao fuso do
// sistema no Node do Windows e desalinharia o resto do teste, que fala com o servidor no fuso da máquina).
const VETORES=JSON.parse(fs.readFileSync(path.join(__dirname,'vetores_qa.json'),'utf8'));
async function paridadeFilho(alias){
  const w=await boot(),hs=w.NestLocal.views.demandas.hs,casos=VETORES.casos.filter(c=>c.tz===alias);let certos=0;const erros=[];
  const dia=w.eval('(new Date(2026,2,9)-new Date(2026,2,8))/36e5');
  ok(dia===(alias==='dst'?23:24),'TZ "'+alias+'" ('+VETORES.tz[alias]+') aplicada no jsdom: o dia 8/3/2026 tem '+dia+' h');
  const tt=(c,k,off)=>at(...c[k])+(off||0);
  for(const c of casos){
    const g=hs.grade(VETORES.agendas[c.agenda],c.setor),a=tt(c,'de',c.de_off);let got;
    if(c.op==='util')got=hs.util(g,a,tt(c,'ate',c.ate_off));
    else if(c.op==='expediente')got=hs.expediente(g,a,tt(c,'ate',c.ate_off)).map(([x,y])=>[x-a,y-a]);
    else got=hs.aberto(g,a);
    if(JSON.stringify(got)===JSON.stringify(c.esp))certos++;
    else if(erros.length<8)erros.push(c.agenda+'/'+c.setor+' '+c.op+' '+JSON.stringify(c.de)+(c.de_off?'+'+c.de_off:'')+(c.ate?'→'+JSON.stringify(c.ate):'')+': JS '+JSON.stringify(got).slice(0,90)+' × Python '+JSON.stringify(c.esp).slice(0,90));
  }
  erros.forEach(e=>console.log('  divergência: '+e));
  ok(certos===casos.length&&casos.length>=500,'paridade JS×Python ('+alias+'): '+certos+' de '+casos.length+' vetores batem (util, expediente e aberto)');
  w.close();
}
function paridade(){
  for(const alias of Object.keys(VETORES.tz)){
    const r=spawnSync(process.execPath,[__filename,'--paridade',alias],{env:{...process.env,TZ:VETORES.tz[alias],TEMPO_PORT:String(PORT)},encoding:'utf8',timeout:240000});
    process.stdout.write(r.stdout||'');if(r.stderr)process.stderr.write(r.stderr);
    PASSOU+=((r.stdout||'').match(/^PASS /gm)||[]).length;
    if(r.status!==0){FALHAS++;process.exitCode=1;console.log('FAIL o processo da paridade ('+alias+') saiu com código '+r.status)}
  }
}

/* ---------- 2. limites das contas puras no JS ---------- */
function limites(w){
  const hs=w.NestLocal.views.demandas.hs,seg=at(2026,11,9),agCom={ativa:true,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[]};
  const g=hs.grade(agCom,'CNC');
  const par=(b,d,u)=>hs.util(g,seg+b*HORA-1,seg+b*HORA)===d&&hs.util(g,seg+b*HORA,seg+b*HORA+1)===u;
  ok(par(7,0,1)&&par(12,1,0)&&par(13,0,1)&&par(17,1,0),'JS: abertura conta e fecho não nas quatro bordas do comercial (±1 ms)');
  ok(hs.aberto(g,seg+7*HORA)&&!hs.aberto(g,seg+7*HORA-1)&&hs.aberto(g,seg+12*HORA-1)&&!hs.aberto(g,seg+12*HORA),'JS: aberto() — abertura inclusa, fecho fora');
  ok(hs.util(g,seg+9*HORA,seg+9*HORA)===0&&hs.util(g,seg+10*HORA,seg+9*HORA)===0&&hs.util(null,5,9)===4&&hs.util(null,9,5)===0,'JS: janela vazia ou invertida vale 0; sem grade é o tempo corrido');
  const d1={ativa:true,padrao:{dias:[1,2,3,4,5,6,7],turnos:[['07:00','08:00']]},setores:{},feriados:[]},g1=hs.grade(d1,'CNC');
  ok(Math.round(hs.util(g1,seg,seg+3700*86400000)/HORA)===3700&&Math.round(hs.util(g1,seg,seg+3701*86400000)/HORA)===3700&&Math.round(hs.util(g1,seg,seg+36500*86400000)/HORA)===3700,'JS: teto de 3700 dias na medida (3700, 3701 e um século dão 3700 h)');
  const noite={...agCom,padrao:{dias:[1,2,3,4,5],turnos:[['22:00','06:00']]},feriados:[{data:'2026-11-10',nome:'x',setores:[]}]},gn=hs.grade(noite,'CNC');
  ok(hs.util(gn,at(2026,11,10),at(2026,11,10,6))===6*HORA&&hs.util(gn,at(2026,11,10,6),at(2026,11,11,12))===0,'JS: feriado vale para o dia em que o turno começa (noite de terça some, a madrugada de terça fica)');
  const fer={...agCom,feriados:[{data:'2026-11-16',nome:'geral',setores:[]},{data:'2026-11-17',nome:'CNC',setores:['CNC']}]};
  ok(hs.util(hs.grade(fer,'CNC'),at(2026,11,16),at(2026,11,18))===0&&hs.util(hs.grade(fer,'ESP'),at(2026,11,16),at(2026,11,18))===9*HORA,'JS: feriado geral e feriado só do CNC (o ESP trabalha na terça)');
  const ex=hs.expediente(g,seg,seg+86400000);
  ok(JSON.stringify(ex)===JSON.stringify([[seg+7*HORA,seg+12*HORA],[seg+13*HORA,seg+17*HORA]]),'JS: expediente do dia = dois turnos');
}

/* ---------- 3. a tela: cronômetro, "Faltam / Atrasada há", SLA e atenção (relógio falso) ---------- */
async function tela(){
  const SEX1630=at(2026,11,13,16,30);setClock(SEX1630);
  const cria=(titulo,est)=>direto('demanda/criar',{titulo,tipo:'dem',motivo:'Outro',prio:'norm',est,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
  for(const [id,n] of [['PCP','Planejamento'],['CNC','Corte CNC']])await direto('setor/salvar',{modo:'novo',id,nome:n,icone:'⚙️',cor:'#3B82F6',rev:0});
  const pv=await direto('pessoa/salvar',{modo:'novo',nome:'Carlos',setor:'CNC',codigo:'1234',rev:0}),carlos=pv.pessoas[pv.pessoas.length-1].id;
  const tk=(await direto('entrar',{pessoa:carlos,codigo:'1234'})).tk;
  const ag=await direto('agenda/salvar',{agenda:{ativa:true,v:0,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]},setores:{},feriados:[]}});
  ok(ag.agenda&&ag.agenda.ativa&&ag.agenda.v===1,'horário de serviço ligado (versão 1) pela API');
  await cria('Demanda A de 60 minutos',60);await cria('Demanda B de 30 minutos',30);await cria('Demanda C de 4 horas',240);
  const A='SOL-1001',B='SOL-1002',C='SOL-1003';
  const dA=(await direto('vista',{})).demandas.find(d=>d.id===A);
  ok(dA&&dA.prazo===at(2026,11,16,7,30)&&dA.agenda_v===1,'A (sex 16:30 + 60 min úteis): prazo segunda 07:30');
  setClock(at(2026,11,13,16,40));await direto('demanda/aceitar',{id:C,tk});
  setClock(at(2026,11,13,16,50));await direto('demanda/pausar',{id:C,tk,motivo:'Máquina parada',obs:''});

  const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();
  await until(()=>$('.dm-tab[data-v=painel]'));
  // relógio da página e do servidor andam juntos (T = W − OFF; o servidor lê W): qualquer nova vista dá o mesmo "agora"
  const OFF=at(2026,11,13,16,50)-w.__T,refresh=async()=>{await w.NestLocal.views.demandas.refresh()};
  await refresh();
  const irPara=async W=>{setClock(W);w.__T=W-OFF;await sleep(1300)};   // o tick de 1 s da tela repinta o "Faltam"
  const tab=async k=>{$('.dm-tab[data-v='+k+']').click();await sleep(120)};
  await tab('sol');
  const rem=id=>{const e=$('[data-rem="'+id+'"]');return e?e.textContent:null},card=id=>$('.dm-card[data-id="'+id+'"]');
  const esperaTxt=async(id,txt,ms=3500)=>until(()=>rem(id)===txt,ms);
  const rotulo=(id,txt)=>id+' "'+txt+'"';
  async function confere(quando,esperado,estadosNaoLate=[]){
    for(const [id,txt] of Object.entries(esperado))ok(await esperaTxt(id,txt),quando+': '+rotulo(id,txt)+(rem(id)===txt?'':' (veio "'+rem(id)+'")'));
    for(const id of estadosNaoLate)ok(card(id)&&card(id).dataset.st!=='late',quando+': '+id+' ainda não está atrasada');
  }
  await confere('16:50 sex',{[A]:'Faltam 40 min',[B]:'Faltam 10 min'},[A,B]);
  // atenção: "Sem aceite" aos 25 min úteis exatos (criadas às 16:30 → 16:55)
  const tags=()=>$$('.dm-al').map(e=>e.querySelector('b').textContent+':'+[...e.querySelectorAll('.dm-tg')].map(t=>t.textContent).join('|'));
  const atencao=async W=>{await irPara(W);await tab('painel');await tab('sol');await tab('painel');return tags()};
  let t=await atencao(at(2026,11,13,16,54,59,999));
  ok(!t.some(x=>x.startsWith(A+':')&&/Sem aceite/.test(x)),'16:54:59,999: sem "Sem aceite" em A ('+t.join(' ; ')+')');
  t=await atencao(at(2026,11,13,16,55));
  ok(t.some(x=>x.startsWith(A+':')&&/Sem aceite há 25 min/.test(x))&&t.some(x=>x.startsWith(B+':')&&/Sem aceite há 25 min/.test(x)),'16:55:00: A e B ganham "Sem aceite há 25 min" ('+t.join(' ; ')+')');
  await tab('sol');
  await irPara(at(2026,11,13,17,0));
  await confere('17:00:00,000 sex',{[A]:'Faltam 30 min',[B]:'Faltam 0 min'},[A,B]);
  await irPara(at(2026,11,13,17,0,0,1));
  await confere('17:00:00,001 sex',{[A]:'Faltam 30 min'},[A]);
  await tab('painel');await tab('sol');
  ok(card(B).dataset.st==='late','1 ms depois do prazo: B vira "atrasada" na tela (data-st=late)');
  bug(rem(B)==='Atrasada há 0 min','B5: B atrasada (pílula vermelha) mas o texto diz "'+rem(B)+'" quando o atraso útil é 0 (hsDif devolve -0 e -0 >= 0)');
  await irPara(at(2026,11,14,12,0));
  await confere('sábado 12:00',{[A]:'Faltam 30 min'},[A]);
  bug(rem(B)==='Atrasada há 0 min','B5: sábado 12:00, B atrasada desde sexta 17:00, mostra "'+rem(B)+'"');
  // gaveta: o cronômetro (tempo decorrido em tempo útil) e a barra de SLA
  card(A).click();await until(()=>$('#dm-drawer.dm-on'));
  const met=(k,id)=>{const e=$('#dm-drawer [data-met="'+k+'"][data-id="'+id+'"]');return e&&e.textContent};
  ok(met('total',A)==='30 min'&&met('wait',A)==='30 min'&&met('exec',A)==='0 min','sábado: cronômetro de A parado em 30 min úteis (decorrido '+met('total',A)+', espera '+met('wait',A)+')');
  const sla=id=>{const e=$('#dm-drawer [data-sla="'+id+'"]');return e&&{w:e.style.width,c:e.parentElement.className}};
  ok(sla(A)&&parseFloat(sla(A).w)===50&&/dm-ok/.test(sla(A).c),'sábado: barra de SLA de A em 50,0% ('+JSON.stringify(sla(A))+')');
  $('#dm-drawer [data-act=close]').click();await sleep(100);
  // pausa aberta de C atravessando o fim de semana: "Pausada há 20 min" só na segunda 07:10
  t=await atencao(at(2026,11,16,7,9,59,999));
  ok(!t.some(x=>x.startsWith(C+':')&&/Pausada/.test(x)),'seg 07:09:59,999: C ainda sem "Pausada" ('+t.join(' ; ')+')');
  t=await atencao(at(2026,11,16,7,10));
  ok(t.some(x=>x.startsWith(C+':')&&/Pausada há 20 min/.test(x)),'seg 07:10:00: C ganha "Pausada há 20 min" (10 min de sexta + 10 de segunda) ('+t.join(' ; ')+')');
  await tab('sol');
  await irPara(at(2026,11,16,7,15));
  await confere('seg 07:15',{[A]:'Faltam 15 min',[B]:'Atrasada há 15 min'},[A]);
  await irPara(at(2026,11,16,7,30));
  await confere('seg 07:30:00,000',{[A]:'Faltam 0 min'},[A]);
  await irPara(at(2026,11,16,7,30,0,1));
  await confere('seg 07:30:00,001',{[A]:'Atrasada há 0 min',[B]:'Atrasada há 30 min'});
  await tab('painel');await tab('sol');
  ok(card(A).dataset.st==='late','1 ms depois do prazo gravado (seg 07:30): A atrasada na tela');
  t=await atencao(at(2026,11,16,8,30));
  ok(t.some(x=>x.startsWith(A+':')&&/Atrasada há 1h/.test(x))&&t.some(x=>x.startsWith(B+':')&&/Atrasada há 1h 30min/.test(x)),'seg 08:30: atenção "Atrasada há 1h" (A) e "1h 30min" (B), em tempo útil ('+t.join(' ; ')+')');
  await tab('sol');
  await confere('seg 08:30',{[A]:'Atrasada há 1h',[B]:'Atrasada há 1h 30min'});
  card(C).click();await until(()=>$('#dm-drawer.dm-on'));
  ok(met('total',C)==='2h'&&met('wait',C)==='10 min'&&met('exec',C)==='10 min'&&met('pause',C)==='1h 40min','seg 08:30: cronômetro de C — espera 10 min, execução 10 min, pausa 1h 40min (veio '+['wait','exec','pause','total'].map(k=>met(k,C)).join(' / ')+')');
  ok(sla(C)&&parseFloat(sla(C).w)===50,'seg 08:30: SLA de C = 120/240 = 50,0% ('+JSON.stringify(sla(C))+')');
  $('#dm-drawer [data-act=close]').click();await sleep(100);
  // almoço: o atraso de B não anda entre 12:00 e 13:00
  await irPara(at(2026,11,16,12,0));
  const a1=rem(B);
  await irPara(at(2026,11,16,12,59,59,999));
  ok(rem(B)==='Atrasada há 5h'&&a1==='Atrasada há 5h','almoço (12:00 a 12:59:59,999): "Atrasada há" de B parado em 5h ('+a1+' → '+rem(B)+')');
  await irPara(at(2026,11,16,13,30));
  await confere('seg 13:30',{[B]:'Atrasada há 5h 30min'});

  // concluída fora do expediente depois do prazo: BUG B4 (texto "no prazo" × barra vermelha)
  setClock(at(2026,11,14,10,0));await direto('demanda/aceitar',{id:B,tk});await direto('demanda/concluir',{id:B,tk,nota:''});
  await refresh();await irPara(at(2026,11,14,10,0));await tab('painel');await tab('sol');
  const doneTxt=rem(B)||'';
  const barra=$('.dm-card[data-id="'+B+'"] .dm-sla');
  console.log('  B concluída sáb 10:00 (prazo sex 17:00): texto "'+doneTxt+'", barra "'+(barra&&barra.className)+'"');
  bug(!(/no prazo/.test(doneTxt)&&barra&&/dm-bad/.test(barra.className)),'B4: concluída depois do prazo fora do expediente — o cartão diz "no prazo" e a barra de SLA fica vermelha (dm-bad)');
  w.close();
}

if(process.argv[2]==='--paridade'){
  PORT=+process.env.TEMPO_PORT;
  paridadeFilho(process.argv[3]).catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());
}else (async()=>{
  const srv=await startServer();
  try{
    paridade();
    const w=await boot();limites(w);w.close();
    await tela();
  }finally{killTree(srv);
    try{fs.rmSync(base,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+base)}}
  console.log('resumo: '+PASSOU+' conferências ok, '+FALHAS+' falhas, '+BUGS+' bug(s) conhecido(s)');
  console.log(process.exitCode?'houve falhas':'tudo certo (bugs conhecidos não reprovam)');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());
