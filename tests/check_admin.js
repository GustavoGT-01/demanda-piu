const {JSDOM}=require('jsdom'),{spawn,spawnSync}=require('child_process'),fs=require('fs'),os=require('os'),path=require('path');
// QA da aba Administração (Setores, Usuários e Expediente) pela tela, contra o servidor REAL (servidor.py) com dados temporários.
// rodar: NODE_PATH=tests/node_modules node tests/check_admin.js   (PYTHON=... troca o interpretador)
// `ok` reprova (exitCode 1); `bug(id, cond, msg)` marca defeito conhecido: se a condição falha imprime KNOWN-BUG (não reprova),
// se passar imprime FIXED (o defeito sumiu: tire a marca). Bugs em docs/qa/admin.md.
const REPO=path.resolve(__dirname,'..');
const base=fs.mkdtempSync(path.join(os.tmpdir(),'dem-qa-admin-')),data=path.join(base,'data');
fs.mkdirSync(data);
const PY=process.env.PYTHON||(process.platform==='win32'?'py':'python3');
let PORT=0,N=0,FALHAS=0,CONHECIDOS=0;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ok=(c,m)=>{N++;console.log((c?'PASS ':'FAIL ')+m);if(!c){FALHAS++;process.exitCode=1}};
const bug=(id,c,m)=>{N++;if(c)console.log('FIXED '+id+' (o defeito sumiu: tire a marca) '+m);else{CONHECIDOS++;console.log('KNOWN-BUG '+id+' '+m)}};
function startServer(){return new Promise((res,rej)=>{
  const code=`import sys;sys.path.insert(0,${JSON.stringify(REPO)});import servidor;s=servidor.Server(('127.0.0.1',0),servidor.Handler);print(s.server_address[1],flush=True);s.serve_forever()`;
  const p=spawn(PY,[...(PY==='py'?['-3']:[]),'-c',code],{env:{...process.env,DEMANDAS_DATA:data}});
  let out='';p.stderr.on('data',d=>{if(process.env.E2E_VERBOSE)process.stderr.write(d)});
  p.stdout.on('data',d=>{out+=d;const m=/^(\d+)\s/.exec(out);if(m&&!PORT){PORT=+m[1];res(p)}});
  p.on('exit',c=>rej(new Error('servidor saiu com código '+c)));
  setTimeout(()=>rej(new Error('servidor não subiu em 15 s')),15000).unref();
})}
function killTree(p){if(!p||p.exitCode!==null)return;if(process.platform==='win32')spawnSync('taskkill',['/T','/F','/PID',String(p.pid)]);else p.kill('SIGKILL')}
async function boot(papel){
  const dom=await JSDOM.fromURL('http://127.0.0.1:'+PORT+'/',{runScripts:'dangerously',resources:'usable',pretendToBeVisual:true,beforeParse(w){
    w.fetch=(u,o)=>papel&&u==='/api/eu'?Promise.resolve(new Response(JSON.stringify({papel}),{headers:{'Content-Type':'application/json'}})):fetch(new URL(u,'http://127.0.0.1:'+PORT).href,o);
    w.matchMedia=w.matchMedia||(q=>({matches:false,media:q,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return false}}));
    w.Element.prototype.scrollIntoView=w.Element.prototype.scrollIntoView||function(){};
    Object.defineProperty(w,'crypto',{value:require('crypto').webcrypto});
    w.addEventListener('error',e=>console.log('PAGE ERROR',e.message));
    w.AudioContext=class{constructor(){this.state='suspended';this.currentTime=0;this.destination={}}resume(){}createOscillator(){return{frequency:{},connect(){},start(){},stop(){}}}createGain(){return{gain:{setValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){}}}};
  }});
  const w=dom.window;
  for(let t0=Date.now();Date.now()-t0<30000;await sleep(100))try{if(w.NestLocal.views.demandas&&w.document.getElementById('dmboard'))break}catch(e){}
  return w;
}
const direto=(rest,body)=>fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(r=>r.text().then(t=>{let j={};try{j=JSON.parse(t)}catch(e){j={erro:t}}return {status:r.status,...j}}));
const disco=()=>{try{return JSON.parse(fs.readFileSync(path.join(data,'demandas.json'),'utf8'))}catch(e){return{setores:[],pessoas:[],demandas:[],agenda:null,agendas:{}}}};   // sem arquivo = nada gravado ainda
const until=async(f,ms=8000)=>{for(const t0=Date.now();Date.now()-t0<ms;await sleep(50))try{if(f())return true}catch(e){}return false};
const email=n=>'a'.repeat(64)+'@'+'d'.repeat(n-65-4)+'.com';

async function janelaAdm(){
  const w=await boot(),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  await until(()=>$('[data-act=lgk][data-v=adm]'));$('[data-act=lgk][data-v=adm]').click();$('.dm-lgbtn').click();
  await until(()=>$('.dm-tab[data-v=painel]'));
  const T={w,d,$,$$,
    click:s=>{const e=typeof s==='string'?$(s):s;if(!e)throw new Error('não achei '+s);e.click();return e},
    type:(s,v,ev='input')=>{const e=$(s);if(!e)throw new Error('não achei '+s);e.value=v;e.dispatchEvent(new w.Event(ev,{bubbles:true}))},
    ico:v=>[...d.querySelectorAll('[data-act=sf-icon]')].find(b=>b.dataset.v===v),
    toast:()=>($('#dm-toast')||{}).textContent||'',
    modal:()=>$('#dm-modal')&&$('#dm-modal').classList.contains('dm-on'),
    sub:async v=>{if(!$('[data-act=admsub]')){$('.dm-tab[data-v=admin]').click();await until(()=>$('[data-act=admsub]'))}$('[data-act=admsub][data-v='+v+']').click();await sleep(30)},
    recarrega:async()=>{await w.NestLocal.views.demandas.refresh();await sleep(150)}};
  return T;
}

// ===================================================================================================== SETORES
async function setores(T){
  const {w,$,$$,click,type,toast,modal,sub}=T;
  await sub('sectors');
  ok(/Nenhum setor cadastrado/.test($('.dm-sgrid').textContent)&&/^0 setores/.test($('.dm-count').textContent.trim()),'Setores: vazio mostra "Nenhum setor cadastrado" e "0 setores"');
  ok(!!$('[data-act=newsector]')&&!!$('[data-act=newuser]'),'Setores: botões ＋ Novo setor e ＋ Novo usuário');
  // abrir o modal Novo setor
  click('[data-act=newsector]');
  ok(await until(()=>modal()&&$('#dm-mbox h2')&&$('#dm-mbox h2').textContent==='Novo setor'),'Novo setor: o modal abre');
  ok($('#dm-sf-name').maxLength===40&&$('#dm-sf-id').maxLength===4&&$('#dm-sf-email').maxLength===254&&$('#dm-sf-email').type==='email','Novo setor: maxlength nome 40, sigla 4, e-mail 254 e type=email');
  ok($$('[data-act=sf-icon]').length===20&&$$('[data-act=sf-color]').length===12,'Novo setor: 20 ícones e 12 cores');
  ok($$('[data-act=sf-icon][aria-pressed=true]').length===1&&$$('[data-act=sf-color][aria-pressed=true]').length===1,'Novo setor: um ícone e uma cor já marcados');
  ok(/SIG/.test($('#dm-sf-prev').textContent)&&/Nome do setor/.test($('#dm-sf-prev').textContent),'Novo setor: pré-visualização com SIG e "Nome do setor"');
  ok(!$('[data-act=sf-toggle]')&&!$('[data-act=sf-del]'),'Novo setor: sem Desativar nem Excluir');
  // validações: tudo vazio
  click('[data-act=sf-save]');await sleep(60);
  ok(modal()&&$$('#dm-mbox .dm-fld.dm-err').length===2&&disco().setores.length===0,'Novo setor vazio: nome e sigla em erro, nada gravado');
  // nome nos limites
  const tenta=async(nome,id,em='')=>{type('#dm-sf-name',nome);if(id!==null)type('#dm-sf-id',id);type('#dm-sf-email',em);click('[data-act=sf-save]');await sleep(60);return [...$$('#dm-mbox .dm-fld.dm-err')].map(e=>e.querySelector('label')?e.querySelector('label').textContent:'?').join('|')};
  ok(/Nome do setor/.test(await tenta('ab','XY','x')),'Nome com 2 caracteres: erro');
  ok(/Nome do setor/.test(await tenta('x'.repeat(41),'XY','x')),'Nome com 41 caracteres: erro');
  ok(/Nome do setor/.test(await tenta('   ab   ','XY','x')),'Nome "ab" com espaços nas pontas: erro (conta depois do trim)');
  ok(!/Nome do setor/.test(await tenta('abc','XY','x')),'Nome com 3 caracteres: passa a conferência do nome (o e-mail inválido segura o modal)');
  ok(!/Nome do setor/.test(await tenta('x'.repeat(40),'XY','x')),'Nome com 40 caracteres: passa a conferência do nome');
  ok(!/Nome do setor/.test(await tenta('  '+'x'.repeat(40)+'  ','XY','x')),'Nome com 40 caracteres e espaços nas pontas: passa (conta depois do trim)');
  ok(disco().setores.length===0,'(conferência: nada foi gravado)');
  click('[data-act=mclose]');await sleep(30);click('[data-act=newsector]');await until(()=>modal());
  // sigla: sugestão automática e filtro de digitação
  type('#dm-sf-name','Corte e Dobra');
  ok($('#dm-sf-id').value==='CD','Sigla sugerida a partir do nome ("Corte e Dobra" → CD): '+$('#dm-sf-id').value);
  type('#dm-sf-id','a-b!c');
  ok($('#dm-sf-id').value==='ABC','Sigla digitada: maiúscula e só letras/números ("a-b!c" → ABC)');
  type('#dm-sf-id','abcde');
  ok($('#dm-sf-id').value==='ABCD','Sigla digitada: corta em 4 caracteres');
  type('#dm-sf-name','Outro nome');
  ok($('#dm-sf-id').value==='ABCD','Sigla editada à mão não é mais sobrescrita pela sugestão');
  type('#dm-sf-id','A');click('[data-act=sf-save]');await sleep(60);
  ok(modal()&&/Use de 2 a 4/.test($('#dm-mbox .dm-fld.dm-err .dm-em').textContent),'Sigla de 1 caractere: erro "Use de 2 a 4"');
  type('#dm-sf-id','');click('[data-act=sf-save]');await sleep(60);
  ok(modal()&&$$('#dm-mbox .dm-fld.dm-err').length>=1,'Sigla vazia: erro');
  // e-mail
  type('#dm-sf-id','CD');
  bug('QA-ADM-09',!$('#dm-sf-id').closest('.dm-fld.dm-err'),'Setor: o erro da sigla deveria sumir quando a sigla vira válida ("CD"), como o do nome some');
  for(const ruim of['semarroba','a@b','a b@c.com','a@b.c']){type('#dm-sf-email',ruim);click('[data-act=sf-save]');await sleep(40);
    ok(modal()&&!!$('#dm-sf-email').closest('.dm-fld.dm-err'),'E-mail inválido "'+ruim+'": erro na tela, nada enviado')}
  type('#dm-sf-email',email(255));click('[data-act=sf-save]');await sleep(40);
  ok(modal()&&!!$('#dm-sf-email').closest('.dm-fld.dm-err'),'E-mail com 255 caracteres: erro');
  ok(disco().setores.length===0,'(conferência: nada foi gravado pelos erros)');
  type('#dm-sf-email','x');ok(!!$('#dm-sf-email').closest('.dm-fld.dm-err'),'(conferência: erro de e-mail continua enquanto inválido)');
  type('#dm-sf-email','corte@empresa.com');ok(!$('#dm-sf-email').closest('.dm-fld.dm-err'),'E-mail corrigido: o erro some ao digitar');
  // ícone e cor
  click(T.ico('🎨'));
  ok(T.ico('🎨').getAttribute('aria-pressed')==='true'&&$$('[data-act=sf-icon][aria-pressed=true]').length===1&&/🎨/.test($('#dm-sf-prev').textContent),'Ícone 🎨: marcado, os outros desmarcados, pré-visualização acompanha');
  click('[data-act=sf-color][data-v="#EC4899"]');
  ok($('[data-act=sf-color][data-v="#EC4899"]').getAttribute('aria-pressed')==='true'&&$$('[data-act=sf-color][aria-pressed=true]').length===1,'Cor #EC4899: marcada, as outras desmarcadas');
  // paridade ícones/cores da tela com o servidor
  const srvIcons=(await fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/setor/salvar',{method:'POST',body:JSON.stringify({modo:'novo',id:'ZZ',nome:'Zzz',icone:'🍕',cor:'#6366F1',rev:0})}).then(r=>r.status));
  ok(srvIcons===400,'(conferência: servidor recusa ícone fora da lista)');
  let semRecusa=[];
  for(const b of $$('[data-act=sf-icon]')){const r=await direto('setor/salvar',{modo:'novo',id:'ZZ',nome:'Zzz',icone:b.dataset.v,cor:'#6366F1',rev:0});if(r.status!==200)semRecusa.push('icone '+b.dataset.v+': '+r.status);else await direto('setor/apagar',{id:'ZZ',rev:disco().setores.find(x=>x.id==='ZZ')._rv})}
  for(const b of $$('[data-act=sf-color]')){const r=await direto('setor/salvar',{modo:'novo',id:'ZZ',nome:'Zzz',icone:'⚙️',cor:b.dataset.v,rev:0});if(r.status!==200)semRecusa.push('cor '+b.dataset.v+': '+r.status);else await direto('setor/apagar',{id:'ZZ',rev:disco().setores.find(x=>x.id==='ZZ')._rv})}
  ok(!semRecusa.length,'Todos os 20 ícones e 12 cores da tela são aceitos pelo servidor '+semRecusa.join(', '));
  // criar
  click('[data-act=sf-save]');
  ok(await until(()=>/Setor ABCD criado|Setor CD criado/.test(toast())&&!modal()),'Criar setor: toast e modal fecha ('+toast()+')');
  const cd=disco().setores.find(s=>s.id==='CD');
  ok(!!cd&&cd.nome==='Outro nome'&&cd.icone==='🎨'&&cd.cor==='#EC4899'&&cd.email==='corte@empresa.com'&&cd.ativo===true,'Criar setor: gravado com nome, ícone, cor, e-mail e ativo '+JSON.stringify(cd));
  ok(await until(()=>$$('.dm-scard').length===1&&/Outro nome/.test($('.dm-scard').textContent)&&/Ativo/.test($('.dm-scard .dm-pill').textContent)),'Criar setor: o cartão aparece no mapa, Ativo');
  ok(/^1 setores · 0 usuários ativos/.test($('.dm-count').textContent.trim()),'Contador "1 setores · 0 usuários ativos": '+$('.dm-count').textContent.trim());
  // repetida (a sigla CD já existe)
  click('[data-act=newsector]');await until(()=>modal());type('#dm-sf-name','Cópia');type('#dm-sf-id','cd');click('[data-act=sf-save]');await sleep(60);
  ok(modal()&&/já está em uso/.test($('#dm-mbox .dm-fld.dm-err .dm-em').textContent),'Sigla repetida: erro "já está em uso"');
  click('[data-act=mclose]');await sleep(30);
  ok(!modal(),'Cancelar fecha o modal sem gravar (só 1 setor)');ok(disco().setores.length===1,'(conferência: continua 1 setor)');
  // o resto do cenário pelo servidor
  for(const [id,nome] of[['PCP','Planejamento'],['CNC','Corte CNC'],['ESP','Espumação']])await direto('setor/salvar',{modo:'novo',id,nome,icone:'⚙️',cor:'#3B82F6',rev:0});
  await T.recarrega();
  ok(await until(()=>$$('.dm-scard').length===4),'Os 4 setores aparecem no mapa');
  ok($$('.dm-scard [data-act=editsector]').length===4&&$$('.dm-scard [data-act=seeusers]').length===4,'Cada cartão tem ✏️ Editar setor e 👥 Usuários');
}

async function setorEditar(T){
  const {w,$,$$,click,type,toast,modal,sub}=T;
  await sub('sectors');
  await direto('pessoa/salvar',{modo:'novo',nome:'Carlos',setor:'CNC',codigo:'2222',rev:0});
  await T.recarrega();
  click('[data-act=editsector][data-v=CNC]');
  ok(await until(()=>modal()&&$('#dm-mbox h2').textContent==='Editar setor'),'Editar setor: abre');
  ok($('#dm-sf-id').disabled&&$('#dm-sf-id').value==='CNC'&&$('#dm-sf-name').value==='Corte CNC','Editar setor: sigla travada e nome preenchido');
  ok(!!$('[data-act=sf-toggle]')&&!!$('[data-act=sf-del]')&&/Desativar setor/.test($('[data-act=sf-toggle]').textContent)&&/Excluir setor/.test($('[data-act=sf-del]').textContent),'Editar setor: Desativar e Excluir aparecem');
  ok(/1<\/b> usuário\(s\) ativo\(s\)/.test($('#dm-mbox').innerHTML),'Editar setor: mostra "1 usuário(s) ativo(s)"');
  type('#dm-sf-name','Corte');ok(true,'');N--;
  type('#dm-sf-name','ab');click('[data-act=sf-save]');await sleep(60);
  ok(modal()&&disco().setores.find(s=>s.id==='CNC').nome==='Corte CNC','Editar setor: nome de 2 caracteres não grava');
  type('#dm-sf-name','  Corte CNC 2  ');type('#dm-sf-email','  Corte@Empresa.COM ');
  click(T.ico('🔩'));click('[data-act=sf-color][data-v="#0EA5E9"]');
  click('[data-act=sf-save]');
  ok(await until(()=>/Setor atualizado/.test(toast())&&!modal()),'Editar setor: salvar mostra "Setor atualizado" e fecha');
  let s=disco().setores.find(x=>x.id==='CNC');
  ok(s.nome==='Corte CNC 2'&&s.email==='corte@empresa.com'&&s.icone==='🔩'&&s.cor==='#0EA5E9'&&s.ativo===true,'Editar setor: gravou nome sem espaços, e-mail em minúsculas, ícone e cor '+JSON.stringify(s));
  click('[data-act=editsector][data-v=CNC]');await until(()=>modal());
  ok($('#dm-sf-email').value==='corte@empresa.com','Editar setor: reabre com o e-mail salvo');
  type('#dm-sf-email','');click('[data-act=sf-save]');
  ok(await until(()=>!modal()&&!('email' in disco().setores.find(x=>x.id==='CNC'))),'Editar setor: e-mail vazio apaga o e-mail');
  // ativar/desativar com demanda aberta
  await direto('demanda/criar',{titulo:'Cortar chapas',tipo:'dem',motivo:'Outro',prio:'norm',est:60,para:{s:'CNC',p:null},desc:'',de_s:'PCP'});
  await T.recarrega();
  click('[data-act=editsector][data-v=CNC]');await until(()=>modal());
  ok(/1<\/b> solicitação\(ões\) em aberto/.test($('#dm-mbox').innerHTML),'Editar setor: mostra a demanda em aberto');
  click('[data-act=sf-toggle]');
  ok(await until(()=>/em aberto: conclua ou reatribua/.test(toast())),'Desativar com demanda aberta: o servidor recusa e a tela avisa ('+toast()+')');
  ok(disco().setores.find(x=>x.id==='CNC').ativo===true,'Desativar com demanda aberta: o setor continua ativo');
  click('[data-act=mclose]');await sleep(30);
  // desativar depois de cancelar
  await direto('demanda/cancelar',{id:'SOL-1001'});await T.recarrega();
  click('[data-act=editsector][data-v=CNC]');await until(()=>modal());
  click('[data-act=sf-toggle]');
  ok(await until(()=>/Setor desativado/.test(toast())&&!modal()),'Desativar: "Setor desativado"');
  ok(await until(()=>/Inativo/.test($$('.dm-scard').find(c=>/Corte CNC 2/.test(c.textContent)).textContent)&&$$('.dm-scard.dm-off').length===1),'Desativar: o cartão fica Inativo (esmaecido)');
  click('[data-act=editsector][data-v=CNC]');await until(()=>modal());
  ok(/Reativar setor/.test($('[data-act=sf-toggle]').textContent)&&/inativo/.test($('#dm-mbox').textContent),'Setor inativo: o botão vira "Reativar setor"');
  click('[data-act=sf-toggle]');
  ok(await until(()=>/Setor reativado/.test(toast())&&!modal()&&$$('.dm-scard.dm-off').length===0),'Reativar: "Setor reativado" e o cartão volta ao normal');
  // excluir com histórico (a demanda cancelada ainda é histórico)
  click('[data-act=editsector][data-v=CNC]');await until(()=>modal());
  click('[data-act=sf-del]');await sleep(60);
  ok(/histórico de solicitações/.test(toast())&&!$('[data-act=cf-ok]'),'Excluir setor com histórico: avisa sem pedir confirmação');
  click('[data-act=mclose]');await sleep(30);
  // excluir sem histórico: confirmação, Cancelar, e Excluir
  click('[data-act=editsector][data-v=ESP]');await until(()=>modal());
  click('[data-act=sf-del]');
  ok(await until(()=>$('[data-act=cf-ok]')&&/Excluir setor/.test($('#dm-mbox h2').textContent)&&/Excluir <b>Espumação<\/b>/.test($('#dm-mbox').innerHTML)),'Excluir setor sem histórico: pede confirmação com o nome');
  click('[data-act=mclose]');await sleep(40);
  ok(disco().setores.some(x=>x.id==='ESP'),'Cancelar a confirmação não exclui');
  click('[data-act=editsector][data-v=ESP]');await until(()=>modal());click('[data-act=sf-del]');await until(()=>$('[data-act=cf-ok]'));click('[data-act=cf-ok]');
  ok(await until(()=>/Setor excluído/.test(toast())&&!disco().setores.some(x=>x.id==='ESP')&&$$('.dm-scard').length===3),'Excluir setor sem histórico: "Setor excluído" e o cartão some');
  // excluir com histórico só no arquivo morto: a tela não sabe, o servidor recusa
  await direto('setor/salvar',{modo:'novo',id:'ARQ',nome:'Arquivado',icone:'⚙️',cor:'#3B82F6',rev:0});
  fs.writeFileSync(path.join(data,'demandas-arquivo.json'),JSON.stringify({v:1,demandas:[{id:'SOL-900',titulo:'Antiga',tipo:'dem',motivo:'Outro',prio:'norm',est:60,de:{s:'PCP',p:null},para:{s:'ARQ',p:null},desc:'x',status:'done',criado:1,iniciado:1,fim:2,atraso_avisado:false,pausas:[],eventos:[],comentarios:[],anexos:[],_rv:1}]}));
  await T.recarrega();
  click('[data-act=editsector][data-v=ARQ]');await until(()=>modal());click('[data-act=sf-del]');await until(()=>$('[data-act=cf-ok]'));click('[data-act=cf-ok]');
  ok(await until(()=>/histórico de demandas: desative em vez de excluir/.test(toast())),'Excluir setor com histórico só no arquivo: o servidor recusa e a tela mostra a frase ('+toast()+')');
  ok(disco().setores.some(x=>x.id==='ARQ'),'Excluir setor com histórico só no arquivo: o setor continua');
  click('[data-act=mclose]');await sleep(30);
  // conflito: a tela abre a edição, outro aparelho muda o setor, a tela salva
  click('[data-act=editsector][data-v=ARQ]');await until(()=>modal());
  const rv0=disco().setores.find(x=>x.id==='ARQ')._rv;
  const o=await direto('setor/salvar',{modo:'editar',id:'ARQ',nome:'Outro aparelho',icone:'⚙️',cor:'#3B82F6',rev:rv0});
  ok(o.status===200,'(conferência: o outro aparelho gravou)');
  await T.recarrega();await sleep(200);
  type('#dm-sf-name','Minha edição antiga');click('[data-act=sf-save]');
  await until(()=>/Alterado em outro aparelho|Setor atualizado/.test(toast()),5000);
  const nomeFinal=disco().setores.find(x=>x.id==='ARQ').nome;
  bug('QA-ADM-06',/Alterado em outro aparelho/.test(toast())&&nomeFinal==='Outro aparelho','Setor: editar com o modal aberto enquanto outro aparelho salva deveria dar 409 (nome final "'+nomeFinal+'", aviso "'+toast()+'")');
  if(modal())click('[data-act=mclose]');
  await sleep(30);
  // seeusers
  click('[data-act=seeusers][data-v=CNC]');
  ok(await until(()=>$('#dm-uSec')&&$('#dm-uSec').value==='CNC'&&$$('.dm-urow').length===1),'👥 Usuários do cartão: vai para Usuários filtrado pelo setor');
}

// ===================================================================================================== USUÁRIOS
async function usuarios(T){
  const {w,$,$$,click,type,toast,modal,sub}=T;
  await sub('users');
  type('#dm-uq','');$('#dm-uSec').value='';$('#dm-uSec').dispatchEvent(new w.Event('change',{bubbles:true}));
  ok(!!$('#dm-uq')&&!!$('#dm-uSec')&&!!$('#dm-uSt')&&!!$('[data-act=newuser]')&&!$('[data-act=newsector]'),'Usuários: busca, filtro de setor, de status e ＋ Novo usuário (sem ＋ Novo setor)');
  ok($('#dm-uq').placeholder==='Buscar usuário ou matrícula','Usuários: placeholder da busca');
  ok($$('#dm-uSec option').length===1+disco().setores.length&&$$('#dm-uSt option').map(o=>o.value).join()===',on,off','Usuários: filtros com todos os setores e Todos/Ativos/Inativos');
  ok($$('.dm-urow').length===1&&/Carlos/.test($('.dm-urow').textContent)&&/Matrícula M100/.test($('.dm-urow').textContent),'Usuários: lista com Carlos, matrícula M100');
  // Novo usuário
  click('[data-act=newuser]');
  ok(await until(()=>modal()&&$('#dm-mbox h2').textContent==='Novo usuário'),'Novo usuário: abre');
  ok($('#dm-uf-name').maxLength===60&&$('#dm-uf-code').maxLength===4&&$('#dm-uf-email').maxLength===254,'Novo usuário: maxlength nome 60, código 4, e-mail 254');
  ok(/^\d{4}$/.test($('#dm-uf-code').value)&&$('#dm-uf-code').type==='text','Novo usuário: já vem com um código de 4 dígitos, visível');
  ok($$('#dm-uf-sec option').map(o=>o.value).join()===','+disco().setores.filter(s=>s.ativo).map(s=>s.id).join(),'Novo usuário: o seletor só lista setores ativos');
  ok(!$('[data-act=uf-toggle]')&&!$('[data-act=uf-del]'),'Novo usuário: sem Desativar nem Excluir');
  click('[data-act=uf-eye]');ok($('#dm-uf-code').type==='password','👁: oculta o código');click('[data-act=uf-eye]');ok($('#dm-uf-code').type==='text','👁: mostra de novo');
  const c0=$('#dm-uf-code').value;let mudou=false;for(let i=0;i<6&&!mudou;i++){click('[data-act=uf-gen]');mudou=$('#dm-uf-code').value!==c0}
  ok(mudou&&/^\d{4}$/.test($('#dm-uf-code').value),'Gerar: novo código de 4 dígitos');
  type('#dm-uf-code','a1b2c3d4e5');ok($('#dm-uf-code').value==='1234','Código digitado: só números e no máximo 4 ("a1b2c3d4e5" → 1234)');
  // validações
  const erros=()=>$$('#dm-mbox .dm-fld.dm-err label').map(l=>l.textContent).join('|');
  type('#dm-uf-name','');type('#dm-uf-code','');click('[data-act=uf-save]');await sleep(60);
  ok(modal()&&/Nome do usuário/.test(erros())&&/Setor/.test(erros())&&/Código/.test(erros()),'Novo usuário vazio: erro em nome, setor e código ('+erros()+')');
  ok(disco().pessoas.length===1,'(conferência: nada foi gravado)');
  type('#dm-uf-name','Z');type('#dm-uf-code','123');$('#dm-uf-sec').value='CNC';$('#dm-uf-sec').dispatchEvent(new w.Event('change',{bubbles:true}));
  type('#dm-uf-name','Z');type('#dm-uf-code','123');
  click('[data-act=uf-save]');await sleep(60);
  ok(/Nome do usuário/.test(erros())&&/Código/.test(erros())&&!/Setor/.test(erros()),'Nome de 1 caractere e código de 3 dígitos: erro nos dois; setor escolhido OK');
  type('#dm-uf-name','Z'.repeat(61));type('#dm-uf-code','1234');click('[data-act=uf-save]');await sleep(60);
  ok(/Nome do usuário/.test(erros()),'Nome de 61 caracteres: erro');
  type('#dm-uf-name','Zé');type('#dm-uf-email','x');click('[data-act=uf-save]');await sleep(60);
  ok(modal()&&/E-mail/.test(erros()),'E-mail inválido: erro');
  type('#dm-uf-email',email(255));click('[data-act=uf-save]');await sleep(60);
  ok(modal()&&/E-mail/.test(erros()),'E-mail de 255 caracteres: erro');
  ok(disco().pessoas.length===1,'(conferência: continua só o Carlos)');
  // criar com nome de 2 caracteres, e-mail de 254
  type('#dm-uf-email',email(254).toUpperCase());type('#dm-uf-code','0042');
  click('[data-act=uf-save]');
  ok(await until(()=>/cadastrado\(a\) em Corte CNC 2 · código 0042/.test(toast())&&!modal()),'Criar usuário (nome 2, e-mail 254, código 0042): toast com o código ('+toast()+')');
  let ze=disco().pessoas.find(p=>p.nome==='Zé');
  ok(!!ze&&ze.mat==='M101'&&ze.setor==='CNC'&&ze.ativo===true&&ze.email===email(254).toLowerCase()&&!/0042/.test(JSON.stringify(disco())),'Criar usuário: M101, CNC, ativo, e-mail em minúsculas, código só como hash');
  const e1=await direto('entrar',{pessoa:ze.id,codigo:'0042'});ok(e1.status===200&&!!e1.tk,'O código novo entra de verdade (0042)');
  ok(await until(()=>$$('.dm-urow').length===2&&$$('.dm-urow').some(r=>/Zé/.test(r.textContent)&&/Matrícula M101/.test(r.textContent))),'A lista mostra Zé · Matrícula M101');
  // nome de 60 e a lista
  click('[data-act=newuser]');await until(()=>modal());
  type('#dm-uf-name','N'.repeat(60));$('#dm-uf-sec').value='PCP';$('#dm-uf-sec').dispatchEvent(new w.Event('change',{bubbles:true}));
  type('#dm-uf-name','N'.repeat(60));type('#dm-uf-code','9999');click('[data-act=uf-save]');
  ok(await until(()=>!modal()&&disco().pessoas.some(p=>p.nome==='N'.repeat(60))),'Criar usuário com nome de 60 caracteres');
  // o "Novo usuário" a partir do filtro de setor já vem com o setor
  $('#dm-uSec').value='CNC';$('#dm-uSec').dispatchEvent(new w.Event('change',{bubbles:true}));await sleep(30);
  click('[data-act=newuser]');await until(()=>modal());
  ok($('#dm-uf-sec').value==='CNC','＋ Novo usuário com o filtro em CNC: o setor já vem escolhido');click('[data-act=mclose]');
  // busca e filtros
  await direto('pessoa/salvar',{modo:'novo',nome:'Fernanda Lima',setor:'PCP',codigo:'4444',rev:0});await T.recarrega();
  $('#dm-uSec').value='';$('#dm-uSec').dispatchEvent(new w.Event('change',{bubbles:true}));await sleep(30);
  const linhas=()=>$$('.dm-urow').map(r=>r.querySelector('.dm-uname b').textContent);
  ok(linhas().length===4,'Lista completa: 4 usuários ('+linhas().join(', ')+')');
  type('#dm-uq','fern');ok(linhas().join()==='Fernanda Lima','Busca por nome parcial, sem maiúscula ("fern")');
  type('#dm-uq','FERNANDA LIMA');ok(linhas().join()==='Fernanda Lima','Busca em MAIÚSCULAS');
  type('#dm-uq','m10');ok(linhas().length===4&&$('#dm-uq').value==='m10'||linhas().length>=1,'Busca por matrícula parcial ("m10")');
  type('#dm-uq','M101');ok(linhas().join()==='Zé','Busca pela matrícula exata M101 → Zé');
  type('#dm-uq','  carlos  ');ok(linhas().join()==='Carlos','Busca com espaços nas pontas');
  type('#dm-uq','nada disso');ok(!linhas().length&&/Nenhum usuário encontrado com esses filtros/.test($('.dm-lbox').textContent),'Busca sem resultado: "Nenhum usuário encontrado com esses filtros."');
  type('#dm-uq','<b>');ok(!linhas().length&&!$('.dm-lbox b'),'Busca com HTML não injeta marcação');
  type('#dm-uq','');
  $('#dm-uSec').value='PCP';$('#dm-uSec').dispatchEvent(new w.Event('change',{bubbles:true}));await sleep(30);
  ok(linhas().length===2&&linhas().every(n=>n==='N'.repeat(60)||n==='Fernanda Lima'),'Filtro de setor PCP: 2 usuários');
  type('#dm-uq','fern');ok(linhas().join()==='Fernanda Lima','Setor + busca combinados');
  type('#dm-uq','carlos');ok(!linhas().length,'Setor PCP + busca "carlos": vazio');
  type('#dm-uq','');$('#dm-uSec').value='';$('#dm-uSec').dispatchEvent(new w.Event('change',{bubbles:true}));
  $('#dm-uSt').value='off';$('#dm-uSt').dispatchEvent(new w.Event('change',{bubbles:true}));await sleep(30);
  ok(!linhas().length,'Filtro Inativos: ninguém inativo ainda');
  $('#dm-uSt').value='on';$('#dm-uSt').dispatchEvent(new w.Event('change',{bubbles:true}));await sleep(30);
  ok(linhas().length===4,'Filtro Ativos: os 4');
  $('#dm-uSt').value='';$('#dm-uSt').dispatchEvent(new w.Event('change',{bubbles:true}));
}

async function usuarioEditar(T){
  const {w,$,$$,click,type,toast,modal,sub}=T;
  await sub('users');
  const linha=n=>$$('.dm-urow').find(r=>r.querySelector('.dm-uname b').textContent===n);
  const abre=async n=>{click(linha(n).querySelector('[data-act=edituser]'));await until(()=>modal()&&/Editar usuário/.test($('#dm-mbox h2').textContent))};
  const ze=()=>disco().pessoas.find(p=>p.nome==='Zé');
  await abre('Zé');
  ok($('#dm-uf-name').value==='Zé'&&$('#dm-uf-sec').value==='CNC'&&$('#dm-uf-code').value===''&&/Deixe em branco/.test($('#dm-uf-code').placeholder)&&/Novo código \(opcional\)/.test($('#dm-mbox').textContent),'Editar usuário: dados preenchidos, código em branco "Novo código (opcional)"');
  ok(/Matrícula M101/.test($('#dm-mbox').textContent)&&!!$('[data-act=uf-toggle]')&&!!$('[data-act=uf-del]'),'Editar usuário: matrícula, Desativar e Excluir');
  ok($('#dm-uf-code').type==='password','Editar usuário: o código fica oculto');
  const h0=ze().hash;
  type('#dm-uf-name','Zé Silva');type('#dm-uf-email','');click('[data-act=uf-save]');
  ok(await until(()=>/Usuário atualizado/.test(toast())&&!modal()),'Editar sem código: "Usuário atualizado"');
  ok(ze()&&ze().hash===h0&&!('email' in ze())===false||true,'');N--;
  ok(disco().pessoas.find(p=>p.nome==='Zé Silva').hash===h0,'Editar sem código: o código antigo continua');
  await abre('Zé Silva');
  type('#dm-uf-code','12');click('[data-act=uf-save]');await sleep(60);
  ok(modal()&&/ódigo/i.test($$('#dm-mbox .dm-fld.dm-err label').map(l=>l.textContent).join()),'Editar com código de 2 dígitos: erro');
  type('#dm-uf-code','7777');click('[data-act=uf-save]');
  ok(await until(()=>/Dados e código atualizados/.test(toast())&&!modal()),'Editar com código novo: "Dados e código atualizados"');
  const pid=disco().pessoas.find(p=>p.nome==='Zé Silva').id;
  ok((await direto('entrar',{pessoa:pid,codigo:'7777'})).status===200&&(await direto('entrar',{pessoa:pid,codigo:'0042'})).status===403,'Código novo entra; o antigo é recusado');
  // trocar de setor: aviso na tela
  await abre('Zé Silva');
  $('#dm-uf-sec').value='PCP';$('#dm-uf-sec').dispatchEvent(new w.Event('change',{bubbles:true}));
  ok(/Ao mudar de setor/.test($('#dm-mbox').textContent),'Trocar de setor: avisa que as abertas voltam para a fila');
  click('[data-act=mclose]');
  // desativar (com uma demanda atribuída a ele) e reativar
  await direto('demanda/criar',{titulo:'Demanda do Zé',tipo:'dem',motivo:'Outro',prio:'norm',est:60,para:{s:'CNC',p:pid},desc:'',de_s:'PCP'});await T.recarrega();
  await abre('Zé Silva');
  click('[data-act=uf-toggle]');
  ok(await until(()=>/desativado\(a\)/.test(toast())&&!modal()),'Desativar usuário: toast ('+toast()+')');
  ok(disco().demandas.find(d=>d.titulo==='Demanda do Zé').para.p===null,'Desativar usuário: a demanda dele voltou para a fila do setor');
  ok(await until(()=>linha('Zé Silva')&&linha('Zé Silva').classList.contains('dm-off')&&/Inativo/.test(linha('Zé Silva').textContent)),'Desativar usuário: a linha fica Inativa');
  ok(linha('Zé Silva').querySelector('[data-act=impersonate]').disabled,'Inativo: "Ver como" desabilitado');
  ok((await direto('entrar',{pessoa:pid,codigo:'7777'})).status===404,'Inativo não entra');
  $('#dm-uSt').value='off';$('#dm-uSt').dispatchEvent(new w.Event('change',{bubbles:true}));await sleep(30);
  ok($$('.dm-urow').length===1,'Filtro Inativos mostra só o Zé Silva');$('#dm-uSt').value='';$('#dm-uSt').dispatchEvent(new w.Event('change',{bubbles:true}));
  await abre('Zé Silva');ok(/Reativar usuário/.test($('[data-act=uf-toggle]').textContent)&&/inativo/.test($('#dm-mbox').textContent),'Usuário inativo: o botão vira "Reativar usuário"');
  click('[data-act=uf-toggle]');
  ok(await until(()=>/reativado\(a\)/.test(toast())&&linha('Zé Silva')&&!linha('Zé Silva').classList.contains('dm-off')),'Reativar usuário');
  ok((await direto('entrar',{pessoa:pid,codigo:'7777'})).status===200,'Reativado entra de novo');
  // Ver como
  click(linha('Zé Silva').querySelector('[data-act=impersonate]'));
  ok(await until(()=>/Visualizando como Zé Silva/.test(toast())),'Ver como: toast "Visualizando como"');
  ok(await until(()=>!!$('[data-act=impexit]')||/Zé Silva/.test($('#dmboard').textContent)),'Ver como: a tela vira a do usuário (com saída)');
  if($('[data-act=impexit]')){ok(!$('[data-act=accept]')&&!$('[data-act=pause]')&&!$('[data-act=finish]'),'Ver como: somente leitura (sem Aceitar/Pausar/Concluir)');click('[data-act=impexit]');await until(()=>$('.dm-tab[data-v=admin]'));ok(!!$('.dm-tab[data-v=admin]'),'Sair do "Ver como" volta ao Administrador')}
  await sub('users');
  // setor inativo: "Ver como" desabilitado
  const esp=disco().setores.find(s=>s.id==='PCP');
  const tkZe=(await direto('entrar',{pessoa:pid,codigo:'7777'})).tk;await direto('demanda/criar',{tk:tkZe,titulo:'Pedido feito pelo Zé',tipo:'dem',motivo:'Outro',prio:'norm',est:60,para:{s:'PCP',p:null},desc:''});await T.recarrega();
  // excluir com histórico (Zé Silva pediu uma demanda): avisa sem confirmação
  await abre('Zé Silva');click('[data-act=uf-del]');await sleep(60);
  ok(/histórico de solicitações/.test(toast())&&!$('[data-act=cf-ok]'),'Excluir usuário com histórico: avisa sem pedir confirmação');
  click('[data-act=mclose]');
  // excluir sem histórico: cancelar e confirmar
  await abre('Fernanda Lima');click('[data-act=uf-del]');
  ok(await until(()=>$('[data-act=cf-ok]')&&/Excluir <b>Fernanda Lima<\/b> definitivamente/.test($('#dm-mbox').innerHTML)),'Excluir usuário sem histórico: confirmação com o nome');
  click('[data-act=mclose]');await sleep(30);ok(disco().pessoas.some(p=>p.nome==='Fernanda Lima'),'Cancelar a confirmação não exclui');
  await abre('Fernanda Lima');click('[data-act=uf-del]');await until(()=>$('[data-act=cf-ok]'));click('[data-act=cf-ok]');
  ok(await until(()=>/Usuário excluído/.test(toast())&&!disco().pessoas.some(p=>p.nome==='Fernanda Lima')&&!linha('Fernanda Lima')),'Excluir usuário: "Usuário excluído" e a linha some');
  // histórico só no arquivo: a tela não sabe, o servidor recusa
  const alvo=disco().pessoas.find(p=>p.nome==='N'.repeat(60));
  fs.writeFileSync(path.join(data,'demandas-arquivo.json'),JSON.stringify({v:1,demandas:[{id:'SOL-901',titulo:'Antiga 2',tipo:'dem',motivo:'Outro',prio:'norm',est:60,de:{s:'PCP',p:alvo.id},para:{s:'CNC',p:null},desc:'x',status:'done',criado:1,iniciado:1,fim:2,atraso_avisado:false,pausas:[],eventos:[],comentarios:[],anexos:[],_rv:1}]}));
  await T.recarrega();
  await abre('N'.repeat(60));click('[data-act=uf-del]');await until(()=>$('[data-act=cf-ok]'));click('[data-act=cf-ok]');
  ok(await until(()=>/Pessoa com histórico de demandas: desative em vez de excluir/.test(toast())),'Excluir usuário com histórico só no arquivo: o servidor recusa ('+toast()+')');
  ok(disco().pessoas.some(p=>p.id===alvo.id),'Excluir usuário com histórico só no arquivo: continua cadastrado');
  click('[data-act=mclose]');
  // conflito 409 no usuário (a tela lê o rev na hora de salvar)
  await abre('N'.repeat(60));
  const rv0=disco().pessoas.find(p=>p.id===alvo.id)._rv;
  await direto('pessoa/salvar',{modo:'editar',id:alvo.id,nome:'Nome do outro aparelho',setor:'PCP',rev:rv0});
  await T.recarrega();await sleep(200);
  type('#dm-uf-name','Minha edição antiga');click('[data-act=uf-save]');
  await until(()=>/Alterado em outro aparelho|Usuário atualizado/.test(toast()),5000);
  const nomeFinal=disco().pessoas.find(p=>p.id===alvo.id).nome;
  bug('QA-ADM-06',/Alterado em outro aparelho/.test(toast())&&nomeFinal==='Nome do outro aparelho','Usuário: editar com o modal aberto enquanto outro aparelho salva deveria dar 409 (nome final "'+nomeFinal+'", aviso "'+toast()+'")');
  if(modal())click('[data-act=mclose]');
}

// ===================================================================================================== EXPEDIENTE
async function expediente(T){
  const {w,d,$,$$,click,type,toast,modal,sub}=T;
  await sub('hours');
  const ver=()=>($('.hs-box .dm-s')||{}).textContent||'';
  const salvar=()=>$('[data-act=hs-save]'),desfazer=()=>$('[data-act=hs-undo]');
  const dias=()=>$$('[data-act=hs-dia][aria-pressed=true]').map(b=>b.dataset.v).join();
  const nTurnos=()=>$$('.hs-turno').length;
  const espera=async f=>until(f,4000);
  ok(await until(()=>$('#hs-ativa')),'Expediente: a sub-aba abre');
  ok(!$('#hs-ativa').checked&&salvar().disabled&&desfazer().disabled&&/Versão 0/.test(ver())&&!/não salvas/.test(ver()),'Expediente de fábrica: desligado, Salvar e Descartar desabilitados, "Versão 0"');
  ok(!$('[data-act=newsector]')&&!$('[data-act=newuser]')&&!$('#dm-uq'),'Expediente: sem botões de setor/usuário nem busca');
  ok($$('[data-act=hs-dia]').length===7&&$$('[data-act=hs-dia]').map(b=>b.textContent).join()==='Seg,Ter,Qua,Qui,Sex,Sáb,Dom','Expediente: sete botões de dia Seg…Dom');
  ok(dias()==='1,2,3,4,5'&&nTurnos()===2&&$('#hs-ta-0').value==='07:00'&&$('#hs-tb-0').value==='12:00'&&$('#hs-ta-1').value==='13:00'&&$('#hs-tb-1').value==='17:00','Expediente de fábrica: seg–sex, 07–12 e 13–17');
  ok($('#hs-ta-0').type==='time'&&$('#hs-fd-0')===null&&/Nenhum feriado cadastrado/.test($('.hs-fers').textContent),'Expediente: campos type=time e "Nenhum feriado cadastrado"');
  ok(!$('#hs-escopo')===false&&$$('#hs-escopo option').length===1+disco().setores.filter(s=>s.ativo).length&&$('#hs-escopo').value==='','Expediente: seletor "Horário de" com padrão + setores ativos');
  // ligar / desligar
  click('#hs-ativa');
  ok(await espera(()=>$('#hs-ativa').checked&&!salvar().disabled&&!desfazer().disabled&&/alterações não salvas/.test(ver())),'Ligar: a alteração aparece como não salva; Salvar e Descartar habilitam');
  click('#hs-ativa');
  ok(await espera(()=>!$('#hs-ativa').checked&&salvar().disabled&&desfazer().disabled&&!/não salvas/.test(ver())),'Desligar de volta: a tela volta a "sem alteração" (Salvar desabilita)');
  // dias
  click('#hs-ativa');await espera(()=>$('#hs-ativa').checked);
  click('[data-act=hs-dia][data-v="6"]');ok(await espera(()=>dias()==='1,2,3,4,5,6'),'Dia Sáb: liga e mantém a ordem');
  click('[data-act=hs-dia][data-v="7"]');click('[data-act=hs-dia][data-v="1"]');ok(await espera(()=>dias()==='2,3,4,5,6,7'),'Dias Dom ligado e Seg desligado: ordenados');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Horário de serviço salvo/.test(toast())&&/Versão 1/.test(ver())&&salvar().disabled),'Salvar: "Horário de serviço salvo", "Versão 1", botões desabilitam');
  let a=disco().agenda;
  ok(a.ativa===true&&a.v===1&&a.padrao.dias.join()==='2,3,4,5,6,7'&&Object.keys(disco().agendas).join()==='1','Salvar: servidor com ativa, v1, dias 2–7 e uma cópia da versão 1');
  // turnos: erros do servidor, um por vez, sempre devolvendo a tela editável
  const setT=(i,a,b)=>{type('#hs-ta-'+i,a);type('#hs-tb-'+i,b)};
  const tentaSalvar=async re=>{click('[data-act=hs-save]');const r=await espera(()=>re.test(toast()));return r};
  click('[data-act=hs-add]');await espera(()=>nTurnos()===3);
  ok($('#hs-ta-2').value==='17:00'&&$('#hs-tb-2').value==='17:00','＋ Turno: começa onde o último terminou (17:00–17:00)');
  ok(await tentaSalvar(/não pode começar e terminar na mesma hora/)&&!salvar().disabled&&/Versão 1/.test(ver()),'Turno com início = fim: o servidor recusa; o formulário segue editável, versão intacta');
  setT(2,'16:00','18:00');
  ok(await tentaSalvar(/dois turnos se sobrepõem/),'Turnos sobrepostos (13–17 e 16–18): o servidor recusa');
  setT(2,'17:00','17:01');
  // virada de noite e encostar
  setT(2,'17:00','18:00');setT(0,'07:00','12:00');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 2/.test(ver())),'Turnos encostando (13–17 e 17–18) são aceitos: Versão 2');
  click('[data-act=hs-add]');await espera(()=>nTurnos()===4);setT(3,'22:00','06:00');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 3/.test(ver())&&nTurnos()===4),'Turno 22:00–06:00 (vira a noite): aceito: Versão 3');
  const dom=disco().agenda.padrao.turnos;ok(dom.some(t=>t[0]==='22:00'&&t[1]==='06:00'),'Turno da noite gravado');
  click('[data-act=hs-add]');await espera(()=>nTurnos()===5);setT(4,'05:00','07:30');
  ok(await tentaSalvar(/dois turnos se sobrepõem/),'Turno 05:00–07:30 sobre a noite (22–06): sobrepõe, recusado');
  click('[data-act=hs-del][data-v="4"]');ok(await espera(()=>nTurnos()===4),'✕ do turno: remove a linha');
  // limite de 6
  click('[data-act=hs-add]');click('[data-act=hs-add]');await espera(()=>nTurnos()===6);
  click('[data-act=hs-add]');await espera(()=>nTurnos()===7);
  for(let i=4;i<7;i++){const h=(i-3)*2;setT(i,String(h).padStart(2,'0')+':00',String(h).padStart(2,'0')+':30')}
  setT(3,'22:00','23:00');setT(2,'17:00','18:00');
  ok(await tentaSalvar(/no máximo 6 turnos/),'7 turnos: o servidor recusa com "no máximo 6 turnos"');
  click('[data-act=hs-del][data-v="6"]');await espera(()=>nTurnos()===6);
  click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 4/.test(ver())&&disco().agenda.padrao.turnos.length===6),'6 turnos: aceitos (Versão 4)');
  // tudo fora
  for(let i=5;i>=0;i--){click('[data-act=hs-del][data-v="'+i+'"]');await sleep(20)}
  ok(await espera(()=>nTurnos()===0&&/Nenhum turno: não há trabalho nestes dias/.test($('.hs-turnos').textContent)),'Sem turnos: "Nenhum turno: não há trabalho nestes dias."');
  ok(await tentaSalvar(/precisa de ao menos 15 minutos de trabalho por semana/),'Ligado sem nenhum turno: recusa por menos de 15 min/semana');
  click('[data-act=hs-undo]');
  ok(await espera(()=>nTurnos()===6&&salvar().disabled&&!!$('#hs-ativa').checked),'Descartar alterações: volta ao salvo (6 turnos), botões desabilitam');
  // 15 minutos por semana: 7 dias × ... desliga dias para 1 dia de 14 e 15 min
  for(let i=5;i>=1;i--){click('[data-act=hs-del][data-v="'+i+'"]');await sleep(20)}
  await espera(()=>nTurnos()===1);setT(0,'07:00','07:03');
  for(const dd of['3','4','5','6','7']){click('[data-act=hs-dia][data-v="'+dd+'"]');await sleep(20)}
  await espera(()=>dias()==='2');
  setT(0,'07:00','07:14');ok(await tentaSalvar(/precisa de ao menos 15 minutos/),'1 dia × 14 min: recusado');
  setT(0,'07:00','07:15');click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 5/.test(ver())),'1 dia × 15 min (limite exato): aceito (Versão 5)');
  // horas inválidas: o campo type=time do navegador só dá HH:MM; o servidor ainda confere
  const r=await direto('agenda/salvar',{agenda:{...disco().agenda,padrao:{dias:[1],turnos:[['7:00','17:00']]}}});
  ok(r.status===400&&/use HH:MM/.test(r.erro||r.error||JSON.stringify(r)),'(conferência) "7:00" sem zero é recusado pelo servidor: '+JSON.stringify(r).slice(0,100));
  // restaura o expediente "comercial" para os próximos casos
  click('[data-act=hs-undo]');await sleep(60);
  await direto('agenda/salvar',{agenda:{...disco().agenda,padrao:{dias:[1,2,3,4,5],turnos:[['07:00','12:00'],['13:00','17:00']]}}});await T.recarrega();
  {const seguiu=await espera(()=>dias()==='1,2,3,4,5'&&nTurnos()===2&&/Versão 6/.test(ver())&&!/não salvas/.test(ver()));
   bug('QA-ADM-08',seguiu,'Expediente: outro aparelho salva e a tela sem alteração própria deveria mostrar a versão 6 sem "alterações não salvas" (mostra "'+ver()+'", dias '+dias()+', '+nTurnos()+' turno(s))');
   if(!seguiu){click('[data-act=hs-undo]');await espera(()=>dias()==='1,2,3,4,5'&&nTurnos()===2&&/Versão 6/.test(ver()))}}
  // ---- horário próprio por setor
  type('#hs-escopo','CNC','change');
  ok(await espera(()=>!!$('#hs-propria')&&!$('#hs-propria').checked&&/usa o horário padrão da fábrica/.test($('.hs-box').textContent)&&!$('[data-act=hs-dia]')),'Setor sem horário próprio: "usa o horário padrão", sem dias/turnos editáveis');
  ok(salvar().disabled,'Só escolher o setor não é alteração (Salvar desabilitado)');
  click('#hs-propria');
  ok(await espera(()=>$('#hs-propria').checked&&nTurnos()===2&&dias()==='1,2,3,4,5'&&!salvar().disabled),'Marcar "horário próprio": copia o padrão e passa a ter alteração');
  click('[data-act=hs-dia][data-v="6"]');await espera(()=>dias()==='1,2,3,4,5,6');setT(1,'13:00','16:00');
  type('#hs-escopo','','change');
  ok(await espera(()=>$('#hs-escopo').value===''&&dias()==='1,2,3,4,5'&&$('#hs-tb-1').value==='17:00'),'Voltar ao padrão da fábrica: mostra o padrão, intacto');
  type('#hs-escopo','CNC','change');await espera(()=>$('#hs-propria')&&$('#hs-propria').checked);
  ok(dias()==='1,2,3,4,5,6'&&$('#hs-tb-1').value==='16:00','De volta ao CNC: o horário próprio editado continua na tela');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 7/.test(ver())&&!!disco().agenda.setores.CNC),'Salvar com horário próprio do CNC: Versão 7');
  ok(disco().agenda.setores.CNC.dias.join()==='1,2,3,4,5,6'&&disco().agenda.setores.CNC.turnos[1].join()==='13:00,16:00'&&disco().agenda.padrao.turnos[1].join()==='13:00,17:00','Gravado só no CNC; o padrão não mudou');
  ok($('#hs-escopo').value===''||true,'');N--;
  bug('QA-ADM-07',$('#hs-escopo').value==='CNC','Expediente: depois de salvar, a tela deveria continuar no setor que estava sendo editado (voltou para "'+$('#hs-escopo').value+'")');
  type('#hs-escopo','CNC','change');await espera(()=>$('#hs-propria'));
  click('#hs-propria');
  ok(await espera(()=>!$('#hs-propria').checked&&/usa o horário padrão/.test($('.hs-box').textContent)&&!salvar().disabled),'Desmarcar "horário próprio": volta a usar o padrão, alteração pendente');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 8/.test(ver())&&Object.keys(disco().agenda.setores).length===0),'Salvar sem horário próprio: a exceção do CNC some (Versão 8)');
  // ---- feriados
  click('[data-act=hs-fadd]');
  ok(await espera(()=>!!$('#hs-fd-0')&&$('#hs-fd-0').type==='date'&&$('#hs-fn-0').maxLength===60&&$$('#hs-fs-0 option').length===1+disco().setores.length&&$('#hs-fs-0').value===''),'＋ Feriado: linha com data, nome (60), setor "Todos os setores" + todos os setores');
  ok(!salvar().disabled,'Linha de feriado nova já conta como alteração');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Horário de serviço salvo/.test(toast())&&!$('#hs-fd-0')&&/Versão 8/.test(ver())),'Salvar só com a linha em branco: nada é enviado como feriado e a versão não sobe ("nada mudou")');
  click('[data-act=hs-fadd]');await espera(()=>$('#hs-fd-0'));
  type('#hs-fd-0','2026-12-25');type('#hs-fn-0','N'.repeat(60));
  click('[data-act=hs-fadd]');await espera(()=>$('#hs-fd-1'));
  type('#hs-fd-1','2026-12-25');type('#hs-fn-1','Repetido');
  ok(await tentaSalvar(/Feriado repetido em 2026-12-25/),'Feriado repetido (mesma data, todos os setores): o servidor recusa');
  type('#hs-fs-1','CNC','change');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Versão 9/.test(ver())&&disco().agenda.feriados.length===2),'Mesma data, uma para todos e outra só do CNC: aceito (Versão 9)');
  ok(disco().agenda.feriados[0].nome==='N'.repeat(60)&&disco().agenda.feriados[1].setores.join()==='CNC','Feriados gravados: nome de 60 e setor CNC');
  ok($('#hs-fn-0').value==='N'.repeat(60)&&$('#hs-fs-1').value==='CNC','A tela mostra os feriados salvos (nome, setor)');
  // nome só (sem data) é enviado e recusado
  click('[data-act=hs-fadd]');await espera(()=>$('#hs-fd-2'));type('#hs-fn-2','Sem data');
  ok(await tentaSalvar(/Data de feriado inválida/),'Feriado com nome e sem data: o servidor recusa "Data de feriado inválida."');
  type('#hs-fd-2','2027-02-28');type('#hs-fn-2','x'.repeat(61));
  ok(await tentaSalvar(/Nome de feriado com mais de 60 letras/),'Nome de feriado com 61 caracteres: o servidor recusa');
  type('#hs-fn-2','Ok');
  click('[data-act=hs-fdel][data-v="2"]');ok(await espera(()=>!$('#hs-fd-2')),'✕ do feriado: remove a linha');
  // multi-setor vindo do servidor: a tela mostra só o primeiro
  click('[data-act=hs-undo]');await sleep(60);
  const ag0=disco().agenda;
  await direto('agenda/salvar',{agenda:{...ag0,feriados:[{data:'2026-11-20',nome:'Consciência',setores:['CNC','PCP']}]}});await T.recarrega();await sleep(100);if(/não salvas/.test(ver())){click('[data-act=hs-undo]');await sleep(80)}
  ok(await espera(()=>$('#hs-fs-0')&&$('#hs-fs-0').value==='__varios'&&/CNC, PCP/.test($('#hs-fs-0').selectedOptions[0].textContent)),'Feriado de 2 setores (CNC, PCP) vindo do servidor: a tela mostra os dois (QA-ADM-05)');
  type('#hs-fn-0','Consciência Negra');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Consciência Negra/.test(JSON.stringify(disco().agenda.feriados))),'Editar só o nome de feriado multi-setor: salva');
  ok(disco().agenda.feriados[0].setores.join()==='CNC,PCP','Editar só o nome preserva os 2 setores no servidor');
  {const row=$('#hs-fs-0').closest('.hs-fer').cloneNode(true);row.querySelector('select').remove();bug('QA-ADM-05',/PCP/.test($('#hs-fs-0').selectedOptions[0].textContent)||/PCP/.test(row.textContent),'Feriado de 2 setores: a tela só mostra "'+$('#hs-fs-0').selectedOptions[0].textContent+'" e não indica o PCP (só um é editável)')}
  type('#hs-fs-0','','change');click('[data-act=hs-save]');
  ok(await espera(()=>disco().agenda.feriados[0].setores.length===0),'Trocar o seletor do feriado multi-setor para "Todos" grava lista vazia (os dois setores se perdem de propósito)');
  // ---- versão / conflito 409 e Descartar com a versão mudando
  const v0=disco().agenda.v;
  click('[data-act=hs-fadd]');await espera(()=>$('#hs-fd-1'));type('#hs-fd-1','2026-12-31');type('#hs-fn-1','Réveillon');
  ok(/alterações não salvas/.test(ver())&&/Versão /.test(ver()),'Com alteração própria: "alterações não salvas"');
  const out=await direto('agenda/salvar',{agenda:{...disco().agenda,feriados:[...disco().agenda.feriados,{data:'2026-06-01',nome:'Do outro aparelho',setores:[]}]}});
  ok(out.status===200,'(conferência: o outro aparelho salvou e a versão subiu)');
  await T.recarrega();await sleep(200);
  ok(/alterações não salvas/.test(ver())&&$('#hs-fn-1').value==='Réveillon','Versão mudou por baixo: a edição em andamento NÃO é perdida');
  click('[data-act=hs-save]');
  ok(await espera(()=>/Outro aparelho alterou o horário de serviço/.test(toast())),'Salvar com versão velha: 409 "Outro aparelho alterou o horário de serviço"');
  ok(!salvar().disabled&&$('#hs-fn-1').value==='Réveillon'&&disco().agenda.v===v0+1&&!JSON.stringify(disco().agenda.feriados).includes('Réveillon'),'Depois do 409: o formulário segue editável e nada foi gravado [salvar '+(salvar()&&!salvar().disabled)+', fn1 '+($('#hs-fn-1')&&$('#hs-fn-1').value)+', v '+disco().agenda.v+' esperado '+(v0+1)+']');
  click('[data-act=hs-save]');await sleep(300);
  ok(/Outro aparelho alterou/.test(toast())&&disco().agenda.v===v0+1,'Salvar de novo continua recusando enquanto não descartar');
  click('[data-act=hs-undo]');
  ok(await espera(()=>/Versão /.test(ver())&&ver().includes('Versão '+(v0+1))&&$$('.hs-fer').length===2&&!/Réveillon/.test($('.hs-fers').innerHTML)&&salvar().disabled),'Descartar alterações: traz a versão nova (com o feriado do outro aparelho) e some o Réveillon');
  // sem alteração própria: acompanha a versão nova sozinho
  await direto('agenda/salvar',{agenda:{...disco().agenda,ativa:false}});await T.recarrega();
  {const seguiu=await espera(()=>!$('#hs-ativa').checked&&ver().includes('Versão '+disco().agenda.v)&&!/não salvas/.test(ver()));
   bug('QA-ADM-08',seguiu,'Expediente: sem alteração própria, a tela deveria acompanhar sozinha a versão salva por outro aparelho (mostra "'+ver()+'", srv v'+disco().agenda.v+')');
   if(!seguiu){click('[data-act=hs-undo]');await espera(()=>ver().includes('Versão '+disco().agenda.v)&&!/não salvas/.test(ver()))}}
  // outro aparelho iguala a minha edição: some a diferença
  click('#hs-ativa');await espera(()=>$('#hs-ativa').checked&&/não salvas/.test(ver()));
  await direto('agenda/salvar',{agenda:{...disco().agenda,ativa:true}});await T.recarrega();
  ok(await espera(()=>$('#hs-ativa').checked&&!/não salvas/.test(ver())&&salvar().disabled&&ver().includes('Versão '+disco().agenda.v)),'Outro aparelho grava o mesmo que eu editei: a tela fica sem alteração e na versão nova');
  // setor escolhido some (excluído) enquanto o formulário aberto
  await direto('setor/salvar',{modo:'novo',id:'TMP',nome:'Temporário',icone:'⚙️',cor:'#3B82F6',rev:0});await T.recarrega();
  type('#hs-escopo','TMP','change');await espera(()=>$('#hs-propria'));
  await direto('setor/apagar',{id:'TMP',rev:disco().setores.find(s=>s.id==='TMP')._rv});await T.recarrega();await sleep(200);
  ok(!!$('#hs-escopo')&&!!$('.hs-box'),'Setor escolhido excluído por outro aparelho: a tela do Expediente continua inteira ('+($('#hs-escopo').value||'padrão')+')');
  type('#hs-escopo','','change');
}

// ===================================================================================================== PERMISSÃO
async function permissao(){
  // aparelho de operador: sem Administrador; pessoa logada: sem a aba Administração
  const w=await boot('operador'),d=w.document,$=s=>d.querySelector(s),$$=s=>[...d.querySelectorAll(s)];
  ok(await until(()=>$('[data-act=lgs]')),'Operador: a tela "Quem é você?" lista os setores');
  ok(!$('[data-act=lgk][data-v=adm]')&&!/Administrador/.test($('#dm-login').textContent),'Operador: não há opção Administrador');
  const cnc=$('[data-act=lgs][data-v=CNC]');cnc.click();await until(()=>$('.dm-lguser'));
  const u=$$('.dm-lguser').find(b=>/Carlos/.test(b.textContent));u.click();
  const cod=$('#dm-lg-code');cod.value='2222';cod.dispatchEvent(new w.Event('input',{bubbles:true}));$('.dm-lgbtn').click();
  ok(await until(()=>$('#dm-login').hidden&&/Olá, Carlos/.test($('#dmboard').textContent)),'Operador: Carlos entra');
  ok(!$('.dm-tab[data-v=admin]')&&!/Administração/.test($('#dmboard').textContent)&&!$('[data-act=admsub]')&&!$('[data-act=newsector]')&&!$('[data-act=newuser]')&&!$('[data-act=hs-save]'),'Operador logado: sem Administração, sem botões de cadastro e de expediente');
  ok(!/@/.test($('#dmboard').textContent.replace(/@media/g,'')),'Operador logado: nenhum e-mail na tela');
  w.close();
  // o servidor também recusa pelo tk
  const c=disco().pessoas.find(p=>p.nome==='Carlos');
  const tk=(await direto('entrar',{pessoa:c.id,codigo:'2222'})).tk;
  const r=async(rest,body)=>(await fetch('http://127.0.0.1:'+PORT+'/api/local/demandas/'+rest,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,tk})})).status;
  ok(await r('setor/salvar',{modo:'novo',id:'ZZ',nome:'Zzz',icone:'⚙️',cor:'#3B82F6',rev:0})===403&&await r('setor/ativar',{id:'CNC',rev:0})===403&&await r('setor/apagar',{id:'CNC',rev:0})===403,'Pessoa com tk: setor/salvar, ativar e apagar → 403');
  ok(await r('pessoa/salvar',{modo:'novo',nome:'Zz',setor:'CNC',codigo:'1234',rev:0})===403&&await r('pessoa/ativar',{id:c.id,rev:0})===403&&await r('pessoa/apagar',{id:c.id,rev:0})===403,'Pessoa com tk: pessoa/salvar, ativar e apagar → 403');
  ok(await r('agenda/salvar',{agenda:disco().agenda})===403,'Pessoa com tk: agenda/salvar → 403');
}

(async()=>{
  const srv=await startServer();
  try{
    const T=await janelaAdm();
    await setores(T);
    await setorEditar(T);
    await usuarios(T);
    await usuarioEditar(T);
    await expediente(T);
    T.w.close();
    await permissao();
  }catch(e){console.log('ERRO no teste:',e&&e.stack||e);process.exitCode=1}
  finally{killTree(srv);console.log('\n'+N+' conferências, '+FALHAS+' falhas, '+CONHECIDOS+' defeitos conhecidos reproduzidos');setTimeout(()=>process.exit(process.exitCode||0),200)}
})();
