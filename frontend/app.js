const STATUS_MAP = {
  'ACTIVE':   { label: 'Активный', cls: 'active' },
  'ЗАПИСАН':  { label: 'Записан',  cls: 'booked' },
  'ДУМАЕТ':   { label: 'Думает',   cls: 'thinking' },
  'МЕНЕДЖЕР': { label: 'Менеджер', cls: 'manager' },
  'ОТКАЗ':    { label: 'Отказ',    cls: 'lost' },
  'КЛИЕНТ':   { label: 'Клиент',   cls: 'client' },
};

const STAGE_LABELS = {
  'НОВЫЙ_ЛИД': 'Новый лид',
  'ВЫЯВЛЕНИЕ_ПОТРЕБНОСТИ': 'Выявление потребности',
  'КВАЛИФИКАЦИЯ': 'Квалификация',
  'ФОРМИРОВАНИЕ_ПОТРЕБНОСТИ': 'Формирование потребности',
  'ПРЕЗЕНТАЦИЯ_РЕШЕНИЯ': 'Презентация решения',
  'ЦЕЛЕВОЕ_ДЕЙСТВИЕ': 'Целевое действие',
  'РАБОТА_С_ВОЗРАЖЕНИЕМ': 'Работа с возражением',
  'ЗАПИСЬ': 'Запись',
  'ПОДТВЕРЖДЕНИЕ': 'Подтверждение',
  'НАПОМИНАНИЕ': 'Напоминание',
  'ПОСЛЕ_ПРОБНОГО': 'После пробного',
  'СОМНЕНИЯ_ПОСЛЕ_ПРОБНОГО': 'Сомнения после пробного',
  'ПРОДАЖА': 'Продажа',
  'ДУМАЕТ_FOLLOWUP': 'Думает (follow-up)',
};

const EVENT_ICONS = {
  'stage_entered':          { icon: '→', title: 'Переход на этап' },
  'stage_exited':           { icon: '←', title: 'Уход с этапа' },
  'objection_raised':       { icon: '⚠', title: 'Возражение' },
  'trial_booked':           { icon: '✓', title: 'Запись на пробный' },
  'transferred_to_manager': { icon: '👤', title: 'Перевод менеджеру' },
  'followup_sent':          { icon: '⏰', title: 'Follow-up' },
  'lead_lost':              { icon: '✕', title: 'Лид потерян' },
  'sale_won':               { icon: '🎉', title: 'Продажа' },
};

const state = {
  leads: [],
  selectedId: null,
  selected: null,
  messages: [],
  events: [],
  status: 'ALL',
  search: '',
  tab: 'messages',
};

/* ------------- helpers ------------- */
const $ = (sel) => document.querySelector(sel);

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function initials(name, fallback) {
  const src = (name || fallback || '?').trim();
  if (!src) return '?';
  const parts = src.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return src.slice(0, 2).toUpperCase();
}

function phoneFromId(id) {
  if (!id) return '';
  const m = String(id).match(/^(\d+)@/);
  if (!m) return id;
  return '+' + m[1];
}

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
}

function fmtDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function fmtRelative(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 0) return fmtTime(iso);
  if (diff < 60) return 'только что';
  if (diff < 3600) return Math.floor(diff / 60) + ' мин назад';
  if (diff < 86400) return Math.floor(diff / 3600) + ' ч назад';
  if (diff < 604800) return Math.floor(diff / 86400) + ' дн назад';
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
}

function stageLabel(s) { return STAGE_LABELS[s] || s || '—'; }

function statusInfo(s) {
  return STATUS_MAP[s] || { label: s || '—', cls: '' };
}

/* ------------- API ------------- */
async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

async function loadStats() {
  try {
    const s = await fetchJSON('/api/stats');
    $('#stat-total').textContent   = s.leads.total ?? 0;
    $('#stat-active').textContent  = s.leads.active ?? 0;
    $('#stat-booked').textContent  = s.leads.booked ?? 0;
    $('#stat-clients').textContent = s.leads.clients ?? 0;
  } catch (e) {
    console.error(e);
  }
}

async function loadLeads() {
  const params = new URLSearchParams({ limit: '200' });
  if (state.search) params.set('search', state.search);
  if (state.status !== 'ALL') params.set('status', state.status);

  try {
    const data = await fetchJSON('/api/leads?' + params.toString());
    state.leads = data.items || [];
    renderLeads();
  } catch (e) {
    console.error(e);
    $('#leads').innerHTML = `<div class="no-results">Ошибка загрузки: ${esc(e.message)}</div>`;
  }
}

async function loadLeadDetail(id) {
  try {
    const [lead, messages, events] = await Promise.all([
      fetchJSON(`/api/leads/${encodeURIComponent(id)}`),
      fetchJSON(`/api/leads/${encodeURIComponent(id)}/messages`),
      fetchJSON(`/api/leads/${encodeURIComponent(id)}/events`),
    ]);
    state.selected = lead;
    state.messages = messages.items || [];
    state.events   = events.items || [];
    renderDetail();
  } catch (e) {
    console.error(e);
  }
}

/* ------------- render: leads ------------- */
function renderLeads() {
  const box = $('#leads');
  if (!state.leads.length) {
    box.innerHTML = '<div class="no-results">Нет лидов под фильтр</div>';
    return;
  }

  box.innerHTML = state.leads.map((l) => {
    const st = statusInfo(l.status);
    const active = state.selectedId === l.whatsapp_id ? ' active' : '';
    const name = l.name || phoneFromId(l.whatsapp_id);
    const preview = l.last_message || '— нет сообщений —';
    const time = fmtRelative(l.last_message_time || l.last_message_at || l.updated_at);

    return `
      <div class="lead${active}" data-id="${esc(l.whatsapp_id)}">
        <div class="avatar">${esc(initials(l.name, phoneFromId(l.whatsapp_id)))}</div>
        <div class="lead-body">
          <div class="lead-row">
            <div class="lead-name">${esc(name)}</div>
            <div class="lead-time">${esc(time)}</div>
          </div>
          <div class="lead-preview">${esc(preview)}</div>
          <div class="lead-badges">
            <span class="badge status ${esc(st.cls)}">${esc(st.label)}</span>
            <span class="badge stage">${esc(stageLabel(l.current_stage))}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');

  box.querySelectorAll('.lead').forEach((el) => {
    el.addEventListener('click', () => {
      const id = el.dataset.id;
      if (id === state.selectedId) return;
      state.selectedId = id;
      renderLeads();
      document.body.classList.add('mobile-detail');
      $('#empty').classList.add('hidden');
      $('#detail').classList.remove('hidden');
      loadLeadDetail(id);
    });
  });
}

/* ------------- render: detail ------------- */
function renderDetail() {
  const l = state.selected;
  if (!l) return;

  const st = statusInfo(l.status);
  const name = l.name || phoneFromId(l.whatsapp_id);

  $('#d-avatar').textContent = initials(l.name, phoneFromId(l.whatsapp_id));
  $('#d-name').textContent   = name;
  $('#d-phone').textContent  = phoneFromId(l.whatsapp_id);

  const stageEl = $('#d-stage');
  stageEl.textContent = stageLabel(l.current_stage);

  const statusEl = $('#d-status');
  statusEl.textContent = st.label;
  statusEl.className = 'badge status ' + st.cls;

  renderMessages();
  renderEvents();
  renderData();
}

/* ------------- render: messages ------------- */
function renderMessages() {
  const box = $('#messages');
  if (!state.messages.length) {
    box.innerHTML = '<div class="no-results">Пока нет сообщений</div>';
    return;
  }

  box.innerHTML = state.messages.map((m) => {
    const dir = m.direction === 'out' ? 'out' : 'in';
    const stage = m.stage_at_moment
      ? `<span class="msg-stage">${esc(stageLabel(m.stage_at_moment))}</span>` : '';
    const rt = m.response_time_ms
      ? `<span>${(m.response_time_ms / 1000).toFixed(1)}s</span>` : '';
    const typ = m.message_type && m.message_type !== 'chat'
      ? `<span>${esc(m.message_type)}</span>` : '';
    return `
      <div class="msg ${dir}">
        ${esc(m.content || '')}
        <div class="msg-meta">
          <span>${esc(fmtTime(m.created_at))}</span>
          ${stage}${typ}${rt}
        </div>
      </div>
    `;
  }).join('');

  // scroll to bottom
  requestAnimationFrame(() => { box.scrollTop = box.scrollHeight; });
}

/* ------------- render: events ------------- */
function renderEvents() {
  const box = $('#events');
  if (!state.events.length) {
    box.innerHTML = '<div class="no-results">Нет событий</div>';
    return;
  }

  box.innerHTML = state.events.map((e) => {
    const cfg = EVENT_ICONS[e.event_type] || { icon: '•', title: e.event_type };
    const parts = [];
    if (e.from_stage && e.to_stage) {
      parts.push(`${stageLabel(e.from_stage)} → ${stageLabel(e.to_stage)}`);
    } else if (e.to_stage) {
      parts.push(stageLabel(e.to_stage));
    }
    const p = e.payload || {};
    if (p.objection) parts.push(`Возражение: ${p.objection}`);
    if (p.trial_datetime) parts.push(`Пробный: ${p.trial_datetime}`);
    if (p.reason) parts.push(`Причина: ${p.reason}`);

    return `
      <div class="event">
        <div class="event-icon">${cfg.icon}</div>
        <div class="event-body">
          <div class="event-title">${esc(cfg.title)}</div>
          ${parts.length ? `<div class="event-sub">${esc(parts.join(' · '))}</div>` : ''}
        </div>
        <div class="event-time">${esc(fmtDateTime(e.created_at))}</div>
      </div>
    `;
  }).join('');
}

/* ------------- render: data ------------- */
function renderData() {
  const l = state.selected;
  if (!l) return;

  const rows = [
    ['Имя', l.name],
    ['WhatsApp ID', phoneFromId(l.whatsapp_id)],
    ['Этап', stageLabel(l.current_stage)],
    ['Предыдущий этап', stageLabel(l.previous_stage)],
    ['Статус', statusInfo(l.status).label],
    ['Направление', l.direction],
    ['Цель', l.goal],
    ['Уровень', l.experience_level],
    ['Формат', l.preferred_format],
    ['Удобное время', l.preferred_time],
    ['Дата пробного', l.trial_datetime ? fmtDateTime(l.trial_datetime) : ''],
    ['Последнее возражение', l.last_objection],
    ['Confidence', l.confidence_last != null ? Number(l.confidence_last).toFixed(2) : ''],
    ['Создан', l.created_at ? fmtDateTime(l.created_at) : ''],
    ['Обновлён', l.updated_at ? fmtDateTime(l.updated_at) : ''],
    ['Последнее сообщение', l.last_message_at ? fmtDateTime(l.last_message_at) : ''],
  ];

  $('#data').innerHTML = rows.map(([k, v]) => {
    const isEmpty = v == null || v === '';
    return `
      <div class="data-item">
        <div class="data-key">${esc(k)}</div>
        <div class="data-val${isEmpty ? ' empty' : ''}">${isEmpty ? '—' : esc(v)}</div>
      </div>
    `;
  }).join('');
}

$('#back-btn').addEventListener('click', () => {
  document.body.classList.remove('mobile-detail');
});
/* ------------- events wiring ------------- */
let searchTimer = null;
$('#search').addEventListener('input', (e) => {
  state.search = e.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadLeads, 300);
});

$('#chips').addEventListener('click', (e) => {
  const chip = e.target.closest('.chip');
  if (!chip) return;
  document.querySelectorAll('#chips .chip').forEach((c) => c.classList.remove('active'));
  chip.classList.add('active');
  state.status = chip.dataset.status;
  loadLeads();
});

document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    const tab = t.dataset.tab;
    state.tab = tab;
    document.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === t));
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.add('hidden'));
    $('#tab-' + tab).classList.remove('hidden');
  });
});

$('#refresh-btn').addEventListener('click', refreshAll);

/* ------------- polling ------------- */
async function refreshAll() {
  await Promise.all([loadStats(), loadLeads()]);
  if (state.selectedId) await loadLeadDetail(state.selectedId);
  const now = new Date();
  $('#live-status').innerHTML =
    `<span class="dot"></span> онлайн · ${fmtTime(now)}`;
}

function startPolling() {
  setInterval(async () => {
    await Promise.all([loadStats(), loadLeads()]);
    if (state.selectedId) await loadLeadDetail(state.selectedId);
    const now = new Date();
    $('#live-status').innerHTML =
      `<span class="dot"></span> онлайн · ${fmtTime(now)}`;
  }, 10000);
}

/* ------------- bootstrap ------------- */
(async function init() {

  if (window.matchMedia('(max-width: 900px)').matches) {
    document.body.classList.remove('mobile-detail');
  }
  await refreshAll();
  startPolling();
})();