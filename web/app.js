'use strict';
/* Casca da Central de demandas. O módulo (demandas.js) espera do ambiente:
   - api(caminho, corpo): GET sem corpo, POST com JSON e o cabeçalho X-Tab; erro vira Error com .status e o texto do servidor;
   - toast(texto): aviso curto quando a tela do módulo não está aberta;
   - NestLocal.views.demandas: o módulo se registra ali; a casca chama refresh() quando o demandas.json muda (/api/rev).
   Também: o botão "⚙ Configurações" (Rede e Backup), só no computador principal; o diálogo é do módulo (config()). */
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

/* ---------- ⚙ Configurações (só no computador principal) ---------- */
$('cx-cfg').onclick = () => {
  const v = window.NestLocal.views.demandas;
  if(v && v.config) v.config('rede'); else toast('A Central de demandas ainda está abrindo.');
};

(async () => {
  const eu = await api('/api/eu').catch(() => null);
  if(eu && eu.papel === 'maquina') $('cx-cfg').hidden = false;   // o servidor recusa /api/rede e /api/backup vindos da rede de qualquer jeito
  // o módulo carrega logo depois e se abre sozinho (o <main> já está em data-view="demandas")
  for(let i = 0; i < 100 && !window.NestLocal.views.demandas; i++) await new Promise(r => setTimeout(r, 50));
  if(!window.NestLocal.views.demandas) toast('Não foi possível abrir a Central de demandas.');
  vigia();
  setInterval(vigia, 3000);
})();
