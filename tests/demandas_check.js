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
async function boot(papel){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/',{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>(u==='/api/rev'&&REVS++,0)||FORA&&String(u).startsWith('/api/')?Promise.reject(new TypeError('Failed to fetch')):papel&&u==='/api/eu'?Promise.resolve(new Response(JSON.stringify({papel}),{headers:{'Content-Type':'application/json'}}))
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
  ok($('#cx-cfg').hidden,'sem o botão ⚙ Configurações');
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
  ok(/^SOL-100[1-9]$/.test($('#dm-rs-prox').textContent)&&$('#dm-rs-prox').textContent!=='SOL-1001','próximo número continua do maior já usado: '+$('#dm-rs-prox').textContent);
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
    w.close();
    await aparelhoOperador();
    await restaurarPelaTela();
  }finally{killTree(srv);   // no Windows o servidor recém-morto ainda pode segurar arquivos: tenta de novo e não reprova por isso
    try{fs.rmSync(base,{recursive:true,force:true,maxRetries:10,retryDelay:200})}catch(e){console.log('aviso: pasta temporária ficou em '+base)}}
  console.log(process.exitCode?'houve falhas':'tudo certo');
})().catch(e=>{console.log('FAIL '+e.stack);process.exitCode=1}).finally(()=>process.exit());   // janela jsdom aberta não pode prender o processo
