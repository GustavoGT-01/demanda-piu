const {JSDOM,requestInterceptor}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// QA da área ACESSO E PERMISSÕES, na tela, contra o servidor REAL (servidor.py) com DEMANDAS_DATA temporário.
// rodar: NODE_PATH=<pasta com jsdom>/node_modules node tests/check_acesso.js   (PYTHON=... troca o interpretador)
// Um servidor só, com o acesso pela rede ligado: o pedido que leva o cabeçalho X-Teste-Rede conta como "de outro aparelho"
// (o servidor não conhece esse cabeçalho: só existe porque este script troca o Handler._remote no processo dele).
//   PC principal (sem cabeçalho) = papel "maquina"; aparelho do escritório = PIN completo; aparelho do chão = PIN operador.
// Bug confirmado e ainda aberto: kb(id, condição, texto) imprime KNOWN-BUG (sem reprovar); se a condição passar, imprime FIXED.
const REPO=path.resolve(__dirname,'..');
const base=fs.mkdtempSync(path.join(os.tmpdir(),'dem-acesso-')),data=path.join(base,'data');
fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,PIN='',PINOP='';
const BASE=()=>'http://127.0.0.1:'+PORT;
function startServer(){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor
o=servidor.Handler._remote
servidor.Handler._remote=lambda h:bool(h.headers.get('X-Teste-Rede')) or o(h)
servidor.NET_ON=True
c=servidor.net_config()
s=servidor.Server(('127.0.0.1',0),servidor.Handler)
print(s.server_address[1],c['pin'],c['pin_op'],flush=True)
s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='';p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+) (\d{6}) (\d{6})\s/.exec(out);if(m&&!PORT){PORT=+m[1];PIN=m[2];PINOP=m[3];res(p)}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ok=(c,m)=>{console.log((c?'PASS ':'FAIL ')+m);if(!c)process.exitCode=1};
const kb=(id,c,m)=>console.log((c?'FIXED     ':'KNOWN-BUG ')+id+' '+m);
const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
// pedido direto ao servidor: sem cabeçalho = o próprio PC (Escritório); com `rede` = outro aparelho com o cookie dado
const call=(rest,body,o={})=>fetch(BASE()+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json',...(o.rede?{'X-Teste-Rede':'1'}:{}),...(o.cookie?{Cookie:o.cookie}:{})},body:JSON.stringify(body)}).then(async r=>({st:r.status,t:await r.text()}));
const direto=async(rest,body,o)=>{const r=await call(rest,body,o);try{return JSON.parse(r.t)}catch(e){return{erro:r.t,st:r.st}}};
const GET=(p,o={})=>fetch(BASE()+p,{headers:{...(o.rede?{'X-Teste-Rede':'1'}:{}),...(o.cookie?{Cookie:o.cookie}:{})}}).then(async r=>({st:r.status,t:await r.text()}));
async function cookieDe(pin){
  const r=await fetch(BASE()+'/api/login',{method:'POST',redirect:'manual',headers:{'Content-Type':'application/x-www-form-urlencoded','X-Teste-Rede':'1'},body:'pin='+pin});
  return r.headers.get('set-cookie').split(';')[0];
}
// Abre a tela. cfg: {rede, cookie, eu: 'real'|'fail'|'hang'}. Devolve a janela; w.__net guarda o que a página pediu.
async function boot(cfg={}){
  const net={log:[],tks:[],gate:null,solta:null};
  net.gate=new Promise(r=>{net.solta=r});
  const hdr=()=>({...(cfg.rede?{'X-Teste-Rede':'1'}:{}),...(cfg.cookie?{Cookie:cfg.cookie}:{})});
  const loader={interceptors:[requestInterceptor(request=>fetch(request.url,{headers:hdr()}))]};   // os scripts da página saem com o cookie e a marca de "outro aparelho"
  const html=await fetch(BASE()+'/',{headers:hdr()}).then(r=>r.text());
  const dom=new JSDOM(html,{url:BASE()+'/',runScripts:'dangerously',resources:loader,pretendToBeVisual:true,beforeParse(w){
    w.__net=net;
    w.fetch=async(u,o={})=>{
      if(u==='/api/eu'){if(cfg.eu==='fail')throw new TypeError('Failed to fetch');if(cfg.eu==='hang')await net.gate}
      const r=await fetch(new URL(u,BASE()).href,{...o,headers:{...(o.headers||{}),...hdr()}});
      net.log.push({m:o.method||'GET',u:String(u),st:r.status,body:o.body});
      if(/\/entrar$/.test(String(u))&&r.ok){try{net.tks.push((await r.clone().json()).tk)}catch(e){}}
      return r;
    };
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.__erros=[];w.addEventListener('error',e=>{w.__erros.push(e.message);console.log('PAGE ERROR',e.message)});
    w.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={}}resume(){this.state='running'}createOscillator(){return{type:'',frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
  }});
  const w=dom.window;
  if(cfg.eu!=='hang')for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  else await sleep(800);
  return w;
}
const helpers=w=>{const d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  const click=s=>{const e=typeof s==='string'?$(s):s;if(!e)throw new Error('não achei '+s);e.click()};
  const digita=(s,v)=>{const e=$(s);e.value=v;e.dispatchEvent(new w.Event('input',{bubbles:true}))};
  const toast=()=>($('#dm-toast')||{}).textContent||'';
  const erro=()=>($('#dm-lg-fld .dm-em')||{}).textContent||'';
  const chip=()=>($('#dm-uchip')||{}).textContent||'';
  const logado=()=>$('#dm-login').hidden;
  const setor=async id=>{click('[data-act=lgs][data-v='+id+']');await sleep(30)};
  const usuario=async nome=>{click($$('.dm-lguser').find(b=>b.textContent.includes(nome)));await sleep(30)};
  const entra=async(sid,nome,cod)=>{await setor(sid);await usuario(nome);digita('#dm-lg-code',cod);click(d.querySelector('#dm-lgform [type=submit]'))};
  // todos os ids que a tela do operador mostra, passando por Recebidas (3 filtros) e Enviadas (2)
  const idsNaTela=async()=>{const s=new Set();
    for(const [tab,fs_] of [['recv',['mine','pend','done']],['sent',['pend','done']]]){
      click('[data-act=tab][data-v='+tab+']');await sleep(40);
      for(const f of fs_){click('[data-act=opf][data-v='+f+']');await sleep(40);$$('.dm-ocard[data-id]').forEach(c=>s.add(c.dataset.id))}}
    return s};
  const nomes=()=>$$('.dm-lguser').map(b=>b.lastElementChild.textContent.trim());   // sem a inicial do avatar
  return{d,$,$$,click,digita,toast,erro,chip,logado,setor,usuario,entra,idsNaTela,nomes};
};
const cartoes=async w=>{const h=helpers(w);return[...(await h.idsNaTela())].sort()};
const igual=(a,b)=>JSON.stringify([...a].sort())===JSON.stringify([...b].sort());

async function semear(){
  const adm=(r,b)=>direto(r,b);
  for(const [id,nome,ic] of [['PCP','Planejamento','🗂️'],['CNC','Corte CNC','⚙️'],['ESP','Espumação','🧰'],['VAZ','Setor sem gente','🏷️'],['INA','Setor inativo','🔧']])
    await adm('setor/salvar',{modo:'novo',id,nome,icone:ic,cor:'#3B82F6',rev:0});
  const pes={};
  for(const [nome,setor,cod] of [['Helena','PCP','1111'],['Carlos','CNC','2222'],['Bruno','CNC','3333'],['Fernanda','ESP','4444'],['Dani Inativa','CNC','6666'],['Ivo','INA','5555']]){
    const v=await adm('pessoa/salvar',{modo:'novo',nome,setor,codigo:cod,rev:0});pes[nome]=v.pessoas[v.pessoas.length-1].id}
  let v=await adm('pessoa/ativar',{id:pes['Dani Inativa'],rev:(await direto('vista',{})).pessoas.find(p=>p.id===pes['Dani Inativa'])._rv});
  v=await direto('vista',{});await adm('setor/ativar',{id:'INA',rev:v.setores.find(s=>s.id==='INA')._rv});
  const tk={};
  for(const [n,c] of [['Helena','1111'],['Carlos','2222'],['Bruno','3333'],['Fernanda','4444']])tk[n]=(await adm('entrar',{pessoa:pes[n],codigo:c})).tk;
  const ped=async(tkk,para,titulo,prio='norm')=>{const b={titulo,tipo:'dem',motivo:'Outro',prio,est:60,para:{s:para,p:null},desc:''};
    if(!tkk)b.de_s='PCP';else b.tk=tkk;const r=await adm('demanda/criar',b);return r.demandas.map(d=>d.id).sort((a,b)=>a.slice(4)-b.slice(4)).pop()};
  const d={};
  d.hc=await ped(tk.Helena,'CNC','Helena para CNC');d.ce=await ped(tk.Carlos,'ESP','Carlos para ESP');
  d.he=await ped(tk.Helena,'ESP','Helena para ESP');d.ec=await ped(null,'CNC','Escritorio para CNC');d.be=await ped(tk.Bruno,'ESP','Bruno para ESP');
  d.urg=await ped(tk.Helena,'CNC','Urgente da Helena para CNC','urg');   // gera um aviso para o Escritório (aud "adm")
  return{pes,tk,d};
}

(async()=>{
  const srv=await startServer();
  try{
    const S=await semear();
    // ---------- 1. PC principal: tela "Quem é você?" ----------
    let w=await boot();let h=helpers(w);
    ok(await until(()=>h.$('#dm-login .dm-lgcard')&&!h.$('#dm-login').hidden),'PC principal abre em "Quem é você?"');
    ok(/Quem é você\?/.test(h.$('#dm-login h2').textContent)&&h.$('#dm-sub').textContent==='Identifique-se para ver as solicitações.','título e subtítulo da tela de entrada');
    ok(h.$('#dm-uchip').textContent.includes('Quem é você?')&&h.$('#dm-bell').disabled&&h.$('.dm-fab').hidden&&h.$('.dm-hdnew').hidden,'sem usuário: chip "Identifique-se", sino desabilitado, sem botão de nova solicitação');
    ok(h.$('#dm-tabs').children.length===0,'sem usuário: nenhuma aba');
    ok(await until(()=>h.$('[data-act=lgk][data-v=adm]')),'PC principal (maquina): a opção Administrador existe');
    ok(h.$('[data-act=lgk][data-v=op]').getAttribute('aria-pressed')==='true'&&h.$('[data-act=lgk][data-v=adm]').getAttribute('aria-pressed')==='false','começa em Operador');
    ok(h.$$('.dm-lgsec').map(b=>b.dataset.v).join()==='PCP,CNC,ESP','só os setores ativos que têm pessoa ativa (sem "Setor sem gente" nem o inativo)');
    ok(h.$$('.dm-lgsec').every(b=>b.getAttribute('aria-pressed')==='false')&&/Escolha o setor para ver os usuários\./.test(h.$('#dm-lgbody').textContent),'nenhum setor marcado; dica "Escolha o setor"');
    const cod=()=>h.$('#dm-lg-code');
    ok(cod().type==='password'&&cod().maxLength===4&&cod().getAttribute('inputmode')==='numeric'&&cod().getAttribute('autocomplete')==='off','campo do código: password, maxlength 4, teclado numérico, sem autocompletar');
    ok(h.$('.dm-eye').getAttribute('aria-label')==='Mostrar ou ocultar o código','botão do olho com rótulo acessível');
    ok(/Digite os 4 dígitos do seu código\./.test(h.erro()),'dica padrão do campo do código');
    // validações do botão Entrar, uma de cada vez
    const submit=()=>h.click('#dm-lgform [type=submit]');
    submit();ok(await until(()=>h.erro()==='Selecione o seu setor.'),'Entrar sem setor: "Selecione o seu setor."');
    ok(h.$('#dm-lg-fld').classList.contains('dm-err')&&h.$('#dm-lg-fld .dm-em').getAttribute('role')==='alert','a mensagem é um alerta e o campo fica vermelho');
    await h.setor('CNC');
    ok(h.$('[data-act=lgs][data-v=CNC]').getAttribute('aria-pressed')==='true'&&h.nomes().join()==='Carlos,Bruno','setor CNC: só Carlos e Bruno (a Dani inativa não aparece)');
    ok(h.erro()==='Digite os 4 dígitos do seu código.','trocar de setor limpa a mensagem de erro');
    submit();ok(await until(()=>h.erro()==='Selecione o seu nome.'),'Entrar sem nome: "Selecione o seu nome."');
    await h.usuario('Carlos');
    ok(h.$$('.dm-lguser').some(b=>b.textContent.includes('Carlos')&&b.getAttribute('aria-pressed')==='true')&&h.erro()==='Digite os 4 dígitos do seu código.'&&w.document.activeElement.id==='dm-lg-code','escolher o nome marca o botão, limpa o erro e leva o foco ao código');
    submit();ok(await until(()=>h.erro()==='Digite os 4 dígitos do seu código.'&&h.$('#dm-lg-fld').classList.contains('dm-err')),'Entrar sem código: pede os 4 dígitos (campo vermelho)');
    // limites do campo
    const casos=[['',''],['1','1'],['123','123'],['1234','1234'],['12345','1234'],['123456789','1234'],['12ab345','1234'],['abcd',''],['1 2 3','123'],['١٢٣٤','']];
    for(const [dig,esp] of casos){h.digita('#dm-lg-code',dig);ok(cod().value===esp,'campo do código: "'+dig+'" → "'+esp+'" (obtido "'+cod().value+'")')}
    h.digita('#dm-lg-code','123');submit();ok(await until(()=>h.erro()==='Digite os 4 dígitos do seu código.'),'3 dígitos: não vai ao servidor ("Digite os 4 dígitos...")');
    ok(!w.__net.log.some(l=>/entrar$/.test(l.u)),'(conferência: nenhum pedido de entrada saiu com dado inválido)');
    h.digita('#dm-lg-code','12');ok(!h.$('#dm-lg-fld').classList.contains('dm-err')&&h.erro()==='Digite os 4 dígitos do seu código.','digitar tira o vermelho e a mensagem de erro');
    // olho
    h.digita('#dm-lg-code','2222');
    h.click('.dm-eye');ok(cod().type==='text'&&cod().value==='2222'&&h.$('.dm-eye').textContent==='🙈','olho: mostra o código digitado');
    h.click('.dm-eye');ok(cod().type==='password'&&h.$('.dm-eye').textContent==='👁','olho de novo: oculta');
    // trocar de setor desmarca a pessoa
    await h.setor('ESP');ok(!h.$$('.dm-lguser').some(b=>b.getAttribute('aria-pressed')==='true')&&h.nomes().join()==='Fernanda','trocar de setor desmarca o nome e lista só o setor novo');
    await h.setor('CNC');
    // código errado e bloqueio (Carlos); Bruno segue livre
    for(let i=1;i<=5;i++){await h.usuario('Carlos');h.digita('#dm-lg-code','000'+i);submit();
      ok(await until(()=>h.erro()==='Código errado.'),'erro '+i+' de 5: "Código errado."');
      if(i===1)ok(cod().value===''&&w.document.activeElement.id==='dm-lg-code'&&!h.logado(),'código errado: campo limpo, foco no código, continua na tela de entrada');
      if(i===1)ok(h.$('#dm-lg-fld').classList.contains('dm-err'),'código errado: campo vermelho')}
    await h.usuario('Carlos');h.digita('#dm-lg-code','2222');submit();
    ok(await until(()=>h.erro()==='Bloqueado por 1 minuto: muitos códigos errados.'),'depois do 5º erro nem o código certo entra: "Bloqueado por 1 minuto..."');
    ok(h.logado()===false,'(conferência: ainda na tela de entrada)');
    await h.usuario('Bruno');h.digita('#dm-lg-code','3333');submit();
    ok(await until(()=>h.logado()&&/Olá, Bruno/.test(h.$('#dmboard').textContent)),'o bloqueio do Carlos não impede o Bruno');
    ok(/Bem-vindo\(a\), Bruno!/.test(h.toast()),'toast de boas-vindas');
    ok(h.chip().includes('Bruno')&&h.chip().includes('Corte CNC'),'chip do cabeçalho: nome e setor');
    ok(h.$$('#dm-tabs .dm-tab').map(b=>b.dataset.v).join()==='recv,sent','pessoa: só as abas Recebidas e Enviadas (sem Painel/Administração)');
    ok(!h.$('.dm-fab').hidden&&!h.$('.dm-hdnew').hidden&&!h.$('#dm-bell').disabled,'pessoa: botão de nova solicitação e sino liberados');
    ok(h.$('#dm-login').textContent==='','a tela de entrada some da árvore de acessibilidade');
    ok(Object.keys(w.localStorage).every(k=>!w.localStorage.getItem(k).includes(w.__net.tks[0]))&&w.document.cookie===''&&w.document.documentElement.innerHTML.indexOf(w.__net.tks[0])<0,'o tk não vai para localStorage, cookie nem para o HTML da página');
    // visão da pessoa: o que a tela mostra de Bruno
    const vBruno=await direto('vista',{tk:w.__net.tks[0]});
    const esperados=vBruno.demandas.map(x=>x.id);
    const naTela=await h.idsNaTela();
    ok([S.d.hc,S.d.ec,S.d.be].every(i=>esperados.includes(i))&&![S.d.ce,S.d.he].some(i=>esperados.includes(i)),'(conferência: o servidor entrega ao Bruno só destino CNC e o pedido dele)');
    ok([...naTela].every(i=>esperados.includes(i)),'tela do Bruno: nenhum pedido fora do que o servidor entregou');
    ok(![S.d.ce,S.d.he].some(i=>h.$('#dmboard').textContent.includes(i)),'tela do Bruno: não aparecem o pedido do Carlos (ESP) nem o da Helena para ESP');
    ok(naTela.has(S.d.be)&&naTela.has(S.d.hc)&&naTela.has(S.d.ec),'tela do Bruno: aparecem o dele (enviado) e os do setor CNC');
    // Quem é você? aberto com alguém dentro; Cancelar
    h.click('#dm-uchip');ok(await until(()=>h.$('#dm-mbox h2')&&h.$('#dm-mbox h2').textContent==='Quem é você?'),'chip abre o "Quem é você?" no meio da sessão');
    ok(/Bruno/.test(h.$('.dm-acct').textContent)&&/Você está aqui agora/.test(h.$('.dm-acct').textContent),'mostra quem está logado');
    ok(!!h.$('[data-act=logout]')&&!!h.$('[data-act=prefs]'),'botões Sair e Meus avisos presentes para a pessoa');
    h.click('[data-act=mclose]');await sleep(60);
    ok(!h.$('#dm-modal').classList.contains('dm-on')&&h.chip().includes('Bruno'),'Cancelar fecha sem mudar de usuário');
    // trocar de usuário com código errado: continua o atual, tk atual segue valendo
    h.click('#dm-uchip');await until(()=>h.$('#dm-lgform'));
    await h.usuario('Carlos');
    await sleep(60);
    ok(h.$$('.dm-lguser').find(b=>b.textContent.includes('Carlos')),'(conferência: Carlos aparece na troca)');
    h.digita('#dm-lg-code','2223');h.click('#dm-lgform [type=submit]');await sleep(60);
    ok(await until(()=>h.erro()==='Código errado.'||h.erro().startsWith('Bloqueado')),'troca com código errado dá erro dentro do diálogo');
    h.click('[data-act=mclose]');await sleep(60);
    ok(h.chip().includes('Bruno')&&(await direto('vista',{tk:w.__net.tks[0]})).papel==='pessoa','troca que falhou não derruba o usuário atual (tk do Bruno segue valendo)');
    // trocar de verdade: Bruno -> Fernanda
    h.click('#dm-uchip');await until(()=>h.$('#dm-lgform'));
    await h.setor('ESP');await h.usuario('Fernanda');h.digita('#dm-lg-code','4444');h.click('#dm-lgform [type=submit]');
    ok(await until(()=>h.chip().includes('Fernanda')&&!h.$('#dm-modal').classList.contains('dm-on')),'trocar de usuário: Fernanda entra');
    ok((await call('vista',{tk:w.__net.tks[0]})).st===401,'trocar de usuário revoga o tk do anterior (Bruno)');
    ok(/Olá, Fernanda/.test(h.$('#dmboard').textContent),'tela passa a ser da Fernanda');
    const naTelaF=await h.idsNaTela();
    ok(![S.d.hc,S.d.ec].some(i=>naTelaF.has(i))&&naTelaF.has(S.d.he)&&naTelaF.has(S.d.ce)&&naTelaF.has(S.d.be),'Fernanda (ESP) vê os 3 que vão para ESP e nenhum de CNC');
    // Sair
    const tkF=w.__net.tks[w.__net.tks.length-1];
    h.click('#dm-uchip');await until(()=>h.$('[data-act=logout]'));h.click('[data-act=logout]');
    ok(await until(()=>!h.logado()&&h.$('#dm-login .dm-lgcard')),'Sair: volta ao "Quem é você?"');
    ok((await call('vista',{tk:tkF})).st===401,'Sair revoga o tk no servidor');
    ok(h.$('#dm-tabs').children.length===0&&h.$('#dm-view').innerHTML===''&&h.$('#dm-bell').disabled,'depois de Sair: sem abas, sem conteúdo, sino desabilitado');
    ok(h.$('#dm-lg-code').value==='','depois de Sair: código vazio');
    console.log('OBS        depois de Sair a tela de entrada lembra o último setor/usuário: '+(h.$$('.dm-lguser').some(b=>b.getAttribute('aria-pressed')==='true')?'sim':'não')+' (comportamento atual, ver docs/qa/acesso.md)');
    // Administrador no PC principal
    h.click('[data-act=lgk][data-v=adm]');
    ok(h.$('[data-act=lgk][data-v=adm]').getAttribute('aria-pressed')==='true'&&!h.$('.dm-lgsec')&&!h.$('#dm-lg-code')&&/Disponível só no computador do escritório/.test(h.$('#dm-lgbody').textContent),'Administrador: some setor/usuário/código e aparece o aviso');
    submit();ok(await until(()=>h.logado()&&h.chip().includes('Escritório')),'Administrador entra direto como Escritório');
    ok(/Bem-vindo\(a\), Escritório!/.test(h.toast()),'toast "Bem-vindo(a), Escritório!"');
    ok(h.$$('#dm-tabs .dm-tab').map(b=>b.dataset.v).join()==='painel,sol,hist,cal,crono,admin','Escritório: abas Painel, Solicitações, Histórico, Calendário, Cronoanálise, Administração');
    ok(w.__net.log.every(l=>l.st<400||l.u==='/api/local/demandas/entrar'),'(conferência: nenhuma resposta de erro até aqui fora as do código)');
    // ---------- 2. Ver como ----------
    h.click('[data-act=tab][data-v=admin]');await sleep(60);h.click('[data-act=admsub][data-v=users]');
    ok(await until(()=>h.$$('[data-act=impersonate]').length>=4),'Administração > Usuários: botões 👁 Ver como');
    const bt=nome=>h.$$('[data-act=impersonate]').find(b=>b.dataset.v===S.pes[nome]);
    ok(bt('Dani Inativa').disabled,'Ver como: desabilitado para pessoa inativa');
    ok(bt('Ivo').disabled,'Ver como: desabilitado para pessoa de setor inativo');
    ok(!bt('Bruno').disabled&&bt('Bruno').title==='Ver o sistema como esta pessoa','Ver como: habilitado para pessoa ativa');
    w.__net.log.length=0;
    h.click(bt('Bruno'));
    ok(await until(()=>h.$('.dm-impbar')),'Ver como Bruno: aparece a faixa do modo visualização');
    ok(/Modo visualização/.test(h.$('.dm-impbar').textContent)&&/Bruno/.test(h.$('.dm-impbar').textContent)&&/Corte CNC/.test(h.$('.dm-impbar').textContent)&&/Só leitura/.test(h.$('.dm-impbar').textContent),'faixa: "Modo visualização", nome, setor e "Só leitura"');
    ok(h.$$('#dm-tabs .dm-tab').map(b=>b.dataset.v).join()==='recv,sent'&&/Olá, Bruno/.test(h.$('#dmboard').textContent),'Ver como mostra a tela de operador do Bruno');
    ok(h.chip().includes('Escritório'),'o chip continua sendo o do Escritório');
    ok(h.$('.dm-fab').hidden,'sem o botão flutuante de nova solicitação');
    ok(!h.$('.dm-opwrap [data-act=new]'),'sem "＋ Nova solicitação" no corpo da tela');
    kb('B1',h.$('.dm-hdnew').hidden,'Ver como (só leitura): o botão "＋ Nova solicitação" do cabeçalho continua visível');
    const visto=await h.idsNaTela();
    ok(!h.$('[data-act=accept],[data-act=pause],[data-act=finish],[data-act=resume],[data-act=reassign],[data-act=nudge],[data-act=cancel]'),'Ver como: nenhum botão de ação nos cartões (aceitar, pausar, concluir, retomar, repassar, cobrar, cancelar)');
    const wC=await boot({rede:true,cookie:await cookieDe(PINOP)});const hC=helpers(wC);
    await until(()=>hC.$('.dm-lgsec'));await hC.entra('CNC','Bruno','3333');
    ok(await until(()=>hC.logado()&&/Olá, Bruno/.test(hC.$('#dmboard').textContent)),'(preparo) o Bruno de verdade entra em outro aparelho (operador)');
    const real=await hC.idsNaTela();
    ok(visto.size>=3&&igual(visto,real),'Ver como Bruno mostra exatamente os pedidos que o Bruno de verdade vê ('+[...visto].sort().join(',')+')');
    ok([S.d.ce,S.d.he].every(i=>!visto.has(i)),'Ver como não vaza pedido que a pessoa não vê (o do Carlos para ESP e o da Helena para ESP)');
    // abrir um cartão em Ver como: só leitura
    h.click('[data-act=tab][data-v=recv]');h.click('[data-act=opf][data-v=pend]');await sleep(60);
    const card=h.$('.dm-ocard[data-id='+S.d.urg+']');ok(!!card,'(conferência: o pedido urgente do CNC aparece em Ver como Bruno)');h.click(card);
    ok(await until(()=>h.$('#dm-drawer.dm-on')),'Ver como: o cartão abre a gaveta');
    ok(/Modo visualização: só leitura/.test(h.$('#dm-drawer').textContent)&&!h.$('#dm-drawer [data-act=comment]')&&!h.$('#dm-cmt'),'gaveta em Ver como: sem ações e sem caixa de comentário');
    ok(!h.$('#dm-drawer [data-act=accept],#dm-drawer [data-act=pause],#dm-drawer [data-act=cancel],#dm-drawer [data-act=nudge],#dm-drawer [data-act=extend]'),'gaveta em Ver como: sem aceitar/pausar/cancelar/cobrar/estender');
    const escritas=()=>w.__net.log.filter(l=>l.m==='POST'&&!/\/(vista|entrar|sair)$/.test(l.u));
    await sleep(500);   // o "marcar como lido" da gaveta sai logo depois de abrir
    kb('B3',escritas().length===0,'Ver como (só leitura): abrir um cartão marca como lidos os avisos do Escritório e grava no servidor ('+escritas().map(l=>l.u.replace('/api/local/demandas/','')).join(',')+')');
    h.click('#dm-drawer [data-act=close]');await sleep(60);
    // botão do cabeçalho em Ver como: abre formulário e cria como Escritório
    w.__net.log.length=0;
    if(!h.$('.dm-hdnew').hidden){
      h.click('.dm-hdnew');await until(()=>h.$('#dm-fm-title'));
      const f=h.$('#dm-fm-title');f.value='Criada em Ver como';f.dispatchEvent(new w.Event('input',{bubbles:true}));
      ok(!!h.$('#dm-fm-title'),'(B1) o formulário de nova solicitação abre mesmo em Ver como: quem o enviasse seria o Escritório (sem tk)');
      h.click('[data-act=mclose]');await sleep(60);
    }
    // sair do Ver como
    h.click('[data-act=impexit]');
    ok(await until(()=>!h.$('.dm-impbar')&&h.$('#dm-tabs .dm-tab[data-v=admin]')),'Voltar ao ADM: some a faixa e voltam as abas de administração');
    ok(h.$('.dm-hdnew')&&!h.$('.dm-fab').hidden,'de volta ao ADM: nova solicitação disponível');
    // ver como outra pessoa e depois trocar de usuário/sair: o modo não vaza para a pessoa
    // ---------- 3. aparelho de operador (PIN dos operadores, papel real "operador") ----------
    const ckOp=await cookieDe(PINOP),ckCo=await cookieDe(PIN);
    const euOp=JSON.parse((await GET('/api/eu',{rede:true,cookie:ckOp})).t);
    ok(euOp.papel==='operador','(conferência: o cookie do PIN dos operadores vira papel "operador")');
    const wo=await boot({rede:true,cookie:ckOp});const ho=helpers(wo);
    ok(await until(()=>ho.$('#dm-login .dm-lgcard')&&!ho.$('#dm-login').hidden),'aparelho de operador abre em "Quem é você?"');
    ok(await until(()=>ho.$('.dm-lgsec')),'a lista de setores chega pelo GET público');
    ok(!ho.$('[data-act=lgk]')&&!/Administrador/.test(ho.$('#dm-login').textContent),'operador: sem a opção Administrador (nem o botão nem o texto)');
    ok(ho.$('#cx-cfg').hidden,'operador: sem o botão ⚙ Configurações');
    ok(ho.$$('.dm-lgsec').map(b=>b.dataset.v).join()==='PCP,CNC,ESP','operador: lista só setores ativos com gente');
    ok(!/@/.test(wo.document.documentElement.innerHTML.replace(/mailto:[^"]*/g,'')),'operador: nenhum e-mail na tela de entrada');
    await ho.entra('ESP','Fernanda','4444');
    ok(await until(()=>ho.logado()&&/Olá, Fernanda/.test(ho.$('#dmboard').textContent)),'operador entra como pessoa com o código');
    ok(ho.$$('#dm-tabs .dm-tab').map(b=>b.dataset.v).join()==='recv,sent','operador: só as abas de pessoa');
    const naF=await ho.idsNaTela();
    ok(naF.has(S.d.he)&&naF.has(S.d.ce)&&naF.has(S.d.be)&&!naF.has(S.d.hc)&&!naF.has(S.d.ec),'operador (Fernanda): vê só o setor ESP');
    ho.click('#dm-bell');await sleep(150);ho.click('#dm-notif [data-act=close]');await sleep(50);
    ho.click('[data-act=tab][data-v=recv]');ho.click('[data-act=opf][data-v=pend]');await sleep(60);
    ho.click(ho.$('.dm-ocard[data-id]'));await until(()=>ho.$('#dm-drawer.dm-on'));ho.click('#dm-drawer [data-act=close]');
    ho.click('#dm-uchip');await until(()=>ho.$('[data-act=prefs]'));ho.click('[data-act=prefs]');await until(()=>ho.$('#dm-mbox h2')&&ho.$('#dm-mbox h2').textContent==='Meus avisos');
    ok(!!ho.$('#dm-mbox h2')&&ho.$('#dm-mbox h2').textContent==='Meus avisos','operador: "Meus avisos" abre');
    ho.click('[data-act=mclose]');await sleep(60);
    ok(!wo.__net.log.some(l=>l.st===403),'operador: usar a tela (entrar, abas, cartão, sino, avisos) não esbarra em 403 do servidor: '+wo.__net.log.filter(l=>l.st===403).map(l=>l.m+' '+l.u).join(','));
    ok(!wo.__erros.length,'operador: nenhum erro de script na página');
    ok((await call('setor/salvar',{tk:wo.__net.tks[0],modo:'novo',id:'XXX',nome:'Invasor',icone:'⚙️',cor:'#3B82F6',rev:0},{rede:true,cookie:ckOp})).st===403,'operador: rota de ADM direto no servidor = 403');
    ok((await GET('/api/rede',{rede:true,cookie:ckOp})).st===403&&(await GET('/api/local/demandas/vista',{rede:true,cookie:ckOp})).st===403,'operador: /api/rede e GET vista = 403');
    // /api/eu fora do ar no aparelho de operador: a tela mostra Administrador, mas o servidor não deixa entrar
    const wf=await boot({rede:true,cookie:ckOp,eu:'fail'});const hf=helpers(wf);
    ok(await until(()=>hf.$('#dm-login .dm-lgcard')&&hf.$('.dm-lgsec')),'operador com /api/eu fora do ar: abre a tela de entrada');
    console.log('OBS        /api/eu falhou no aparelho de operador: opção Administrador na tela = '+(hf.$('[data-act=lgk][data-v=adm]')?'sim (a tela abre por falta de informação; o servidor é quem barra)':'não'));
    if(hf.$('[data-act=lgk][data-v=adm]')){hf.click('[data-act=lgk][data-v=adm]');hf.click('#dm-lgform [type=submit]');
      ok(await until(()=>/Este aparelho não tem acesso de administrador\./.test(hf.$('#dm-login').textContent)),'…e Entrar como Administrador nesse aparelho é recusado com mensagem');
      ok(!hf.logado()&&!hf.$('#dm-tabs .dm-tab[data-v=admin]'),'…sem abrir nenhuma tela de administração')}
    // /api/eu demorando: nada de Administrador até ele responder
    const wh=await boot({eu:'hang'});const hh=helpers(wh);
    await until(()=>hh.$('.dm-lgcard'),3000);
    ok(!hh.$('[data-act=lgk][data-v=adm]')&&!/Administrador/.test(hh.$('#dm-login').textContent||''),'enquanto /api/eu não responde, a tela não mostra Administrador');
    wh.__net.solta();
    ok(await until(()=>hh.$('[data-act=lgk][data-v=adm]'),8000),'quando /api/eu responde "maquina", Administrador aparece');
    // PIN completo na rede: tem Administrador e entra como Escritório; sem ⚙
    const wcmp=await boot({rede:true,cookie:ckCo});const hcm=helpers(wcmp);
    ok(await until(()=>hcm.$('[data-act=lgk][data-v=adm]')),'aparelho do escritório (PIN completo): tem a opção Administrador');
    ok(hcm.$('#cx-cfg').hidden,'aparelho do escritório pela rede: sem o botão ⚙ Configurações (só o PC principal)');
    hcm.click('[data-act=lgk][data-v=adm]');hcm.click('#dm-lgform [type=submit]');
    ok(await until(()=>hcm.logado()&&hcm.chip().includes('Escritório')),'PIN completo: Administrador entra como Escritório');
    // ---------- 4. sessão perdida (lost) ----------
    // Helena entra no PC principal; o Escritório a desativa; a tela cai em "Quem é você?" com a mensagem
    w.close();w=await boot();h=helpers(w);
    await until(()=>h.$('.dm-lgsec'));await h.entra('PCP','Helena','1111');
    ok(await until(()=>h.logado()&&/Olá, Helena/.test(h.$('#dmboard').textContent)),'(preparo) Helena entra no PC principal');
    const rvC=(await direto('vista',{})).pessoas.find(p=>p.id===S.pes.Helena)._rv;
    await direto('pessoa/ativar',{id:S.pes.Helena,rev:rvC});
    ok(await until(()=>!h.logado()&&h.$('#dm-login .dm-lgcard'),15000),'desativada pelo Escritório: a tela da Helena volta ao "Quem é você?" sozinha');
    ok(h.erro()==='Identifique-se de novo.'&&/🔒 Identifique-se de novo\./.test(h.toast()||(w.document.body.textContent)),'com a mensagem "Identifique-se de novo." (e o aviso 🔒)');
    ok(h.$('#dm-lg-code').value==='','e o código vazio');
    // nova pessoa criada depois de a tela abrir: a lista da tela de entrada não a mostra (lista velha) e ainda lista a desativada
    const vNova=await direto('pessoa/salvar',{modo:'novo',nome:'Nova Pessoa',setor:'PCP',codigo:'7777',rev:0});
    await sleep(4500);
    await h.setor('PCP');
    kb('B2',!h.nomes().includes('Helena')&&h.nomes().includes('Nova Pessoa'),'depois de "Identifique-se de novo.", a lista da tela de entrada continua a de antes (mostra "Helena" já desativada e não mostra "Nova Pessoa"): ['+h.nomes().join(', ')+']');
    await h.usuario('Nova Pessoa');h.digita('#dm-lg-code','7777');h.click('#dm-lgform [type=submit]');
    ok(await until(()=>h.logado()&&/Olá, Nova Pessoa/.test(h.$('#dmboard').textContent)),'a pessoa cadastrada depois de a tela abrir entra sem recarregar a página (B2 corrigido)');
    ok(!vNova.erro,'(conferência: o Escritório cadastrou a Nova Pessoa)');
    ok(!w.__erros.length,'PC principal: nenhum erro de script na página durante o roteiro');
    w.close();wo.close();wf.close();wh.close();wcmp.close();wC.close();
  }catch(e){console.log('FAIL exceção no roteiro: '+(e&&e.stack||e));process.exitCode=1}
  finally{killTree(srv);try{fs.rmSync(base,{recursive:true,force:true})}catch(e){}}
  process.exit(process.exitCode||0);
})();
