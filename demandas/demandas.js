/* Central de demandas: tela do programa (porte do projeto DEMANDA).
   Script clássico numa IIFE: o único global novo é window.NestLocal.views.demandas = {open, rev, refresh}.
   Dados vêm de /api/local/demandas/... pelo api() do app.js (contrato em local/demandas/CONTRATO.md).
   Todo texto vindo da API entra por esc() ou textContent; cores passam por col(); nada de eval. */
(function(){
'use strict';
const BASE = '/api/local/demandas/';
const MIN = 60000, HOUR = 3600000, DAY = 86400000;
const TYPE = {dem: ['📌', 'Demanda'], alt: ['✏️', 'Alteração'], set: ['🔁', 'Entre setores'], man: ['🛠️', 'Manutenção'], mat: ['📦', 'Material']};
const REASONS = ['Falta de material', 'Quebra de máquina', 'Defeito de qualidade', 'Mudança de projeto', 'Ajuste de planejamento', 'Retrabalho', 'Solicitação do cliente', 'Outro'];
const PAUSE_REASONS = ['Aguardando material', 'Aguardando outro setor', 'Máquina parada', 'Aguardando aprovação', 'Troca de turno ou intervalo', 'Informação incompleta'];
const PRIO = {low: ['Baixa', 0], norm: ['Normal', 1], high: ['Alta', 2], urg: ['Urgente', 3]};
const STL = {new: 'Aberta', prog: 'Em andamento', pause: 'Pausada', late: 'Atrasada', done: 'Concluída', canc: 'Cancelada'};
const EVL = {created: 'Solicitação criada', assigned: 'Responsável definido', started: 'Iniciada', paused: 'Pausada', resumed: 'Retomada', done: 'Concluída', canc: 'Cancelada', reassigned: 'Reatribuída', prio: 'Prioridade alterada', deadline: 'Prazo ajustado', nudge: 'Cobrança enviada', late: 'Prazo estourado', attach: 'Anexo enviado'};
const NT = {urg: ['🚨', 'Solicitação urgente'], late: ['⏰', 'Prazo estourado'], pause: ['⏸', 'Solicitação pausada'], new: ['📥', 'Nova solicitação'], nudge: ['🔔', 'Cobrança'], canc: ['✕', 'Solicitação cancelada'], accepted: ['▶', 'Solicitação iniciada'], done: ['✅', 'Solicitação concluída']};
const ALERT_KINDS = ['urg', 'late', 'pause', 'new', 'nudge', 'canc'];
const ICONS = ['🗂️', '⚙️', '🔩', '🪵', '🪚', '🧽', '🛠️', '🧵', '✂️', '🪡', '📦', '✅', '🔧', '🏷️', '🚚', '🎨', '🧪', '🖥️', '🧰', '🏭'];
const COLORS = ['#6366F1', '#3B82F6', '#0EA5E9', '#06B6D4', '#0D9488', '#10B981', '#65A30D', '#D97706', '#E4572E', '#EC4899', '#8B5CF6', '#64748B'];
const ANX = {max: 5 * 1024 * 1024, n: 5, ext: /\.(jpe?g|png|pdf)$/i, mime: {jpg: 'image/jpeg', png: 'image/png', pdf: 'application/pdf'}};
const AID = /^a[0-9a-f]{16}$/;
const DOW = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
const SUB_ADM = 'Acompanhe, priorize e analise as solicitações entre setores em tempo real.';
const SUB_OP = 'Receba, execute e acompanhe as solicitações do seu setor.';

/* ---------- estado (só memória da página: o tk nunca vai para storage) ---------- */
const D = {
  booted: false, srv: null, euPronto: false, pub: null, v: null, at: 0, tk: null, eu: null, role: null, imp: null,
  tab: 'painel', opTab: 'recv', opF: 'mine', view: 'board', mapSort: 'crit', q: '', fSt: '', fSec: '', fPrio: '', fType: '',
  hq: '', hSt: '', hFrom: '', hTo: '', hArq: '', arq: null, period: 7, crono: null, cronoP: 0,
  admSub: 'sectors', uq: '', uSec: '', uSt: '', open: null, notif: false, mod: null, form: null, sform: null, uform: null,
  lg: {k: 'op', sec: '', user: '', code: '', show: false, err: ''}, seen: null, feedSeen: null, lastKey: '', noIntro: false,
  dirty: false, ticks: 0, pubErr: '',
};
let root = null;

/* ---------- utilidades ---------- */
const $ = id => document.getElementById(id);
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const col = c => /^#[0-9a-fA-F]{6}$/.test(String(c || '')) ? c : '#64748B';
const num = (v, d) => {const n = Number(v); return isFinite(n) ? n : (d === undefined ? 0 : d)};
const p2 = n => String(n).padStart(2, '0');
const now = () => D.v ? num(D.v.agora, Date.now()) + (Date.now() - D.at) : Date.now();
const fT = ms => {const d = new Date(ms); return p2(d.getHours()) + ':' + p2(d.getMinutes())};
const fD = ms => {const d = new Date(ms); return p2(d.getDate()) + '/' + p2(d.getMonth() + 1)};
const sameDay = (a, b) => fD(a) === fD(b) && new Date(a).getFullYear() === new Date(b).getFullYear();
const fDT = ms => ms ? (sameDay(ms, now()) ? 'hoje ' + fT(ms) : fD(ms) + ' ' + fT(ms)) : '—';
const fFull = ms => {if(!ms) return '—'; const d = new Date(ms); return p2(d.getDate()) + '/' + p2(d.getMonth() + 1) + '/' + d.getFullYear() + ' ' + fT(ms)};
function dur(m){
  if(m == null || !isFinite(Number(m))) return '—';
  m = Math.max(0, Math.round(Number(m)));
  if(m < 60) return m + ' min';
  const h = Math.floor(m / 60), r = m % 60;
  if(h >= 48) return Math.floor(h / 24) + 'd ' + (h % 24) + 'h';
  return h + 'h' + (r ? ' ' + p2(r) + 'min' : '');
}
const avg = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : NaN;
const fBytes = b => {b = num(b); return b < 1024 ? b + ' B' : b < 1048576 ? Math.round(b / 1024) + ' KB' : (b / 1048576).toFixed(1).replace('.', ',') + ' MB'};
const visible = () => {const m = document.querySelector('main'); return !!m && m.dataset.view === 'demandas'};
const sidNum = id => num(String(id).replace(/\D/g, ''));
const first = s => Array.from(String(s || '?'))[0] || '?';

/* ---------- dados ---------- */
const setores = () => (D.v && D.v.setores) || (D.pub && D.pub.setores) || [];
const pessoas = () => (D.v && D.v.pessoas) || (D.pub && D.pub.pessoas) || [];
const reqs = () => (D.v && D.v.demandas) || [];
function sec(id){return setores().find(s => s.id === id) || {id: String(id || '?'), nome: String(id || '?'), icone: '🏭', cor: '#64748B', ativo: false}}
function per(id){return id ? pessoas().find(p => p.id === id) || null : null}
const byId = id => reqs().find(r => r.id === id) || (D.arq || []).find(r => r.id === id) || null;
const activeSectors = () => setores().filter(s => s.ativo);
const usersOf = s => pessoas().filter(p => p.setor === s);
const peopleOf = s => pessoas().filter(p => p.setor === s && p.ativo && sec(s).ativo);
const isAdm = () => D.role === 'adm' && !D.imp;
const meId = () => D.imp || (D.eu && D.eu.id) || null;
const meSec = () => {const p = per(meId()); return p ? p.setor : (D.eu && D.eu.setor) || null};
const myName = () => D.role === 'adm' ? 'Escritório' : (D.eu && D.eu.nome) || '';
function fix(r){
  if(!r || typeof r !== 'object') return r;
  r.de = r.de || {s: '', p: null}; r.para = r.para || {s: '', p: null};
  for(const k of ['pausas', 'eventos', 'comentarios', 'anexos']) if(!Array.isArray(r[k])) r[k] = [];
  if(r.prazo == null) r.prazo = num(r.criado) + num(r.est) * MIN;
  return r;
}

/* ---------- regras de tempo (derivados do servidor + o tempo que passou desde a vista) ---------- */
const isAct = r => r.status === 'new' || r.status === 'prog' || r.status === 'pause';
const lateNow = r => isAct(r) && (!!r.atrasada || now() > num(r.prazo));
const lateDone = r => r.status === 'done' && num(r.fim) > num(r.prazo);
const dispSt = r => lateNow(r) ? 'late' : r.status;
const openPause = r => {const p = (r.pausas || [])[r.pausas.length - 1]; return p && !p.fim ? p : null};
function mets(r){
  const dt = isAct(r) && D.v ? Math.max(0, (now() - num(D.v.agora, now())) / MIN) : 0;
  let w = num(r.espera), e = num(r.execucao), p = num(r.pausado), t = num(r.total);
  if(dt){t += dt; if(r.status === 'new') w += dt; else if(r.status === 'prog') e += dt; else p += dt}
  return {w, e, p, t, sla: r.est ? t / r.est * 100 : 0};
}
function slaCls(r){
  if(r.status === 'done') return lateDone(r) ? 'dm-bad' : 'dm-ok';
  if(r.status === 'canc') return 'dm-ok';
  const p = mets(r).sla;
  return p < 70 ? 'dm-ok' : p < 100 ? 'dm-warn' : 'dm-bad';
}
function remText(r){
  if(r.status === 'done'){const d = (num(r.fim) - num(r.prazo)) / MIN; return d <= 0 ? 'Concluída ' + fT(r.fim) + ' · no prazo' : 'Concluída com atraso de ' + dur(d)}
  if(r.status === 'canc') return 'Cancelada ' + (r.fim ? fT(r.fim) : '');
  const rem = (num(r.prazo) - now()) / MIN;
  return rem >= 0 ? 'Faltam ' + dur(rem) : 'Atrasada há ' + dur(-rem);
}
const sortAtt = (a, b) => (lateNow(b) - lateNow(a)) || ((PRIO[b.prio] || PRIO.norm)[1] - (PRIO[a.prio] || PRIO.norm)[1]) || (num(a.prazo) - num(b.prazo));
const slaC = v => v == null ? '' : v >= 85 ? 'dm-good' : v >= 65 ? 'dm-warnc' : 'dm-badc';

/* ---------- componentes ---------- */
const chip = s => {const S = sec(s); return `<span class="dm-abbr" style="--dm-sc:${col(S.cor)}" title="${esc(S.nome)}">${esc(S.id)}</span>`};
const pname = pid => {const p = per(pid); return p ? p.nome : 'Sem responsável'};
const deName = r => r.de.p ? pname(r.de.p) : 'Escritório';
function av(pid){
  const p = per(pid);
  if(!p) return '<span class="dm-av dm-none" title="Sem responsável">?</span>';
  return `<span class="dm-av" style="--dm-sc:${col(sec(p.setor).cor)}" title="${esc(p.nome)}">${esc(first(p.nome))}</span>`;
}
const avDe = r => r.de.p ? av(r.de.p) : '<span class="dm-av" style="--dm-sc:#6C8BFF" title="Escritório">E</span>';
const pill = ds => `<span class="dm-pill" data-st="${esc(ds)}">${esc(STL[ds] || ds)}</span>`;
const pb = p => `<span class="dm-pb" data-p="${esc(p)}">${esc((PRIO[p] || [p])[0])}</span>`;
const typ = t => (TYPE[t] || ['📌', t]).map(esc).join(' ');
const slaBar = r => `<div class="dm-sla ${slaCls(r)}"><span data-sla="${esc(r.id)}" style="width:${Math.min(100, mets(r).sla).toFixed(1)}%"></span></div>`;
const tabIco = k => `<svg class="dm-tab-ico" aria-hidden="true" width="16" height="16"><use href="#dm-i-${k}"/></svg>`;
const opt = (v, t, cur) => `<option value="${esc(v)}"${String(cur) === String(v) ? ' selected' : ''}>${esc(t)}</option>`;
const secOpts = (cur, all) => (all ? setores() : setores().filter(s => s.ativo || s.id === cur)).map(s => opt(s.id, s.id + ' · ' + s.nome + (s.ativo ? '' : ' (inativo)'), cur)).join('');
const peopleOpts = (s, cur) => opt('', '— Qualquer pessoa do setor —', cur || '') + peopleOf(s).map(p => opt(p.id, p.nome, cur)).join('');

function card(r){
  const ds = dispSt(r);
  return `<button type="button" class="dm-card" data-act="open" data-id="${esc(r.id)}" data-st="${ds}">
   <div class="dm-r1"><span>${esc(r.id)} · ${typ(r.tipo)}</span>${pb(r.prio)}</div>
   <div class="dm-nm">${esc(r.titulo)}</div>
   <div class="dm-route">${chip(r.de.s)}→${chip(r.para.s)}${av(r.para.p)}<span>${esc(pname(r.para.p))}</span></div>
   ${slaBar(r)}
   <div class="dm-r2">${pill(ds)}<span data-rem="${esc(r.id)}">${esc(remText(r))}</span></div></button>`;
}
function lrow(r){
  return `<div class="dm-lrow" role="button" tabindex="0" data-act="open" data-id="${esc(r.id)}" data-p="${esc(r.prio)}"><b>${esc(r.id)}</b><span class="dm-tt">${esc(r.titulo)}</span><span class="dm-cw">${chip(r.de.s)}→${chip(r.para.s)}</span><span class="dm-cw">${av(r.para.p)}<span>${esc(pname(r.para.p))}</span></span>${pill(dispSt(r))}</div>`;
}

/* ---------- servidor ---------- */
function errMsg(e){
  let m = e && e.message ? String(e.message) : '';
  try{const j = JSON.parse(m); if(j && typeof j === 'object') m = String(j.erro || j.error || j.msg || j.mensagem || j.detail || m)}catch(_){/* texto puro */}
  m = m.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  if(!m || /failed to fetch|networkerror/i.test(m)) m = 'Sem resposta do servidor.';
  return m.length > 300 ? m.slice(0, 297) + '…' : m;
}
/* rest '' = GET da vista (ADM) ou lista pública. Pessoa: o tk entra em todo corpo. 401 de pessoa: volta ao "Quem é você?". */
async function call(rest, body, o){
  o = o || {};
  const path = rest ? BASE + rest : '/api/local/demandas';
  let b = body;
  if(b !== undefined && D.role === 'pessoa' && !o.notk) b = Object.assign({}, b, {tk: D.tk});
  try{
    if(typeof window.api !== 'function') throw new Error('Sem conexão com o servidor.');
    const r = await window.api(path, b);
    if(!o.notake) take(r);
    return r;
  }catch(e){
    if(o.raw) throw e;
    const m = errMsg(e);
    if(e && e.status === 401 && D.role === 'pessoa'){lost(m); return null}
    if(!o.quiet) toast('⚠️ ' + m);
    return null;
  }
}
function take(r){
  if(!r || typeof r !== 'object' || !D.role) return;
  const v = r.vista && typeof r.vista === 'object' ? r.vista : r;
  if(!Array.isArray(v.demandas) || !Array.isArray(v.setores)) return;
  if(v.papel && v.papel !== D.role) return;   // resposta de outro papel (troca no meio do caminho)
  apply(v);
}
function apply(v){
  const firstLoad = !D.v;
  v.demandas.forEach(fix);
  v.notas = Array.isArray(v.notas) ? v.notas : [];
  v.feed = Array.isArray(v.feed) ? v.feed : [];
  v.pessoas = Array.isArray(v.pessoas) ? v.pessoas : [];
  D.v = v; D.at = Date.now();
  if(v.eu && D.role === 'pessoa') D.eu = v.eu;
  notesCheck(firstLoad);
  renderBell();
  bkAlert();
  restCheck();
}
async function loadPub(){
  try{
    const r = await window.api('/api/local/demandas');
    D.pub = {setores: Array.isArray(r && r.setores) ? r.setores : [], pessoas: Array.isArray(r && r.pessoas) ? r.pessoas : []};
    D.pubErr = '';
  }catch(e){D.pubErr = errMsg(e)}
}

/* ---------- notificações: alertas para o que chegou desde a última vista ---------- */
function notesCheck(firstLoad){
  const ns = D.v.notas;
  if(firstLoad || !D.seen){D.seen = new Set(ns.map(n => n.id)); return}
  const fresh = ns.filter(n => !D.seen.has(n.id));
  ns.forEach(n => D.seen.add(n.id));
  const me = myName();
  let ring = false;
  fresh.filter(n => !n.lida && !(n.quem && n.quem === me)).sort((a, b) => num(a.t) - num(b.t)).forEach(n => {
    ring = true;
    const t = NT[n.tipo] || ['🔔', 'Aviso'];
    if(ALERT_KINDS.includes(n.tipo)){
      if(visible()) showAlert(n);
      else gtoast(t[0] + ' Demandas: ' + t[1] + ' · ' + n.dem);
    }else if(n.tipo === 'accepted') dtoast(n.dem + ' iniciada por ' + (n.quem || 'o setor'));
    else if(n.tipo === 'done') dtoast('✅ ' + n.dem + ' foi concluída');
  });
  if(ring) ringBell();
}
const unread = () => D.role && D.v ? D.v.notas.filter(n => !n.lida).length : 0;
function renderBell(){
  if(!root) return;
  const n = unread(), b = $('dm-badge');
  b.hidden = !n; b.textContent = n > 99 ? '99+' : String(n);
  // contador no botão do rail e na aba "Demandas" do tablet do chão (app.js)
  for(const nb of document.querySelectorAll('[data-local="demandas"] .dm-navbadge')){nb.hidden = !n; nb.textContent = n > 99 ? '99+' : String(n)}
}
function ringBell(){const bt = $('dm-bell'); if(!bt) return; bt.classList.remove('dm-ring'); void bt.offsetWidth; bt.classList.add('dm-ring')}
function showAlert(n){
  const r = byId(n.dem), box = $('dm-alerts');
  if(!r || !box) return;
  const t = NT[n.tipo] || ['🔔', 'Aviso'], op = openPause(r);
  const motivo = n.tipo === 'pause' && n.texto ? n.texto : (op && n.tipo === 'pause' ? op.motivo : r.motivo);
  const el = document.createElement('div');
  el.className = 'dm-alert'; el.dataset.k = n.tipo; el.dataset.n = String(n.id); el.setAttribute('role', 'alert');
  el.innerHTML = `<h4><span>${t[0]} ${t[1]}</span><button type="button" class="dm-btn dm-sm" data-act="ax" aria-label="Fechar alerta">✕</button></h4>
   <dl class="dm-kv"><dt>Solicitação</dt><dd>${esc(r.id)} · ${esc(r.titulo)}</dd><dt>Setores</dt><dd>${chip(r.de.s)} → ${chip(r.para.s)}</dd><dt>Responsável</dt><dd>${esc(pname(r.para.p))}</dd><dt>Motivo</dt><dd>${esc(motivo)}</dd>${n.quem ? `<dt>Quem</dt><dd>${esc(n.quem)} às ${fT(n.t)}</dd>` : ''}<dt>Prazo</dt><dd data-rem="${esc(r.id)}">${esc(remText(r))}</dd></dl>
   <div class="dm-acts2"><button type="button" class="dm-btn dm-sm dm-primary" data-act="alertview" data-id="${esc(r.id)}">Ver solicitação</button><button type="button" class="dm-btn dm-sm" data-act="ax">Dispensar</button></div>`;
  box.prepend(el);
  while(box.children.length > 3) box.lastChild.remove();
  setTimeout(() => {if(el.parentNode) el.remove()}, 26000);
}
function toast(m){
  const t = root && $('dm-toast');
  if(!t){gtoast(m); return}
  t.textContent = m; t.classList.add('dm-on');
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove('dm-on'), 2600);
}
function gtoast(m){if(typeof window.toast === 'function') try{window.toast(m)}catch(_){/* sem toast do app */}}
const dtoast = m => visible() ? toast(m) : gtoast(m);
async function markReadFor(id){
  const ids = D.v ? D.v.notas.filter(n => n.dem === id && !n.lida).map(n => n.id) : [];
  for(const nid of ids) await call('nota/lida', {nid}, {quiet: true});
  if(ids.length){renderBell(); if(D.notif) renderNotif()}
}

/* ---------- quem é você (no lugar do login do DEMANDA) ---------- */
function become(role, eu, tk){
  Object.assign(D, {role, eu: eu || null, tk: tk || null, imp: null, v: null, seen: null, feedSeen: null, arq: null, crono: null, cronoP: 0, open: null, notif: false, lastKey: ''});
  if(root){$('dm-alerts').textContent = ''; closePanels()}
}
// aparelho restrito (PIN do chão ou das Demandas): só operador; o servidor recusa o resto de qualquer jeito
const restrito = () => !!D.srv && D.srv !== 'maquina' && D.srv !== 'completo';
function whoBody(){
  const L = D.lg, admOk = D.euPronto && !restrito();   // até o /api/eu responder, nada de Administrador na tela
  if(!admOk) L.k = 'op';
  const op = L.k === 'op', secs = activeSectors().filter(s => peopleOf(s.id).length);
  if(op && L.sec && !secs.some(s => s.id === L.sec)) L.sec = '';
  const users = op && L.sec ? peopleOf(L.sec) : [];
  const seg = admOk ? `<div class="dm-seg dm-lgseg" role="group" aria-label="Tipo de acesso"><button type="button" data-act="lgk" data-v="op" aria-pressed="${op}">Operador</button><button type="button" data-act="lgk" data-v="adm" aria-pressed="${!op}">Administrador</button></div>` : '';
  if(!op) return seg + `<div class="dm-note">Disponível só no computador do escritório (PIN completo). Entra direto como <b>Escritório</b>.</div>${L.err ? `<div class="dm-fld dm-err"><span class="dm-em" role="alert">${esc(L.err)}</span></div>` : ''}`;
  return seg + `<div class="dm-lglbl">1. Seu setor</div>${secs.length ? `<div class="dm-lgsecs">${secs.map(s => `<button type="button" class="dm-lgsec" data-act="lgs" data-v="${esc(s.id)}" aria-pressed="${L.sec === s.id}" style="--dm-sc:${col(s.cor)}"><i>${esc(s.icone)}</i>${esc(s.nome)}</button>`).join('')}</div>` : `<div class="dm-lghint">${D.pubErr ? esc(D.pubErr) : 'Nenhum setor com pessoas ativas. Peça ao escritório para cadastrar.'}</div>`}
   <div class="dm-lglbl">2. Seu nome</div>${L.sec ? `<div class="dm-lgusers">${users.map(p => `<button type="button" class="dm-lguser" data-act="lgu" data-v="${esc(p.id)}" aria-pressed="${L.user === p.id}">${av(p.id)}<span>${esc(p.nome)}</span></button>`).join('')}</div>` : '<div class="dm-lghint">Escolha o setor para ver os usuários.</div>'}
   <div class="dm-fld ${L.err ? 'dm-err' : ''}" id="dm-lg-fld" style="margin-top:12px"><label for="dm-lg-code">3. Código</label><div class="dm-pwrap"><input id="dm-lg-code" type="${L.show ? 'text' : 'password'}" inputmode="numeric" pattern="[0-9]*" maxlength="4" autocomplete="off" placeholder="••••" value="${esc(L.code)}"><button type="button" class="dm-eye" data-act="lgeye" aria-label="Mostrar ou ocultar o código">${L.show ? '🙈' : '👁'}</button></div><span class="dm-em" role="alert">${esc(L.err || 'Digite os 4 dígitos do seu código.')}</span></div>`;
}
function renderLogin(){
  const box = $('dm-login');
  // o cartão é montado (e anima) uma vez; trocar de etapa redesenha só o corpo, como o #lgBody do DEMANDA
  if(!$('dm-lgbody') || !box.contains($('dm-lgbody'))) box.innerHTML = '<form class="dm-lgcard" id="dm-lgform" novalidate><div class="dm-lghead"><h2>Quem é você?</h2><p class="dm-bfn">Central de demandas</p><p>Entre com o seu código pessoal de 4 dígitos.</p></div><div id="dm-lgbody"></div><button type="submit" class="dm-btn dm-primary dm-lgbtn">Entrar</button></form>';
  $('dm-lgbody').innerHTML = whoBody();
}
function openWho(){
  D.mod = {kind: 'who'};
  const cur = D.role ? `<div class="dm-acct">${D.role === 'adm' ? '<span class="dm-av" style="--dm-sc:#6C8BFF">E</span>' : av(D.eu && D.eu.id)}<div><b>${esc(D.role === 'adm' ? 'Escritório' : myName())}</b><small>Você está aqui agora · ${D.role === 'adm' ? 'Administrador' : esc(sec(meSec()).nome) + ' · matrícula ' + esc(D.eu && D.eu.mat)}</small></div></div>` : '';
  openModal(`<form id="dm-lgform" novalidate><h2>Quem é você?</h2><p class="dm-note" style="margin-top:0">Entre com o seu código pessoal de 4 dígitos.</p>${cur}<div id="dm-lgbody">${whoBody()}</div><div class="dm-mfoot">${D.role ? '<button type="button" class="dm-btn dm-danger" data-act="logout">Sair ⎋</button><span class="dm-spacer"></span>' : ''}<button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="submit" class="dm-btn dm-primary">Entrar</button></div></form>`);
}
const rerenderWho = () => {const b = $('dm-lgbody'); if(b) b.innerHTML = whoBody(); else if(D.mod && D.mod.kind === 'who') openWho(); else renderLogin(); if(D.lg.err){const f = $('dm-lg-code'); if(f) f.focus()}};
async function doLogin(){
  const L = D.lg;
  L.err = '';
  if(L.k === 'adm'){
    if(restrito()) return;
    let r = null;
    try{r = await window.api('/api/local/demandas')}catch(e){L.err = errMsg(e)}
    if(r && (r.papel !== 'adm' || !Array.isArray(r.demandas))) L.err = 'Este aparelho não tem acesso de administrador.';
    if(L.err){rerenderWho(); return}
    if(D.role === 'pessoa' && D.tk) window.api(BASE + 'sair', {tk: D.tk}).catch(() => {});
    become('adm'); D.tab = 'painel';
    take(r); closeModal(); render();
    toast('Bem-vindo(a), Escritório!');
    return;
  }
  if(!L.sec){L.err = 'Selecione o seu setor.'; rerenderWho(); return}
  if(!L.user){L.err = 'Selecione o seu nome.'; rerenderWho(); return}
  if(!/^[0-9]{4}$/.test(L.code)){L.err = 'Digite os 4 dígitos do seu código.'; rerenderWho(); return}
  let r;
  try{r = await call('entrar', {pessoa: L.user, codigo: L.code}, {raw: true, notk: true, notake: true})}
  catch(e){L.err = errMsg(e); L.code = ''; rerenderWho(); return}
  if(!r || !r.tk){L.err = 'Não foi possível entrar.'; L.code = ''; rerenderWho(); return}
  if(D.role === 'pessoa' && D.tk && D.tk !== r.tk) window.api(BASE + 'sair', {tk: D.tk}).catch(() => {});
  become('pessoa', r.eu, String(r.tk));
  D.opTab = 'recv'; D.opF = 'mine'; L.code = ''; L.show = false;
  take(r);
  closeModal(); render();
  toast('Bem-vindo(a), ' + myName() + '!');
}
async function logout(){
  if(D.role === 'pessoa' && D.tk) window.api(BASE + 'sair', {tk: D.tk}).catch(() => {});
  become(null);
  D.lg.code = ''; D.lg.err = '';
  closeModal();
  await loadPub();
  render();
}
function lost(m){
  become(null);
  D.lg.err = m || 'Identifique-se de novo.'; D.lg.code = '';
  closeModal(); render();
  dtoast('🔒 ' + D.lg.err);
}

/* ---------- cabeçalho, abas e visualização como pessoa ---------- */
function renderChip(){
  const el = $('dm-uchip');
  if(!D.role){el.innerHTML = '<span class="dm-av dm-none">?</span><span class="dm-t"><b>Quem é você?</b><small>Identifique-se</small></span>'; return}
  if(D.role === 'adm'){el.innerHTML = '<span class="dm-av" style="--dm-sc:#6C8BFF">E</span><span class="dm-t"><b>Escritório</b><small>Administrador</small></span>'; return}
  el.innerHTML = `${av(D.eu && D.eu.id)}<span class="dm-t"><b>${esc(myName())}</b><small>${esc(sec(meSec()).nome)}</small></span>`;
}
function renderImp(){
  const el = $('dm-imp'), p = D.imp && per(D.imp);
  el.innerHTML = p ? `<div class="dm-impbar"><span>👁 <b>Modo visualização:</b> você está vendo o sistema como <b>${esc(p.nome)}</b> (${esc(sec(p.setor).nome)}). Só leitura: as ações ficam com a própria pessoa.</span><button type="button" class="dm-btn dm-sm" data-act="impexit">Voltar ao ADM</button></div>` : '';
}
function renderTabs(){
  const el = $('dm-tabs');
  if(!D.role){el.innerHTML = ''; return}
  let t, cur;
  if(isAdm()){t = [['painel', 'Painel', ''], ['sol', 'Solicitações', reqs().filter(isAct).length], ['hist', 'Histórico', ''], ['crono', 'Cronoanálise', ''], ['admin', 'Administração', '']]; cur = D.tab}
  else{const me = meId(); t = [['recv', '📥 Recebidas', reqs().filter(r => r.para.p === me && isAct(r)).length], ['sent', '📤 Enviadas', reqs().filter(r => r.de.p === me && isAct(r)).length]]; cur = D.opTab}
  el.innerHTML = t.map(([k, l, n]) => `<button type="button" class="dm-tab" data-act="tab" data-v="${k}" aria-pressed="${k === cur}">${isAdm() ? tabIco(k) : ''}${l}${n !== '' ? `<span class="dm-cnt">${n}</span>` : ''}</button>`).join('');
}
function clock(){
  const el = root && $('dm-clock'); if(!el) return;
  const d = new Date();
  el.textContent = DOW[d.getDay()] + ' ' + p2(d.getDate()) + '/' + p2(d.getMonth() + 1) + ' · ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
}

/* ---------- ADM: painel ---------- */
function attention(){
  const out = [], N = now();
  for(const r of reqs()){
    if(!isAct(r)) continue;
    const tags = []; let score = 0;
    if(lateNow(r)){tags.push({k: 'late', t: 'Atrasada há ' + dur((N - num(r.prazo)) / MIN)}); score += 100}
    if(r.prio === 'urg'){tags.push({k: 'urg', t: 'Urgente'}); score += 60}
    const op = openPause(r);
    if(op && (N - num(op.ini)) / MIN >= 20){tags.push({k: 'pause', t: 'Pausada há ' + dur((N - num(op.ini)) / MIN)}); score += 40}
    if(r.status === 'new' && (N - num(r.criado)) / MIN >= 25){tags.push({k: 'wait', t: 'Sem aceite há ' + dur((N - num(r.criado)) / MIN)}); score += 30}
    if(tags.length) out.push({r, tags, score});
  }
  return out.sort((a, b) => b.score - a.score);
}
function mapa(act, intro){
  const rows = activeSectors().map(s => {const l = act.filter(r => r.para.s === s.id); return {s, n: l.length, lt: l.filter(lateNow).length, u: l.filter(r => r.prio === 'urg').length, pz: l.filter(r => r.status === 'pause').length, nu: !peopleOf(s.id).length}});
  const mx = Math.max(1, ...rows.map(r => r.n)), az = (a, b) => String(a.s.nome).localeCompare(String(b.s.nome), 'pt-BR');
  if(D.mapSort === 'crit') rows.sort((a, b) => (b.lt * 100 + b.u * 10 + b.pz * 3 + b.n) - (a.lt * 100 + a.u * 10 + a.pz * 3 + a.n) || az(a, b));
  else rows.sort(az);
  const tot = rows.reduce((t, r) => t + r.n, 0), lt = rows.filter(r => r.lt).length, ok = rows.filter(r => !r.lt && !r.u).length;
  const cnt = n => intro ? ` data-count="${n}"` : '';
  return `<div class="dm-panel"><div class="dm-ph"><h3>Mapa de setores</h3><span class="dm-s">Solicitações em aberto por setor responsável. Clique para filtrar.</span></div>
   <div class="dm-mapbar"><div class="dm-mapsum"><span><b>${rows.length}</b> setores</span><span><b${cnt(tot)}>${tot}</b> em aberto</span>${lt ? `<span class="dm-ml"><b>${lt}</b> com atraso</span>` : ''}<span class="dm-mo"><b>${ok}</b> em dia</span></div><span class="dm-spacer"></span><div class="dm-seg" role="group" aria-label="Ordem do mapa"><button type="button" data-act="msort" data-v="crit" aria-pressed="${D.mapSort === 'crit'}">Mais críticos</button><button type="button" data-act="msort" data-v="az" aria-pressed="${D.mapSort === 'az'}">A–Z</button></div></div>
   <div class="dm-map" id="dm-map">${rows.map((r, i) => `<button type="button" class="dm-tile${intro ? ' dm-intro' : ''}${r.lt ? ' dm-hasLate' : ''}${r.n ? '' : ' dm-idle'}${D.fSec === r.s.id ? ' dm-pick' : ''}" data-act="sector" data-v="${esc(r.s.id)}" title="${esc(r.s.nome)} · ${r.n} em aberto" style="--dm-sc:${col(r.s.cor)};--dm-d:${Math.min(i, 14) * 45}ms">
    <div class="dm-thead"><span class="dm-tico">${esc(r.s.icone)}</span><span class="dm-tname">${chip(r.s.id)}<em>${esc(r.s.nome)}</em></span></div>
    <div class="dm-tnum"><b${cnt(r.n)}>${r.n}</b>em aberto</div>
    <div class="dm-tbar"><span style="width:${r.n ? Math.max(6, r.n / mx * 100).toFixed(1) : 0}%"></span></div>
    <div class="dm-ttags">${r.lt ? `<span class="dm-tg" data-k="late">${r.lt} atras.</span>` : ''}${r.u ? `<span class="dm-tg" data-k="urg">${r.u} urg.</span>` : ''}${r.pz ? `<span class="dm-tg" data-k="pause">${r.pz} paus.</span>` : ''}${r.nu ? '<span class="dm-tg" data-k="wait">Sem usuários</span>' : ''}${!r.lt && !r.u && !r.pz && !r.nu ? '<span class="dm-ok0">Em dia</span>' : ''}</div></button>`).join('') || '<div class="dm-empty">Nenhum setor ativo. Cadastre em Administração.</div>'}</div></div>`;
}
function vPainel(intro){
  const all = reqs(), act = all.filter(isAct), N = now();
  const c = {new: act.filter(r => r.status === 'new').length, prog: act.filter(r => r.status === 'prog').length, pause: act.filter(r => r.status === 'pause').length, late: act.filter(lateNow).length, urg: act.filter(r => r.prio === 'urg').length, done: all.filter(r => r.status === 'done' && r.fim && sameDay(r.fim, N)).length};
  const K = [['new', 'new', 'Abertas', 'Aguardando aceite'], ['prog', 'prog', 'Em andamento', 'Sendo executadas'], ['pause', 'pause', 'Pausadas', 'Com impedimento'], ['late', 'late', 'Atrasadas', 'Prazo estourado'], ['urg', 'late', 'Urgentes', 'Ainda em aberto'], ['done', 'done', 'Concluídas hoje', 'Finalizadas']];
  const att = attention();
  const feed = D.v.feed.slice(0, 10), seen = D.feedSeen, key = f => num(f.t) + '|' + f.msg;
  D.feedSeen = new Set(D.v.feed.map(key));
  return `${bkAviso()}<div class="dm-kpis">${K.map(([k, st, l, s]) => `<button type="button" class="dm-kpi" data-act="kpi" data-v="${k}" data-st="${st}"><b${intro ? ` data-count="${c[k]}"` : ''}>${c[k]}</b><span>${l}</span><small>${s}</small></button>`).join('')}</div>
   ${mapa(act, intro)}
   <div class="dm-grid2"><div class="dm-panel"><div class="dm-ph"><h3>🚨 Atenção agora</h3><span class="dm-s">${att.length} itens exigem atenção</span></div>${att.slice(0, 7).map(a => {
     const r = a.r, op = openPause(r);
     return `<div class="dm-al" data-k="${a.tags[0].k}"><div class="dm-al-h"><b>${esc(r.id)}</b>${a.tags.map(t => `<span class="dm-tg" data-k="${t.k}">${esc(t.t)}</span>`).join('')}</div>
      <div class="dm-al-t">${esc(r.titulo)}</div>
      <div class="dm-al-m">${chip(r.de.s)}→${chip(r.para.s)}<span>${esc(pname(r.para.p))}</span>${op ? `<span>· <b>Motivo:</b> ${esc(op.motivo)} (${esc(op.por)})</span>` : `<span>· ${esc(r.motivo)}</span>`}</div>
      <div class="dm-al-b"><button type="button" class="dm-btn dm-sm" data-act="open" data-id="${esc(r.id)}">Ver</button><button type="button" class="dm-btn dm-sm" data-act="nudge" data-id="${esc(r.id)}">🔔 Cobrar</button><button type="button" class="dm-btn dm-sm" data-act="reassign" data-id="${esc(r.id)}">↪ Reatribuir</button></div></div>`;
   }).join('') || '<div class="dm-empty">Nada crítico no momento. 🎉</div>'}</div>
   <div class="dm-panel"><div class="dm-ph"><h3>Atividade ao vivo</h3><span class="dm-s">Últimos eventos</span></div><ul class="dm-feed">${feed.map(f => `<li class="${f.tipo === 'warn' ? 'dm-warn' : f.tipo === 'ok' ? 'dm-ok' : ''}${seen && !seen.has(key(f)) ? ' dm-in' : ''}"><time>${fT(f.t)}</time><button type="button" data-act="open" data-id="${esc(f.dem)}">${esc(f.msg)}</button></li>`).join('') || '<li class="dm-empty" style="width:100%;display:block">Sem eventos ainda.</li>'}</ul></div></div>`;
}

/* ---------- ADM: solicitações ---------- */
function filtered(){
  const q = D.q.trim().toLowerCase();
  return reqs().filter(r => {
    if(D.fSec && r.para.s !== D.fSec) return false;
    if(D.fPrio && r.prio !== D.fPrio) return false;
    if(D.fType && r.tipo !== D.fType) return false;
    if(D.fSt === 'late'){if(!lateNow(r)) return false}
    else if(D.fSt === 'open'){if(!isAct(r)) return false}
    else if(D.fSt && r.status !== D.fSt) return false;
    if(q && !(r.id + ' ' + r.titulo + ' ' + r.motivo + ' ' + pname(r.para.p)).toLowerCase().includes(q)) return false;
    return true;
  });
}
function vSol(){
  const list = filtered(), N = now();
  let h = `<div class="dm-filters"><input type="search" id="dm-q" placeholder="Buscar ID, título, motivo" aria-label="Buscar" value="${esc(D.q)}">
   <select id="dm-fSt" aria-label="Status">${[['', 'Todos os status'], ['open', 'Em aberto'], ['new', 'Abertas'], ['prog', 'Em andamento'], ['pause', 'Pausadas'], ['late', 'Atrasadas'], ['done', 'Concluídas'], ['canc', 'Canceladas']].map(([v, t]) => opt(v, t, D.fSt)).join('')}</select>
   <select id="dm-fSec" aria-label="Setor responsável">${opt('', 'Todos os setores', D.fSec)}${secOpts(D.fSec, true)}</select>
   <select id="dm-fPrio" aria-label="Prioridade">${opt('', 'Todas as prioridades', D.fPrio)}${['urg', 'high', 'norm', 'low'].map(k => opt(k, PRIO[k][0], D.fPrio)).join('')}</select>
   <select id="dm-fType" aria-label="Tipo">${opt('', 'Todos os tipos', D.fType)}${Object.entries(TYPE).map(([k, v]) => opt(k, v[0] + ' ' + v[1], D.fType)).join('')}</select>
   <button type="button" class="dm-btn dm-sm" data-act="clear">Limpar filtros</button><span class="dm-spacer"></span><span class="dm-count">${list.length} solicitações</span>
   <div class="dm-seg" role="group" aria-label="Visualização"><button type="button" data-act="view" data-v="board" aria-pressed="${D.view === 'board'}">Quadro</button><button type="button" data-act="view" data-v="list" aria-pressed="${D.view === 'list'}">Lista</button></div></div>`;
  if(D.view === 'board'){
    const cols = D.fSt === 'canc' ? ['canc'] : ['new', 'prog', 'pause', 'done'];
    const names = {new: 'Abertas', prog: 'Em andamento', pause: 'Pausadas', done: 'Concluídas (24h)', canc: 'Canceladas'};
    h += `<div class="dm-board${cols.length === 1 ? ' dm-one' : ''}">${cols.map(c => {
      let l = list.filter(r => r.status === c);
      l = c === 'done' || c === 'canc' ? l.filter(r => N - num(r.fim) < DAY).sort((a, b) => num(b.fim) - num(a.fim)) : l.sort(sortAtt);
      return `<div class="dm-col" data-st="${c}"><h3><span class="dm-dot"></span>${names[c]}<span class="dm-n">${l.length}</span></h3><div class="dm-list">${l.slice(0, 60).map(card).join('') || '<div class="dm-empty">Nada por aqui com os filtros atuais.</div>'}</div></div>`;
    }).join('')}</div>`;
  }else{
    const l = list.slice().sort((a, b) => (isAct(b) - isAct(a)) || sortAtt(a, b) || (num(b.criado) - num(a.criado))).slice(0, 90);
    h += `<div class="dm-lbox"><div class="dm-lhead"><span>ID</span><span>Solicitação</span><span>De → Para</span><span>Responsável</span><span>Status</span></div>${l.map(lrow).join('') || '<div class="dm-empty" style="margin:12px">Nenhuma solicitação encontrada. Limpe os filtros para ver todas.</div>'}</div>`;
  }
  return h;
}

/* ---------- ADM: histórico (principal + arquivo morto sob pedido) ---------- */
function histAll(){const m = new Map(); for(const r of reqs()) m.set(r.id, r); for(const r of D.arq || []) if(r && !m.has(r.id)) m.set(r.id, r); return [...m.values()]}
function vHist(){
  const all = histAll(), q = D.hq.trim().toLowerCase();
  const list = all.filter(r => {
    if(D.hFrom && r.de.s !== D.hFrom) return false;
    if(D.hTo && r.para.s !== D.hTo) return false;
    if(D.hSt === 'late'){if(!lateNow(r)) return false}
    else if(D.hSt && r.status !== D.hSt) return false;
    if(q && !(r.id + ' ' + r.titulo + ' ' + (r.motivo || '')).toLowerCase().includes(q)) return false;
    return true;
  }).sort((a, b) => num(b.criado) - num(a.criado));
  const pairs = {};
  for(const r of all){if(!r.de.s || !r.para.s) continue; const k = r.de.s + '\u0000' + r.para.s; (pairs[k] = pairs[k] || {from: r.de.s, to: r.para.s, n: 0}).n++}
  const rel = Object.values(pairs).sort((a, b) => b.n - a.n || a.from.localeCompare(b.from));
  const st = ms => ms ? `<time>${fFull(ms)}</time>` : '<span class="dm-muted">—</span>';
  return `<div class="dm-filters"><input type="search" id="dm-hq" placeholder="Buscar ID, título ou motivo" aria-label="Buscar no histórico" value="${esc(D.hq)}">
    <select id="dm-hSt" aria-label="Status do histórico">${[['', 'Todos os status'], ['new', 'Abertas'], ['prog', 'Em andamento'], ['pause', 'Pausadas'], ['late', 'Atrasadas'], ['done', 'Concluídas'], ['canc', 'Canceladas']].map(([v, t]) => opt(v, t, D.hSt)).join('')}</select>
    <select id="dm-hFrom" aria-label="Setor de origem">${opt('', 'Origem', D.hFrom)}${secOpts(D.hFrom, true)}</select>
    <select id="dm-hTo" aria-label="Setor de destino">${opt('', 'Destino', D.hTo)}${secOpts(D.hTo, true)}</select>
    <select id="dm-hArq" aria-label="Arquivo morto">${[['', 'Só as recentes'], ['30', '+ arquivo: 30 dias'], ['90', '+ arquivo: 90 dias'], ['365', '+ arquivo: 1 ano']].map(([v, t]) => opt(v, t, D.hArq)).join('')}</select>
    <button type="button" class="dm-btn dm-sm" data-act="hclear">Limpar</button><span class="dm-spacer"></span><span class="dm-count">${list.length} de ${all.length}</span></div>
   <div class="dm-panel"><div class="dm-ph"><h3>Relações entre setores</h3><span class="dm-s">Cada par é origem → destino, com o total de demandas. Clique para filtrar a lista.</span></div><div class="dm-rels">${rel.map(p => `<button type="button" class="dm-rel" data-act="hrel" data-from="${esc(p.from)}" data-to="${esc(p.to)}" aria-pressed="${D.hFrom === p.from && D.hTo === p.to}" aria-label="${esc(sec(p.from).nome)} para ${esc(sec(p.to).nome)}, ${p.n} demandas">${chip(p.from)}<i>→</i>${chip(p.to)}<b>${p.n}</b></button>`).join('') || '<div class="dm-empty" style="width:100%">Nenhuma relação registrada.</div>'}</div></div>
   <div class="dm-lbox"><div class="dm-hhead"><span>ID</span><span>Solicitação</span><span>Relação</span><span>Aberta</span><span>Início</span><span>Fim</span><span>Status</span></div>${list.slice(0, 400).map(r => `<div class="dm-hrow" role="button" tabindex="0" data-act="open" data-id="${esc(r.id)}"><div><b>${esc(r.id)}</b></div><div style="min-width:0"><span class="dm-tt">${esc(r.titulo)}</span></div><div class="dm-hrel">${chip(r.de.s)}<i>→</i>${chip(r.para.s)}</div>${st(r.criado)}${st(r.iniciado)}${st(r.fim)}<div>${pill(dispSt(r))}</div></div>`).join('') || '<div class="dm-empty" style="margin:12px">Nenhuma demanda nesse recorte.</div>'}</div>`;
}
async function loadArq(){
  if(!D.hArq){D.arq = null; renderView(); return}
  const days = num(D.hArq, 30), N = now();
  const r = await call('historico', {de: N - days * DAY, ate: N}, {notake: true});
  D.arq = r && Array.isArray(r.demandas) ? r.demandas.map(fix) : [];
  if(isAdm() && D.tab === 'hist') renderView();
}

/* ---------- ADM: cronoanálise ---------- */
async function loadCrono(quiet){
  const p = D.period;
  const r = await call('crono', {dias: p}, {quiet, notake: true});
  if(r && r.kpis && p === D.period){D.crono = r; D.cronoP = p}
  if(isAdm() && D.tab === 'crono' && !busyUI()) renderView();
}
function gantt(g){
  if(!g || !Array.isArray(g.linhas)) return '<div class="dm-empty">Sem solicitações no intervalo.</div>';
  const GS = num(g.ini), GE = num(g.fim), span = Math.max(1, GE - GS), L = t => Math.max(0, Math.min(100, (num(t) - GS) / span * 100)), NOWg = GE - 3 * HOUR;
  let axis = '';
  for(let t = Math.ceil(GS / HOUR) * HOUR; t <= GE; t += HOUR){const h = new Date(t).getHours(); if(h % 2 === 0) axis += `<span style="left:${L(t).toFixed(2)}%">${p2(h)}h</span>`}
  const body = g.linhas.map(r => {
    const segs = (r.segs || []).map(s => {
      const l = L(s.a), w = L(s.b) - l;
      if(w <= 0) return '';
      const k = {wait: 'dm-wait', exec: 'dm-exec', pause: 'dm-pause'}[s.k] || 'dm-wait', live = r.viva && s.k !== 'wait' && num(s.b) >= NOWg - MIN;
      return `<i class="dm-gs ${k}${live ? ' dm-live' : ''}" style="left:${l.toFixed(2)}%;width:${Math.max(0.4, w).toFixed(2)}%"></i>`;
    }).join('');
    const dl = num(r.prazo), dm = dl >= GS && dl <= GE ? `<i class="dm-gd${r.atrasada ? ' dm-late' : ''}" style="left:${L(dl).toFixed(2)}%" title="Prazo ${fT(dl)}"></i>` : '';
    return `<div class="dm-grow" role="button" tabindex="0" data-act="open" data-id="${esc(r.id)}"><div class="dm-glab"><b>${esc(r.id)}</b>${chip(r.de)}→${chip(r.para)}<span class="dm-gt" title="${esc(r.titulo)}">${esc(r.titulo)}</span></div><div class="dm-gtrack">${segs}${dm}<i class="dm-gnow" style="left:${L(NOWg).toFixed(2)}%"></i></div></div>`;
  }).join('');
  return `<div class="dm-gaxis">${axis}</div>${body || '<div class="dm-empty">Sem solicitações no intervalo.</div>'}<div class="dm-legend"><span><i style="background:repeating-linear-gradient(45deg,color-mix(in srgb,var(--dm-s-new) 45%,transparent) 0 3px,transparent 3px 6px);border:1px solid var(--dm-s-new)"></i>Espera</span><span><i style="background:var(--dm-s-prog)"></i>Execução</span><span><i style="background:var(--dm-s-pause)"></i>Pausa</span><span><i style="background:var(--dm-s-late)"></i>Prazo</span><span><i style="background:var(--dm-brand)"></i>Agora</span></div>`;
}
function vCrono(){
  const seg = `<div class="dm-filters"><h3 class="dm-h3">Cronoanálise das solicitações</h3><span class="dm-spacer"></span><div class="dm-seg" role="group" aria-label="Período">${[[1, 'Hoje'], [7, '7 dias'], [30, '30 dias']].map(([v, l]) => `<button type="button" data-act="period" data-v="${v}" aria-pressed="${D.period === v}">${l}</button>`).join('')}</div></div>`;
  const c = D.crono;
  if(!c || D.cronoP !== D.period) return seg + '<div class="dm-loading">Carregando a cronoanálise…</div>';
  const k = c.kpis || {}, ab = num(k.abertas), cc = num(k.concluidas);
  const ck = [['📨', 'Solicitações', ab, 'abertas no período'], ['✅', 'Concluídas', cc, 'de ' + ab + ' abertas'], ['🎯', 'Cumprimento do prazo', k.pct_prazo == null ? '—' : num(k.pct_prazo) + '%', num(k.no_prazo) + ' de ' + cc + ' no prazo'],
    ['⏳', 'Espera média', dur(k.espera), 'até alguém iniciar'], ['⚙️', 'Execução média', dur(k.execucao), 'estimado ' + dur(k.estimado)], ['⏸', 'Tempo em pausa', dur(k.pausado), 'média por solicitação']];
  const rows = (c.setores || []).map(x => ({s: x.s, n: num(x.n), w: num(x.espera), e: num(x.execucao), p: num(x.pausado), es: num(x.estimado), sla: x.sla == null ? null : Math.round(num(x.sla))}));
  const scale = Math.max(1, ...rows.map(x => Math.max(x.w + x.e + x.p, x.es))) * 1.1;
  const big = rows.filter(x => x.n >= 3), ins = [];
  if(big.length){
    const gw = big.slice().sort((a, b) => b.w - a.w)[0], gs = big.filter(x => x.sla != null).sort((a, b) => a.sla - b.sla)[0], ge = big.filter(x => x.es > 0).sort((a, b) => (b.e / b.es) - (a.e / a.es))[0];
    ins.push(['⏳ Maior espera para iniciar', chip(gw.s) + ' ' + esc(sec(gw.s).nome) + ' leva em média ' + dur(gw.w) + ' para aceitar uma solicitação.']);
    if(gs) ins.push(['🎯 Menor cumprimento de prazo', chip(gs.s) + ' ' + esc(sec(gs.s).nome) + ' cumpre apenas ' + gs.sla + '% dos prazos.']);
    if(ge) ins.push(['⚙️ Execução vs. estimado', chip(ge.s) + ' ' + esc(sec(ge.s).nome) + ' executa em ' + Math.round(ge.e / ge.es * 100) + '% do tempo estimado.']);
  }
  const rl = (c.motivos || []).map(m => [String(m.motivo), num(m.n)]), rtot = ab || rl.reduce((t, x) => t + x[1], 0) || 1, rmax = rl.length ? Math.max(1, rl[0][1]) : 1;
  if(rl.length) ins.push(['📌 Motivo mais comum', esc(rl[0][0]) + ': ' + rl[0][1] + ' solicitações (' + Math.round(rl[0][1] / rtot * 100) + '%).']);
  const rk = (c.ranking || []).map(x => ({p: x.p, n: num(x.n), sla: x.sla == null ? null : Math.round(num(x.sla))})), rkMax = rk.length ? Math.max(1, ...rk.map(x => x.n)) : 1;
  let cum = 0;
  return seg + `<div class="dm-ckpis">${ck.map(([i, l, v, s]) => `<div class="dm-ck"><span>${i} ${l}</span><b>${esc(v)}</b><small>${esc(s)}</small></div>`).join('')}</div>
   ${ins.length ? `<div class="dm-insights">${ins.map(([t, d]) => `<div class="dm-ins"><b>${t}</b>${d}</div>`).join('')}</div>` : ''}
   <div class="dm-panel"><div class="dm-ph"><h3>Tempo por setor responsável</h3><span class="dm-s">Espera + execução + pausas × tempo estimado (traço preto)</span></div>
    <div class="dm-chead"><span>Setor</span><span>Concl.</span><span>Espera</span><span>Execução</span><span>Estimado</span><span>No prazo</span><span>Distribuição do tempo</span></div>
    ${rows.map(x => `<div class="dm-crow"><div class="dm-sn">${chip(x.s)}<span>${esc(sec(x.s).nome)}</span></div><div>${x.n}</div><div>${dur(x.w)}</div><div>${dur(x.e)}</div><div>${dur(x.es)}</div><div class="${slaC(x.sla)}">${x.sla == null ? '—' : x.sla + '%'}</div>
      <div class="dm-cbar"><div class="dm-stack"><i class="dm-w" style="width:${(x.w / scale * 100).toFixed(2)}%"></i><i class="dm-e" style="width:${(x.e / scale * 100).toFixed(2)}%"></i><i class="dm-p" style="width:${(x.p / scale * 100).toFixed(2)}%"></i><span class="dm-est" style="left:${(x.es / scale * 100).toFixed(2)}%"></span></div></div></div>`).join('') || '<div class="dm-empty">Sem solicitações concluídas neste período.</div>'}
    <div class="dm-legend"><span><i style="background:var(--dm-s-new)"></i>Espera até iniciar</span><span><i style="background:var(--dm-s-prog)"></i>Execução</span><span><i style="background:var(--dm-s-pause)"></i>Pausas</span><span><i style="background:var(--dm-ink)"></i>Tempo estimado</span></div></div>
   <div class="dm-panel"><div class="dm-ph"><h3>Linha do tempo (últimas 10h + próximas 3h)</h3><span class="dm-s">Clique em uma linha para abrir a solicitação</span></div>${gantt(c.gantt)}</div>
   <div class="dm-grid2" style="grid-template-columns:1fr 1fr">
    <div class="dm-panel"><div class="dm-ph"><h3>Motivos mais frequentes</h3></div>${rl.map(([m, n]) => {cum += n; return `<div class="dm-par"><span class="dm-pl" title="${esc(m)}">${esc(m)}</span><div class="dm-pbar"><span style="width:${(n / rmax * 100).toFixed(1)}%"></span></div><b>${n}</b><small>${Math.round(cum / rtot * 100)}%</small></div>`}).join('') || '<div class="dm-empty">Sem dados.</div>'}<div class="dm-note">A coluna da direita mostra o percentual acumulado (Pareto).</div></div>
    <div class="dm-panel"><div class="dm-ph"><h3>Ranking de responsáveis</h3></div>${rk.map((x, i) => `<div class="dm-rk"><b>${i + 1}º</b>${av(x.p)}<div class="dm-rn"><span>${esc(pname(x.p))}</span>${per(x.p) ? chip(per(x.p).setor) : ''}</div><div class="dm-barc"><div class="dm-pbar dm-pg"><span style="width:${(x.n / rkMax * 100).toFixed(1)}%"></span></div></div><b class="${slaC(x.sla)}">${x.sla == null ? '—' : x.sla + '%'}</b></div>`).join('') || '<div class="dm-empty">Sem dados.</div>'}<div class="dm-note">Concluídas no período e % entregue dentro do prazo.</div></div>
   </div>`;
}

/* ---------- ADM: administração ---------- */
function sectorStats(sid){
  const all = reqs(), act = all.filter(r => r.para.s === sid && isAct(r)), N = now(), d7 = all.filter(r => r.para.s === sid && r.status === 'done' && num(r.fim) >= N - 7 * DAY);
  return {on: usersOf(sid).filter(p => p.ativo).length, open: act.length, late: act.filter(lateNow).length, sla: d7.length ? Math.round(d7.filter(r => !lateDone(r)).length / d7.length * 100) : null};
}
function userStats(pid){
  const mine = reqs().filter(r => r.para.p === pid), N = now(), d7 = mine.filter(r => r.status === 'done' && num(r.fim) >= N - 7 * DAY);
  return {open: mine.filter(isAct).length, done: d7.length, sla: d7.length ? Math.round(d7.filter(r => !lateDone(r)).length / d7.length * 100) : null};
}
const ativoPill = on => on ? '<span class="dm-pill" data-st="prog">Ativo</span>' : '<span class="dm-pill" data-st="canc">Inativo</span>';
function vAdmin(){
  const sub = D.admSub, users = sub === 'users', u = D.v.anexos_uso;
  const head = `<div class="dm-filters"><div class="dm-seg" role="group" aria-label="Administração"><button type="button" data-act="admsub" data-v="sectors" aria-pressed="${!users}">Setores</button><button type="button" data-act="admsub" data-v="users" aria-pressed="${users}">Usuários</button></div>
   ${users ? `<input type="search" id="dm-uq" placeholder="Buscar usuário ou matrícula" aria-label="Buscar usuário" value="${esc(D.uq)}"><select id="dm-uSec" aria-label="Setor">${opt('', 'Todos os setores', D.uSec)}${secOpts(D.uSec, true)}</select><select id="dm-uSt" aria-label="Status">${[['', 'Todos os status'], ['on', 'Ativos'], ['off', 'Inativos']].map(([v, t]) => opt(v, t, D.uSt)).join('')}</select>` : ''}
   <span class="dm-spacer"></span><span class="dm-count">${users ? '' : setores().length + ' setores · ' + pessoas().filter(p => p.ativo).length + ' usuários ativos'}${u ? ' · anexos ' + fBytes(u.bytes) + ' de ' + fBytes(u.cota) : ''}</span>
   <button type="button" class="dm-btn" data-act="newuser">＋ Novo usuário</button>${users ? '' : '<button type="button" class="dm-btn dm-primary" data-act="newsector">＋ Novo setor</button>'}</div>`;
  if(!users) return head + `<div class="dm-sgrid">${setores().map(s => {
    const st = sectorStats(s.id), us = usersOf(s.id).filter(p => p.ativo);
    return `<div class="dm-scard${s.ativo ? '' : ' dm-off'}" style="--dm-sc:${col(s.cor)}">
     <div class="dm-sh"><span class="dm-sico">${esc(s.icone)}</span><div class="dm-sname"><b>${esc(s.nome)}</b><span>${chip(s.id)}</span></div>${ativoPill(s.ativo)}</div>
     <div class="dm-sstats"><div><b>${st.on}</b>usuários</div><div><b>${st.open}</b>em aberto</div><div><b>${st.late}</b>atrasadas</div><div><b class="${slaC(st.sla)}">${st.sla == null ? '—' : st.sla + '%'}</b>no prazo (7d)</div></div>
     <div class="dm-avs">${us.slice(0, 6).map(p => av(p.id)).join('')}${us.length > 6 ? `<span class="dm-more">+${us.length - 6}</span>` : ''}${!us.length ? '<span class="dm-tg" data-k="late">Sem usuários ativos</span>' : ''}</div>
     <div class="dm-sbtn"><button type="button" class="dm-btn dm-sm" data-act="seeusers" data-v="${esc(s.id)}">👥 Usuários</button><button type="button" class="dm-btn dm-sm" data-act="editsector" data-v="${esc(s.id)}">✏️ Editar setor</button></div></div>`;
  }).join('') || '<div class="dm-empty">Nenhum setor cadastrado. Comece por ＋ Novo setor.</div>'}</div>`;
  const q = D.uq.trim().toLowerCase(), order = id => setores().findIndex(s => s.id === id);
  const list = pessoas().filter(p => (!D.uSec || p.setor === D.uSec) && (!D.uSt || (D.uSt === 'on') === !!p.ativo) && (!q || (p.nome + ' ' + p.mat).toLowerCase().includes(q)))
    .sort((a, b) => order(a.setor) - order(b.setor) || String(a.nome).localeCompare(String(b.nome), 'pt-BR'));
  return head + `<div class="dm-lbox"><div class="dm-uhead"><span>Usuário</span><span>Setor</span><span>Acesso</span><span>Desempenho</span><span>Status</span><span></span></div>${list.map(p => {
    const st = userStats(p.id), S = sec(p.setor);
    return `<div class="dm-urow${p.ativo ? '' : ' dm-off'}"><div class="dm-uname">${av(p.id)}<div><b>${esc(p.nome)}</b><small>Matrícula ${esc(p.mat)}</small></div></div>
     <div class="dm-usec">${chip(p.setor)}<span>${esc(S.nome)}</span></div><div class="dm-upin"><small>Código</small><code>••••</code></div>
     <div class="dm-ustat"><span>${st.open} em aberto</span><span>${st.done} concl. (7d)</span><span class="${slaC(st.sla)}">${st.sla == null ? 'sem dados' : st.sla + '% no prazo'}</span></div>
     <div class="dm-ust">${ativoPill(p.ativo)}</div>
     <div class="dm-uact"><button type="button" class="dm-btn dm-sm" data-act="edituser" data-v="${esc(p.id)}">✏️ Editar</button><button type="button" class="dm-btn dm-sm" data-act="impersonate" data-v="${esc(p.id)}"${p.ativo && S.ativo ? '' : ' disabled'} title="Ver o sistema como esta pessoa">👁 Ver como</button></div></div>`;
  }).join('') || '<div class="dm-empty" style="margin:12px">Nenhum usuário encontrado com esses filtros.</div>'}</div>`;
}

/* ---------- operador ---------- */
function ocard(r, mode){
  const ds = dispSt(r), op = openPause(r), me = meId(), mineR = r.para.p === me, id = esc(r.id), ro = !!D.imp;
  const B = (a, l, c) => `<button type="button" class="dm-btn dm-big ${c || ''}" data-act="${a}" data-id="${id}">${l}</button>`;
  let b = '', own = '';
  if(ro) b = '';
  else if(mode === 'recv'){
    if(r.status === 'new') b = B('accept', '▶ Aceitar e iniciar', 'dm-go') + B('reassign', '↪ Repassar');
    else if(mineR){
      if(r.status === 'prog') b = B('pause', '⏸ Pausar', 'dm-pz') + B('finish', '✔ Concluir', 'dm-fin') + B('reassign', '↪ Repassar');
      else if(r.status === 'pause') b = B('resume', '▶ Retomar', 'dm-go') + B('finish', '✔ Concluir', 'dm-fin');
    }else if(isAct(r)) own = `<div class="dm-pinfo dm-lock">🔒 Em andamento com <b>${esc(pname(r.para.p))}</b>. Só ele(a) pode pausar ou concluir.</div>`;
  }else if(isAct(r)) b = B('nudge', '🔔 Cobrar andamento') + B('cancel', '✕ Cancelar', 'dm-danger');
  return `<div class="dm-ocard" data-act="open" data-id="${id}" data-st="${ds}">
   <div class="dm-oh"><b>${id}</b>${pill(ds)}${pb(r.prio)}${mode === 'recv' && mineR && isAct(r) ? '<span class="dm-tg" data-k="wait">Minha</span>' : ''}<span class="dm-oty">${typ(r.tipo)}</span></div>
   <h3>${esc(r.titulo)}</h3>
   <div class="dm-route">${chip(r.de.s)}→${chip(r.para.s)}<span>${mode === 'recv' ? 'De ' + esc(deName(r)) : 'Para ' + esc(pname(r.para.p))}</span></div>
   <div class="dm-meta-line"><span>📌 ${esc(r.motivo)}</span><span>⏱ Estipulado: ${dur(r.est)}</span>${r.anexos.length ? `<span>📎 ${r.anexos.length}</span>` : ''}${r.comentarios.length ? `<span>💬 ${r.comentarios.length}</span>` : ''}</div>
   ${op ? `<div class="dm-pinfo">⏸ <b>${esc(op.motivo)}</b> · por ${esc(op.por)} às ${fT(op.ini)}${op.obs ? ' · ' + esc(op.obs) : ''}</div>` : ''}${own}
   ${slaBar(r)}<div class="dm-slarow"><span data-rem="${id}">${esc(remText(r))}</span><span>Prazo ${fDT(r.prazo)}</span></div>
   ${b ? `<div class="dm-obtns">${b}</div>` : ''}</div>`;
}
function vOp(){
  const me = per(meId()) || {id: meId(), nome: myName(), setor: meSec(), mat: D.eu && D.eu.mat}, sid = me.setor, S = sec(sid), N = now();
  const recv = reqs().filter(r => r.para.s === sid), sent = reqs().filter(r => r.de.p === me.id);
  const mineA = recv.filter(r => isAct(r) && r.para.p === me.id), queue = recv.filter(r => r.status === 'new');
  const mode = D.opTab, fl = mode === 'recv' ? [['mine', 'Minhas'], ['pend', 'Fila do setor'], ['done', 'Concluídas']] : [['pend', 'Em aberto'], ['done', 'Concluídas']];
  const cur = fl.some(x => x[0] === D.opF) ? D.opF : fl[0][0];
  let list;
  if(mode === 'recv'){
    if(cur === 'mine') list = recv.filter(r => isAct(r) && r.para.p === me.id);
    else if(cur === 'pend') list = recv.filter(isAct);
    else list = recv.filter(r => (r.status === 'done' || r.status === 'canc') && r.para.p === me.id && N - num(r.fim) < 2 * DAY);
  }else list = cur === 'done' ? sent.filter(r => (r.status === 'done' || r.status === 'canc') && N - num(r.fim) < 2 * DAY) : sent.filter(isAct);
  list = cur === 'done' ? list.sort((a, b) => num(b.fim) - num(a.fim)).slice(0, 15) : list.sort(sortAtt);
  const emptyMsg = mode === 'recv' && cur === 'mine' ? 'Você não tem solicitações em andamento agora.<br>Abra a <b>Fila do setor</b> para pegar uma nova.<br><button type="button" class="dm-btn dm-sm" data-act="opf" data-v="pend" style="margin-top:10px">Ver fila do setor</button>'
    : mode === 'sent' && cur === 'pend' ? 'Você ainda não enviou solicitações em aberto. Use <b>＋ Nova solicitação</b> para pedir algo a outro setor.' : 'Nada por aqui no momento.';
  const d = new Date(N);
  return `<div class="dm-opwrap"><div class="dm-ophead"><span class="dm-orb">${esc(S.icone)}</span><div><h2>Olá, ${esc(me.nome)}</h2><div class="dm-opsub">${esc(S.nome)} · matrícula ${esc(me.mat || '—')} · ${DOW[d.getDay()]} ${fD(N)}</div></div>
    <div class="dm-opstats"><div><b>${queue.length}</b>Na fila do setor</div><div><b>${mineA.filter(r => r.status === 'prog').length}</b>Minhas em andamento</div><div><b>${mineA.filter(r => r.status === 'pause').length}</b>Minhas pausadas</div><div><b>${mineA.filter(lateNow).length}</b>Minhas atrasadas</div></div></div>
   <div class="dm-filters"><div class="dm-seg" role="group">${fl.map(([k, l]) => `<button type="button" data-act="opf" data-v="${k}" aria-pressed="${k === cur}">${l}</button>`).join('')}</div><span class="dm-spacer"></span>${D.imp ? '' : '<button type="button" class="dm-btn dm-primary" data-act="new">＋ Nova solicitação</button>'}</div>
   ${list.map(r => ocard(r, mode)).join('') || `<div class="dm-empty">${emptyMsg}</div>`}</div>`;
}

/* ---------- gaveta da solicitação ---------- */
const canComment = r => !D.imp && (D.role === 'adm' || [r.de.s, r.para.s].includes(meSec()));
const canAttach = r => !D.imp && r.status !== 'canc' && r.anexos.length < ANX.n && (D.role === 'adm' || r.de.p === meId() || r.para.s === meSec());
const canDelAttach = (r, a) => !D.imp && isAct(r) && (D.role === 'adm' || a.por === myName());
function actionsHtml(r){
  if(!isAct(r)) return '';
  const id = esc(r.id), b = (a, l, c) => `<button type="button" class="dm-btn ${c || ''}" data-act="${a}" data-id="${id}">${l}</button>`;
  let h = '';
  if(D.imp) h = '<div class="dm-note" style="width:100%;margin:0">👁 Modo visualização: só leitura.</div>';
  else if(D.role === 'adm'){
    h = b('nudge', '🔔 Cobrar') + b('reassign', '↪ Reatribuir') + `<button type="button" class="dm-btn" data-act="extend" data-id="${id}" data-v="30">+30 min</button><button type="button" class="dm-btn" data-act="extend" data-id="${id}" data-v="60">+1 h</button>`
      + `<label class="dm-inl">Prioridade <select id="dm-dr-prio" data-id="${id}">${Object.keys(PRIO).map(k => opt(k, PRIO[k][0], r.prio)).join('')}</select></label>` + b('cancel', '✕ Cancelar', 'dm-danger');
  }else{
    const mineR = r.para.p === meId();
    if(r.para.s === meSec()){
      if(r.status === 'new') h += b('accept', '▶ Aceitar e iniciar', 'dm-go');
      else if(mineR){
        if(r.status === 'prog') h += b('pause', '⏸ Pausar', 'dm-pz') + b('finish', '✔ Concluir', 'dm-fin');
        if(r.status === 'pause') h += b('resume', '▶ Retomar', 'dm-go') + b('finish', '✔ Concluir', 'dm-fin');
      }else h += `<div class="dm-note" style="width:100%;margin:0">🔒 Em andamento com <b>${esc(pname(r.para.p))}</b>. Só ele(a) pode atualizar esta solicitação.</div>`;
      if(r.status === 'new' || mineR) h += b('reassign', '↪ Repassar');
    }
    if(r.de.p === meId() && r.para.p !== meId()) h += b('nudge', '🔔 Cobrar') + b('cancel', '✕ Cancelar', 'dm-danger');
  }
  return h ? `<div class="dm-dact">${h}</div>` : '';
}
function renderDrawer(){
  const el = $('dm-drawer'), r = byId(D.open);
  if(!r){closePanels(); return}
  const ci = $('dm-cmt'), keep = ci ? {v: ci.value, f: document.activeElement === ci} : null, sc = el.scrollTop;
  const ds = dispSt(r), m = mets(r), id = esc(r.id);
  const logs = r.eventos.slice().sort((a, b) => num(a.t) - num(b.t));
  el.innerHTML = `<button type="button" class="dm-btn dm-x" data-act="close" aria-label="Fechar">✕</button>
   <div class="dm-dtags">${pill(ds)}${pb(r.prio)}<span class="dm-tg" data-k="mut">${typ(r.tipo)}</span></div>
   <h2>${esc(r.titulo)}</h2><div class="dm-hsub">${id} · aberta ${fDT(r.criado)} por ${esc(deName(r))} (${esc(r.de.s)})</div>
   <div class="dm-big-route"><div class="dm-who">${chip(r.de.s)} ${avDe(r)} ${esc(deName(r))}</div><b>→</b><div class="dm-who">${chip(r.para.s)} ${av(r.para.p)} ${esc(pname(r.para.p))}</div></div>
   <div class="dm-slarow"><span>Prazo: <b>${fDT(r.prazo)}</b></span><span data-rem="${id}">${esc(remText(r))}</span></div>${slaBar(r)}
   <div class="dm-slarow"><span>Tempo estipulado: <b>${dur(r.est)}</b></span><span>Decorrido: <b data-met="total" data-id="${id}">${dur(m.t)}</b></span></div>
   <div class="dm-mets"><div>Espera<b data-met="wait" data-id="${id}">${dur(m.w)}</b></div><div>Execução<b data-met="exec" data-id="${id}">${dur(m.e)}</b></div><div>Pausas<b data-met="pause" data-id="${id}">${dur(m.p)}</b></div><div>Estimado<b>${dur(r.est)}</b></div></div>
   <div class="dm-meta"><div>Motivo<b>${esc(r.motivo)}</b></div><div>Setor responsável<b>${esc(sec(r.para.s).nome)}</b></div></div>
   ${actionsHtml(r)}
   <div class="dm-secx">Descrição</div><div class="dm-desc">${esc(r.desc || 'Sem descrição adicional.')}</div>
   <div class="dm-secx">Anexos</div><div class="dm-files">${r.anexos.map(a => `<span class="dm-file"><button type="button" class="dm-fo" data-act="aopen" data-aid="${esc(a.id)}" title="${esc(a.nome)} · enviado por ${esc(a.por)}">${a.tipo === 'pdf' ? '📄' : '🖼️'} ${esc(a.nome)} · ${fBytes(a.bytes)}</button>${canDelAttach(r, a) ? `<button type="button" class="dm-fx" data-act="adel" data-id="${id}" data-aid="${esc(a.id)}" aria-label="Remover anexo">✕</button>` : ''}</span>`).join('')}${!r.anexos.length ? '<span class="dm-note">Nenhum anexo.</span>' : ''}${canAttach(r) ? `<button type="button" class="dm-btn dm-sm" data-act="aadd" data-id="${id}">＋ Adicionar foto/arquivo</button>` : ''}</div>
   ${r.pausas.length ? `<div class="dm-secx">Pausas registradas</div>${r.pausas.map(p => `<div class="dm-pcard"><b>${esc(p.motivo)}</b><div class="dm-note" style="margin:2px 0 0">${fT(p.ini)} → ${p.fim ? fT(p.fim) + ' (' + dur((num(p.fim) - num(p.ini)) / MIN) + ')' : 'em andamento'} · por ${esc(p.por)}${p.obs ? ' · ' + esc(p.obs) : ''}</div></div>`).join('')}` : ''}
   <div class="dm-secx">Histórico</div><ul class="dm-tl">${logs.map(e => `<li data-ev="${esc(e.ev)}"><i></i><b>${esc(EVL[e.ev] || e.ev)}</b><time>${fDT(e.t)}</time><small>${esc(e.quem)}${e.nota ? ' · ' + esc(e.nota) : ''}</small></li>`).join('')}</ul>
   <div class="dm-secx">Comentários</div><div class="dm-cmts">${r.comentarios.map(c => `<div class="dm-cmt"><small>${esc(c.quem)} · ${fDT(c.t)}</small>${esc(c.texto)}</div>`).join('') || '<div class="dm-note">Nenhum comentário ainda.</div>'}</div>
   ${canComment(r) ? `<div class="dm-cmtf"><input type="text" id="dm-cmt" maxlength="1000" placeholder="Escreva um comentário" aria-label="Comentário"><button type="button" class="dm-btn dm-primary" data-act="comment" data-id="${id}">Enviar</button></div>` : ''}`;
  const ci2 = $('dm-cmt');
  if(keep && ci2){ci2.value = keep.v; if(keep.f) ci2.focus()}
  el.scrollTop = sc;
}
function openDrawer(id){
  if(!byId(id)){toast('Solicitação não encontrada (pode ter ido para o arquivo morto).'); return}
  D.open = id; D.notif = false; $('dm-notif').classList.remove('dm-on');
  renderDrawer();
  $('dm-drawer').classList.add('dm-on'); $('dm-scrim').classList.add('dm-on');
  const x = $('dm-drawer').querySelector('.dm-x'); if(x) try{x.focus({preventScroll: true})}catch(_){/* foco sem rolar */}
  root.scrollLeft = 0; root.scrollTop = 0;
  markReadFor(id);
}
function closePanels(){
  if(!root) return;
  const had = D.open || D.notif;
  D.open = null; D.notif = false;
  $('dm-drawer').classList.remove('dm-on'); $('dm-notif').classList.remove('dm-on'); $('dm-scrim').classList.remove('dm-on');
  if(had && D.dirty && !modalOn()) render();
}
function renderNotif(){
  const list = (D.v ? D.v.notas : []).slice(0, 40), un = list.filter(n => !n.lida).length;
  $('dm-notif').innerHTML = `<button type="button" class="dm-btn dm-x" data-act="close" aria-label="Fechar">✕</button><h2>Notificações</h2><div class="dm-hsub">${un} não lidas</div>
   <div class="dm-acts2"><button type="button" class="dm-btn dm-sm" data-act="noteall"${un ? '' : ' disabled'}>Marcar todas como lidas</button></div>
   ${list.map(n => {
     const r = byId(n.dem), t = NT[n.tipo] || ['🔔', 'Aviso'];
     if(!r) return '';
     return `<div class="dm-pcard${n.lida ? '' : ' dm-new'}"><div style="display:flex;justify-content:space-between;gap:8px"><b>${t[0]} ${t[1]}</b><span class="dm-note" style="margin:0">${fDT(n.t)}</span></div>
      <div style="margin:4px 0;font-weight:600">${esc(r.id)} · ${esc(r.titulo)}</div>
      <div class="dm-al-m">${chip(r.de.s)}→${chip(r.para.s)}<span>${esc(pname(r.para.p))}</span>${n.texto ? `<span>· <b>${n.tipo === 'pause' ? 'Motivo:' : 'Obs.:'}</b> ${esc(n.texto)}</span>` : ''}${n.quem ? `<span>· por ${esc(n.quem)}</span>` : ''}</div>
      <div class="dm-acts2" style="margin-top:8px"><button type="button" class="dm-btn dm-sm dm-primary" data-act="noteopen" data-id="${esc(r.id)}" data-n="${esc(n.id)}">Ver solicitação</button></div></div>`;
   }).join('') || '<div class="dm-empty" style="margin-top:14px">Nenhuma notificação.</div>'}`;
}
function openNotif(){
  if(!D.role) return;
  D.open = null; $('dm-drawer').classList.remove('dm-on');
  D.notif = true; renderNotif();
  $('dm-notif').classList.add('dm-on'); $('dm-scrim').classList.add('dm-on');
}

/* ---------- modais ---------- */
const modalOn = () => !!root && $('dm-modal').classList.contains('dm-on');
function openModal(html, wide){   // wide: true = largo; texto = classe própria da caixa
  const box = $('dm-mbox');
  box.className = 'dm-mbox' + (wide ? ' ' + (wide === true ? 'dm-wide' : wide) : '');
  box.innerHTML = html;
  $('dm-modal').classList.add('dm-on');
  const f = box.querySelector('input:not([type=radio]):not([disabled]),textarea,select');
  if(f && f.focus) try{f.focus({preventScroll: true})}catch(_){f.focus()}
}
function closeModal(){
  if(!root) return;
  if(D.mod && D.mod.url && window.URL && URL.revokeObjectURL) URL.revokeObjectURL(D.mod.url);
  $('dm-modal').classList.remove('dm-on'); $('dm-mbox').textContent = ''; $('dm-mbox').removeAttribute('aria-labelledby'); delete $('dm-mbox').dataset.sec;
  D.mod = null; D.form = null; D.sform = null; D.uform = null; D.cfg = null;
  if(D.dirty && !D.open && !D.notif) render();
}
function modalConfirm(title, msgHtml, okLabel, run){
  D.mod = {kind: 'confirm', run};
  openModal(`<h2>${esc(title)}</h2><div class="dm-note" style="font-size:14px">${msgHtml}</div><div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Voltar</button><button type="button" class="dm-btn dm-danger" data-act="cf-ok">${esc(okLabel)}</button></div>`);
}
const head = r => `<div class="dm-note" style="margin-top:0">${esc(r.id)} · ${esc(r.titulo)}</div>`;
function modalPause(r){
  D.mod = {kind: 'pause', id: r.id};
  openModal(`<h2>Registrar pausa</h2>${head(r)}<div class="dm-rsn">${PAUSE_REASONS.map((k, i) => `<label><input type="radio" name="dm-pr" value="${esc(k)}"${i === 0 ? ' checked' : ''}> ${esc(k)}</label>`).join('')}</div>
   <div class="dm-fld"><label for="dm-pobs">Observação (opcional)</label><textarea id="dm-pobs" rows="3" maxlength="500" placeholder="Ex.: faltam 4 espumas D33"></textarea></div>
   <div class="dm-note">A gerência será avisada na hora com a solicitação, o setor, o motivo e quem pausou.</div>
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-pz" data-act="m-pause-ok">⏸ Registrar pausa</button></div>`);
}
function modalFinish(r){
  D.mod = {kind: 'finish', id: r.id};
  const m = mets(r);
  openModal(`<h2>Concluir solicitação</h2>${head(r)}<div class="dm-mets"><div>Espera<b>${dur(m.w)}</b></div><div>Execução<b>${dur(m.e)}</b></div><div>Pausas<b>${dur(m.p)}</b></div><div>Estimado<b>${dur(r.est)}</b></div></div>
   <div class="dm-fld"><label for="dm-fnote">Observação de entrega (opcional)</label><textarea id="dm-fnote" rows="3" maxlength="500" placeholder="Ex.: material entregue no setor"></textarea></div>
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-fin" data-act="m-finish-ok">✔ Confirmar conclusão</button></div>`);
}
function modalReassign(r){
  D.mod = {kind: 'reassign', id: r.id};
  openModal(`<h2>${D.role === 'adm' ? 'Reatribuir' : 'Repassar'} solicitação</h2>${head(r)}
   <div class="dm-two"><div class="dm-fld"><label for="dm-ra-s">Setor</label><select id="dm-ra-s">${secOpts(r.para.s)}</select></div><div class="dm-fld"><label for="dm-ra-p">Pessoa</label><select id="dm-ra-p">${peopleOpts(r.para.s, r.para.p)}</select></div></div>
   <div class="dm-fld"><label for="dm-ra-n">Observação (opcional)</label><textarea id="dm-ra-n" rows="2" maxlength="500"></textarea></div>
   <div class="dm-note">Se mudar de setor, a solicitação volta para “Aberta” e o novo setor é avisado.</div>
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-primary" data-act="m-ra-ok">Confirmar</button></div>`);
}
function modalCancel(r){
  D.mod = {kind: 'cancel', id: r.id};
  openModal(`<h2>Cancelar solicitação</h2>${head(r)}<div class="dm-fld"><label for="dm-cn">Motivo do cancelamento</label><textarea id="dm-cn" rows="3" maxlength="500" placeholder="Ex.: pedido duplicado"></textarea></div>
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Voltar</button><button type="button" class="dm-btn dm-danger" data-act="m-cn-ok">Cancelar solicitação</button></div>`);
}

/* nova solicitação */
/* rascunho da nova solicitação: neste aparelho, por pessoa, por 24 h; sobrevive à queda da conexão e ao "Identifique-se
   de novo". Nunca guarda o tk. O cid (chave do pedido) vai junto: reenviar depois de uma resposta perdida não duplica. */
const RASC_VIDA = 24 * 3600000, CID_RE = /^[A-Za-z0-9_-]{8,64}$/;
const novoCid = () => window.crypto && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
const rascKey = () => 'dm-rascunho:' + (D.role === 'adm' ? 'adm' : meId());
function rascLe(){
  try{const r = JSON.parse(localStorage.getItem(rascKey()) || 'null'); return r && typeof r === 'object' && num(r.t) > Date.now() - RASC_VIDA ? r : null}
  catch(_){return null}
}
function rascGrava(){
  const f = D.form;
  if(!f || !D.role) return;
  try{
    if(!f.titulo.trim() && !f.desc.trim()) localStorage.removeItem(rascKey());
    else localStorage.setItem(rascKey(), JSON.stringify({t: Date.now(), cid: f.cid, tipo: f.tipo, titulo: f.titulo, desc: f.desc, fromS: f.fromS, toS: f.toS, toP: f.toP, motivo: f.motivo, prio: f.prio, est: f.est, anexos: f.files.length}));
  }catch(_){/* sem armazenamento no aparelho: o rascunho só não sobrevive */}
}
function rascApaga(){try{localStorage.removeItem(rascKey())}catch(_){/* idem */}}
function openNew(fresh){
  if(!D.role) return;
  const act = activeSectors(), adm = D.role === 'adm', sids = act.map(s => s.id);
  const fromS = adm ? ((act.find(s => s.id === 'PCP') || act[0] || {}).id || '') : meSec();
  D.form = {tipo: 'dem', titulo: '', desc: '', fromS, toS: '', toP: '', motivo: '', prio: 'norm', est: 60, files: [], err: {}, cid: novoCid()};
  const r = fresh ? null : rascLe();
  if(r){   // o que veio do aparelho passa pelas mesmas listas da tela
    const est = num(r.est), toS = sids.includes(r.toS) ? r.toS : '';
    Object.assign(D.form, {tipo: TYPE[r.tipo] ? r.tipo : 'dem', titulo: String(r.titulo || '').slice(0, 140), desc: String(r.desc || '').slice(0, 2000),
      fromS: adm && sids.includes(r.fromS) ? r.fromS : fromS, toS, toP: toS && peopleOf(toS).some(p => p.id === r.toP) ? r.toP : '',
      motivo: REASONS.includes(r.motivo) ? r.motivo : '', prio: PRIO[r.prio] ? r.prio : 'norm', est: est >= 1 && est <= 43200 ? est : 60,
      recup: num(r.t), semAnexos: num(r.anexos) > 0});
    if(typeof r.cid === 'string' && CID_RE.test(r.cid)) D.form.cid = r.cid;
  }
  D.mod = {kind: 'new'};
  renderForm();
}
function renderForm(){
  const f = D.form, e = f.err, chipsEst = [30, 60, 120, 240, 480], custom = !chipsEst.includes(f.est);
  const cu = f.est % 60 === 0 && f.est >= 60 ? 'h' : 'm', cv = cu === 'h' ? f.est / 60 : f.est;
  const me = per(meId());
  openModal(`<h2>Nova solicitação</h2><div class="dm-note" style="margin-top:0">Preencha os dados. O setor responsável é avisado na hora e você acompanha o andamento em tempo real.</div>
   ${f.recup ? `<div class="dm-rasc" id="dm-fm-rasc"><span>📝 Rascunho recuperado de ${fD(f.recup)} ${fT(f.recup)}${f.semAnexos ? ' · refaça os anexos' : ''}</span><button type="button" class="dm-btn dm-sm" data-act="m-draft-x">Descartar</button></div>` : ''}
   <div class="dm-fld"><span class="dm-lbl">Tipo</span><div class="dm-opts">${Object.entries(TYPE).map(([k, v]) => `<button type="button" class="dm-opt" data-act="m-type" data-v="${k}" aria-pressed="${f.tipo === k}">${v[0]} ${v[1]}</button>`).join('')}</div></div>
   <div class="dm-fld${e.titulo ? ' dm-err' : ''}"><label for="dm-fm-title">Título</label><input type="text" id="dm-fm-title" maxlength="140" placeholder="Ex.: Corte de 8 chapas de MDF 15mm" value="${esc(f.titulo)}"><span class="dm-em">Descreva a solicitação com 5 a 140 caracteres.</span></div>
   <div class="dm-fld"><label for="dm-fm-desc">Descrição (opcional)</label><textarea id="dm-fm-desc" rows="3" maxlength="2000" placeholder="Detalhes, medidas, referências...">${esc(f.desc)}</textarea></div>
   <div class="dm-two">
    <div class="dm-fld${e.fromS ? ' dm-err' : ''}"><span class="dm-lbl">Solicitante</span>${D.role === 'adm' ? `<select id="dm-fm-fromS" aria-label="Setor solicitante">${secOpts(f.fromS)}</select><span class="dm-em">Escolha o setor que pede.</span>` : `<div class="dm-fixed">${chip(f.fromS)} ${esc(me ? me.nome : myName())}</div>`}</div>
    <div class="dm-fld${e.toS ? ' dm-err' : ''}"><label for="dm-fm-toS">Setor responsável</label><select id="dm-fm-toS">${opt('', 'Selecione o setor', f.toS)}${secOpts(f.toS)}</select><span class="dm-em">Escolha o setor responsável.</span></div>
   </div>
   <div class="dm-fld"><label for="dm-fm-toP">Pessoa responsável</label><select id="dm-fm-toP"${f.toS ? '' : ' disabled'}>${f.toS ? peopleOpts(f.toS, f.toP) : opt('', 'Escolha o setor primeiro', '')}</select>${f.toS && !peopleOf(f.toS).length ? '<div class="dm-note">⚠️ Este setor ainda não tem usuários ativos. A solicitação ficará aguardando até alguém ser cadastrado.</div>' : ''}</div>
   <div class="dm-fld${e.motivo ? ' dm-err' : ''}"><span class="dm-lbl">Motivo</span><div class="dm-opts">${REASONS.map(k => `<button type="button" class="dm-opt" data-act="m-reason" data-v="${esc(k)}" aria-pressed="${f.motivo === k}">${esc(k)}</button>`).join('')}</div><span class="dm-em">Selecione o motivo da solicitação.</span></div>
   <div class="dm-fld"><span class="dm-lbl">Prioridade</span><div class="dm-opts">${Object.keys(PRIO).map(k => `<button type="button" class="dm-opt" data-p="${k}" data-act="m-prio" data-v="${k}" aria-pressed="${f.prio === k}">${PRIO[k][0]}</button>`).join('')}</div></div>
   <div class="dm-fld${e.est ? ' dm-err' : ''}"><span class="dm-lbl">Tempo estipulado para concluir</span><div class="dm-opts">${[['30', '30 min'], ['60', '1 h'], ['120', '2 h'], ['240', '4 h'], ['480', '8 h']].map(([m, l]) => `<button type="button" class="dm-opt" data-act="m-est" data-v="${m}" aria-pressed="${!custom && f.est === +m}">${l}</button>`).join('')}</div>
    <div class="dm-row"><span class="dm-note" style="margin:0">Personalizado:</span><input type="number" min="1" max="43200" id="dm-fm-estN" value="${esc(cv)}" style="width:92px;flex:none" aria-label="Tempo"><select id="dm-fm-estU" aria-label="Unidade">${opt('m', 'minutos', cu)}${opt('h', 'horas', cu)}</select></div>
    <div class="dm-prev" id="dm-fm-prev">${prevTxt(f.est)}</div><span class="dm-em">Informe um tempo entre 1 minuto e 30 dias.</span></div>
   <div class="dm-fld"><span class="dm-lbl">Anexos (JPG, PNG ou PDF, até 5 MB, no máximo 5)</span><div class="dm-files">${f.files.map((x, i) => `<span class="dm-file">📎 ${esc(x.name)} · ${fBytes(x.size)}<button type="button" class="dm-fx" data-act="m-rmfile" data-v="${i}" aria-label="Remover">✕</button></span>`).join('')}${f.files.length < ANX.n ? '<button type="button" class="dm-btn dm-sm" data-act="m-addfile">＋ Adicionar foto/arquivo</button>' : ''}</div></div>
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-primary" data-act="m-submit">Enviar solicitação</button></div>`);
  rascGrava();
}
const prevTxt = est => est > 0 ? `Prazo final: <b>${fDT(now() + est * MIN)}</b> (${dur(est)} a partir de agora)` : 'Informe o tempo estipulado.';
function setEstFromInputs(rerender){
  const n = parseFloat($('dm-fm-estN').value), u = $('dm-fm-estU').value;
  D.form.est = n > 0 ? Math.round(n * (u === 'h' ? 60 : 1)) : 0; D.form.err.est = 0;
  if(rerender) renderForm(); else $('dm-fm-prev').innerHTML = prevTxt(D.form.est);
}
async function submitNew(el){
  const f = D.form, err = {}, t = f.titulo.trim();
  if(t.length < 5 || t.length > 140) err.titulo = 1;
  if(!f.toS) err.toS = 1;
  if(!f.motivo) err.motivo = 1;
  if(!(f.est >= 1 && f.est <= 43200)) err.est = 1;
  if(D.role === 'adm' && !f.fromS) err.fromS = 1;
  f.err = err;
  if(Object.keys(err).length){renderForm(); const e1 = $('dm-mbox').querySelector('.dm-fld.dm-err'); if(e1 && e1.scrollIntoView) e1.scrollIntoView({block: 'center'}); return}
  const body = {titulo: t, tipo: f.tipo, motivo: f.motivo, prio: f.prio, est: Math.round(f.est), para: {s: f.toS, p: f.toP || null}, desc: f.desc.trim().slice(0, 2000), cid: f.cid};
  if(D.role === 'adm') body.de_s = f.fromS;
  const before = new Set(reqs().map(r => r.id)), files = f.files.slice(), to = f.toS;
  el.disabled = true;
  const r = await call('demanda/criar', body);
  if(el.isConnected) el.disabled = false;
  if(!r) return;
  const nid = reqs().map(x => x.id).filter(id => !before.has(id)).sort((a, b) => sidNum(a) - sidNum(b)).pop();
  rascApaga();   // só depois de o servidor confirmar
  closeModal();
  toast('✅ Solicitação enviada para ' + sec(to).nome);
  if(D.role === 'pessoa' && !D.imp){D.opTab = 'sent'; D.opF = 'pend'}
  render();
  if(nid && files.length){await upload(nid, files); if(!busyUI()) render()}
}

/* setor */
function suggestId(name){
  const stop = ['DE', 'DA', 'DO', 'DAS', 'DOS', 'E'];
  const w = name.normalize('NFD').replace(/[̀-ͯ]/g, '').toUpperCase().replace(/[^A-Z0-9 ]/g, ' ').split(/\s+/).filter(x => x && !stop.includes(x));
  let id = w.length >= 2 ? w.slice(0, 4).map(x => x[0]).join('') : (w[0] || '').slice(0, 3);
  if(id.length < 2) id = (w[0] || '').slice(0, 2);
  const base = id.slice(0, 3), has = x => setores().some(s => s.id === x);
  let n = 2;
  while(id && has(id) && n < 10){id = base + n; n++}
  return id;
}
function openSF(mode, id){
  const s = id ? sec(id) : null, n = setores().length;
  D.sform = mode === 'edit' ? {mode, id, name: s.nome, icon: s.icone, color: col(s.cor), idTouched: true, err: {}} : {mode, id: '', name: '', icon: ICONS[n % ICONS.length], color: COLORS[n % COLORS.length], idTouched: false, err: {}};
  D.mod = {kind: 'sector'};
  renderSF();
}
function updateSFPrev(){
  const f = D.sform, el = $('dm-sf-prev'); if(!f || !el) return;
  el.innerHTML = `<span class="dm-abbr" style="--dm-sc:${col(f.color)}">${esc(f.id || 'SIG')}</span><span>${esc(f.icon)} ${esc(f.name || 'Nome do setor')}</span>`;
}
function renderSF(){
  const f = D.sform, e = f.err, edit = f.mode === 'edit', s = edit ? sec(f.id) : null, st = edit ? sectorStats(f.id) : null;
  openModal(`<h2>${edit ? 'Editar setor' : 'Novo setor'}</h2><div class="dm-note" style="margin-top:0">${edit ? 'A sigla não pode ser alterada porque identifica o setor no histórico.' : 'O novo setor passa a aparecer no mapa, nos filtros e na criação de solicitações.'}</div>
   <div class="dm-fld${e.name ? ' dm-err' : ''}"><label for="dm-sf-name">Nome do setor</label><input type="text" id="dm-sf-name" maxlength="40" value="${esc(f.name)}" placeholder="Ex.: Pintura"><span class="dm-em">Informe o nome (3 a 40 caracteres).</span></div>
   <div class="dm-two"><div class="dm-fld${e.id ? ' dm-err' : ''}"><label for="dm-sf-id">Sigla (2 a 4 caracteres)</label><input type="text" id="dm-sf-id" maxlength="4" value="${esc(f.id)}"${edit ? ' disabled' : ''} style="text-transform:uppercase" placeholder="Ex.: PIN"><span class="dm-em">${esc(e.idMsg || 'Sigla inválida.')}</span></div>
    <div class="dm-fld"><span class="dm-lbl">Pré-visualização</span><div class="dm-fixed" id="dm-sf-prev"></div></div></div>
   <div class="dm-fld"><span class="dm-lbl">Ícone</span><div class="dm-opts">${ICONS.map(i => `<button type="button" class="dm-opt dm-eo" data-act="sf-icon" data-v="${i}" aria-pressed="${f.icon === i}">${i}</button>`).join('')}</div></div>
   <div class="dm-fld"><span class="dm-lbl">Cor do setor</span><div class="dm-opts">${COLORS.map(c => `<button type="button" class="dm-sw" style="--dm-sc:${c}" data-act="sf-color" data-v="${c}" aria-pressed="${f.color === c}" aria-label="Cor ${c}"></button>`).join('')}</div></div>
   ${edit ? `<div class="dm-note"><b>${st.on}</b> usuário(s) ativo(s) · <b>${st.open}</b> solicitação(ões) em aberto · status: <b>${s.ativo ? 'ativo' : 'inativo'}</b></div>
    <div class="dm-dact"><button type="button" class="dm-btn" data-act="sf-toggle">${s.ativo ? '⏸ Desativar setor' : '▶ Reativar setor'}</button><button type="button" class="dm-btn dm-danger" data-act="sf-del">🗑 Excluir setor</button></div>` : ''}
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-primary" data-act="sf-save">${edit ? 'Salvar alterações' : 'Criar setor'}</button></div>`);
  updateSFPrev();
}

/* pessoa (código de 4 dígitos no lugar da senha) */
function genCode(){
  const a = new Uint32Array(1);
  if(window.crypto && crypto.getRandomValues) crypto.getRandomValues(a); else a[0] = Math.floor(Math.random() * 1e9);
  return String(a[0] % 10000).padStart(4, '0');
}
function openUF(mode, id, setor){
  const p = id ? per(id) : null;
  D.uform = mode === 'edit' ? {mode, id, name: p.nome, setor: p.setor, code: '', show: false, err: {}} : {mode, id: null, name: '', setor: setor || '', code: genCode(), show: true, err: {}};
  D.mod = {kind: 'user'};
  renderUF();
}
function renderUF(){
  const f = D.uform, e = f.err, edit = f.mode === 'edit', p = edit ? per(f.id) : null, st = edit ? userStats(f.id) : null;
  const moving = edit && f.setor && p.setor !== f.setor;
  openModal(`<h2>${edit ? 'Editar usuário' : 'Novo usuário'}</h2><div class="dm-note" style="margin-top:0">${edit ? 'Matrícula ' + esc(p.mat) : 'A pessoa entra pelo “Quem é você?” escolhendo o setor, o nome e digitando o código. Só vê o que é do setor dela e o que ela pediu.'}</div>
   <div class="dm-fld${e.name ? ' dm-err' : ''}"><label for="dm-uf-name">Nome do usuário</label><input type="text" id="dm-uf-name" maxlength="60" value="${esc(f.name)}" placeholder="Ex.: Roberto"><span class="dm-em">Informe o nome (2 a 60 caracteres).</span></div>
   <div class="dm-fld${e.setor ? ' dm-err' : ''}"><label for="dm-uf-sec">Setor</label><select id="dm-uf-sec">${opt('', 'Selecione o setor', f.setor)}${secOpts(f.setor)}</select><span class="dm-em">Escolha o setor do usuário.</span></div>
   <div class="dm-fld${e.code ? ' dm-err' : ''}"><label for="dm-uf-code">${edit ? 'Novo código (opcional)' : 'Código de 4 dígitos'}</label><div class="dm-row"><div class="dm-pwrap" style="flex:1"><input type="${f.show ? 'text' : 'password'}" id="dm-uf-code" inputmode="numeric" pattern="[0-9]*" maxlength="4" autocomplete="off" value="${esc(f.code)}" placeholder="${edit ? 'Deixe em branco para manter' : '••••'}"><button type="button" class="dm-eye" data-act="uf-eye" aria-label="Mostrar ou ocultar o código">${f.show ? '🙈' : '👁'}</button></div><button type="button" class="dm-btn" data-act="uf-gen">Gerar</button></div><span class="dm-em">O código tem exatamente 4 números.</span></div>
   ${moving ? '<div class="dm-note">⚠️ Ao mudar de setor, as solicitações em aberto atribuídas a ' + esc(p.nome) + ' voltam para a fila do setor atual.</div>' : ''}
   ${edit ? `<div class="dm-note"><b>${st.open}</b> em aberto · <b>${st.done}</b> concluídas (7d) · desempenho: <b>${st.sla == null ? 'sem dados' : st.sla + '% no prazo'}</b> · status: <b>${p.ativo ? 'ativo' : 'inativo'}</b></div>
    <div class="dm-dact"><button type="button" class="dm-btn" data-act="uf-toggle">${p.ativo ? '⏸ Desativar usuário' : '▶ Reativar usuário'}</button><button type="button" class="dm-btn dm-danger" data-act="uf-del">🗑 Excluir usuário</button></div>` : ''}
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-primary" data-act="uf-save">${edit ? 'Salvar alterações' : 'Criar usuário'}</button></div>`);
}

/* ---------- anexos: conferência no cliente, base64 para o servidor, Blob para abrir ---------- */
function pickFiles(cb){
  const inp = document.createElement('input');
  inp.type = 'file'; inp.multiple = true; inp.hidden = true;
  inp.accept = '.jpg,.jpeg,.png,.pdf,image/jpeg,image/png,application/pdf';
  inp.addEventListener('change', () => {const fs = Array.from(inp.files || []); inp.remove(); cb(fs)});
  root.appendChild(inp);
  inp.click();
}
function checkFile(f){
  const n = String(f && f.name || '');
  if(!ANX.ext.test(n)) return 'Só JPG, PNG ou PDF: ' + n;
  if(f.type && !/^(image\/(jpeg|png)|application\/pdf)$/.test(f.type)) return 'Tipo não aceito: ' + n;
  if(!f.size) return n + ' está vazio.';
  if(f.size > ANX.max) return n + ' passa de 5 MB.';
  return '';
}
function b64(f){
  return new Promise((res, rej) => {
    const fr = new FileReader();
    fr.onload = () => {const s = String(fr.result || ''); res(s.slice(s.indexOf(',') + 1))};
    fr.onerror = () => rej(new Error('Não foi possível ler ' + f.name));
    fr.readAsDataURL(f);
  });
}
async function upload(id, files){
  let ok = 0;
  for(const f of files){
    const e = checkFile(f);
    if(e){toast('⚠️ ' + e); continue}
    let dados;
    try{dados = await b64(f)}catch(x){toast('⚠️ ' + x.message); continue}
    const r = await call('anexo/enviar', {id, nome: String(f.name).replace(/[\u0000-\u001f\u007f]/g, '').slice(-120), dados});
    if(!r) break;
    ok++;
  }
  if(ok) toast('📎 ' + ok + ' anexo(s) enviado(s)');
  return ok;
}
function addFilesTo(r){
  pickFiles(async fs => {
    const room = ANX.n - r.anexos.length, ok = [];
    for(const f of fs){const e = checkFile(f); if(e) toast('⚠️ ' + e); else ok.push(f)}
    if(ok.length > room) toast('⚠️ No máximo ' + ANX.n + ' anexos por solicitação.');
    if(ok.length && room > 0){await upload(r.id, ok.slice(0, room)); render()}
  });
}
async function openAnexo(aid){
  if(!AID.test(aid)) return;
  const r = D.role === 'adm' ? await call('anexo/' + aid, undefined, {notake: true}) : await call('anexo/ler', {aid}, {notake: true});
  if(!r || typeof r.dados !== 'string') return;
  const tipo = ANX.mime[r.tipo];
  if(!tipo){toast('⚠️ Tipo de anexo desconhecido.'); return}
  let bin;
  try{bin = atob(r.dados)}catch(_){toast('⚠️ Anexo danificado.'); return}
  const u8 = new Uint8Array(bin.length);
  for(let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  if(!(window.URL && URL.createObjectURL)){toast('⚠️ Este navegador não abre anexos.'); return}
  const url = URL.createObjectURL(new Blob([u8], {type: tipo})), nome = String(r.nome || 'anexo.' + r.tipo);
  if(r.tipo === 'pdf'){
    const a = document.createElement('a');
    a.href = url; a.download = nome; a.rel = 'noopener'; a.hidden = true;
    root.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    toast('⬇ ' + nome + ' baixado');
    return;
  }
  if(D.mod && D.mod.url) URL.revokeObjectURL(D.mod.url);
  D.mod = {kind: 'viewer', url};
  openModal('<h2 id="dm-vw-t"></h2><div class="dm-viewer"><img id="dm-vw-img" alt=""></div><div class="dm-mfoot"><a class="dm-btn" id="dm-vw-dl">⬇ Baixar</a><button type="button" class="dm-btn dm-primary" data-act="mclose">Fechar</button></div>', true);
  $('dm-vw-t').textContent = nome;
  const img = $('dm-vw-img'), dl = $('dm-vw-dl');
  img.src = url; img.alt = nome; dl.href = url; dl.download = nome;
}

/* ---------- desenho ---------- */
const typing = () => {const a = document.activeElement; return !!a && !!root && root.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && !(D.mod && D.mod.kind === 'who')};
const busyUI = () => modalOn() || !!D.open || D.notif || typing();
function renderView(){
  const el = $('dm-view');
  if(!D.role || !D.v){el.innerHTML = ''; return}
  const key = D.role + '|' + (D.imp || '') + '|' + (isAdm() ? D.tab + (D.tab === 'admin' ? D.admSub : '') : D.opTab), intro = key !== D.lastKey && !D.noIntro;
  D.lastKey = key;
  const sc = $('dm-scroll'), top = sc.scrollTop, a = document.activeElement, fid = a && el.contains(a) && a.id ? a.id : '', sel = fid && a.selectionStart != null ? [a.selectionStart, a.selectionEnd] : null;
  el.innerHTML = !isAdm() ? vOp() : D.tab === 'painel' ? vPainel(intro) : D.tab === 'sol' ? vSol() : D.tab === 'hist' ? vHist() : D.tab === 'crono' ? vCrono() : vAdmin();
  if(intro) sc.scrollTop = 0; else sc.scrollTop = top;
  if(fid){const f = $(fid); if(f){f.focus(); if(sel && f.setSelectionRange) try{f.setSelectionRange(sel[0], sel[1])}catch(_){/* tipo sem seleção */}}}
  if(intro) countUp(el);
}
function render(){
  if(!root) return;
  const who = !D.role;
  $('dm-login').hidden = !who;
  if(who) renderLogin(); else $('dm-login').textContent = '';   // escondido de verdade: nada duplicado na árvore de acessibilidade
  $('dm-sub').textContent = who ? 'Identifique-se para ver as solicitações.' : isAdm() ? SUB_ADM : SUB_OP;
  renderChip(); renderImp(); renderTabs(); renderView(); renderBell();
  root.querySelector('.dm-fab').hidden = who || !!D.imp;
  root.querySelector('.dm-hdnew').hidden = who;
  $('dm-bell').disabled = who;
  if(D.open) renderDrawer();
  if(D.notif) renderNotif();
  clock();
  D.dirty = false;
}
function soft(){if(busyUI()){patch(); renderBell(); D.dirty = true} else render()}
function patch(){
  if(!D.v || !root) return;
  root.querySelectorAll('[data-rem]').forEach(el => {const r = byId(el.dataset.rem); if(r) el.textContent = remText(r)});
  root.querySelectorAll('[data-sla]').forEach(el => {const r = byId(el.dataset.sla); if(r){el.style.width = Math.min(100, mets(r).sla).toFixed(1) + '%'; if(el.parentElement) el.parentElement.className = 'dm-sla ' + slaCls(r)}});
  root.querySelectorAll('[data-met]').forEach(el => {const r = byId(el.dataset.id); if(!r) return; const m = mets(r), k = el.dataset.met; el.textContent = dur(k === 'wait' ? m.w : k === 'exec' ? m.e : k === 'pause' ? m.p : m.t)});
}
function countUp(el){
  if(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if(typeof requestAnimationFrame !== 'function' || !window.performance) return;
  el.querySelectorAll('[data-count]').forEach(x => {
    const n = num(x.dataset.count);
    if(!n) return;
    const t0 = performance.now(), d = 650;
    const f = t => {const k = Math.min(1, (t - t0) / d); x.textContent = String(Math.round(n * (1 - Math.pow(1 - k, 3)))); if(k < 1) requestAnimationFrame(f)};
    x.textContent = '0'; requestAnimationFrame(f);
  });
}
function flip(fn){
  const pos = {};
  root.querySelectorAll('#dm-map .dm-tile').forEach(t => {pos[t.dataset.v] = t.getBoundingClientRect()});
  D.noIntro = true; fn(); D.noIntro = false;
  root.querySelectorAll('#dm-map .dm-tile').forEach(t => {
    const o = pos[t.dataset.v]; if(!o || !t.animate) return;
    const n = t.getBoundingClientRect(), dx = o.left - n.left, dy = o.top - n.top;
    if(dx || dy) t.animate([{transform: `translate(${dx}px,${dy}px)`}, {transform: 'none'}], {duration: 450, easing: 'cubic-bezier(.2,.8,.2,1)'});
  });
}

/* ---------- ⚙ Configurações (só no computador principal): Rede e Backup ---------- */
const BK_TIPO = {auto: 'diária', inicio: 'ao ligar', manual: 'manual', 'antes-restaurar': 'antes de restaurar'};
const BK_RET = [['diarias', 'Diárias'], ['semanais', 'Semanais'], ['mensais', 'Mensais'], ['manuais', 'Manuais']];
const BK_LIM = [[1000, '1 GB'], [2000, '2 GB'], [5000, '5 GB'], [10000, '10 GB'], [50000, '50 GB'], [1000000, 'Sem limite']];
const gBytes = b => num(b) >= 1073741824 ? (num(b) / 1073741824).toFixed(1).replace('.', ',') + ' GB' : fBytes(b);
const fQuando = ms => (sameDay(ms, Date.now()) ? 'Hoje' : fD(ms)) + ', ' + fT(ms);
/* rotas da casca (/api/rede, /api/backup): fora do call(), que é das demandas */
async function sys(path, body){
  try{return await window.api(path, body)}catch(e){toast('⚠️ ' + errMsg(e)); return null}
}
async function openCfg(sec){
  if(D.srv !== 'maquina' || !root) return;
  const [rede, bk] = await Promise.all([sys('/api/rede'), sys('/api/backup')]);
  if(!rede || !bk) return;
  D.cfg = {sec: sec === 'backup' ? 'backup' : 'rede', rede, bk};
  openModal('', 'dm-cfgbox');
  renderCfg();
}
function renderCfg(){
  const c = D.cfg, box = $('dm-mbox');
  if(!c || !box) return;
  const r = c.bk.resumo, dot = r && r.alerta ? `<span class="dm-cfgdot" title="${esc(r.texto)}"></span>` : '';
  const nav = [['rede', '🌐 Rede', ''], ['backup', '💾 Backup', dot]].map(([k, l, x]) => `<button type="button" data-act="cfg-sec" data-v="${k}"${c.sec === k ? ' aria-current="page"' : ''}>${l}${x}</button>`).join('');
  const tela = c.sec + (c.rest ? ':restaurar' : '');
  const corpo = box.querySelector('.dm-cfgbody'), topo = corpo && box.dataset.sec === tela ? corpo.scrollTop : 0;   // mesma tela: não pula para o topo
  box.setAttribute('aria-labelledby', 'dm-cfg-t');
  box.dataset.sec = tela;
  box.innerHTML = `<div class="dm-cfg"><div class="dm-cfghead"><h2 id="dm-cfg-t">⚙ Configurações</h2><small>Só neste computador</small><button type="button" class="dm-btn dm-sm" data-act="mclose" aria-label="Fechar">✕</button></div>
   <nav class="dm-cfgnav" aria-label="Seções das configurações">${nav}</nav>
   <div class="dm-cfgbody">${c.sec === 'rede' ? cfgRede(c.rede) : c.rest ? cfgRest(c.rest) : cfgBackup(c.bk)}</div></div>`;
  box.querySelector('.dm-cfgbody').scrollTop = topo;
}
function cfgRede(n){
  const msg = n.on && !n.active ? 'Feche e abra o programa (iniciar.bat) para ligar o acesso.' : !n.on && n.active ? 'Feche e abra o programa (iniciar.bat) para desligar o acesso.' : '';
  const urls = (n.urls || []).map(u => `<code class="dm-cfgurl">${esc(u)}</code>`).join('') || '<p class="dm-note">Nenhum endereço de rede encontrado neste computador.</p>';
  return `<section class="dm-cfgsec"><h3>Acesso pela rede</h3>
   <label class="dm-cfgsw"><input type="checkbox" id="dm-cfg-on"${n.on ? ' checked' : ''}><i aria-hidden="true"></i><span><b>Ligar o acesso pela rede</b><small>Outros computadores, celulares e tablets do mesmo Wi-Fi usam a Central com PIN. Ligar ou desligar vale depois de reiniciar o programa.</small></span></label>
   ${msg ? `<p class="dm-cfgmsg" id="dm-cfg-msg">${esc(msg)}</p>` : ''}</section>
  ${n.on ? `<section class="dm-cfgsec"><h3>PINs</h3><div class="dm-cfgpins">
    <div class="dm-cfgpin"><span>PIN do escritório</span><b id="dm-cfg-pin">${esc(n.pin)}</b><small>Abre tudo, inclusive a Administração. Use só nos computadores do escritório.</small><button type="button" class="dm-btn dm-sm" data-act="cfg-pin" data-v="pin">Gerar novo</button></div>
    <div class="dm-cfgpin"><span>PIN dos operadores</span><b id="dm-cfg-pinop">${esc(n.pin_op)}</b><small>Abre só a tela de operador: pedir, aceitar e acompanhar solicitações.</small><button type="button" class="dm-btn dm-sm" data-act="cfg-pin" data-v="pin_op">Gerar novo</button></div></div>
    <p class="dm-note">Gerar um PIN novo desconecta os aparelhos que entraram com o antigo.</p></section>
   <section class="dm-cfgsec"><h3>Endereços para os outros aparelhos</h3>${n.active ? urls : '<p class="dm-note">Os endereços aparecem depois de reiniciar o programa com o acesso ligado.</p>'}</section>` : ''}`;
}
function cfgBackup(p){
  const f = p.cfg, ok = p.estado.ultimo_ok, falha = p.estado.ultima_falha, falhou = falha && (!ok || falha.t > ok.t);
  const lims = BK_LIM.some(([v]) => v === f.limite_mb) ? BK_LIM : BK_LIM.concat([[f.limite_mb, String(f.limite_mb / 1000).replace('.', ',') + ' GB']]).sort((a, b) => a[0] - b[0]);
  const limTxt = lims.find(([v]) => v === f.limite_mb)[1], uso = Math.min(100, p.usado / (f.limite_mb * 1048576) * 100);
  return `<section class="dm-cfgsec"><h3>Cópia automática<span class="dm-spacer"></span><label class="dm-cfgsw"><input type="checkbox" id="dm-bk-on"${f.on ? ' checked' : ''}><i aria-hidden="true"></i><b id="dm-bk-ontx">${f.on ? 'Ligada' : 'Desligada'}</b></label></h3>
   <div class="dm-cfglinha"><label for="dm-bk-hora">Todo dia às</label><input id="dm-bk-hora" type="time" value="${esc(f.hora)}">
    <label class="dm-inl"><input type="checkbox" id="dm-bk-lig"${f.ao_ligar ? ' checked' : ''}> Também ao ligar o programa, se a última cópia tiver mais de 20 h</label></div>
   <p class="dm-note">Se o computador estiver desligado no horário, a cópia é feita assim que ele for ligado.</p></section>
  <section class="dm-cfgsec"><h3>Onde guardar</h3>
   <div class="dm-cfgdest"><span class="dm-cfgico" aria-hidden="true">🗄️</span><span><b>Pasta neste computador</b> · <code id="dm-bk-pasta">${esc(p.pasta)}</code></span>
    <span class="dm-acts"><span class="dm-pill" data-st="${p.pasta_ok ? 'prog' : 'new'}">${p.pasta_ok ? 'Pronta' : 'Criada no 1º backup'}</span><button type="button" class="dm-btn dm-sm" data-act="bk-abrir"${p.pasta_ok ? '' : ' disabled'}>📂 Abrir pasta</button></span>
    <small>Protege contra erro e arquivo corrompido, mas não contra o computador quebrar.${p.livre != null ? ' ' + gBytes(p.livre) + ' livres.' : ''}</small></div>
   <div class="dm-fld"><label for="dm-bk-local">Outra pasta (vazio = a padrão)</label><input id="dm-bk-local" value="${esc(f.local)}" placeholder="${esc(f.local ? '' : p.pasta)}" autocomplete="off" spellcheck="false"></div>
   <p class="dm-note">⚠ A cópia contém nomes, matrículas e os códigos das pessoas. Guarde-a em local seguro; em pen drive, use BitLocker. Os PINs de rede não entram na cópia.</p></section>
  <section class="dm-cfgsec"><h3>Quantas cópias guardar</h3>
   <div class="dm-cfgret">${BK_RET.map(([k, l]) => `<label>${l}<input type="number" id="dm-bk-${k}" min="1" max="60" value="${num(f.ret[k])}"></label>`).join('')}
    <label>Limite de espaço<select id="dm-bk-lim">${lims.map(([v, l]) => `<option value="${v}"${v === f.limite_mb ? ' selected' : ''}>${l}</option>`).join('')}</select></label></div>
   <div class="dm-cfgbar" aria-hidden="true"><span style="width:${uso.toFixed(1)}%"></span></div>
   <p class="dm-note" id="dm-bk-uso">Usando ${gBytes(p.usado)}${f.limite_mb >= 1000000 ? '' : ' de ' + limTxt} com ${p.copias.length} ${p.copias.length === 1 ? 'cópia' : 'cópias'}. Manuais e "antes de restaurar" contam à parte: ficam as últimas de cada.</p></section>
  <section class="dm-cfgsec"><h3>Último backup<span class="dm-spacer"></span><button type="button" class="dm-btn dm-sm dm-primary" data-act="bk-agora"${p.rodando ? ' disabled' : ''}>💾 Fazer backup agora</button></h3>
   ${ok ? `<div class="dm-cfgult" id="dm-bk-ult"><div>Quando<b>${fQuando(ok.t)}</b></div><div>Tamanho<b>${gBytes(ok.bytes)}</b></div><div>Tipo<b>${esc(BK_TIPO[ok.tipo] || ok.tipo)}</b></div><div>Integridade<b class="dm-good">Verificado ✓</b></div></div>` : '<p class="dm-note" id="dm-bk-ult">Nenhum backup feito ainda.</p>'}
   ${ok && ok.faltando ? `<p class="dm-note">${num(ok.faltando)} anexo(s) apagado(s) durante a cópia ficaram de fora.</p>` : ''}
   ${falhou ? `<p class="dm-cfgerr" id="dm-bk-falha">Última tentativa (${fQuando(falha.t)}) falhou: ${esc(falha.erro)}.</p>` : ''}</section>
  <section class="dm-cfgsec"><h3>Cópias guardadas</h3>${p.copias.length ? `<div class="dm-cfglista"><div class="dm-cfgcp dm-cfgth"><span>Cópia</span><span>Tipo</span><span>Tamanho</span><span></span></div>${p.copias.map(x => `<div class="dm-cfgcp"><span><b>${x.t ? fQuando(x.t) : ''}</b><small>${esc(x.nome)}</small></span><span class="dm-cfgtipo" data-t="${esc(x.tipo)}">${esc(BK_TIPO[x.tipo] || x.tipo)}</span><span>${gBytes(x.bytes)}</span><button type="button" class="dm-btn dm-sm" data-act="bk-rest" data-v="${esc(x.nome)}">Restaurar</button></div>`).join('')}</div>` : '<p class="dm-note">Nenhuma cópia nesta pasta.</p>'}</section>
  <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="mclose">Cancelar</button><button type="button" class="dm-btn dm-primary" data-act="bk-salvar">Salvar</button></div>`;
}
/* confirmação antes de restaurar (mockup 01, cena 2): compara agora com a cópia e pede RESTAURAR digitado */
function cfgRest(r){
  const a = r.agora.contagem || {}, k = r.copia.contagem || {}, quando = r.copia.t ? fQuando(num(r.copia.t)) : r.nome;
  const dem = x => num(x.demandas) + num(x.arquivo), mais = dem(a) - dem(k), grav = num(r.agora.rev) - num(r.copia.rev);
  const lado = (t, x) => `<div>${esc(t)}<b>${dem(x)} demandas</b>${num(x.anexos)} anexos · ${num(x.pessoas)} pessoas · ${num(x.setores)} setores</div>`;
  return `<section class="dm-cfgsec"><h3>Restaurar a cópia de ${esc(quando)}?</h3>
   <p class="dm-note">Os dados da Central de demandas voltam a ser exatamente os desta cópia.</p>
   <div class="dm-rscmp">${lado('Agora', a)}<span class="dm-rsseta" aria-hidden="true">→</span>${lado('Cópia de ' + quando, k)}</div>
   <div class="dm-rsperde" id="dm-rs-perde"><b>Vai se perder:</b> tudo o que foi feito depois de ${esc(quando)}${grav > 0 ? ': ' + grav + (grav === 1 ? ' alteração gravada' : ' alterações gravadas') : ''}${mais > 0 ? ' (' + mais + (mais === 1 ? ' solicitação' : ' solicitações') + ' a mais agora)' : ''}.</div>
   <div class="dm-secx">O que vai acontecer</div>
   <ol class="dm-rspassos">
    <li>A cópia escolhida é conferida (hash ✓). Se tiver defeito, nada muda.</li>
    <li>Antes de trocar, é feita uma <b>cópia de segurança do estado atual</b> ("antes de restaurar"). Dá para desfazer por ela.</li>
    <li>Os dados são trocados. Os números continuam do maior já usado: o próximo é o <b id="dm-rs-prox">${esc(r.proximo)}</b>. Nenhum número se repete.</li>
    <li>As pessoas nos celulares e tablets voltam para "Quem é você?" e digitam o código de novo. Os aparelhos <b>não</b> precisam do PIN de novo.</li>
    <li>As telas abertas se atualizam sozinhas em até 3 segundos e mostram o aviso "Dados restaurados".</li></ol>
   <div class="dm-fld dm-rsconf"><label for="dm-rs-c">Para confirmar, digite RESTAURAR</label><input id="dm-rs-c" autocomplete="off" spellcheck="false" placeholder="RESTAURAR"></div>
   <div class="dm-mfoot"><button type="button" class="dm-btn" data-act="bk-rest-x">Cancelar</button><button type="button" class="dm-btn dm-danger" data-act="bk-rest-ok" id="dm-rs-ok" disabled>Restaurar esta cópia</button></div></section>`;
}
async function bkRestPrevia(el, nome){
  if(el) el.disabled = true;
  const r = await sys('/api/backup/previa', {nome});
  if(el && el.isConnected) el.disabled = false;
  if(r && D.cfg){D.cfg.rest = r; renderCfg(); const f = $('dm-rs-c'); if(f) f.focus()}
}
async function bkRestaurar(el){
  const c = D.cfg, inp = $('dm-rs-c');
  if(!c || !c.rest || !inp || inp.value.trim().toUpperCase() !== 'RESTAURAR') return;
  const quando = c.rest.copia.t ? fQuando(num(c.rest.copia.t)) : c.rest.nome;
  el.disabled = true;
  const p = await sys('/api/backup/restaurar', {nome: c.rest.nome, confirmo: 'RESTAURAR'});
  if(el.isConnected) el.disabled = false;
  if(!p || !D.cfg) return;
  D.cfg.rest = null; D.cfg.bk = p;
  if(p.estado.restaurado) D.restT = num(p.estado.restaurado.t);   // esta tela já avisa aqui
  renderCfg();
  toast('♻️ Dados restaurados para ' + quando);
  refresh();
}
function restCheck(){   // a primeira vista da página só anota; uma restauração nova depois dela vira aviso
  const r = D.v.backup && D.v.backup.restaurado, t = r ? num(r.t) : 0;
  if(D.restT === undefined){D.restT = t; return}
  if(t && t !== D.restT){D.restT = t; dtoast('♻️ Dados restaurados para ' + fQuando(num(r.copia_t)))}
}
async function cfgRedeOn(inp){
  const n = await sys('/api/rede', {on: inp.checked});
  if(!n){inp.checked = !inp.checked; return}
  if(D.cfg){D.cfg.rede = n; renderCfg()}
}
async function cfgPin(k){
  const q = k === 'pin' ? 'Gerar um PIN do escritório novo? Todos os aparelhos que já entraram vão precisar do PIN novo.'
    : 'Gerar um PIN dos operadores novo? Os aparelhos de operador que já entraram vão precisar do PIN novo.';
  if(!window.confirm(q)) return;
  const n = await sys('/api/rede', k === 'pin' ? {newpin: true} : {newpin_op: true});
  if(n && D.cfg){D.cfg.rede = n; renderCfg(); toast('PIN novo gerado')}
}
async function bkPost(el, path, body){
  if(el) el.disabled = true;
  const p = await sys(path, body);
  if(el && el.isConnected) el.disabled = false;
  if(p && D.cfg){D.cfg.bk = p; renderCfg()}
  return p;
}
async function bkAgora(el){
  const p = await bkPost(el, '/api/backup/agora', {});
  if(!p) return;
  toast('💾 Backup feito e verificado (' + gBytes(p.estado.ultimo_ok.bytes) + ')');
  refresh();   // o aviso do Painel some
}
function bkSalvar(el){
  const v = k => $('dm-bk-' + k), body = {on: v('on').checked, hora: v('hora').value, ao_ligar: v('lig').checked, local: v('local').value.trim(), limite_mb: num(v('lim').value), ret: {}};
  for(const [k] of BK_RET) body.ret[k] = num(v(k).value, -1);
  bkPost(el, '/api/backup', body).then(p => {if(p){toast('Configuração do backup salva'); refresh()}});
}
/* aviso de backup no Painel do ADM: faixa fixa e, uma vez por dia, o alerta flutuante */
function bkAviso(){
  const b = D.v.backup;
  if(!b || !b.alerta) return '';
  const k = b.alerta === 'grave' ? 'late' : 'pause', pc = D.srv === 'maquina';
  return `<div class="dm-al dm-bkav" data-k="${k}" role="alert" id="dm-bkav"><span class="dm-bkico" aria-hidden="true">💾</span><div class="dm-bktxt"><div class="dm-al-h"><b>Backup</b><span class="dm-tg" data-k="${k}">${b.alerta === 'grave' ? 'Atenção' : 'Aviso'}</span></div>
   <div class="dm-al-t">${esc(b.texto)}</div><div class="dm-al-m"><span>${pc ? 'Detalhes em ⚙ Configurações → Backup.' : 'Resolva no computador principal, em ⚙ Configurações.'}</span></div></div>
   ${pc ? '<div class="dm-al-b"><button type="button" class="dm-btn dm-sm dm-primary" data-act="bk-agora">💾 Fazer backup agora</button><button type="button" class="dm-btn dm-sm" data-act="cfg-open" data-v="backup">Abrir configurações</button></div>' : ''}</div>`;
}
function bkAlert(){
  const b = D.v.backup;
  if(!isAdm() || !b || b.alerta !== 'grave' || !root || !visible()) return;
  const dia = new Date().toDateString();
  if(D.bkDia === dia) return;
  D.bkDia = dia;
  try{if(localStorage.getItem('dm-bk-aviso') === dia) return; localStorage.setItem('dm-bk-aviso', dia)}catch(_){/* sem armazenamento: uma vez por abertura */}
  const el = document.createElement('div');
  el.className = 'dm-alert'; el.dataset.k = 'backup'; el.setAttribute('role', 'alert');
  el.innerHTML = `<h4><span>💾 Backup</span><button type="button" class="dm-btn dm-sm" data-act="ax" aria-label="Fechar alerta">✕</button></h4><p class="dm-note">${esc(b.texto)}</p>
   <div class="dm-acts2">${D.srv === 'maquina' ? '<button type="button" class="dm-btn dm-sm dm-primary" data-act="cfg-open" data-v="backup">Abrir configurações</button>' : ''}<button type="button" class="dm-btn dm-sm" data-act="ax">Dispensar</button></div>`;
  $('dm-alerts').prepend(el);
}

/* ---------- ações ---------- */
async function run(el, rest, body, okMsg, after){
  if(el) el.disabled = true;
  const r = await call(rest, body);
  if(el && el.isConnected) el.disabled = false;
  if(!r) return null;
  if(after) after(r);
  if(okMsg) toast(okMsg);
  render();
  return r;
}
function act(a, d, el, ev){
  const r = d.id ? byId(d.id) : null;
  switch(a){
    case 'tab':
      if(isAdm()){D.tab = d.v; if(d.v === 'crono' && (!D.crono || D.cronoP !== D.period)) loadCrono()}
      else{D.opTab = d.v; D.opF = d.v === 'recv' ? 'mine' : 'pend'}
      closePanels(); render(); break;
    case 'kpi': D.fSec = ''; D.fPrio = ''; D.fType = ''; D.q = ''; if(d.v === 'urg'){D.fPrio = 'urg'; D.fSt = 'open'} else D.fSt = d.v; D.tab = 'sol'; render(); break;
    case 'msort': D.mapSort = d.v; flip(renderView); break;
    case 'sector': {
      const rc = el.getBoundingClientRect(), z = Math.max(rc.width, rc.height, 40), sp = document.createElement('span');
      sp.className = 'dm-rip';
      sp.style.cssText = `width:${z}px;height:${z}px;left:${(ev ? ev.clientX - rc.left : rc.width / 2) - z / 2}px;top:${(ev ? ev.clientY - rc.top : rc.height / 2) - z / 2}px`;
      el.appendChild(sp); el.classList.add('dm-pick');
      setTimeout(() => {D.fSec = d.v; D.fSt = 'open'; D.fPrio = ''; D.fType = ''; D.q = ''; D.tab = 'sol'; render()}, 260);
      break;
    }
    case 'clear': D.fSt = D.fSec = D.fPrio = D.fType = D.q = ''; renderView(); break;
    case 'view': D.view = d.v; renderView(); break;
    case 'opf': D.opF = d.v; renderView(); break;
    case 'period': D.period = num(d.v, 7); renderView(); loadCrono(); break;
    case 'hclear': D.hq = D.hSt = D.hFrom = D.hTo = ''; renderView(); break;
    case 'hrel': D.hFrom = d.from; D.hTo = d.to; renderView(); break;
    case 'admsub': D.admSub = d.v; renderView(); break;
    case 'open': openDrawer(d.id); break;
    case 'close': closePanels(); break;
    case 'bell': openNotif(); break;
    case 'noteall': run(el, 'nota/todas', {}, '', () => {}).then(() => {if(D.notif) renderNotif()}); break;
    case 'noteopen': call('nota/lida', {nid: num(d.n)}, {quiet: true}).then(() => {renderBell(); openDrawer(d.id)}); break;
    case 'alertview': {const al = el.closest('.dm-alert'); if(al) al.remove(); openDrawer(d.id); break}
    case 'ax': {const al = el.closest('.dm-alert'); if(al){const nid = al.dataset.n; al.remove(); if(nid) call('nota/lida', {nid: num(nid)}, {quiet: true}).then(renderBell)} break}
    case 'new': if(!D.role) return; openNew(); break;
    case 'theme': root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark'; break;
    case 'who': if(D.role) openWho(); else{const f = $('dm-login').querySelector('button'); if(f) f.focus({preventScroll: true})} break;
    case 'mclose': closeModal(); break;
    case 'logout': logout(); break;
    case 'lgk': D.lg.k = d.v; D.lg.err = ''; D.lg.code = ''; rerenderWho(); break;
    case 'lgs': D.lg.sec = d.v; D.lg.user = ''; D.lg.err = ''; rerenderWho(); break;
    case 'lgu': D.lg.user = d.v; D.lg.err = ''; rerenderWho(); {const f = $('dm-lg-code'); if(f) f.focus()} break;
    case 'lgeye': {D.lg.show = !D.lg.show; const f = $('dm-lg-code'); if(f){f.type = D.lg.show ? 'text' : 'password'; f.focus()} el.textContent = D.lg.show ? '🙈' : '👁'; break}
    case 'impexit': D.imp = null; D.opF = 'pend'; closePanels(); render(); break;
    case 'impersonate': {const p = per(d.v); if(!p || D.role !== 'adm') return; D.imp = p.id; D.opTab = 'recv'; D.opF = 'pend'; closePanels(); render(); toast('Visualizando como ' + p.nome); break}
    case 'accept': if(r) run(el, 'demanda/aceitar', {id: r.id}, '▶ Solicitação iniciada'); break;
    case 'resume': if(r) run(el, 'demanda/retomar', {id: r.id}, '▶ Solicitação retomada'); break;
    case 'pause': if(r) modalPause(r); break;
    case 'finish': if(r) modalFinish(r); break;
    case 'reassign': if(r) modalReassign(r); break;
    case 'cancel': if(r) modalCancel(r); break;
    case 'nudge': if(r) run(el, 'demanda/cobrar', {id: r.id}, '🔔 Cobrança enviada para ' + sec(r.para.s).nome); break;
    case 'extend': if(r) run(el, 'demanda/estender', {id: r.id, minutos: num(d.v)}, 'Prazo estendido em ' + dur(num(d.v))); break;
    case 'comment': {
      const inp = $('dm-cmt'), text = inp ? inp.value.trim() : '';
      if(!r || !text) return;
      if(!D.cmt || D.cmt.id !== r.id || D.cmt.texto !== text) D.cmt = {id: r.id, texto: text, cid: novoCid()};   // mesmo texto reenviado = mesma chave
      run(el, 'demanda/comentar', {id: r.id, texto: text.slice(0, 1000), cid: D.cmt.cid}, '', () => {D.cmt = null; const b = $('dm-cmt'); if(b) b.value = ''});
      break;
    }
    case 'aopen': openAnexo(d.aid); break;
    case 'aadd': if(r) addFilesTo(r); break;
    case 'adel': {
      const an = r && r.anexos.find(x => x.id === d.aid); if(!an) return;
      modalConfirm('Remover anexo', 'Remover <b>' + esc(an.nome) + '</b> desta solicitação? Esta ação não pode ser desfeita.', 'Remover anexo', b => run(b, 'anexo/apagar', {id: r.id, aid: an.id}, 'Anexo removido', closeModal));
      break;
    }
    case 'cf-ok': if(D.mod && D.mod.run) D.mod.run(el); break;
    case 'cfg-open': {const al = el.closest('.dm-alert'); if(al) al.remove(); openCfg(d.v); break}
    case 'cfg-sec': if(D.cfg){D.cfg.sec = d.v; D.cfg.rest = null; renderCfg()} break;
    case 'bk-rest': bkRestPrevia(el, d.v); break;
    case 'bk-rest-x': if(D.cfg){D.cfg.rest = null; renderCfg()} break;
    case 'bk-rest-ok': bkRestaurar(el); break;
    case 'cfg-pin': cfgPin(d.v); break;
    case 'bk-agora': bkAgora(el); break;
    case 'bk-abrir': bkPost(el, '/api/backup/abrir', {}); break;
    case 'bk-salvar': bkSalvar(el); break;
    case 'm-type': D.form.tipo = d.v; renderForm(); break;
    case 'm-reason': D.form.motivo = d.v; D.form.err.motivo = 0; renderForm(); break;
    case 'm-prio': D.form.prio = d.v; renderForm(); break;
    case 'm-est': D.form.est = num(d.v); D.form.err.est = 0; renderForm(); break;
    case 'm-addfile': pickFiles(fs => {
      if(!D.form) return;
      for(const f of fs){const e = checkFile(f); if(e) toast('⚠️ ' + e); else if(D.form.files.length < ANX.n) D.form.files.push(f); else toast('⚠️ No máximo ' + ANX.n + ' anexos.')}
      renderForm();
    }); break;
    case 'm-rmfile': D.form.files.splice(num(d.v), 1); renderForm(); break;
    case 'm-submit': submitNew(el); break;
    case 'm-draft-x': openNew(true); break;   // o formulário vazio apaga o rascunho ao desenhar
    case 'm-pause-ok': {
      const id = D.mod && D.mod.id, s = root.querySelector('input[name=dm-pr]:checked');
      if(!id || !s) return;
      run(el, 'demanda/pausar', {id, motivo: s.value, obs: $('dm-pobs').value.replace(/\s+/g, ' ').trim().slice(0, 500)}, '⏸ Pausa registrada. A gerência foi avisada.', closeModal);
      break;
    }
    case 'm-finish-ok': {const id = D.mod && D.mod.id; if(id) run(el, 'demanda/concluir', {id, nota: $('dm-fnote').value.replace(/\s+/g, ' ').trim().slice(0, 500)}, '✔ Solicitação concluída', closeModal); break}
    case 'm-ra-ok': {const id = D.mod && D.mod.id; if(id) run(el, 'demanda/reatribuir', {id, s: $('dm-ra-s').value, p: $('dm-ra-p').value || null, nota: $('dm-ra-n').value.replace(/\s+/g, ' ').trim().slice(0, 500)}, '↪ Solicitação reatribuída', closeModal); break}
    case 'm-cn-ok': {const id = D.mod && D.mod.id; if(id) run(el, 'demanda/cancelar', {id, motivo: $('dm-cn').value.replace(/\s+/g, ' ').trim().slice(0, 500)}, 'Solicitação cancelada', closeModal); break}
    case 'newsector': openSF('new'); break;
    case 'editsector': openSF('edit', d.v); break;
    case 'seeusers': D.admSub = 'users'; D.uSec = d.v; D.uSt = ''; D.uq = ''; renderView(); break;
    case 'newuser': openUF('new', null, D.uSec || ''); break;
    case 'edituser': openUF('edit', d.v); break;
    case 'sf-icon': D.sform.icon = d.v; renderSF(); break;
    case 'sf-color': D.sform.color = d.v; renderSF(); break;
    case 'sf-save': {
      const f = D.sform, e = {}, name = f.name.trim(), id = f.id.trim().toUpperCase(), edit = f.mode === 'edit';
      if(name.length < 3 || name.length > 40) e.name = 1;
      if(!edit){if(!/^[A-Z0-9]{2,4}$/.test(id)){e.id = 1; e.idMsg = 'Use de 2 a 4 letras ou números.'} else if(setores().some(s => s.id === id)){e.id = 1; e.idMsg = 'Esta sigla já está em uso.'}}
      f.err = e;
      if(Object.keys(e).length){renderSF(); return}
      const s = edit ? sec(f.id) : null;
      run(el, 'setor/salvar', {modo: edit ? 'editar' : 'novo', id: edit ? f.id : id, nome: name, icone: f.icon, cor: f.color, rev: s ? num(s._rv) : 0}, edit ? 'Setor atualizado' : '✅ Setor ' + id + ' criado. Agora cadastre os usuários dele.', closeModal);
      break;
    }
    case 'sf-toggle': {const s = sec(D.sform.id); run(el, 'setor/ativar', {id: s.id, rev: num(s._rv)}, s.ativo ? 'Setor desativado' : 'Setor reativado', closeModal); break}
    case 'sf-del': {
      const s = sec(D.sform.id);
      if(reqs().some(x => x.de.s === s.id || x.para.s === s.id)){toast('Este setor tem histórico de solicitações. Desative em vez de excluir.'); return}
      const n = usersOf(s.id).length;
      modalConfirm('Excluir setor', 'Excluir <b>' + esc(s.nome) + '</b>' + (n ? ' e ' + n + ' usuário(s)' : '') + '? Esta ação não pode ser desfeita.', 'Excluir setor', b => run(b, 'setor/apagar', {id: s.id, rev: num(s._rv)}, 'Setor excluído', () => {if(D.fSec === s.id) D.fSec = ''; if(D.uSec === s.id) D.uSec = ''; closeModal()}));
      break;
    }
    case 'uf-gen': D.uform.code = genCode(); D.uform.show = true; D.uform.err.code = 0; renderUF(); break;
    case 'uf-eye': {D.uform.show = !D.uform.show; const f = $('dm-uf-code'); if(f) f.type = D.uform.show ? 'text' : 'password'; el.textContent = D.uform.show ? '🙈' : '👁'; break}
    case 'uf-save': {
      const f = D.uform, e = {}, name = f.name.trim(), edit = f.mode === 'edit';
      if(name.length < 2 || name.length > 60) e.name = 1;
      if(!f.setor || !setores().some(s => s.id === f.setor)) e.setor = 1;
      if(edit ? f.code && !/^[0-9]{4}$/.test(f.code) : !/^[0-9]{4}$/.test(f.code)) e.code = 1;
      f.err = e;
      if(Object.keys(e).length){renderUF(); return}
      const p = edit ? per(f.id) : null, body = {modo: edit ? 'editar' : 'novo', nome: name, setor: f.setor, rev: p ? num(p._rv) : 0};
      if(edit) body.id = f.id;
      if(f.code) body.codigo = f.code;
      const msg = edit ? (f.code ? 'Dados e código atualizados' : 'Usuário atualizado') : '✅ ' + name + ' cadastrado(a) em ' + sec(f.setor).nome + ' · código ' + f.code;
      run(el, 'pessoa/salvar', body, msg, closeModal);
      break;
    }
    case 'uf-toggle': {const p = per(D.uform.id); if(p) run(el, 'pessoa/ativar', {id: p.id, rev: num(p._rv)}, p.nome + (p.ativo ? ' desativado(a)' : ' reativado(a)'), closeModal); break}
    case 'uf-del': {
      const p = per(D.uform.id); if(!p) return;
      if(reqs().some(x => x.de.p === p.id || x.para.p === p.id)){toast('Este usuário tem histórico de solicitações. Desative em vez de excluir.'); return}
      modalConfirm('Excluir usuário', 'Excluir <b>' + esc(p.nome) + '</b> definitivamente? Esta ação não pode ser desfeita.', 'Excluir usuário', b => run(b, 'pessoa/apagar', {id: p.id, rev: num(p._rv)}, 'Usuário excluído', closeModal));
      break;
    }
  }
}

/* ---------- eventos (um ouvinte por tipo, tudo delegado na raiz do módulo) ---------- */
function onClick(e){
  if(e.target === $('dm-modal')){closeModal(); return}
  const t = e.target.closest('[data-act]');
  if(!t || !root.contains(t) || t.disabled) return;
  if(t.tagName === 'A') return;
  act(t.dataset.act, t.dataset, t, e);
}
function onInput(e){
  const id = e.target.id, v = e.target.value;
  if(id === 'dm-q'){D.q = v; renderView()}
  else if(id === 'dm-hq'){D.hq = v; renderView()}
  else if(id === 'dm-uq'){D.uq = v; renderView()}
  else if(id === 'dm-lg-code'){const c = v.replace(/\D/g, '').slice(0, 4); if(c !== v) e.target.value = c; D.lg.code = c; if(D.lg.err){D.lg.err = ''; const f = $('dm-lg-fld'); if(f) f.classList.remove('dm-err')}}
  else if(id === 'dm-fm-title' && D.form){D.form.titulo = v; rascGrava(); if(D.form.err.titulo && v.trim().length >= 5){D.form.err.titulo = 0; e.target.closest('.dm-fld').classList.remove('dm-err')}}
  else if(id === 'dm-fm-desc' && D.form){D.form.desc = v; rascGrava()}
  else if(id === 'dm-fm-estN' && D.form) setEstFromInputs();
  else if(id === 'dm-sf-name' && D.sform){const f = D.sform; f.name = v; if(f.mode === 'new' && !f.idTouched){f.id = suggestId(v); $('dm-sf-id').value = f.id} f.err.name = 0; e.target.closest('.dm-fld').classList.remove('dm-err'); updateSFPrev()}
  else if(id === 'dm-sf-id' && D.sform){const f = D.sform; f.id = v.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 4); e.target.value = f.id; f.idTouched = true; updateSFPrev()}
  else if(id === 'dm-uf-name' && D.uform) D.uform.name = v;
  else if(id === 'dm-rs-c'){const b = $('dm-rs-ok'); if(b) b.disabled = v.trim().toUpperCase() !== 'RESTAURAR'}
  else if(id === 'dm-uf-code' && D.uform){const c = v.replace(/\D/g, '').slice(0, 4); if(c !== v) e.target.value = c; D.uform.code = c}
}
function onChange(e){
  const id = e.target.id, v = e.target.value;
  if(id === 'dm-fSt'){D.fSt = v; renderView()}
  else if(id === 'dm-fSec'){D.fSec = v; renderView()}
  else if(id === 'dm-fPrio'){D.fPrio = v; renderView()}
  else if(id === 'dm-fType'){D.fType = v; renderView()}
  else if(id === 'dm-hSt'){D.hSt = v; renderView()}
  else if(id === 'dm-hFrom'){D.hFrom = v; renderView()}
  else if(id === 'dm-hTo'){D.hTo = v; renderView()}
  else if(id === 'dm-hArq'){D.hArq = v; loadArq()}
  else if(id === 'dm-uSec'){D.uSec = v; renderView()}
  else if(id === 'dm-uSt'){D.uSt = v; renderView()}
  else if(id === 'dm-dr-prio'){const r = byId(e.target.dataset.id); if(r) run(null, 'demanda/prioridade', {id: r.id, prio: v}, 'Prioridade: ' + (PRIO[v] || [v])[0])}
  else if(id === 'dm-fm-fromS' && D.form){D.form.fromS = v; D.form.err.fromS = 0; rascGrava()}
  else if(id === 'dm-fm-toS' && D.form){D.form.toS = v; D.form.toP = ''; D.form.err.toS = 0; renderForm()}
  else if(id === 'dm-fm-toP' && D.form){D.form.toP = v; rascGrava()}
  else if(id === 'dm-fm-estU' && D.form) setEstFromInputs(true);
  else if(id === 'dm-ra-s'){$('dm-ra-p').innerHTML = peopleOpts(v, '')}
  else if(id === 'dm-uf-sec' && D.uform){D.uform.setor = v; D.uform.err.setor = 0; renderUF()}
  else if(id === 'dm-cfg-on') cfgRedeOn(e.target);
  else if(id === 'dm-bk-on') $('dm-bk-ontx').textContent = e.target.checked ? 'Ligada' : 'Desligada';
}
function onSubmit(e){if(e.target && e.target.id === 'dm-lgform'){e.preventDefault(); doLogin()}}
function onKey(e){
  if(!root || !visible()) return;
  if(e.key === 'Escape'){if(modalOn()) closeModal(); else if(D.open || D.notif) closePanels(); return}
  if(e.key !== 'Enter' && e.key !== ' ') return;
  const t = e.target;
  if(!t || !root.contains(t)) return;
  if(t.getAttribute && t.getAttribute('role') === 'button' && t.dataset.act){e.preventDefault(); act(t.dataset.act, t.dataset, t, null)}
  else if(e.key === 'Enter' && t.id === 'dm-cmt'){e.preventDefault(); const b = root.querySelector('[data-act=comment]'); if(b) b.click()}
}

/* ---------- ciclo de vida ---------- */
async function boot(){
  D.booted = true;
  try{const eu = await window.api('/api/eu'); D.srv = eu && eu.papel || null}catch(_){D.srv = null}
  D.euPronto = true;
  await loadPub();
  render();
}
async function refresh(){
  if(!D.role) return;
  const r = D.role === 'adm' ? await call('', undefined, {quiet: true}) : await call('vista', {}, {quiet: true});
  if(!r || !root) return;
  if(isAdm() && D.tab === 'crono' && visible()) loadCrono(true);
  soft();
}
function tick(){
  if(!root || !visible()) return;
  clock();
  if(!D.role || !D.v) return;
  patch();
  if(++D.ticks >= 30){D.ticks = 0; if(!busyUI()) render()}   // contagens e "atrasada" sem esperar gravação no servidor
}
const LIVE = {
  open(){if(!D.booted) boot(); else{render(); refresh()}},
  rev: () => D.v ? D.v.rev : null,
  refresh: () => refresh(),
  config: sec => openCfg(sec),   // botão ⚙ Configurações da casca (app.js)
};

const SVGNS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs){const e = document.createElementNS(SVGNS, tag); for(const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v); return e}
function symbols(host){
  const S = (id, vb, kids, sw) => {
    if(document.getElementById(id)) return;
    const s = svgEl('symbol', {id, viewBox: vb, fill: 'none', stroke: 'currentColor', 'stroke-width': sw || '1.6', 'stroke-linecap': 'square', 'stroke-linejoin': 'miter'});
    kids.forEach(([t, a]) => s.appendChild(svgEl(t, a)));
    host.appendChild(s);
  };
  // ícone: prancheta com linhas
  S('dm-i-dem', '0 0 24 24', [['rect', {x: '5', y: '4', width: '14', height: '17', rx: '2'}], ['path', {d: 'M9 4V2.8h6V4M8.5 10h7M8.5 14h7M8.5 18h4'}]], '1.75');
  // abas (icons.svg do DEMANDA)
  S('dm-i-painel', '0 0 16 16', [['rect', {x: '1.2', y: '1.2', width: '5.4', height: '5.4'}], ['rect', {x: '9.4', y: '1.2', width: '5.4', height: '5.4'}], ['rect', {x: '1.2', y: '9.4', width: '5.4', height: '5.4'}], ['rect', {x: '9.4', y: '9.4', width: '5.4', height: '5.4'}]]);
  S('dm-i-sol', '0 0 16 16', [['rect', {x: '1.2', y: '2.2', width: '9.2', height: '11.6'}], ['path', {d: 'M12.2 6.2H15M13.4 4.6 15 6.2 13.4 7.8'}]]);
  S('dm-i-hist', '0 0 16 16', [['path', {d: 'M1.4 3.2H6.2M8.6 3.2h2.2v2.2'}], ['path', {d: 'M1.4 8H14.6'}], ['path', {d: 'M1.4 12.8H14.6'}]]);
  S('dm-i-crono', '0 0 16 16', [['path', {d: 'M1.2 8h3.6M6.2 8h3.6M11.2 8h3.6'}]]);
  S('dm-i-admin', '0 0 16 16', [['path', {d: 'M1.2 4.6H14.8'}], ['rect', {x: '4.2', y: '2.6', width: '3.2', height: '4'}], ['path', {d: 'M1.2 11.4H14.8'}], ['rect', {x: '8.6', y: '9.4', width: '3.2', height: '4'}]]);
}
const SKELETON = '<div class="dm-scroll" id="dm-scroll"><div class="dm-wrap">'
  + '<header class="dm-top"><div><h1 class="dm-h1">Central de demandas</h1><p class="dm-bfn">Demandas entre setores</p><p class="dm-sub0" id="dm-sub"></p></div>'
  + '<div class="dm-acts"><span class="dm-clock" id="dm-clock"></span><button type="button" class="dm-uchip" data-act="who" id="dm-uchip" aria-label="Quem é você"></button>'
  + '<button type="button" class="dm-btn dm-bell" id="dm-bell" data-act="bell" aria-label="Notificações">🔔<b id="dm-badge" hidden>0</b></button>'
  + '<button type="button" class="dm-btn" data-act="theme" aria-label="Alternar tema">◐ Tema</button>'
  + '<button type="button" class="dm-btn dm-primary dm-hdnew" data-act="new">＋ Nova solicitação</button></div></header>'
  + '<div id="dm-imp"></div><nav class="dm-tabs" id="dm-tabs" aria-label="Seções"></nav><div id="dm-view"></div></div></div>'
  + '<button type="button" class="dm-fab" data-act="new" aria-label="Nova solicitação">＋</button>'
  + '<div class="dm-scrim" id="dm-scrim" data-act="close"></div><aside class="dm-drawer" id="dm-drawer" aria-label="Detalhes da solicitação"></aside><aside class="dm-drawer" id="dm-notif" aria-label="Notificações"></aside>'
  + '<div class="dm-login" id="dm-login" hidden></div><div class="dm-modal" id="dm-modal"><div class="dm-mbox" id="dm-mbox" role="dialog" aria-modal="true"></div></div>'
  + '<div class="dm-alerts" id="dm-alerts" aria-live="assertive"></div><div class="dm-toast" id="dm-toast" role="status"></div>';

(function mount(){
  if(document.getElementById('dmboard')) return;
  const sym = document.querySelector('svg symbol'), sprite = sym && sym.parentNode;
  const exp = document.querySelector('.nav[data-view="export"]');
  if(exp && !document.querySelector('.nav[data-view="demandas"]')){
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'nav';
    b.dataset.view = 'demandas'; b.dataset.local = 'demandas'; b.dataset.tip = 'Demandas';
    b.setAttribute('aria-label', 'Demandas');
    const ic = svgEl('svg', {class: 'ic', 'aria-hidden': 'true'});
    ic.appendChild(svgEl('use', {href: '#dm-i-dem'}));
    const sp = document.createElement('span'); sp.textContent = 'Demandas';
    const badge = document.createElement('b');
    badge.className = 'dm-navbadge'; badge.hidden = true;
    badge.style.cssText = 'position:absolute;top:3px;left:22px;min-width:16px;height:16px;padding:0 4px;border-radius:8px;background:#DC3F4A;color:#fff;font:700 10px/16px system-ui,sans-serif;text-align:center;pointer-events:none';
    b.append(ic, sp, badge);
    exp.parentNode.insertBefore(b, exp.nextSibling);
  }
  const main = document.querySelector('main');
  root = document.createElement('section');
  root.className = 'board'; root.id = 'dmboard'; root.setAttribute('aria-label', 'Demandas');
  root.dataset.theme = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  root.innerHTML = SKELETON;
  const plan = document.getElementById('planboard');
  if(plan && plan.parentNode) plan.parentNode.insertBefore(root, plan);
  else (main || document.body).appendChild(root);
  let host = sprite;
  if(!host){const s = svgEl('svg', {width: '0', height: '0', 'aria-hidden': 'true', style: 'position:absolute'}); host = svgEl('defs'); s.appendChild(host); root.appendChild(s)}
  symbols(host);
  root.addEventListener('click', onClick);
  root.addEventListener('input', onInput);
  root.addEventListener('change', onChange);
  root.addEventListener('submit', onSubmit);
  document.addEventListener('keydown', onKey);
  setInterval(tick, 1000);
  window.NestLocal = window.NestLocal || {views: {}};
  window.NestLocal.views = window.NestLocal.views || {};
  window.NestLocal.views.demandas = LIVE;
  render();
  if(main && main.dataset.view === 'demandas') LIVE.open();
})();
})();
