'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const md = SafeMarkdown.render;

let STATUS = {}, MENTORS = [], MODES = {}, MODE = 'auto', CHAT = 0, POLL = null, CHATS = [], VIEW = 'chat';

// ---------------------------------------------------------------- language
// English by default. The server keeps the choice in data/config.json, so the AI answers in the same language.
const LANG_KEY = 'aym.language';
let LANG = readLS(LANG_KEY) === 'es' ? 'es' : 'en';
const L = (en, es) => LANG === 'es' ? es : en;
const LOCALE = () => L('en', 'es');
// The HTML is written in English; data-es* attributes carry the Spanish text.
function translateDom(root = document) {
  if (LANG !== 'es') return;
  root.querySelectorAll('[data-es]').forEach(e => { e.textContent = e.dataset.es; });
  root.querySelectorAll('[data-es-html]').forEach(e => { e.innerHTML = e.dataset.esHtml; });
  root.querySelectorAll('[data-es-placeholder]').forEach(e => { e.placeholder = e.dataset.esPlaceholder; });
  root.querySelectorAll('[data-es-title]').forEach(e => { e.title = e.dataset.esTitle; });
  root.querySelectorAll('[data-es-aria]').forEach(e => e.setAttribute('aria-label', e.dataset.esAria));
}
function setLanguage(lang) {
  LANG = lang === 'es' ? 'es' : 'en';
  saveLS(LANG_KEY, LANG);
  document.documentElement.lang = LANG;
  $$('.lang-seg .seg[data-lang]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.lang === LANG)));
}
$$('.lang-seg .seg[data-lang]').forEach(b => b.addEventListener('click', async () => {
  if (b.dataset.lang === LANG) return;
  try { await api('/api/settings', { language: b.dataset.lang }); saveLS(LANG_KEY, b.dataset.lang); location.reload(); } catch (e) { alert(e.message); }
}));

async function api(path, data) {
  const op = data ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) } : {};
  const r = await fetch(path, op);
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { location.reload(); throw new Error(L('Session expired', 'Sesión vencida')); }
  if (!r.ok) throw new Error(j.error || `error ${r.status}`);
  return j;
}
function readLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function saveLS(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* no storage */ } }

// ---------------------------------------------------------------- brand and AI status
function applyBrand() {
  const app = STATUS.app || {};
  // Three lengths of the name; the sidebar shows the one that fits (CSS container queries)
  const name = app.name || 'Ask Your Mentors', words = name.split(/\s+/).filter(Boolean);
  $('#brand-name').title = name;
  $('#brand-name .name-full').textContent = name;
  $('#brand-name .name-mid').textContent = words.length > 2 ? `${words[0]} ${words[words.length - 1]}` : name;
  $('#brand-name .name-short').textContent = words.length > 1 ? words.map(w => w[0]).join('').toUpperCase() : name.slice(0, 4);
  if (app.icon) $('#brand-icon').textContent = app.icon;     // an emoji in the settings replaces the logo
  document.title = app.name || 'Ask Your Mentors';
  paintAI();
}
// The AI switch: off = base mode (the mentors' exact words, no AI); on = the chosen AI, Claude Code by default.
const aiOn = () => STATUS.ai_enabled !== false && STATUS.provider !== 'none';
function paintAI() {
  const on = aiOn(), sw = $('#ai-switch'), d = $('#ai-detail');
  sw.setAttribute('aria-checked', String(on));
  const name = STATUS.provider_name || 'Claude Code', short = STATUS.provider === 'claude' ? 'Claude' : name;
  const [cls, text, help] = !on ? ['', L('Off · base mode', 'Apagada · modo base'), L('Answers with the mentors\' exact words and the minute. Turn it on for written answers.', 'Responde con las palabras exactas de los referentes y el minuto. Enciéndela para respuestas redactadas.')]
    : STATUS.ai_status === 'connected' ? ['ok', `${L('On', 'Encendida')} · ${name}`, L(`${name} is connected and answers your questions.`, `${name} está conectado y responde tus preguntas.`)]
    : STATUS.ai_status === 'not_installed' ? ['warn', `${L('Install', 'Instalar')} ${short}`, L('Click to see how to install it.', 'Haz clic para ver cómo instalarlo.')]
    : ['warn', `${L('Connect', 'Conectar')} ${short}`, L('Click to see how to connect it.', 'Haz clic para ver cómo conectarlo.')];
  d.className = 'link-btn ' + cls; d.textContent = text; d.title = help;
  paintBrain();
}
$('#ai-switch').addEventListener('click', async () => {
  const on = !aiOn();
  $('#ai-switch').setAttribute('aria-checked', String(on));
  try {
    STATUS = { ...STATUS, ...(await api('/api/settings', { ai_enabled: on })) };
    applyBrand(); if (!CHAT) paintEmpty();
    if (on && STATUS.ai_status !== 'connected') openConnect();
  } catch (e) { alert(e.message); paintAI(); }
});
$('#ai-detail').addEventListener('click', () => { if (aiOn()) openConnect(); });

// Second brain: off by default. On = the AI may READ the user's notes folder to personalize the answers.
function paintBrain() {
  const b = STATUS.brain || {}, on = !!b.enabled, d = $('#brain-detail');
  $('#brain-switch').setAttribute('aria-checked', String(on));
  const short = (b.path || '').split(/[\\/]/).filter(Boolean).pop() || '';      // only the folder name; the full path is in the tooltip
  d.className = 'link-btn ' + (on && aiOn() ? 'ok' : '');
  d.textContent = !on ? L('Off · not connected', 'Apagado · sin conectar')
    : aiOn() ? `${L('On', 'Encendido')} · ${short}` : L('On · needs the AI on', 'Encendido · necesita la IA encendida');
  d.title = on ? L(`The AI reads only what it needs from ${b.path}, read-only. Click to change the folder.`, `La IA lee solo lo que necesita de ${b.path}, sin modificar nada. Haz clic para cambiar la carpeta.`)
    : L('Turn it on to connect your notes, or create a second brain from scratch.', 'Enciéndelo para conectar tus notas o crear un segundo cerebro desde cero.');
}
async function askBrainPath() {
  const current = (STATUS.brain || {}).path || '';
  const p = prompt(L('Where is your second brain? Paste the full path of the folder with your notes (Markdown or text).\nExample: ~/Documents/my-notes\n\nThe AI will only READ it, never modify it.',
    '¿Dónde está tu segundo cerebro? Pega la ruta completa de la carpeta con tus notas (Markdown o texto).\nEjemplo: ~/Documentos/mis-notas\n\nLa IA solo la LEE, nunca la modifica.'), current);
  return p === null ? null : p.trim();
}
function openBrain() {
  $('#brain-status').textContent = ''; $('#brain-status').className = 'small';
  $('#dlg-brain').showModal();
}
async function brainAction(path) {
  const st = $('#brain-status');
  st.className = 'small muted';
  st.textContent = L('Look for the window that just opened on your computer…', 'Busca la ventana que se acaba de abrir en tu computador…');
  try {
    const r = await api(path, {});
    if (r.no_picker) { st.textContent = ''; return typeBrainPath(); }
    if (!r.ok) { st.textContent = L('Cancelled.', 'Cancelado.'); return; }
    STATUS = { ...STATUS, ...r }; paintBrain();
    st.className = 'small ok';
    st.textContent = r.created
      ? L(`✓ Created in ${r.folder}. Open that folder with Claude Code and paste prompt 1 of PROMPTS.md: the AI interviews you and fills it.`,
          `✓ Creado en ${r.folder}. Abre esa carpeta con Claude Code y pega el prompt 1 de PROMPTS.md: la IA te entrevista y lo llena.`)
      : L(`✓ Connected: ${r.folder}`, `✓ Conectado: ${r.folder}`);
    if (!aiOn()) st.textContent += ' ' + L('Turn the AI on too: the second brain is used by the AI.', 'Enciende también la IA: el segundo cerebro lo usa la IA.');
  } catch (e) { st.className = 'small error'; st.textContent = e.message; }
}
async function typeBrainPath() {
  const p = await askBrainPath(); if (!p) return;
  try { STATUS = { ...STATUS, ...(await api('/api/settings', { brain_path: p, brain_enabled: true })) }; paintBrain(); $('#dlg-brain').close(); }
  catch (e) { alert(e.message); }
}
$('#brain-pick').addEventListener('click', () => brainAction('/api/brain/pick'));
$('#brain-create').addEventListener('click', () => brainAction('/api/brain/create'));
$('#brain-type').addEventListener('click', typeBrainPath);
$('#close-brain').addEventListener('click', () => $('#dlg-brain').close());
$('#brain-switch').addEventListener('click', async () => {
  const b = STATUS.brain || {}, on = !b.enabled;
  if (on && !b.path) return openBrain();                 // first time: choose or create the folder
  try { STATUS = { ...STATUS, ...(await api('/api/settings', { brain_enabled: on })) }; paintBrain(); }
  catch (e) { alert(e.message); }
});
$('#brain-detail').addEventListener('click', openBrain);

function connectButton(text = L('Connect Claude', 'Conectar Claude')) { return `<button type="button" class="small primary open-connect">${text}</button>`; }
document.addEventListener('click', ev => { if (ev.target.closest('.open-connect')) openConnect(); });

// ---------------------------------------------------------------- connect Claude Code (in-app guide)
function paintSteps() {
  const st = STATUS.ai_status;
  const done = { install: st === 'no_session' || st === 'connected', login: st === 'connected', account: st === 'connected', check: st === 'connected' };
  $$('#dlg-connect [data-step]').forEach(li => li.classList.toggle('done', !!done[li.dataset.step]));
  const msg = {
    connected: L('✓ Claude is connected. You can close this window.', '✓ Claude está conectado. Ya puedes cerrar esta ventana.'),
    no_session: L('Claude is installed; you still need to log in (step 3).', 'Claude está instalado; falta iniciar sesión (paso 3).'),
    not_installed: L('I cannot find Claude Code on this computer yet (step 2).', 'Todavía no encuentro Claude Code en este computador (paso 2).'),
    no_ai: L('The app is set up without AI.', 'La app está configurada sin IA.') };
  $('#connect-status').textContent = STATUS.provider === 'claude' || st === 'no_ai' ? (msg[st] || '')
    : L(`The app uses ${STATUS.provider_name}: ${st === 'connected' ? 'connected' : 'not connected'}.`,
        `La app usa ${STATUS.provider_name}: ${st === 'connected' ? 'conectado' : 'sin conexión'}.`);
  $('#connect-status').className = st === 'connected' ? 'ok' : 'muted';
}
function showPick(p) {
  $$('#dlg-connect [data-pick]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.pick === p)));
  $('#pick-claude').hidden = p !== 'claude'; $('#pick-gemini').hidden = p !== 'gemini';
  $('#gemini-status').textContent = STATUS.has_gemini_key ? L('A key is already saved. Paste a new one to replace it.', 'Ya hay una clave guardada. Pega una nueva para reemplazarla.') : '';
}
$$('#dlg-connect [data-pick]').forEach(b => b.addEventListener('click', () => showPick(b.dataset.pick)));
function openConnect() {
  if (!$('#dlg-connect').open) $('#dlg-connect').showModal();
  const pick = STATUS.provider === 'gemini' ? 'gemini' : 'claude';
  showPick(pick);
  if (pick === 'gemini') return;
  if (STATUS.provider) paintSteps(); else $('#connect-status').textContent = '';
  $('#check-connection').click();          // on open, check right away whether it is already connected
}
$('#gemini-eye').addEventListener('click', () => {
  const shown = $('#gemini-key').classList.toggle('shown'), b = $('#gemini-eye');
  b.setAttribute('aria-pressed', String(shown));
  b.setAttribute('aria-label', shown ? L('Hide the key', 'Ocultar la clave') : L('Show the key', 'Mostrar la clave'));
});
$('#gemini-key').addEventListener('input', () => {        // pasted keys often bring spaces or line breaks: cleaned on the fly
  const v = $('#gemini-key').value, clean = v.replace(/\s+/g, '');
  if (v !== clean) $('#gemini-key').value = clean;
});
$('#save-gemini').addEventListener('click', async () => {
  const key = $('#gemini-key').value.trim();
  if (!key) return $('#gemini-key').focus();
  $('#gemini-status').textContent = L('Saving…', 'Guardando…');
  try {
    STATUS = { ...STATUS, ...(await api('/api/settings', { gemini_key: key })) };
    $('#gemini-key').value = ''; applyBrand(); if (!CHAT) paintEmpty();
    $('#gemini-status').textContent = L('✓ Gemini is on. You can close this window.', '✓ Gemini quedó encendida. Ya puedes cerrar esta ventana.');
    $('#gemini-status').className = 'ok small';
  } catch (e) { $('#gemini-status').textContent = e.message; $('#gemini-status').className = 'error small'; }
});
$('#close-connect').addEventListener('click', () => $('#dlg-connect').close());
$('#check-connection').addEventListener('click', async () => {
  const b = $('#check-connection'); b.disabled = true; $('#connect-status').textContent = L('Checking…', 'Revisando…');
  try {
    if (STATUS.provider !== 'claude') await api('/api/settings', { provider: 'claude' });     // this tab means "use Claude"
    STATUS = await api('/api/status?check=1'); applyBrand(); paintSteps(); if (!CHAT) paintEmpty();
  } catch (e) { $('#connect-status').textContent = e.message; }
  b.disabled = false;
});
$$('#dlg-connect .copy').forEach(b => b.addEventListener('click', async () => {
  const label = L('Copy', 'Copiar');
  try { await navigator.clipboard.writeText($('#' + b.dataset.copy).textContent); b.textContent = L('Copied ✓', 'Copiado ✓'); setTimeout(() => { b.textContent = label; }, 1800); }
  catch (e) { b.textContent = L('Select it and copy', 'Selecciónalo y copia'); }
}));

let INITIAL_MODE_SET = false;
async function loadStatus() {
  STATUS = await api('/api/status');
  MODES = STATUS.modes || {};
  if (STATUS.language && STATUS.language !== LANG) {            // the server has the last word on the language
    setLanguage(STATUS.language); location.reload(); return new Promise(() => {});
  }
  if (!INITIAL_MODE_SET && STATUS.initial_mode) { MODE = STATUS.initial_mode; INITIAL_MODE_SET = true; }
  applyBrand();
}
async function loadMentors() {
  const d = await api('/api/mentors');
  MENTORS = d.mentors; MODES = d.modes; GROUPS = d.groups || [];
  $('#n-mentors').textContent = MENTORS.length ? `${L('My mentors', 'Mis referentes')} · ${MENTORS.length}` : L('My mentors', 'Mis referentes');
  if (MODE !== 'auto' && MODE !== 'all' && !slugsOf(MODE) && !MENTORS.find(r => r.slug === MODE)) MODE = 'auto';
  paintChips();
}

// ---------------------------------------------------------------- views
function showView(v) {
  VIEW = v;
  $$('.view').forEach(s => { s.hidden = s.id !== `view-${v}`; });
  $('#open-mentors').classList.toggle('active', v === 'mentors');
  if (v === 'mentors') { paintMentors(); checkAI(); }
  if (window.innerWidth <= 760) collapseSidebar(true);
}
// Opening My mentors checks whether the AI just got connected; if so, the server writes the missing
// profiles by itself and the list refreshes with the progress.
async function checkAI() {
  try { STATUS = await api('/api/status?check=1'); applyBrand(); await refreshJobs(true); } catch (e) { /* offline */ }
}
$('#open-mentors').addEventListener('click', () => showView(VIEW === 'mentors' ? 'chat' : 'mentors'));
$('#back-to-chat').addEventListener('click', () => showView('chat'));

// ---------------------------------------------------------------- avatars
const imageOf = r => ((r?.sources || []).find(f => /^\/thumb\//.test(f.image || '')) || {}).image || '';
function avatar(r, cls = '') {
  const img = imageOf(r);
  if (img) return `<img class="avatar ${cls}" src="${esc(img)}" alt="">`;
  const c = /^#[0-9a-f]{6}$/i.test(r?.color || '') ? r.color : '#8792a5';
  const ini = r ? (r.initials || r.name.slice(0, 2)) : '?';
  return `<span class="avatar ${cls}" style="background:${c}22;color:${c};border-color:${c}66">${esc(ini)}</span>`;
}
// Bullseye for "AI picks" (Tabler Icons target-arrow, MIT license, drawn here so nothing loads from outside)
const BULLSEYE = '<svg class="mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 12a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M12 7a5 5 0 1 0 5 5"/><path d="M13 3.055a9 9 0 1 0 7.941 7.945"/><path d="M15 6v3h3l3 -3h-3v-3l-3 3"/><path d="M15 9l-3 3"/></svg>';
// "Everyone": a group of people (same stroke style as the bullseye)
const GROUP = '<svg class="mode-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="8" r="3"/><path d="M3 20v-1a5 5 0 0 1 10 0v1"/><circle cx="17" cy="9" r="2.5"/><path d="M15.5 14.2A4 4 0 0 1 21 18v1"/></svg>';
const MODE_ICONS = { auto: BULLSEYE, all: GROUP };
const modeIcon = k => MODE_ICONS[k] || faces(slugsOf(k)) || '👥';
let GROUPS = [];
function slugsOf(m) {
  if (String(m).startsWith('multi:')) return m.slice(6).split(',').filter(Boolean);
  return (GROUPS.find(g => g.id === m) || {}).slugs || null;
}
// Overlapping pictures of the members of a group
// Overlapping pictures of a group: at most `max`, then a "+N"; hovering shows every name
const namesOf = slugs => slugs.map(s => (MENTORS.find(r => r.slug === s) || { name: s }).name).join(', ');
function faces(slugs, max = 3) {
  if (!slugs || !slugs.length) return '';
  const extra = slugs.length - max > 0 ? slugs.length - (max - 1) : 0, shown = extra ? slugs.slice(0, max - 1) : slugs;
  return `<span class="faces" title="${esc(namesOf(slugs))}">${shown.map(s => avatar(MENTORS.find(r => r.slug === s), 'face')).join('')}${extra ? `<span class="avatar face more">+${extra}</span>` : ''}</span>`;
}
// In the chat list: two pictures stacked in the same square as a single avatar, and "+N" if there are more
function groupIcon(slugs) {
  const two = slugs.slice(0, 2).map(s => avatar(MENTORS.find(r => r.slug === s), 'face')).join('');
  const more = slugs.length > 2 ? `<span class="more-badge">+${slugs.length - 2}</span>` : '';
  return `<span class="avatar mode group${slugs.length === 1 ? ' single' : ''}" title="${esc(namesOf(slugs))}">${two}${more}</span>`;
}
function chatIcon(mode) {
  if (slugsOf(mode)) return groupIcon(slugsOf(mode));
  if (MODES[mode]) return `<span class="avatar mode">${modeIcon(mode)}</span>`;
  return avatar(MENTORS.find(x => x.slug === mode));
}
function modeName(m) {
  if (MODES[m]) return MODES[m];
  if (String(m).startsWith('multi:')) return slugsOf(m).map(s => (MENTORS.find(r => r.slug === s) || { name: s }).name).join(' + ');
  return (MENTORS.find(x => x.slug === m) || {}).name || m;
}
// Icon of the platform each source comes from (own SVG drawings, nothing loaded from outside)
const SVG = {
  youtube: '<rect x="1" y="4.5" width="22" height="15" rx="4.5" fill="#FF0033"/><path d="M10 8.7v6.6l5.8-3.3z" fill="#fff"/>',
  spotify: '<circle cx="12" cy="12" r="11" fill="#1DB954"/><path d="M6.3 9.4c3.9-1.1 8-.8 11.3 1M6.9 12.6c3.2-.9 6.5-.6 9.3.9M7.5 15.6c2.6-.7 5.2-.4 7.3.7" stroke="#0b0e14" stroke-width="1.7" fill="none" stroke-linecap="round"/>',
  apple: '<rect x="1" y="1" width="22" height="22" rx="6" fill="#9b36d6"/><circle cx="12" cy="10" r="2.6" fill="#fff"/><path d="M10.6 14h2.8l-.5 6h-1.8z" fill="#fff"/><path d="M7.2 14.6a6 6 0 1 1 9.6 0" stroke="#fff" stroke-width="1.6" fill="none" stroke-linecap="round"/>',
  rss: '<rect x="1" y="1" width="22" height="22" rx="5" fill="#F26522"/><circle cx="7" cy="17" r="2" fill="#fff"/><path d="M5 11.2a7.8 7.8 0 0 1 7.8 7.8M5 6a13 13 0 0 1 13 13" stroke="#fff" stroke-width="2.3" fill="none" stroke-linecap="round"/>',
  pdf: '<path d="M5 1.5h9.5L20 7v15.5H5z" fill="#E5322D"/><path d="M14.5 1.5V7H20" fill="#ff8a86"/><text x="12.5" y="17.5" font-size="6.3" font-weight="700" font-family="Arial" text-anchor="middle" fill="#fff">PDF</text>',
  web: '<circle cx="12" cy="12" r="10" fill="#3b82f6"/><path d="M2 12h20M12 2c3 3.2 3 16.8 0 20M12 2c-3 3.2-3 16.8 0 20" stroke="#fff" stroke-width="1.4" fill="none"/>',
  file: '<path d="M5 1.5h9.5L20 7v15.5H5z" fill="#8792a5"/><path d="M14.5 1.5V7H20" fill="#c3cad6"/><path d="M8 12h8M8 15h8M8 18h5" stroke="#fff" stroke-width="1.4"/>',
};
function platform(f) {
  const u = ((f.url || '') + ' ' + (f.page || '')).toLowerCase();
  if (f.type === 'youtube') return 'youtube';
  if (f.type === 'file') return /\.pdf$/i.test(f.name || '') ? 'pdf' : 'file';
  if (f.type === 'web') return /\.pdf(\?|$)/.test(f.url || '') ? 'pdf' : 'web';
  if (/spotify|anchor\.fm|podcasters\.spotify/.test(u)) return 'spotify';
  if (/podcasts\.apple/.test(u)) return 'apple';
  return 'rss';
}
const platformName = p => ({ youtube: 'YouTube', spotify: L('Podcast on Spotify', 'Podcast en Spotify'), apple: 'Apple Podcasts', rss: 'Podcast',
  pdf: 'PDF', web: L('Web page', 'Página web'), file: L('Document', 'Documento') }[p] || p);
const sourceIcon = f => `<svg class="platform" viewBox="0 0 24 24" aria-hidden="true">${SVG[platform(f)]}</svg>`;
const initials = n => n.trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase();

// ---------------------------------------------------------------- mentor picker (dropdown with search)
// Under its button, as wide as the screen allows, never past the edges (the width itself is in the CSS)
function placeSelector() {
  const sel = $('#selector'), b = $('#open-selector');
  if (sel.hidden || !b) return;
  const r = b.getBoundingClientRect();
  sel.style.left = Math.max(8, Math.min(r.left, window.innerWidth - sel.offsetWidth - 8)) + 'px';
  sel.style.top = (r.bottom + 6) + 'px';
  sel.style.maxHeight = `min(70vh, 600px, ${Math.max(220, window.innerHeight - r.bottom - 18)}px)`;
}
window.addEventListener('resize', placeSelector);
function toggleSelector(open) {
  const sel = $('#selector'), b = $('#open-selector');
  open = open ?? sel.hidden;
  if (!open || !b) { sel.hidden = true; return; }
  sel.hidden = false; placeSelector(); $('#sel-filter').value = '';
  PICKED = new Set(String(MODE).startsWith('multi:') ? slugsOf(MODE) : MENTORS.find(r => r.slug === MODE) ? [MODE] : []);
  paintSelector(); $('#sel-filter').focus();
}
function paintSelector() {
  const q = $('#sel-filter').value.trim().toLowerCase();
  const list = MENTORS.filter(r => !q || r.name.toLowerCase().includes(q));
  $('#sel-list').innerHTML = list.map(r => `<button type="button" class="sel-item ${PICKED.has(r.slug) ? 'active' : ''}" data-slug="${esc(r.slug)}" aria-pressed="${PICKED.has(r.slug)}">
      <span class="check-mark">${PICKED.has(r.slug) ? '✓' : ''}</span>${avatar(r)}<span class="sel-text"><b>${esc(r.name)}</b><small>${r.status.with_text} ${L('with text', 'con texto')} · ${esc(hoursText(r.status.hours))}</small></span></button>`).join('')
    || `<p class="muted small" style="padding:8px">${L('No one with that name.', 'Nadie con ese nombre.')}</p>`;
  $$('#sel-list .sel-item').forEach(b => b.addEventListener('click', () => {
    PICKED.has(b.dataset.slug) ? PICKED.delete(b.dataset.slug) : PICKED.add(b.dataset.slug);
    applyPick(); paintSelector();
  }));
  const n = PICKED.size, one = n === 1 ? MENTORS.find(r => PICKED.has(r.slug)) : null;
  $('#sel-count').textContent = !n ? L('No one checked: the AI picks', 'Nadie marcado: la IA elige')
    : one ? L(`${one.name} answers`, `Responde ${one.name}`) : L(`${n} checked: they answer together`, `${n} marcados: responden juntos`);
}
let PICKED = new Set();
// Saved on every check: none = the AI picks, one = that mentor, several = they answer together
function applyPick() {
  MODE = !PICKED.size ? 'auto' : PICKED.size === 1 ? [...PICKED][0] : 'multi:' + [...PICKED].join(',');
  paintChips(); if (!CHAT) paintEmpty();
}
$('#sel-filter').addEventListener('input', paintSelector);
$('#sel-filter').addEventListener('keydown', ev => {
  if (ev.key === 'Enter') {                      // Enter checks the first match
    const p = $('#sel-list .sel-item'); if (p) p.click();
  }
  if (ev.key === 'Escape') toggleSelector(false);
});
$('#selector').addEventListener('click', ev => ev.stopPropagation());     // a click inside (even if it repaints) does not close it
document.addEventListener('click', ev => { if (!$('#selector').hidden && !ev.target.closest('#open-selector')) toggleSelector(false); });
window.addEventListener('resize', () => toggleSelector(false));

// Duration in words: "1 hour 36 minutes", "54 hours", "25 minutes"
const plural = (n, en, es) => `${n.toLocaleString(LOCALE())} ${L(en, es)}${n === 1 ? '' : 's'}`;
function hoursText(h) {
  const min = Math.round((+h || 0) * 60);
  if (!min) return L('less than a minute', 'menos de un minuto');
  const hh = Math.floor(min / 60), mm = min % 60;
  if (!hh) return plural(mm, 'minute', 'minuto');
  return hh >= 10 || !mm ? plural(hh, 'hour', 'hora') : `${plural(hh, 'hour', 'hora')} ${plural(mm, 'minute', 'minuto')}`;
}

function paintChips() {
  const hints = { auto: L('The AI decides which 2 or 3 mentors have something real to say.', 'La IA decide qué 2 o 3 referentes tienen algo real que decir.'),
    all: L('Everyone with material on the topic: summary, each voice and where they disagree.', 'Todos los que tengan material sobre el tema: resumen, cada voz y en qué chocan.') };
  const chip = c => `<button type="button" class="chip ${c.k === MODE ? 'active' : ''}" data-mode="${esc(c.k)}" title="${esc(c.t)}">${c.v}</button>`;
  const add = `<button type="button" class="chip add" id="chip-add" title="${L('Add a mentor', 'Agregar un referente')}">${L('+ Add', '+ Agregar')}</button>`;
  $('#question-form').hidden = !MENTORS.length;
  $('.fine-print').hidden = !MENTORS.length;
  if (!MENTORS.length) { $('#chips').innerHTML = ''; return; }
  const modes = Object.keys(MODES).map(k => ({ k, v: `${modeIcon(k)} ${esc(MODES[k])}`, t: hints[k] || '' }));
  const picked = MENTORS.find(r => r.slug === MODE);
  const multi = String(MODE).startsWith('multi:');
  const selector = `<button type="button" class="chip selector-btn ${picked || multi ? 'active' : ''}" id="open-selector" aria-haspopup="dialog" title="${L('Pick mentors to answer in their own voice', 'Elegir referentes para que respondan en su voz')}">
    ${multi ? `${faces(slugsOf(MODE))}${esc(modeName(MODE))}` : picked ? `${avatar(picked, 'mini-avatar')}${esc(picked.name)}` : `👤 ${L('Pick mentors', 'Elegir referentes')}`} <span class="caret">▾</span></button>`;
  $('#chips').innerHTML = `${modes.map(chip).join('')}<span class="sep"></span>${selector}${add}`;
  $('#open-selector').addEventListener('click', ev => { ev.stopPropagation(); toggleSelector(); });
  $$('#chips .chip[data-mode]').forEach(b => b.addEventListener('click', () => { MODE = b.dataset.mode; paintChips(); if (!CHAT) paintEmpty(); }));
  $('#chip-add').addEventListener('click', () => openAdd());
}

// ---------------------------------------------------------------- empty chat screen
function paintEmpty() {
  const thread = $('#thread');
  if (!MENTORS.length) {
    const who = STATUS.provider === 'claude' && STATUS.ai_ready ? L('Claude searches for them on the internet', 'Claude la busca en internet') : L('The app searches for them', 'La app la busca');
    thread.innerHTML = `<div class="welcome">
      <div class="big-icon">🎙️</div>
      <h2>${L('Who do you want to learn from?', '¿De quién quieres aprender?')}</h2>
      <p class="muted">${L(`Type the name of a person who publishes videos or podcasts. ${who}, shows you what it found and you confirm it is them. Then it downloads their transcripts and you can ask them questions with citations to the exact minute.`,
        `Escribe el nombre de una persona que publique videos o podcasts. ${who}, te muestra lo que encontró y tú confirmas que sea la persona correcta. Después descarga sus transcripciones y podrás preguntarle con citas al minuto exacto.`)}</p>
      <div id="finder-welcome"></div>
      ${toolNotices()}
    </div>`;
    mountFinder($('#finder-welcome'));
    return;
  }
  const loading = MENTORS.filter(r => r.job && ['queued', 'running'].includes(r.job.status));
  const name = esc(modeName(MODE));
  const who = MODE === 'auto' ? L('The AI picks who has something real to say.', 'La IA elige quién tiene algo real que decir.')
    : MODE === 'all' ? L('Everyone who has talked about the topic answers.', 'Responden todos los que hayan hablado del tema.')
    : slugsOf(MODE) ? L(`${name} answer, each in their own voice, and where they disagree.`, `Responden ${name}, cada uno en su voz, y dónde chocan.`)
    : L(`${name} answers, in their own voice.`, `Responde ${name}, en su voz.`);
  const names = loading.map(r => esc(r.name)).join(', ');
  thread.innerHTML = `<div class="empty">
    <h2>${L('Ask your mentors', 'Pregúntale a tus referentes')}</h2>
    <p>${who} ${L('Every idea comes with the citation to the exact minute of the video or episode.', 'Cada idea llega con la cita al minuto exacto del video o episodio.')}</p>
    ${loading.length ? `<p class="progress">⏳ ${L(`Downloading content from ${names}. You can already ask about what has been downloaded.`, `Descargando contenido de ${names}. Ya puedes preguntar sobre lo que ya se descargó.`)}</p>` : ''}
    ${!STATUS.ai_ready && STATUS.provider === 'claude' ? `<p class="notice notice-row"><span>${L('Claude is not connected: answers come in base mode (their exact words with the minute). Connecting an AI is optional.', 'Claude no está conectado: las respuestas llegan en modo base (sus palabras exactas con el minuto). Conectar una IA es opcional.')}</span> ${connectButton()}</p>` : ''}
    <p class="muted small">${STATUS.ai_ready ? L(`${esc(STATUS.provider_name)} answers in about 20 seconds: it reads the transcripts instead of guessing.`, `Responde ${esc(STATUS.provider_name)} en unos 20 segundos: lee las transcripciones en vez de adivinar.`)
      : STATUS.provider === 'claude' ? '' : L('Base mode: each mentor answers with their own words and the minute, in under a second.', 'Modo base: cada referente responde con sus propias palabras y el minuto, en menos de un segundo.')}</p>
  </div>`;
}
function toolNotices() {
  const out = [];
  if (STATUS.missing_ytdlp) out.push(L('<code>yt-dlp</code> is missing to download YouTube subtitles (macOS: <code>brew install yt-dlp</code>). Ask your AI to install it.',
    'Falta <code>yt-dlp</code> para descargar subtítulos de YouTube (macOS: <code>brew install yt-dlp</code>). Pídele a tu IA que lo instale.'));
  if (!STATUS.ai_ready && STATUS.provider === 'claude') out.push(`<span>${L('Works without AI: answers bring each mentor\'s exact words with the minute. Connecting Claude (optional) adds written answers and a smarter search for people.',
    'Funciona sin IA: las respuestas traen las palabras exactas de cada referente con el minuto. Conectar Claude (opcional) agrega respuestas redactadas y una búsqueda de personas más precisa.')}</span> ${connectButton()}`);
  return out.map(a => `<p class="notice">${a}</p>`).join('');
}

// ---------------------------------------------------------------- chat list
const COLLAPSED_KEY = 'aym.collapsed';
function collapsedZones() { try { return JSON.parse(readLS(COLLAPSED_KEY) || '{}'); } catch (e) { return {}; } }
function toggleZone(z) { const p = collapsedZones(); p[z] = !p[z]; saveLS(COLLAPSED_KEY, JSON.stringify(p)); loadChats(); }
const unreadCount = l => { const n = l.filter(c => !c.is_read).length; return n ? `<span class="unread">${n} ${L('unread', 'sin leer')}</span>` : ''; };
function zoneHeader(z, text, list) {
  const col = !!collapsedZones()[z];
  return `<button type="button" class="section ${col ? 'collapsed' : ''}" data-zone="${z}" aria-expanded="${!col}"><span class="arrow">▾</span>${text}${unreadCount(list)}${col ? `<span class="count">${list.length}</span>` : ''}</button>`;
}
function chatCard(c) {
  return `<div class="chat ${c.id === CHAT ? 'active' : ''} ${c.is_read ? '' : 'unread-chat'}" data-id="${c.id}" title="${esc(c.title)}${c.is_read ? '' : L(' (unread)', ' (sin leer)')}" draggable="true">
    <span class="unread-dot"></span>${chatIcon(c.mode)}
    <div class="content"><div class="title">${esc(c.title)}</div><small>${esc(modeName(c.mode))} · ${esc(readableDate(c.updated))}</small></div>
    ${c.pinned ? `<span class="pin" title="${L('Pinned', 'Fijada')}">📌</span>` : ''}
    <button type="button" class="more" title="${L('Options', 'Opciones')}" aria-label="${L('Options', 'Opciones')}">⋯</button></div>`;
}
async function loadChats() {
  const { chats } = await api('/api/chats');
  CHATS = chats;
  if (!chats.length) { $('#chats').innerHTML = `<div class="muted" style="font-size:13px;padding:8px">${L('No chats yet.', 'Sin charlas todavía.')}</div>`; return; }
  const pinned = chats.filter(c => c.pinned), rest = chats.filter(c => !c.pinned), col = collapsedZones();
  $('#chats').innerHTML =
    `<div class="zone ${pinned.length ? '' : 'empty-zone'} ${col.pinned ? 'collapsed' : ''}" data-pinned="1">${zoneHeader('pinned', L('📌 Pinned', '📌 Fijadas'), pinned)}${pinned.map(chatCard).join('')}<div class="drop-hint">${L('Drop here to pin', 'Suelta aquí para fijar')}</div></div>` +
    `<div class="zone ${col.recent ? 'collapsed' : ''}" data-pinned="0">${zoneHeader('recent', L('Recent', 'Recientes'), rest)}${rest.map(chatCard).join('')}<div class="drop-hint">${L('Drop here to unpin', 'Suelta aquí para quitar de fijadas')}</div></div>`;
  $$('.section[data-zone]').forEach(b => b.addEventListener('click', () => toggleZone(b.dataset.zone)));
  $$('.chat').forEach(d => {
    d.addEventListener('click', () => { showView('chat'); openChat(+d.dataset.id); });
    d.addEventListener('contextmenu', ev => { ev.preventDefault(); openMenu(+d.dataset.id, ev.clientX, ev.clientY); });
    d.querySelector('.more').addEventListener('click', ev => { ev.stopPropagation(); const b = ev.currentTarget.getBoundingClientRect(); openMenu(+d.dataset.id, b.left, b.bottom + 2); });
    d.addEventListener('dragstart', ev => {
      ev.dataTransfer.setData('text/plain', d.dataset.id); ev.dataTransfer.effectAllowed = 'move'; closeMenu();
      setTimeout(() => { d.classList.add('ghost'); $('#chats').classList.add('dragging'); }, 0);
    });
    d.addEventListener('dragend', () => { d.classList.remove('ghost'); $('#chats').classList.remove('dragging'); $$('.zone.over').forEach(z => z.classList.remove('over')); });
  });
  $$('.zone').forEach(z => {
    z.addEventListener('dragover', ev => { ev.preventDefault(); z.classList.add('over'); });
    z.addEventListener('dragleave', ev => { if (!z.contains(ev.relatedTarget)) z.classList.remove('over'); });
    z.addEventListener('drop', async ev => {
      ev.preventDefault(); z.classList.remove('over');
      const id = +ev.dataTransfer.getData('text/plain'), pinned = z.dataset.pinned === '1', c = CHATS.find(k => k.id === id);
      if (!c || !!c.pinned === pinned) return;
      try { await api('/api/chat/pin', { id, pinned }); loadChats(); } catch (e) { alert(e.message); }
    });
  });
}

function openMenu(id, x, y) {
  const c = CHATS.find(k => k.id === id); if (!c) return;
  const items = [
    { k: 'pin', icon: c.pinned ? '📍' : '📌', t: c.pinned ? L('Unpin', 'Quitar de fijadas') : L('Pin to top', 'Fijar arriba') },
    { k: 'read', icon: c.is_read ? '🔵' : '✅', t: c.is_read ? L('Mark as unread', 'Marcar como no leída') : L('Mark as read', 'Marcar como leída') },
    { k: 'rename', icon: '✏️', t: L('Rename', 'Renombrar') }, { k: 'open', icon: '💬', t: L('Open', 'Abrir') },
    { k: 'delete', icon: '🗑️', t: L('Delete chat', 'Borrar charla'), danger: true }];
  const menu = $('#context-menu');
  menu.innerHTML = `<div class="menu-title">${chatIcon(c.mode)}<span>${esc(c.title)}</span></div>` +
    items.map(i => `<button type="button" role="menuitem" class="${i.danger ? 'danger' : ''}" data-k="${i.k}"><span class="menu-icon">${i.icon}</span>${i.t}</button>`).join('');
  menu.hidden = false;
  menu.style.left = Math.min(x, window.innerWidth - menu.offsetWidth - 8) + 'px';
  menu.style.top = Math.min(y, window.innerHeight - menu.offsetHeight - 8) + 'px';
  menu.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { closeMenu(); chatAction(b.dataset.k, c); }));
  menu.querySelector('button').focus();
}
function closeMenu() { $('#context-menu').hidden = true; }
document.addEventListener('click', ev => { if (!ev.target.closest('#context-menu')) closeMenu(); });
document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeMenu(); });
window.addEventListener('resize', closeMenu);

async function chatAction(k, c) {
  try {
    if (k === 'open') { showView('chat'); return openChat(c.id); }
    if (k === 'pin') { await api('/api/chat/pin', { id: c.id, pinned: !c.pinned }); return loadChats(); }
    if (k === 'read') { await api('/api/chat/read', { id: c.id, read: !c.is_read }); return loadChats(); }
    if (k === 'rename') {
      const t = prompt(L('New name for the chat:', 'Nuevo nombre de la charla:'), c.title);
      if (t === null || !t.trim()) return;
      await api('/api/chat/rename', { id: c.id, title: t.trim() }); return loadChats();
    }
    if (k === 'delete') {
      if (!confirm(L(`Delete the chat "${c.title}"? This cannot be undone.`, `¿Borrar la charla "${c.title}"? No se puede deshacer.`))) return;
      await api('/api/chat/delete', { id: c.id });
      if (CHAT === c.id) newChat();
      return loadChats();
    }
  } catch (e) { alert(e.message); }
}

// ---------------------------------------------------------------- chat thread
// "October 23, 19:42" / "23 de octubre, 19:42" (this year) or with the year for previous years
const MONTHS = {
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
  es: ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'] };
function readableDate(t) {
  const m = String(t || '').match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2})/);
  if (!m) return t || '';
  const thisYear = +m[1] === new Date().getFullYear(), month = MONTHS[LANG][+m[2] - 1], day = +m[3];
  return L(`${month} ${day}${thisYear ? '' : `, ${m[1]}`}, ${m[4]}`, `${day} de ${month}${thisYear ? '' : ` de ${m[1]}`}, ${m[4]}`);
}
// "8 seconds", "1 minute 12 seconds"
function readableDuration(sec) {
  sec = Math.round(+sec || 0);
  if (!sec) return '';
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? (s ? `${plural(m, 'minute', 'minuto')} ${plural(s, 'second', 'segundo')}` : plural(m, 'minute', 'minuto')) : plural(s, 'second', 'segundo');
}

function paintMessages(messages) {
  const thread = $('#thread');
  if (!messages.length) { paintEmpty(); return; }
  thread.innerHTML = messages.map(m => {
    if (m.role === 'user') return `<div class="msg user"><div class="meta">${L('You', 'Tú')} · ${esc(modeName(m.mode))}</div>${esc(m.text)}</div>`;
    if (m.status === 'pending') {
      const many = MODES[m.mode] || slugsOf(m.mode), who = MODES[m.mode] ? L('your mentors', 'tus referentes') : esc(modeName(m.mode));
      return `<div class="msg ai"><div class="waiting"><span class="dot"></span>${L(`Reading what ${who} said about it…`, `Leyendo lo que ${many ? 'dijeron' : 'dijo'} ${who} sobre esto…`)}</div></div>`;
    }
    if (m.status === 'stopped') return `<div class="msg ai stopped"><div class="meta"><b>${esc(modeName(m.mode))}</b></div>⏹ ${L('You stopped this answer.', 'Detuviste esta respuesta.')}</div>`;
    return `<div class="msg ai ${m.status === 'error' ? 'error' : ''}"><div class="meta"><b>${esc(modeName(m.mode))}</b><span>${readableDuration(m.seconds)}</span></div><div class="md">${m.status === 'error' ? esc(m.text) : md(m.text)}</div></div>`;
  }).join('') + (QUEUE[CHAT] || []).map((q, i) => `<div class="msg user queued"><div class="meta">${L('Queued · sent when the previous answer finishes', 'En cola · se envía cuando termine la respuesta anterior')}
      <button type="button" class="unqueue" data-i="${i}" title="${L('Remove from the queue', 'Quitar de la cola')}">✕</button></div>${esc(q.question)}</div>`).join('');
  $$('#thread .unqueue').forEach(b => b.addEventListener('click', () => { QUEUE[CHAT].splice(+b.dataset.i, 1); openChat(CHAT); }));
  PENDING = (messages.find(m => m.status === 'pending') || {}).id || 0;
  composerState();
  thread.scrollTop = thread.scrollHeight;
}
async function openChat(id) {
  CHAT = id;
  const { chat, messages } = await api(`/api/chat?id=${id}`);
  MODE = chat.mode; paintChips(); paintMessages(messages);
  const pend = messages.find(m => m.status === 'pending');
  if (!chat.is_read && !pend) await api('/api/chat/read', { id, read: true }).catch(() => {});
  loadChats();
  if (pend) poll(pend.id);
}
// While an answer is on its way: Stop button, and whatever you type goes to a queue that is sent afterwards.
let PENDING = 0;
const QUEUE = {};
function composerState() {
  $('#stop').hidden = !PENDING;
  $('#send').textContent = PENDING ? L('Queue it', 'Poner en cola') : L('Send', 'Enviar');
  $('#send').title = PENDING ? L('Sent by itself when the previous answer finishes', 'Se envía sola cuando termine la respuesta anterior') : '';
}
function poll(mid) {
  clearInterval(POLL);
  POLL = setInterval(async () => {
    try {
      const r = await api(`/api/answer?id=${mid}`);
      if (r.status !== 'pending') {
        clearInterval(POLL);
        const next = (QUEUE[CHAT] || []).shift();
        if (next) return send(next.question, next.mode);           // the next one in the queue goes out by itself
        if (CHAT) openChat(CHAT);
      }
    } catch (e) { clearInterval(POLL); }
  }, 2000);
}
async function send(question, mode) {
  $('#send').disabled = true;
  try {
    const r = await api('/api/ask', { question, mode, chat_id: CHAT });
    CHAT = r.chat_id;
    await openChat(CHAT);
    poll(r.message_id);
  } catch (e) { alert(e.message); }
  $('#send').disabled = false;
}
async function ask() {
  const question = $('#question').value.trim();
  if (!question) return;
  if (!MENTORS.length) { $('#thread .s-query') && $('#thread .s-query').focus(); return; }
  $('#question').value = ''; fitComposer();
  if (PENDING && CHAT) {                                    // an answer is on its way: to the queue
    (QUEUE[CHAT] = QUEUE[CHAT] || []).push({ question, mode: MODE });
    return openChat(CHAT);
  }
  send(question, MODE);
}
$('#stop').addEventListener('click', async () => {
  if (!PENDING) return;
  $('#stop').disabled = true;
  try { await api('/api/chat/stop', { message_id: PENDING }); } catch (e) { alert(e.message); }
  $('#stop').disabled = false;
});
// A new conversation always starts from the default (the AI picks), not from the mentors of the chat that was open
function newChat(mode) { CHAT = 0; PENDING = 0; MODE = mode || STATUS.initial_mode || 'auto'; PICKED = new Set(); clearInterval(POLL); composerState(); paintChips(); paintMessages([]); loadChats(); }
function fitComposer() { const t = $('#question'); t.style.height = 'auto'; t.style.height = t.scrollHeight + 2 + 'px'; }
$('#question').addEventListener('input', fitComposer);
$('#question-form').addEventListener('submit', ev => { ev.preventDefault(); ask(); });
$('#question').addEventListener('keydown', ev => {
  if (ev.key !== 'Enter' || ev.shiftKey || ev.isComposing || ev.keyCode === 229) return;
  ev.preventDefault(); ask();
});
$('#new-chat').addEventListener('click', () => { showView('chat'); newChat(); $('#question').focus(); });

// ---------------------------------------------------------------- sidebar: collapse and width
const SB_WIDTH = 'aym.sidebar.width', SB_COLLAPSED = 'aym.sidebar.collapsed', SB_MIN = 200, SB_MAX = 460, SB_DEF = 290;
const clamp = n => Math.min(SB_MAX, Math.max(SB_MIN, Math.round(n)));
function sidebarWidth() { const n = parseInt(readLS(SB_WIDTH) || '', 10); return Number.isFinite(n) ? clamp(n) : SB_DEF; }
function applySidebar(width, collapsed) {
  $('#app').style.setProperty('--sidebar-w', width + 'px');
  $('#app').classList.toggle('collapsed', collapsed);
  $('#show-sidebar').hidden = !collapsed;
}
const MIN_CHAT = 520;
window.addEventListener('resize', () => {
  if (window.innerWidth > 760 && !$('#app').classList.contains('collapsed') && window.innerWidth - sidebarWidth() < MIN_CHAT) applySidebar(sidebarWidth(), true);
});
function collapseSidebar(c) { saveLS(SB_COLLAPSED, c ? '1' : '0'); applySidebar(sidebarWidth(), c); }
$('#hide-sidebar').addEventListener('click', () => collapseSidebar(true));
$('#show-sidebar').addEventListener('click', () => collapseSidebar(false));
document.addEventListener('keydown', ev => {
  if (!(ev.metaKey || ev.ctrlKey) || ev.altKey || (ev.key !== 'b' && ev.key !== 'B')) return;
  ev.preventDefault(); collapseSidebar(!$('#app').classList.contains('collapsed'));
});
$('#resizer').addEventListener('pointerdown', ev => {
  if (ev.button !== 0) return;
  ev.preventDefault();
  const x0 = ev.clientX, w0 = $('#sidebar').getBoundingClientRect().width; let raw = w0;
  $('#app').classList.add('resizing');
  const move = e => { raw = w0 + (e.clientX - x0); $('#app').style.setProperty('--sidebar-w', clamp(raw) + 'px'); };
  const release = () => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', release);
    $('#app').classList.remove('resizing');
    if (raw < SB_MIN - 40) { collapseSidebar(true); return; }
    saveLS(SB_WIDTH, String(clamp(raw))); applySidebar(clamp(raw), false);
  };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', release);
});
$('#resizer').addEventListener('dblclick', () => { saveLS(SB_WIDTH, String(SB_DEF)); applySidebar(SB_DEF, false); });

// ---------------------------------------------------------------- mentor finder (one field)
// The AI looks the person up on the internet and proposes candidates; the user says "yes, this one" and that's it.
// Or, by hand: a name plus PDFs or links (an author whose books you have), with no search at all.
let STOP_FINDER = () => {};
function mountFinder(box, onAdded, target = null) {   // target: an existing mentor that gets the chosen sources
  STOP_FINDER();                                        // a finder mounted before (welcome or dialog) stops its search
  box.innerHTML = '';
  const root = $('#tpl-finder').content.firstElementChild.cloneNode(true);
  translateDom(root);
  box.appendChild(root);
  const f = root.querySelector('form.finder:not(.manual)'), manual = root.querySelector('form.manual');
  const q = f.querySelector('.s-query'), out = f.querySelector('.s-output'), go = f.querySelector('.s-go'), stopBtn = f.querySelector('.s-stop');
  if (target) root.querySelector('.add-modes').hidden = true;     // adding sources to someone who exists: only the search
  root.querySelectorAll('[data-add]').forEach(b => b.addEventListener('click', () => {
    const isManual = b.dataset.add === 'manual';
    root.querySelectorAll('[data-add]').forEach(x => { x.classList.toggle('active', x === b); x.setAttribute('aria-selected', x === b); });
    f.hidden = isManual; manual.hidden = !isManual;
    if (isManual && !manual.querySelector('.m-name').value) manual.querySelector('.m-name').value = q.value.trim();
    (isManual ? manual.querySelector('.m-name') : q).focus();
  }));
  mountManual(manual, onAdded);
  let first = '', run = 0, sid = 0;
  // Typing another name and pressing Enter, or Stop: the search in progress is dropped (and its Claude process cut)
  function stop(note) {
    run++;
    if (sid) api('/api/identify/cancel', { id: sid }).catch(() => {});
    sid = 0; stopBtn.hidden = true;
    if (note) out.innerHTML = `<p class="muted">${L('Search stopped. Type another name or search again.', 'Búsqueda detenida. Escribe otro nombre o vuelve a buscar.')}</p>`;
  }
  STOP_FINDER = () => stop(false);
  stopBtn.addEventListener('click', () => { stop(true); q.focus(); });
  async function search(text, hint) {
    stop(false);
    const my = run;
    stopBtn.hidden = false;
    const who = STATUS.provider === 'claude' && STATUS.ai_ready ? L('Claude is searching for', 'Claude está buscando') : L('Searching for', 'Buscando');
    out.innerHTML = `<div class="waiting"><span class="dot"></span>${who} <b>${esc(text)}</b> ${L('on the internet: YouTube channels, podcasts and texts…', 'en internet: canales de YouTube, podcasts y textos…')}</div>`;
    try {
      const { id } = await api('/api/identify', { q: text, hint });
      if (my !== run) return api('/api/identify/cancel', { id }).catch(() => {});   // stopped while it was starting
      sid = id;
      let r, painted = false;
      for (;;) {
        await new Promise(ok => setTimeout(ok, 1200));
        if (my !== run) return;                         // another name was searched, or Stop
        r = await api(`/api/identify?id=${id}`);
        if (my !== run) return;
        if (r.status !== 'searching') break;
        if (r.refining && r.candidates && r.candidates.length && !painted) { paintCandidates(r, text, true); painted = true; }
      }
      paintCandidates(r, text, false);
    } catch (e) { if (my === run) out.innerHTML = `<div class="error">${esc(e.message)}</div>`; }
    if (my === run) { sid = 0; stopBtn.hidden = true; }
  }
  function paintCandidates(r, text, refining) {
    if (r.status === 'error') { out.innerHTML = `<div class="error">${esc(r.error)}</div>`; return; }
    const cands = r.candidates || [];
    const open = x => { const u = SafeMarkdown.safeUrl(x.page || (x.type === 'youtube' ? x.url : '')); return u ? `<a class="open-link" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${x.type === 'youtube' ? L('See channel', 'Ver canal') : L('See page', 'Ver página')} ↗</a>` : ''; };
    const mini = (x, cls) => x.image ? `<img class="${cls}" src="${esc(x.image)}" alt="">` : `<span class="${cls} no-img">${sourceIcon(x)}</span>`;
    const cards = cands.map((c, i) => `<div class="candidate" data-i="${i}">
      <div class="top">${c.image ? `<img class="avatar large" src="${esc(c.image)}" alt="">` : `<span class="avatar large">${esc(initials(c.name))}</span>`}
        <div><b>${esc(c.name)}</b><p class="muted">${esc(c.description)}</p></div></div>
      ${c.notice ? `<p class="notice warn">⚠️ ${esc(c.notice)}</p>` : ''}
      <div class="sources">${c.sources.map((x, j) => `<div class="source ${x.music ? 'music' : ''}"><label class="check"><input type="checkbox" data-j="${j}" ${x.music ? '' : 'checked'}>${mini(x, 'mini')}
        <span class="src-text"><span class="kind">${sourceIcon(x)} ${platformName(platform(x))}${x.music ? ` · <b class="text-warn">${L('music channel', 'canal de música')}</b>` : ''}</span>${esc(x.name || x.url)}</span></label>${open(x)}</div>`).join('')}</div>
      ${c.sources.some(x => x.music) ? `<p class="muted small">${L('The music channel comes unchecked: check it only if you really want their songs as material.', 'El canal de música viene sin marcar: márcalo solo si de verdad quieres sus canciones como material.')}</p>` : ''}
      <div class="actions"><button type="button" class="primary" data-yes="${i}">${L('Yes, add', 'Sí, agregar')}</button></div>
    </div>`).join('');
    out.innerHTML = (refining ? `<div class="waiting refining"><span class="dot"></span>${L('This is what I found first. Claude is checking which channels are official and looking for the missing ones (about 30 seconds)…', 'Esto es lo primero que encontré. Claude está verificando cuáles son los canales oficiales y buscando los que falten (unos 30 segundos)…')}</div>` : '') +
      (r.no_claude ? `<p class="notice notice-row"><span>${L('Claude is not connected, so this comes from the basic search (it may bring similar channels). With Claude the app identifies the person and their official sources.', 'Claude no está conectado, así que esto sale de la búsqueda básica (puede traer canales parecidos). Con Claude la app identifica a la persona y sus fuentes oficiales.')}</span> ${connectButton()}</p>` : '') +
      (r.notice ? `<p class="notice">${esc(r.notice)}</p>` : '') +
      (cands.length ? `<p class="muted small">${cands.length > 1 ? L('Which one is it?', '¿Cuál es?') : L('Is it this one?', '¿Es este?')}</p>${cards}`
        : `<p class="muted">${L(`I found no one for “${esc(text)}”.`, `No encontré a nadie con «${esc(text)}».`)}</p>`) +
      `<div class="not-it"><span class="muted small">${cands.length ? L('None of them?', '¿No es ninguno de estos?') : L('Try with more detail:', 'Prueba con más detalle:')}</span>
        <div class="form-row"><input class="s-hint" maxlength="300" placeholder="${L('Give me a hint: country, topic, channel name or paste a URL', 'Dame una pista: país, tema, nombre del canal o pega una URL')}">
        <button type="button" class="s-again">${L('Search again', 'Buscar de nuevo')}</button></div></div>`;
    out.querySelectorAll('[data-yes]').forEach(b => b.addEventListener('click', () => confirmCandidate(cands[+b.dataset.yes], b.closest('.candidate'), b)));
    const hint = out.querySelector('.s-hint');
    const again = () => { if (hint.value.trim()) search(first, hint.value.trim()); };
    out.querySelector('.s-again').addEventListener('click', again);
    hint.addEventListener('keydown', ev => { if (ev.key === 'Enter') { ev.preventDefault(); again(); } });
  }
  async function confirmCandidate(c, card, button) {
    const sources = c.sources.filter((x, j) => card.querySelector(`[data-j="${j}"]`).checked);
    if (!sources.length) return alert(L('Leave at least one source checked.', 'Deja marcada al menos una fuente.'));
    button.disabled = true;
    try {
      if (target) {                                    // add to an existing mentor: only the sources it does not have yet
        const have = new Set(target.sources.map(x => x.url));
        const fresh = sources.filter(x => !have.has(x.url)).map(x => ({ url: x.url, name: x.name || '' }));
        if (fresh.length) await api('/api/mentors/source', { slug: target.slug, sources: fresh });
        await loadMentors(); if (onAdded) onAdded(target); paintMentors(); refreshJobs(true);
        return;
      }
      stop(false);                                     // Claude was still refining: the user already chose
      const { mentor } = await api('/api/mentors', { ...c, sources });
      await loadMentors();
      if (onAdded) onAdded(mentor);
      showView('mentors');
      refreshJobs(true);
    } catch (e) { button.disabled = false; alert(e.message); }
  }
  f.addEventListener('submit', ev => {
    ev.preventDefault();
    const t = q.value.trim();
    if (t.length < 2) return q.focus();
    first = t; search(t, '');
  });
  setTimeout(() => q.focus(), 50);
}
// Manual: the name, one or several PDFs/texts and optional links; the same routes as "+ Add" on an existing mentor
function mountManual(form, onAdded) {
  const out = form.querySelector('.m-output'), go = form.querySelector('.m-go');
  form.addEventListener('submit', async ev => {
    ev.preventDefault();
    const name = form.querySelector('.m-name').value.trim(), files = [...form.querySelector('.m-files').files];
    const links = form.querySelector('.m-links').value.split(/\s+/).map(x => x.trim()).filter(Boolean);
    const say = (html, cls = 'muted') => { out.innerHTML = `<p class="${cls}">${html}</p>`; };
    if (name.length < 2) { form.querySelector('.m-name').focus(); return say(L('Type the person\'s name.', 'Escribe el nombre de la persona.'), 'error'); }
    if (!files.length && !links.length) return say(L('Upload at least one PDF or text, or paste a link.', 'Sube al menos un PDF o texto, o pega un enlace.'), 'error');
    const bad = links.find(u => !/^https?:\/\/\S+$/.test(u));
    if (bad) return say(L(`This link must start with https://: ${esc(bad)}`, `Este enlace debe empezar con https://: ${esc(bad)}`), 'error');
    if (links.length > 10) return say(L('At most 10 links at once.', 'Máximo 10 enlaces a la vez.'), 'error');
    const big = files.find(x => x.size > MAX_UPLOAD);
    if (big) return say(L(`${esc(big.name)} is larger than 40 MB.`, `${esc(big.name)} pesa más de 40 MB.`), 'error');
    go.disabled = true;
    const failed = [];
    try {
      const { mentor } = await api('/api/mentors/manual', { name, language: LANG });
      for (const [i, file] of files.entries()) {
        out.innerHTML = `<div class="waiting"><span class="dot"></span>${L(`Reading ${i + 1} of ${files.length}: ${esc(file.name)}…`, `Leyendo ${i + 1} de ${files.length}: ${esc(file.name)}…`)}</div>`;
        // the profile is written once, after the last file
        try { await sendDocument(mentor.slug, file, i === files.length - 1); } catch (e) { failed.push(`${file.name}: ${e.message}`); }
      }
      if (links.length) {
        try { await api('/api/mentors/source', { slug: mentor.slug, sources: links.map(url => ({ url })) }); } catch (e) { failed.push(e.message); }
      }
      await loadMentors();
      if (failed.length) alert(L('The mentor was created, but this failed:\n', 'El referente quedó creado, pero esto falló:\n') + failed.join('\n'));
      if (onAdded) onAdded(mentor);
      showView('mentors');
      refreshJobs(true);
    } catch (e) { say(esc(e.message), 'error'); }
    go.disabled = false;
  });
}
function openAdd(target = null) {
  if (!target || !target.slug) target = null;            // only a mentor, never a click event
  $('#dlg-add h2').textContent = target ? L(`Find sources for ${target.name}`, `Buscar fuentes de ${target.name}`) : L('Add a mentor', 'Agregar referente');
  mountFinder($('#finder-dlg'), () => $('#dlg-add').close(), target);
  if (target) $('#finder-dlg .s-query').value = target.name;
  $('#dlg-add').showModal();
  if (target) $('#finder-dlg form.finder').requestSubmit();
}
// "+ Add" inside a mentor's sources: search online by name, paste a link, or upload a PDF
const PDF_ICON = '<svg class="platform" viewBox="0 0 24 24" aria-hidden="true">' + SVG.pdf + '</svg>';
function openSourceMenu(slug, anchor) {
  const r = MENTORS.find(x => x.slug === slug); if (!r) return;
  const items = [
    { k: 'find', icon: '🔎', t: L('Search online by name', 'Buscar en internet por nombre'), d: L('Their official channels and podcasts', 'Sus canales y podcasts oficiales') },
    { k: 'source', icon: '🔗', t: L('Paste a link', 'Pegar un enlace'), d: L('YouTube, podcast, web page or PDF', 'YouTube, podcast, página web o PDF') },
    { k: 'upload', icon: PDF_ICON, t: L('Upload a PDF or text', 'Subir un PDF o texto'), d: L('From your computer', 'Desde tu computador') }];
  const menu = $('#context-menu');
  menu.innerHTML = items.map(i => `<button type="button" role="menuitem" class="menu-rich" data-k="${i.k}"><span class="menu-icon">${i.icon}</span><span><b>${i.t}</b><small>${i.d}</small></span></button>`).join('');
  menu.hidden = false;
  const b = anchor.getBoundingClientRect();
  menu.style.left = Math.min(b.left, window.innerWidth - menu.offsetWidth - 8) + 'px';
  menu.style.top = Math.min(b.bottom + 4, window.innerHeight - menu.offsetHeight - 8) + 'px';
  menu.querySelectorAll('button').forEach(x => x.addEventListener('click', ev => { ev.stopPropagation(); closeMenu(); mentorAction(x.dataset.k, slug); }));
  menu.querySelector('button').focus();
}
$('#add-mentor').addEventListener('click', () => openAdd());
$('#close-add').addEventListener('click', () => $('#dlg-add').close());
$('#dlg-add').addEventListener('close', () => STOP_FINDER());     // closing the dialog drops the search in progress

// ---------------------------------------------------------------- your mentors
let JOBS = [], JOBS_POLL = null;
// The pieces of a mentor row that change while a job runs: built apart so a refresh can patch them in place
function jobOf(r) { const t = r.job; return { t, active: !!t && (t.status === 'queued' || t.status === 'running') }; }
// The server estimates it from the pace of this run; "" while there is not enough to measure yet
function timeLeft(s) {
  s = Math.round(+s || 0); if (!s) return '';
  const h = Math.floor(s / 3600), m = Math.round(s % 3600 / 60);
  const t = s < 60 ? L('under 1 min', 'menos de 1 min') : h ? `${h} h${m ? ` ${m} min` : ''}` : `${m} min`;
  return L(`~${t} left`, `faltan ~${t}`);
}
function progressParts(r) {
  const e = r.status, { t, active } = jobOf(r);
  const fresh = t && t.status === 'done' && t.kind === 'download' && minutesSince(t.finished) < 30;     // just finished: say what came in
  if (!(t && (active || t.status === 'error' || !e.with_text || fresh))) return null;
  const what = t.kind === 'profile' ? L('✍️ The AI writes their profile', '✍️ La IA escribe su perfil') : L('⟳ Updating', '⟳ Actualizando');
  return {
    id: t.id, cls: t.status === 'error' ? 'error' : (t.status === 'done' ? 'finished' : ''),
    bar: active && t.kind === 'download', pct: Math.max(0, Math.min(100, +t.percent || 0)), eta: active ? timeLeft(t.eta) : '',
    body: active ? `${what}: ${esc(t.progress)}` : fresh ? `✓ ${esc(String(t.summary || '').trim())}` : shortError(t),
    log: (JOBS.find(x => x.id === t.id)?.log || '').split('\n').slice(-40).join('\n'),
  };
}
function progressHTML(r) {
  const g = progressParts(r);
  if (!g) return '';
  return `<div class="progress ${g.cls}" data-job="${g.id}">${g.bar ? `<div class="bar-row"><b>${Math.round(g.pct)}%</b><div class="bar" role="progressbar" aria-valuenow="${Math.round(g.pct)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${g.pct}%"></span></div><small class="eta">${g.eta}</small></div>` : ''}<div class="prog-text">${g.body}</div>
    ${g.log ? `<details class="job-log"><summary>${L('See details', 'Ver detalle')}</summary><pre>${esc(g.log)}</pre></details>` : ''}</div>`;
}
function statsText(r) {
  const e = r.status, { active } = jobOf(r);
  return active && !e.with_text ? L('Preparing their first material…', 'Preparando su primer material…')
    : `${L(`${e.with_text} of ${e.indexed} with text`, `${e.with_text} de ${e.indexed} con texto`)}${e.hours ? ` · ${hoursText(e.hours)}` : ''}${e.without_text && !active ? ` · ${e.without_text} ${L('without subtitles', 'sin subtítulos')}` : ''}`;
}
function buttonsHTML(r) {
  const e = r.status, { t, active } = jobOf(r), profile = (r.profile || '').trim();
  const canUpdate = r.sources.some(f => ['youtube', 'rss', 'web'].includes(f.type));
  return `<button type="button" class="small primary" data-act="ask" ${e.with_text ? '' : 'disabled'}>💬 ${L('Ask', 'Preguntar')}</button>
        ${active ? `<button type="button" class="small" data-act="cancel" data-id="${t.id}">⏹ ${L('Stop', 'Detener')}</button>`
          : `${canUpdate ? `<button type="button" class="small" data-act="all" title="${L('Brings their new videos, episodes and pages; what you already have is not downloaded again.', 'Trae sus videos, episodios y páginas nuevos; lo que ya tienes no se vuelve a descargar.')}">⟳ ${L('Update material', 'Actualizar material')}</button>` : ''}${missingProfile(profile) && e.with_text ? `<button type="button" class="small" data-act="profile" title="${L('The AI reads their material and writes how they think, how they talk and their phrases', 'La IA lee su material y escribe cómo piensa, cómo habla y sus frases')}">✍️ ${L('Write profile', 'Escribir perfil')}</button>` : ''}`}
        <button type="button" class="small danger" data-act="delete">🗑 ${L('Delete', 'Eliminar')}</button>`;
}
function paintMentors() {
  if (!MENTORS.length) {
    $('#mentor-list').innerHTML = `<div class="empty"><h2>${L('You have no mentors yet', 'Todavía no tienes referentes')}</h2><p>${L('Press <b>+ Add</b> and type the name of someone you learn from.', 'Haz clic en <b>+ Agregar</b> y escribe el nombre de alguien de quien aprendes.')}</p></div>`;
    return;
  }
  const open = new Set($$('#mentor-list details.profile[open]').map(d => d.closest('.mentor-row').dataset.slug));
  $('#mentor-list').innerHTML = MENTORS.map(r => {
    const e = r.status;
    const sources = r.sources.map(f => {
      const u = SafeMarkdown.safeUrl(f.page || f.url);
      const inner = `${sourceIcon(f)}<span>${esc(f.name || f.url)}</span>`;
      return u ? `<a class="source-chip" href="${esc(u)}" target="_blank" rel="noopener noreferrer" title="${esc(platformName(platform(f)))}">${inner}</a>`
        : f.type === 'file' && f.id ? `<button type="button" class="source-chip doc" data-act="doc" data-id="${esc(f.id)}" title="${L('See the document', 'Ver el documento')}">${inner}</button>`
        : `<span class="source-chip" title="${L('Uploaded document', 'Documento subido')}">${inner}</span>`;
    }).join('');
    const profile = (r.profile || '').trim();
    return `<article class="mentor-row" data-slug="${esc(r.slug)}" data-sig="${esc(rowSignature(r))}">
      ${avatar(r, 'large')}
      <div class="info">
        <h3>${esc(r.name)}</h3>
        <div class="stats-line">${statsText(r)}</div>
        <div class="sources-box">
          <span class="sources-head">${L('Sources', 'Fuentes')}</span>
          <div class="sources-line">${sources}<button type="button" class="source-add" data-act="add-source" aria-haspopup="menu" title="${L('Add a channel, podcast, link or PDF', 'Agregar un canal, podcast, enlace o PDF')}">＋ ${L('Add', 'Agregar')}</button></div>
        </div>
        ${e.indexed ? `<button type="button" class="link see-material" data-act="material">📚 ${L('See all the material', 'Ver todo el material')} (${e.indexed.toLocaleString(LOCALE())})</button>` : ''}
        <div class="progress-slot">${progressHTML(r)}</div>
        ${profile ? `<details class="profile" ${open.has(r.slug) ? 'open' : ''}><summary>${L('Profile: how they think and how they talk', 'Perfil: cómo piensa y cómo habla')}</summary><div class="md">${md(profile)}</div></details>` : ''}
      </div>
      <div class="buttons">${buttonsHTML(r)}</div></article>`;
  }).join('');
}
// What, if it changes, needs the whole row redrawn (sources, profile, name); the rest is patched in place
const rowSignature = r => JSON.stringify([r.name, r.profile, r.sources.map(f => f.url + f.name + (f.image || '')), r.status.indexed > 0]);
// Live update while a job runs: only the progress, the counts and the buttons change. An open "See details" stays
// open, keeps its scroll (or follows the end if you were at the end) and the page does not jump.
function updateMentors() {
  const rows = $$('#mentor-list .mentor-row');
  if (rows.length !== MENTORS.length || MENTORS.some((r, i) => rows[i].dataset.slug !== r.slug || rows[i].dataset.sig !== rowSignature(r))) return paintMentors();
  MENTORS.forEach((r, i) => {
    const row = rows[i], slot = row.querySelector('.progress-slot'), g = progressParts(r);
    const stats = row.querySelector('.stats-line'), st = statsText(r);
    if (stats.innerHTML !== st) stats.innerHTML = st;
    const mat = row.querySelector('.see-material');
    if (mat) mat.textContent = `📚 ${L('See all the material', 'Ver todo el material')} (${r.status.indexed.toLocaleString(LOCALE())})`;
    const btns = buttonsHTML(r), box = row.querySelector('.buttons');
    if (box.dataset.html !== btns) { box.innerHTML = btns; box.dataset.html = btns; }
    const cur = slot.querySelector('.progress');
    if (!g) { if (cur) slot.innerHTML = ''; return; }
    if (!cur || +cur.dataset.job !== g.id || !!cur.querySelector('.bar') !== g.bar || (g.log && !cur.querySelector('pre'))) {
      const wasOpen = !!slot.querySelector('details.job-log[open]');
      slot.innerHTML = progressHTML(r);
      if (wasOpen && slot.querySelector('details.job-log')) slot.querySelector('details.job-log').open = true;
      return;
    }
    cur.className = `progress ${g.cls}`;
    if (g.bar) {
      cur.querySelector('.bar-row b').textContent = `${Math.round(g.pct)}%`;
      cur.querySelector('.bar span').style.width = `${g.pct}%`;
      cur.querySelector('.bar').setAttribute('aria-valuenow', String(Math.round(g.pct)));
      cur.querySelector('.bar-row .eta').textContent = g.eta;
    }
    const text = cur.querySelector('.prog-text');
    if (text.innerHTML !== g.body) text.innerHTML = g.body;
    const pre = cur.querySelector('pre');
    if (pre && pre.textContent !== g.log) {
      const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
      const top = pre.scrollTop;
      pre.textContent = g.log;
      pre.scrollTop = atEnd ? pre.scrollHeight : top;
    }
  });
}
// One listener for the whole list, so patched buttons keep working
$('#mentor-list').addEventListener('click', ev => {
  const b = ev.target.closest('[data-act]');
  if (!b || !b.closest('.mentor-row')) return;
  const slug = b.closest('.mentor-row').dataset.slug;
  if (b.dataset.act === 'add-source') { ev.stopPropagation(); return openSourceMenu(slug, b); }
  mentorAction(b.dataset.act, slug, b.dataset.id);
});
// Minutes since a "YYYY-MM-DD HH:MM:SS" time saved by the server (local time)
function minutesSince(t) { const d = new Date(String(t || '').replace(' ', 'T')); return isNaN(d) ? 1e9 : (Date.now() - d) / 60000; }
// A profile that only has the intro line ("Who they are.") still needs the AI
const missingProfile = f => !f || (/^\*\*(Who they are|Quién es)\.\*\*/.test(f) && (f.match(/\*\*/g) || []).length <= 2);
// A long AI error is summarized in one line; the full detail stays in "See details"
function shortError(t) {
  const txt = String(t.summary || t.status || '');
  if (t.status !== 'error') return esc(txt);
  const what = t.kind === 'profile' ? L('The AI could not write the profile', 'La IA no pudo escribir el perfil') : L('The download failed', 'La descarga falló');
  if (/auth|login|connect|session|sesi[oó]n/i.test(txt)) return STATUS.ai_ready
    ? L(`${what} because Claude was not connected. It is now: press “Write profile”.`, `${what} porque Claude no estaba conectado. Ya lo está: haz clic en «Escribir perfil».`)
    : `${what}: ${L('Claude is not connected.', 'Claude no está conectado.')} ${connectButton()}`;
  if (/not supported|model/i.test(txt)) return L(`${what}: the configured AI rejected the model. Check "ai" in data/config.json or go back to Claude.`, `${what}: la IA configurada rechazó el modelo. Revisa "ai" en data/config.json o vuelve a Claude.`);
  return `${what}: ${esc(txt.split('\n')[0].slice(0, 160))}`;
}
// ---------------------------------------------------------------- where a mentor's material came from
let MATERIAL = [];
async function openMaterial(r) {
  $('#mat-title').textContent = L(`${r.name}'s material`, `Material de ${r.name}`);
  $('#mat-filter').value = ''; $('#mat-list').innerHTML = `<div class="waiting"><span class="dot"></span>${L('Loading…', 'Cargando…')}</div>`;
  $('#dlg-material').showModal();
  try { MATERIAL = (await api(`/api/mentors/material?slug=${encodeURIComponent(r.slug)}`)).items; paintMaterial(); }
  catch (e) { $('#mat-list').innerHTML = `<div class="error">${esc(e.message)}</div>`; }
}
function shortDuration(s) { s = Math.round(+s || 0); if (!s) return ''; const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return h ? `${h} h ${m} min` : `${m} min`; }
function paintMaterial() {
  const q = $('#mat-filter').value.trim().toLowerCase();
  const list = MATERIAL.filter(x => !q || x.title.toLowerCase().includes(q));
  const withText = MATERIAL.filter(x => x.has_text).length, loc = LOCALE();
  $('#mat-summary').textContent = L(`${MATERIAL.length.toLocaleString(loc)} sources · ${withText.toLocaleString(loc)} with text (the ones the AI can cite)${q ? ` · ${list.length} match` : ''}`,
    `${MATERIAL.length.toLocaleString(loc)} fuentes · ${withText.toLocaleString(loc)} con texto (las que la IA puede citar)${q ? ` · ${list.length} coinciden` : ''}`);
  $('#mat-list').innerHTML = list.slice(0, 800).map(x => {
    const u = SafeMarkdown.safeUrl(x.url);
    const t = u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>` : esc(x.title);
    return `<div class="mat-item ${x.has_text ? '' : 'missing'}">${sourceIcon({ type: x.type, url: x.url, name: x.title })}
      <span class="mat-title">${t}<small>${[x.date, shortDuration(x.duration), x.has_text ? '' : L('no text: the AI cannot read it', 'sin texto: la IA no lo puede leer')].filter(Boolean).join(' · ')}</small></span></div>`;
  }).join('') + (list.length > 800 ? `<p class="muted small">${L(`And ${list.length - 800} more: filter by title to see them.`, `Y ${list.length - 800} más: filtra por título para verlos.`)}</p>` : '');
}
$('#mat-filter').addEventListener('input', paintMaterial);
$('#close-material').addEventListener('click', () => $('#dlg-material').close());

const MAX_UPLOAD = 40 * 1024 * 1024;
function sendDocument(slug, file, profile = true) {
  return new Promise((ok, fail) => {
    const reader = new FileReader();
    reader.onerror = () => fail(new Error(L('Could not read the file.', 'No pude leer el archivo.')));
    reader.onload = () => api('/api/mentors/file', { slug, name: file.name, data: reader.result, profile }).then(ok, fail);
    reader.readAsDataURL(file);
  });
}
// A PDF uploaded as a source: preview first, with a button to download it
function openDocument(r, id) {
  const f = r.sources.find(x => x.type === 'file' && x.id === id); if (!f) return;
  const url = `/api/mentors/document?slug=${encodeURIComponent(r.slug)}&id=${encodeURIComponent(id)}`;
  $('#doc-title').textContent = f.name;
  $('#doc-download').href = url + '&download=1';
  $('#doc-download').setAttribute('download', f.name);
  $('#doc-frame').src = url;
  $('#dlg-doc').showModal();
}
$('#close-doc').addEventListener('click', () => $('#dlg-doc').close());
$('#dlg-doc').addEventListener('close', () => { $('#doc-frame').src = 'about:blank'; });
function uploadDocument(slug) {
  const input = document.createElement('input');
  input.type = 'file'; input.accept = '.pdf,.txt,.md,.html,.htm';
  input.addEventListener('change', async () => {
    const f = input.files[0]; if (!f) return;
    if (f.size > MAX_UPLOAD) return alert(L('The file is larger than 40 MB.', 'El archivo pesa más de 40 MB.'));
    try { const r = await sendDocument(slug, f); await loadMentors(); paintMentors(); alert(r.note || L('Document added.', 'Documento agregado.')); }
    catch (e) { alert(e.message); }
  });
  input.click();
}
async function mentorAction(act, slug, id) {
  const r = MENTORS.find(x => x.slug === slug);
  try {
    if (act === 'ask') { showView('chat'); newChat(slug); $('#question').focus(); return; }
    if (act === 'profile') { if (!STATUS.ai_ready) return openConnect(); await api('/api/mentors/profile', { slug }); return refreshJobs(true); }
    if (act === 'material') return openMaterial(r);
    if (act === 'find') return openAdd(r);
    if (act === 'source') {
      const url = prompt(L(`Paste the link for ${r.name}: a YouTube channel, a podcast (RSS), a web page or a PDF.`, `Pega el enlace para ${r.name}: un canal de YouTube, un podcast (RSS), una página web o un PDF.`));
      if (!url || !url.trim()) return;
      await api('/api/mentors/source', { slug, url: url.trim() }); await loadMentors(); return refreshJobs(true);
    }
    if (act === 'upload') return uploadDocument(slug);
    if (act === 'doc') return openDocument(r, id);
    if (act === 'all') { await api('/api/mentors/download', { slug, limit: 0 }); return refreshJobs(true); }
    if (act === 'cancel') { await api('/api/jobs/cancel', { id: +id }); return refreshJobs(true); }
    if (act === 'delete') {
      if (!confirm(L(`Delete ${r.name} and their downloaded transcripts? This cannot be undone.`, `¿Eliminar a ${r.name} y sus transcripciones descargadas? No se puede deshacer.`))) return;
      await api('/api/mentors/delete', { slug, files: true });
      await loadMentors(); paintMentors(); if (!CHAT) paintEmpty();
    }
  } catch (e) { alert(e.message); }
}
let HAD_ACTIVE = false;
async function refreshJobs(force) {
  try { JOBS = (await api('/api/jobs')).jobs; } catch (e) { return; }
  const active = JOBS.some(t => t.status === 'queued' || t.status === 'running');
  if (active || HAD_ACTIVE || force) {
    await loadMentors();
    if (VIEW === 'mentors') updateMentors();
    if (!CHAT && VIEW === 'chat' && !$('#thread .welcome')) paintEmpty();
  }
  HAD_ACTIVE = active;
  clearTimeout(JOBS_POLL);
  JOBS_POLL = setTimeout(refreshJobs, active ? 2500 : 10000);
}

// ---------------------------------------------------------------- start
async function loadData() {
  await Promise.all([loadStatus(), loadMentors()]);
  await loadChats();
  document.body.classList.remove('loading');
}
setInterval(() => { if ($('#context-menu').hidden && !$('#chats').classList.contains('dragging')) loadChats().catch(() => {}); }, 15000);
(async function start() {
  setLanguage(LANG); translateDom(); composerState();
  const c = readLS(SB_COLLAPSED);
  applySidebar(sidebarWidth(), c === null ? window.innerWidth <= 760 : c === '1');
  try { await loadData(); } catch (e) { $('#thread').innerHTML = `<div class="empty error">${L('Could not connect to the server', 'No pude conectar con el servidor')}: ${esc(e.message)}</div>`; return; }
  // Direct links: #mentors or #chat=<id>
  const h = location.hash.slice(1), mc = h.match(/^chat=(\d+)$/);
  showView(h === 'mentors' ? 'mentors' : 'chat');
  if (mc) openChat(+mc[1]).catch(() => paintEmpty()); else paintEmpty();
  refreshJobs();
  window.dispatchEvent(new Event('resize'));          // if it starts in a narrow window, the panel hides
})();

// ---------------------------------------------------------------- dialogs: click outside or Esc to close
$$('dialog.dialog').forEach(d => d.addEventListener('click', ev => { if (ev.target === d) d.close(); }));
