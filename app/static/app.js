'use strict';
const $ = id => document.getElementById(id);
let csrf = '', user = null, labels = {}, activeId = null, facts = [], busy = false, timer, catalogRequest = 0;
function el(tag, text, cls) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; }
function toast(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(timer); timer = setTimeout(() => $('toast').hidden = true, 6500); }
async function api(path, method = 'GET', body) {
  const response = await fetch('/api' + path, { method, credentials: 'same-origin', headers: {'Content-Type':'application/json','X-CSRF-Token':csrf}, body:body === undefined ? undefined : JSON.stringify(body) });
  let data; try { data = await response.json(); } catch { throw new Error('Сервер не ответил. Проверьте, запущено ли приложение.'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') { user = null; showSession(); }
    const error = new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте введённые данные.'); error.data = data; error.status = response.status; throw error;
  }
  return data;
}
function formatted(key, value) {
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  if (key === 'budget_max') return new Intl.NumberFormat('ru-RU').format(value) + ' ₽';
  if (key === 'rooms') return value === 0 ? 'Студия' : value + ' комн.';
  if (key === 'min_area') return value + ' м²';
  if (key === 'payment_method') return value === 'cash' ? 'Собственные средства' : 'Ипотека';
  return String(value);
}
function clearPrivateViews() {
  catalogRequest++; $('matching-only').checked = false; $('catalog').replaceChildren(); $('catalog-count').textContent = ''; $('catalog-empty').hidden = true;
  for (const id of ['messages','memory-list','own-fact-editor','admin-detail','conversations','admin-users']) $(id).replaceChildren();
  $('used-facts').hidden = true; $('memory-indicator').hidden = true;
}
function showSession() {
  $('login-screen').hidden = !!user; $('application').hidden = !user;
  if (user) { $('user-name').textContent = user.display_name; $('user-role').textContent = user.role === 'admin' ? 'Администратор' : 'Клиент'; $('avatar').textContent = user.display_name[0]; $('admin-nav').hidden = user.role !== 'admin'; }
}
async function start() {
  try {
    const data = await api('/bootstrap'); csrf = data.csrf_token; user = data.user; labels = data.labels;
    $('key-warning').hidden = data.ai_configured;
    showSession();
    if (user) { await refreshConversations(); await refreshFacts(); await switchView(location.pathname === '/admin' ? 'admin' : 'chat'); }
  } catch (e) { toast(e.message); }
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); $('login-error').textContent = ''; const button = event.submitter; button.disabled = true;
  try { const data = await api('/login', 'POST', {username:$('username').value.trim(),password:$('password').value}); csrf = data.csrf_token; user = data.user; $('password').value = ''; activeId = null; clearPrivateViews(); showSession(); await refreshConversations(); await refreshFacts(); await switchView('chat'); }
  catch (e) { $('login-error').textContent = e.message; } finally { button.disabled = false; }
});
$('logout').addEventListener('click', async () => { if (busy) return toast('Дождитесь завершения ответа.'); try { await api('/logout','POST'); activeId = null; facts = []; user = null; clearPrivateViews(); await start(); } catch(e) { toast(e.message); } });
const titles = {chat:'AI-консультант',catalog:'Каталог квартир',data:'Мои данные',admin:'Администрирование'};
async function switchView(view) {
  if (view === 'admin' && user?.role !== 'admin') { toast('Доступно только администратору.'); return; }
  document.querySelectorAll('.view').forEach(node => node.hidden = node.id !== 'view-' + view);
  document.querySelectorAll('[data-view]').forEach(node => node.classList.toggle('active',node.dataset.view === view));
  $('page-title').textContent = titles[view];
  if (view === 'chat') await loadMessages();
  if (view === 'catalog') await loadCatalog();
  if (view === 'data') { await refreshFacts(); renderEditor($('own-fact-editor'),facts); }
  if (view === 'admin') await loadAdmin();
}
document.querySelectorAll('[data-view]').forEach(node => node.addEventListener('click',() => switchView(node.dataset.view).catch(e => toast(e.message))));
$('manage-memory').addEventListener('click',() => switchView('data').catch(e => toast(e.message)));
async function refreshConversations() {
  const rows = await api('/conversations'); const target = $('conversations'); target.replaceChildren();
  if (!rows.length) target.append(el('p','Начните свой первый подбор','empty-convs'));
  for (const conv of rows) {
    const row = el('div',undefined,'conversation-row' + (conv.id === activeId ? ' active' : ''));
    const open = el('button','◷  ' + conv.title,'conversation-open'); open.title = conv.title;
    open.addEventListener('click', async () => { if (busy) return; activeId = conv.id; $('used-facts').hidden = true; try { await refreshConversations(); await switchView('chat'); } catch(e) { toast(e.message); } });
    const remove = el('button','×','conversation-delete'); remove.title = 'Удалить диалог'; remove.setAttribute('aria-label','Удалить диалог ' + conv.title);
    remove.addEventListener('click', async () => { if (busy || !confirm('Удалить этот диалог? Сохранённые предпочтения останутся.')) return; try { await api('/conversations/' + conv.id,'DELETE'); if (activeId === conv.id) {activeId = null; $('used-facts').hidden = true; await loadMessages();} await refreshConversations(); } catch(e) { toast(e.message); } });
    row.append(open,remove); target.append(row);
  }
}
$('new-chat').addEventListener('click', async () => { if (busy) return; activeId = null; $('used-facts').hidden = true; $('memory-indicator').hidden = true; try { await refreshConversations(); await switchView('chat'); $('chat-input').focus(); } catch(e) {toast(e.message);} });
function welcome() {
  const wrap = el('div',undefined,'welcome'); wrap.append(el('div','✧','welcome-icon'),el('h3','Здравствуйте, ' + user.display_name + '!'),el('p','Я помогу найти квартиру в «Северном парке». Расскажите, что для вас важно: бюджет, количество комнат, этаж или отделка.'));
  const suggestions = el('div',undefined,'suggestions');
  for (const text of ['Ищу двушку до 9 миллионов','Что есть подходящего для меня?','Расскажи о жилом комплексе']) { const button = el('button',text,'suggestion'); button.append(el('span','↗')); button.addEventListener('click',() => { $('chat-input').value = text; $('chat-input').focus(); }); suggestions.append(button); }
  wrap.append(suggestions); $('messages').append(wrap);
}
async function loadMessages() {
  const target = $('messages'); target.replaceChildren();
  if (!activeId) { welcome(); return; }
  const data = await api('/conversations/' + activeId);
  for (const message of data.messages) {
    const row = el('article',undefined,'message ' + message.role); const bubble = el('div',undefined,'message-content');
    bubble.append(el('span',message.role === 'user' ? 'ВЫ' : 'ПЕРСОНАЛЬНЫЙ AI-МЕНЕДЖЕР','message-label'),document.createTextNode(message.content));
    row.append(el('span',message.role === 'user' ? user.display_name[0] : '✧','message-avatar'),bubble); target.append(row);
  }
  target.scrollTop = target.scrollHeight;
}
async function refreshFacts() {
  facts = await api('/facts'); const target = $('memory-list'); target.replaceChildren();
  if (!facts.length) target.append(el('div','Пока нет сохранённых пожеланий','memory-empty'));
  for (const fact of facts) { const row = el('div',undefined,'fact-item'); row.append(el('div',labels[fact.key],'fact-label'),el('div',formatted(fact.key,fact.value),'fact-value')); target.append(row); }
}
$('chat-input').addEventListener('keydown',event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('chat-form').requestSubmit(); } });
$('chat-form').addEventListener('submit', async event => {
  event.preventDefault(); if (busy || !$('chat-input').value.trim()) return;
  busy = true; const content = $('chat-input').value.trim(); $('send').disabled = true; $('send').textContent = 'Подбираю…'; $('chat-input').disabled = true; $('memory-indicator').hidden = true;
  let saved = false;
  try {
    if (!activeId) activeId = (await api('/conversations','POST')).id;
    const result = await api('/conversations/' + activeId + '/messages','POST',{content}); saved = true;
    $('memory-indicator').hidden = !result.memory_updated;
    if (result.warning) toast(result.warning);
    const entries = Object.entries(result.used_facts);
    $('used-facts').textContent = entries.length ? 'Использованы пожелания: ' + entries.map(([key,value]) => labels[key] + ': ' + formatted(key,value)).join(' · ') : 'Подбор без сохранённых ограничений';
    $('used-facts').hidden = false;
  } catch(e) { saved = !!e.data?.user_message_saved; if (e.data?.memory_updated) $('memory-indicator').hidden = false; toast(e.message); }
  finally {
    if (saved) $('chat-input').value = '';
    busy = false; $('send').disabled = false; $('send').textContent = 'Отправить ↑'; $('chat-input').disabled = false;
    if (user) { try { await loadMessages(); await refreshFacts(); await refreshConversations(); } catch(e) {toast(e.message);} }
    $('chat-input').focus();
  }
});
$('matching-only').addEventListener('change', () => loadCatalog().catch(e => toast(e.message)));
$('catalog-manage-memory').addEventListener('click', () => switchView('data').catch(e => toast(e.message)));
async function loadCatalog() {
  const request = ++catalogRequest, matching = $('matching-only').checked;
  const target = $('catalog'); target.replaceChildren(); $('catalog-count').textContent = ''; $('catalog-empty').hidden = true;
  const data = await api(matching ? '/apartments?matching_only=true' : '/apartments');
  if (request !== catalogRequest || !user) return;
  const rows = matching ? data.items : data;
  $('catalog-count').textContent = 'Найдено квартир: ' + rows.length;
  if (matching && (!data.criteria_applied || !rows.length)) {
    $('catalog-empty-text').textContent = data.criteria_applied ? 'По вашим сохранённым пожеланиям подходящих квартир пока нет' : 'Критерии подбора ещё не заданы';
    $('catalog-empty').hidden = false;
  }
  for (const a of rows) {
    const card = el('article',undefined,'apartment-card'); const plan = el('div',undefined,'floor-plan'); const outline = el('div',undefined,'plan-outline'); outline.setAttribute('aria-hidden','true'); for(let i=0;i<4;i++) outline.append(el('i')); plan.append(el('span',a.building + ' · ' + a.id),outline);
    const info = el('div',undefined,'card-details'); info.append(el('div','СДАЧА В ' + a.delivery_year + ' ГОДУ','card-meta'),el('h3',(a.rooms === 0 ? 'Студия' : a.rooms + '-комнатная') + ' · ' + a.area + ' м²'),el('div',formatted('budget_max',a.price),'card-price'),el('div',a.floor + '/' + a.total_floors + ' этаж · ' + (a.finishing ? 'С отделкой' : 'Без отделки'),'card-specs'),el('span','Учебный объект','card-tag'));
    const button = el('button','Обсудить с AI-менеджером ↗','card-select'); button.addEventListener('click',async () => { try { await switchView('chat'); $('chat-input').value = 'Меня интересует квартира ' + a.id; $('chat-input').focus(); } catch(e) {toast(e.message);} }); info.append(button); card.append(plan,info); target.append(card);
  }
}
function factInput(key,value) {
  let input;
  if (['finishing','exclude_first_floor','payment_method','rooms','delivery_year'].includes(key)) {
    input = el('select'); const options = ['finishing','exclude_first_floor'].includes(key) ? [[true,'Да'],[false,'Нет']] : key === 'payment_method' ? [['mortgage','Ипотека'],['cash','Собственные средства']] : key === 'rooms' ? [[0,'Студия'],[1,'1'],[2,'2'],[3,'3']] : [[2027,'2027'],[2028,'2028']];
    for(const [v,text] of options) {const option = el('option',text); option.value = JSON.stringify(v); input.append(option);} if(value !== undefined) input.value = JSON.stringify(value);
  } else { input = el('input'); input.type = ['budget_max','min_area','preferred_floor'].includes(key) ? 'number' : 'text'; input.required = true; if (input.type === 'number') {input.min = key === 'min_area' ? '0.1' : '1'; input.step = key === 'min_area' ? '0.1' : '1';} else input.maxLength = 500; input.value = value === undefined ? '' : value; }
  input.dataset.key = key; return input;
}
function parseInput(key,input) {
  if(input.tagName === 'SELECT') return JSON.parse(input.value);
  if(['budget_max','min_area','preferred_floor'].includes(key)) return Number(input.value);
  return input.value.trim();
}
function renderEditor(target, rows, uid) {
  target.replaceChildren(); const table = el('table',undefined,'fact-table'); const head = el('tr'); for(const text of ['Пожелание','Значение','Источник','Изменено','Действия']) head.append(el('th',text)); const thead = el('thead'); thead.append(head); table.append(thead); const tbody = el('tbody');

  for (const fact of rows) {
    const row = el('tr'); row.append(el('td',labels[fact.key]),el('td',formatted(fact.key,fact.value)),el('td',({chat:'Из чата',manual:'Вручную',admin:'Администратор'})[fact.source]),el('td',new Date(fact.updated_at + 'Z').toLocaleString('ru-RU')));
    const actions = el('td'); const edit = el('button','Изменить'); const remove = el('button','Удалить','danger');
    edit.addEventListener('click',() => {select.value = fact.key; replaceValue(fact.value); input.focus();});
    remove.addEventListener('click',async () => {if(!confirm('Удалить пожелание «' + labels[fact.key] + '»?')) return; try { await api((uid ? '/admin/users/' + uid : '') + '/facts/' + fact.key,'DELETE'); await afterEdit(); } catch(e) {toast(e.message);} }); actions.append(edit,remove); row.append(actions); tbody.append(row);
  }
  table.append(tbody); target.append(table); if(!rows.length) target.append(el('p','Сохранённых пожеланий пока нет.','muted'));
  const form = el('form',undefined,'editor-form'); const keyLabel = el('label','Пожелание'); const select = el('select'); for(const [key,label] of Object.entries(labels)) {const option = el('option',label); option.value = key; select.append(option);} keyLabel.append(select);
  const valueLabel = el('label','Значение'); let input = factInput(select.value); valueLabel.append(input);
  function replaceValue(value) {input.remove(); input = factInput(select.value,value); valueLabel.append(input);}
  select.addEventListener('change',() => {const existing = rows.find(f => f.key === select.value); replaceValue(existing?.value);});
  const save = el('button','Сохранить пожелание','primary'); save.type = 'submit'; form.append(keyLabel,valueLabel,save);
  async function afterEdit() { $('used-facts').hidden = true; $('memory-indicator').hidden = true; if(uid) await loadAdminDetail(uid); else {await refreshFacts(); renderEditor(target,facts);} toast('Память сохранена'); }
  form.addEventListener('submit',async event => {event.preventDefault(); save.disabled = true; try {await api((uid ? '/admin/users/' + uid : '') + '/facts/' + select.value,'PUT',{value:parseInput(select.value,input)}); await afterEdit();} catch(e) {toast(e.message);} finally {save.disabled = false;} });
  target.append(form,el('p','Числа вводятся без пробелов: бюджет — в рублях, площадь — в м². Интересующая квартира — ID из каталога, например B-705.','editor-note'));
}
async function loadAdmin() {
  const users = await api('/admin/users'); const target = $('admin-users'); const previous = target.value; target.replaceChildren(); const placeholder = el('option','Выберите пользователя'); placeholder.value = ''; target.append(placeholder);
  for (const u of users) {const option = el('option',u.display_name + ' · ' + u.username + ' · ' + u.role); option.value = u.id; target.append(option);} target.value = previous; if(previous) await loadAdminDetail(previous);
}
$('admin-users').addEventListener('change', async () => {try { if($('admin-users').value) await loadAdminDetail($('admin-users').value); else $('admin-detail').replaceChildren(); } catch(e) {toast(e.message);} });
async function loadAdminDetail(uid) {
  const data = await api('/admin/users/' + uid); const target = $('admin-detail'); target.replaceChildren(); target.append(el('h3','Память: ' + data.user.display_name)); const editor = el('div'); target.append(editor); renderEditor(editor,data.facts,uid); target.append(el('h3','История диалогов'));
  if(!data.conversations.length) target.append(el('p','Диалогов пока нет.','muted'));
  for (const conv of data.conversations) { const details = el('details',undefined,'admin-dialog'); details.append(el('summary','#' + conv.id + ' · ' + conv.title)); for(const m of conv.messages) {const p = el('div',undefined,'admin-message'); p.append(el('strong',m.role === 'user' ? data.user.display_name : 'AI-менеджер'),document.createTextNode(m.content)); details.append(p);} target.append(details); }
}
start();
