'use strict';
/* Casca da Central de demandas. O módulo (demandas.js) espera do ambiente:
   - api(caminho, corpo): GET sem corpo, POST com JSON e o cabeçalho X-Tab; erro vira Error com .status e o texto do servidor;
   - toast(texto): aviso curto quando a tela do módulo não está aberta;
   - NestLocal.views.demandas: o módulo se registra ali; a casca chama refresh() quando o demandas.json muda (/api/rev).
   Também: o painel "⚙ Rede" (ligar o acesso pela rede e ver os PINs), só no computador principal. */
const $ = id => document.getElementById(id);
const TAB = crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2);
window.NestLocal = window.NestLocal || {views: {}};

async function api(path, body){
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Tab': TAB}, body: JSON.stringify(body)};
  let r;
  try{r = await fetch(path, opt)}catch(_){throw Error('O servidor está desligado. Abra o iniciar.bat e tente de novo.')}
  if(!r.ok){const e = Error(await r.text()); e.status = r.status; throw e}
  return r.json();
}
window.api = api;

function toast(text){
  const t = $('cx-toast');
  t.textContent = String(text || ''); t.hidden = !text;
  clearTimeout(toast.h); toast.h = setTimeout(() => {t.hidden = true}, 2600);
}
window.toast = toast;

/* atualização entre aparelhos: uma pergunta leve a cada 3 s */
let REV = null;
async function vigia(){
  try{
    const r = await api('/api/rev');
    const v = window.NestLocal.views.demandas;
    if(REV !== null && r.rev !== REV && v && v.rev() !== r.rev) await Promise.resolve(v.refresh()).catch(() => {});
    REV = r.rev;
  }catch(_){/* servidor fora do ar: tenta de novo no próximo ciclo */}
}

/* ---------- ⚙ Rede (só no computador principal) ---------- */
function mostraRede(n){
  $('cx-on').checked = n.on;
  $('cx-pins').hidden = !n.on;
  $('cx-pin').textContent = n.pin || '';
  $('cx-pinop').textContent = n.pin_op || '';
  const urls = $('cx-urls');
  urls.textContent = '';
  if(n.on && n.active){
    urls.append('Nos outros aparelhos, abra no navegador:');
    for(const u of n.urls || []){const c = document.createElement('code'); c.textContent = u; urls.append(c)}
    if(!(n.urls || []).length) urls.append(' nenhum endereço de rede encontrado neste computador.');
  }
  $('cx-msg').textContent = n.on && !n.active ? 'Feche e abra o programa (iniciar.bat) para ligar o acesso.'
    : !n.on && n.active ? 'Feche e abra o programa (iniciar.bat) para desligar o acesso.' : '';
}
async function rede(body, pergunta){
  if(pergunta && !confirm(pergunta)) return;
  try{mostraRede(await api('/api/rede', body))}catch(e){toast(e.message)}
}
$('cx-rede').onclick = async () => {try{mostraRede(await api('/api/rede')); $('cx-fundo').hidden = false}catch(e){toast(e.message)}};
$('cx-fechar').onclick = () => {$('cx-fundo').hidden = true};
$('cx-fundo').onclick = e => {if(e.target === $('cx-fundo')) $('cx-fundo').hidden = true};
document.addEventListener('keydown', e => {if(e.key === 'Escape') $('cx-fundo').hidden = true});
$('cx-on').onchange = e => rede({on: e.target.checked});
$('cx-novo').onclick = () => rede({newpin: true}, 'Gerar um PIN do escritório novo? Todos os aparelhos que já entraram vão precisar do PIN novo.');
$('cx-novoop').onclick = () => rede({newpin_op: true}, 'Gerar um PIN dos operadores novo? Os aparelhos de operador que já entraram vão precisar do PIN novo.');

(async () => {
  const eu = await api('/api/eu').catch(() => null);
  if(eu && eu.papel === 'maquina') $('cx-rede').hidden = false;   // o servidor recusa /api/rede vindo da rede de qualquer jeito
  // o módulo carrega logo depois e se abre sozinho (o <main> já está em data-view="demandas")
  for(let i = 0; i < 100 && !window.NestLocal.views.demandas; i++) await new Promise(r => setTimeout(r, 50));
  if(!window.NestLocal.views.demandas) toast('Não foi possível abrir a Central de demandas.');
  vigia();
  setInterval(vigia, 3000);
})();
