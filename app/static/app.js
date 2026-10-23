'use strict';

const $ = (selector) => document.querySelector(selector);
const kinds = ['noul', 'choice', 'score'];
const questionIds = {noul: 'approve', choice: 'route', score: 'risk'};
const storageKey = 'decision-workspace.question-sets.v1';
let limits = {state: 20000, instructions: 2000, criteria: 2000, key: 64, rows: 20};
let library = [];
let storageHealthy = true;
let busy = false;
let hasResults = false;

function icons() {
  if (window.lucide) window.lucide.createIcons({attrs: {'stroke-width': 1.7}});
}

function notice(message = '', success = false) {
  $('#notice').textContent = message;
  $('#notice').hidden = !message;
  $('#notice').classList.toggle('success', success);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function updateRows(kind) {
  const rows = [...$(`#${kind}-rows`).children];
  rows.forEach((row, index) => {
    if (kind === 'score') row.querySelector('.level-number').textContent = index;
    row.querySelectorAll('input').forEach((input) => {
      const label = input.dataset.field === 'key' ? 'キー' : kind === 'score' ? '採点基準' : '説明';
      input.setAttribute('aria-label', `${kind === 'score' ? 'Score' : 'Choice'} ${index + 1} ${label}`);
    });
    const remove = row.querySelector('.remove-row');
    remove.disabled = rows.length <= 1;
    remove.setAttribute('aria-label', `${kind === 'score' ? '採点基準' : '選択肢'} ${index + 1} を削除`);
  });
  $(`#add-${kind}`).disabled = rows.length >= limits.rows;
}

function addRow(kind, value, focus = false) {
  const container = $(`#${kind}-rows`);
  if (container.children.length >= limits.rows) return;
  const row = $(`#${kind}-row-template`).content.firstElementChild.cloneNode(true);
  row.querySelectorAll('input').forEach((input) => {
    input.value = kind === 'score' ? value : value[input.dataset.field];
  });
  row.querySelector('.remove-row').addEventListener('click', () => {
    row.remove();
    updateRows(kind);
    invalidateResults();
    $(`#add-${kind}`).focus();
  });
  container.append(row);
  updateRows(kind);
  icons();
  if (focus) row.querySelector('input').focus();
}

function capture() {
  const values = {state: $('#state').value};
  for (const kind of kinds) {
    values[kind] = {enabled: $(`#${kind}-enabled`).checked, instructions: $(`#${kind}-instructions`).value};
  }
  values.choice.criteria = [...$('#choice-rows').children].map((row) => ({
    key: row.querySelector('[data-field="key"]').value,
    description: row.querySelector('[data-field="description"]').value,
  }));
  values.score.criteria = [...document.querySelectorAll('#score-rows [data-field="criterion"]')].map((input) => input.value);
  return values;
}

function refreshEnabled() {
  for (const kind of kinds) $(`#${kind}-fields`).disabled = !$(`#${kind}-enabled`).checked;
  $('#state-count').textContent = `${$('#state').value.length.toLocaleString()} / ${limits.state.toLocaleString()}`;
}

function clearResults(message = '未実行') {
  for (const kind of kinds) {
    const result = $(`#${kind}-result`);
    result.replaceChildren(element('p', 'result-label', 'RESULT'),
      element('p', 'empty', $(`#${kind}-enabled`).checked ? message : '無効'));
  }
  $('#raw-response').hidden = true;
  $('#raw-response').open = false;
  $('#raw-json').textContent = '';
  $('#usage').textContent = '—';
  hasResults = false;
}

function invalidateResults() {
  refreshEnabled();
  if (hasResults) {
    clearResults();
    $('#status').textContent = '準備完了';
  }
}

function restore(values) {
  $('#state').value = values.state;
  for (const kind of kinds) {
    $(`#${kind}-enabled`).checked = values[kind].enabled;
    $(`#${kind}-instructions`).value = values[kind].instructions;
  }
  for (const kind of ['choice', 'score']) {
    $(`#${kind}-rows`).replaceChildren();
    const fallback = kind === 'choice' ? {key: '', description: ''} : '';
    const rows = values[kind].criteria.length ? values[kind].criteria : [fallback];
    rows.forEach((value) => addRow(kind, value));
  }
  refreshEnabled();
  clearResults();
  $('#status').textContent = '準備完了';
}

function isDraft(value) {
  const text = (item, max) => typeof item === 'string' && item.length <= max;
  if (!value || !text(value.state, limits.state)) return false;
  if (!kinds.every((kind) => value[kind] && typeof value[kind].enabled === 'boolean'
      && text(value[kind].instructions, limits.instructions))) return false;
  if (!Array.isArray(value.choice.criteria) || value.choice.criteria.length > limits.rows) return false;
  if (!value.choice.criteria.every((item) => item && text(item.key, limits.key)
      && text(item.description, limits.criteria))) return false;
  return Array.isArray(value.score.criteria) && value.score.criteria.length <= limits.rows
    && value.score.criteria.every((item) => text(item, limits.criteria));
}

function parseLibrary(raw) {
  if (raw === null) return [];
  const data = JSON.parse(raw);
  if (data?.schemaVersion !== 1 || !Array.isArray(data.sets) || data.sets.length > 50) throw new Error('invalid');
  const ids = new Set();
  const names = new Set();
  for (const item of data.sets) {
    if (!item || typeof item.id !== 'string' || item.id.length > 80 || !item.id
        || typeof item.name !== 'string' || !item.name.trim() || item.name.length > 80
        || ids.has(item.id) || names.has(item.name) || !isDraft(item.values)) throw new Error('invalid');
    ids.add(item.id);
    names.add(item.name);
  }
  return data.sets;
}

function readLibrary() {
  return parseLibrary(localStorage.getItem(storageKey));
}

async function initializeLibrary() {
  $('#library-controls').disabled = true;
  try {
    if (localStorage.getItem(storageKey) === null) {
      const response = await fetch('/static/default-questions.json');
      if (!response.ok) throw new Error('samples');
      const raw = JSON.stringify(await response.json());
      parseLibrary(raw);
      if (localStorage.getItem(storageKey) === null) localStorage.setItem(storageKey, raw);
    }
  } catch {
    notice('初期サンプルを保存できませんでした。接続・ブラウザーの保存設定を確認してください。質問の実行は利用できます。');
  } finally {
    loadLibrary();
    $('#library-controls').disabled = busy;
  }
}

function renderLibrary(selected = $('#saved-set').value) {
  $('#saved-set').replaceChildren(new Option('未選択', ''));
  library.forEach((item) => $('#saved-set').add(new Option(item.name, item.id)));
  $('#saved-set').value = library.some((item) => item.id === selected) ? selected : '';
  $('#restore').disabled = !$('#saved-set').value || !storageHealthy;
  $('#delete').disabled = !$('#saved-set').value || !storageHealthy;
  $('#save').disabled = !storageHealthy;
}

function loadLibrary() {
  try {
    library = readLibrary();
    storageHealthy = true;
  } catch {
    storageHealthy = false;
    library = [];
    notice('保存データを読み込めません。ブラウザーの保存設定・データを確認してください。質問の実行は利用できます。');
  }
  renderLibrary();
}

function writeLibrary(next, selected = '') {
  try {
    localStorage.setItem(storageKey, JSON.stringify({schemaVersion: 1, sets: next}));
    library = next;
    renderLibrary(selected);
    return true;
  } catch {
    notice('保存できません。ブラウザーの保存容量・設定を確認してください。');
    return false;
  }
}

function saveDraft() {
  const name = $('#set-name').value.trim();
  if (!name) { notice('保存名を入力してください。'); $('#set-name').focus(); return; }
  try {
    const current = readLibrary();
    const existing = current.find((item) => item.name === name);
    if (existing && !window.confirm(`「${name}」を上書きしますか？`)) return;
    if (!existing && current.length >= 50) { notice('保存件数の上限は50件です。不要な質問を削除してください。'); return; }
    const item = {id: existing?.id || `q-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      name, values: capture(), updatedAt: new Date().toISOString()};
    if (!isDraft(item.values)) throw new Error('invalid');
    const next = existing ? current.map((entry) => entry.id === existing.id ? item : entry) : [...current, item];
    if (writeLibrary(next, item.id)) notice('質問を保存しました。', true);
  } catch {
    notice('保存データを確認できないため、上書きしませんでした。ブラウザーの保存設定・データを確認してください。');
  }
}

function requestPayload(values) {
  if (!values.state.trim()) throw new Error('質問・コンテキストを入力してください。');
  if (!kinds.some((kind) => values[kind].enabled)) throw new Error('少なくとも1つの質問形式を有効にしてください。');
  const payload = structuredClone(values);
  for (const kind of kinds) {
    if (!payload[kind].enabled) {
      payload[kind].instructions = '';
      if (kind !== 'noul') payload[kind].criteria = [];
    }
  }
  const keys = payload.choice.criteria.map((item) => item.key.trim());
  if (new Set(keys).size !== keys.length) throw new Error('Choice のキーは重複できません。');
  return payload;
}

const percent = (value) => `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
const number = (value) => Number(value.toFixed(4)).toLocaleString('ja-JP');

function probabilityRow(label, value) {
  const row = element('div', 'probability');
  const meter = element('meter');
  meter.min = 0;
  meter.max = 1;
  meter.value = value;
  meter.setAttribute('aria-label', label);
  row.append(element('span', '', label), meter, element('span', '', percent(value)));
  return row;
}

function showAnswer(kind, answer, snapshot) {
  const target = $(`#${kind}-result`);
  target.replaceChildren(element('p', 'result-label', 'RESULT'));
  const label = kind === 'noul' ? '肯定確率' : kind === 'choice' ? '選択結果' : '期待スコア';
  const value = kind === 'noul' ? percent(answer.noul) : kind === 'choice' ? answer.choice : number(answer.score);
  target.append(element('p', 'metric-label', label), element('p', 'metric-value', value));
  if (kind === 'choice') {
    const selected = snapshot.choice.criteria.find((item) => item.key.trim() === answer.choice);
    if (selected) target.append(element('p', 'answer-description', selected.description));
  }
  if (answer.confidence !== undefined) target.append(element('p', 'confidence', `信頼度 ${percent(answer.confidence)}`));
  for (const [key, value] of Object.entries(answer.probabilities || {})) {
    const description = kind === 'score' ? `${key} · ${typeof answer.legend[key] === 'string' ? answer.legend[key] : JSON.stringify(answer.legend[key])}`
      : snapshot.choice.criteria.find((item) => item.key.trim() === key)?.description || key;
    target.append(probabilityRow(description, value));
  }
}

function showResults(data, snapshot) {
  for (const kind of kinds) if (snapshot[kind].enabled) showAnswer(kind, data.answers[questionIds[kind]], snapshot);
  const tokens = data.input_tokens === null ? '入力トークン数 未取得' : `入力 ${data.input_tokens.toLocaleString()} tokens`;
  const cost = data.estimated_cost_usd === null ? '推定費用 未設定' : `推定費用 $${data.estimated_cost_usd.toFixed(6)} USD`;
  $('#usage').textContent = `${tokens} · ${cost}`;
  $('#raw-json').textContent = JSON.stringify(data, null, 2);
  $('#raw-response').hidden = false;
  hasResults = true;
}

function setBusy(value) {
  busy = value;
  $('#workspace').disabled = value;
  $('#library-controls').disabled = value;
  $('#run').disabled = value;
  $('#decision-form').setAttribute('aria-busy', String(value));
}

async function submit(event) {
  event.preventDefault();
  if (busy) return;
  notice();
  let snapshot;
  let payload;
  try { snapshot = capture(); payload = requestPayload(snapshot); }
  catch (error) { notice(error.message); return; }
  clearResults('処理中…');
  setBusy(true);
  $('#status').textContent = '実行中';
  try {
    const response = await fetch('/api/decision', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) {
      const fields = Array.isArray(data.fields) ? ` (${data.fields.join(', ')})` : '';
      throw new Error((typeof data.detail === 'string' ? data.detail : '実行に失敗しました。') + fields);
    }
    showResults(data, snapshot);
    $('#status').textContent = '完了';
  } catch (error) {
    clearResults('取得失敗');
    $('#status').textContent = '失敗';
    notice(error instanceof TypeError || error instanceof SyntaxError ? 'サーバーとの通信に失敗しました。接続を確認してください。' : error.message);
  } finally {
    setBusy(false);
    refreshEnabled();
  }
}

$('#decision-form').addEventListener('submit', submit);
$('#decision-form').addEventListener('input', invalidateResults);
$('#decision-form').addEventListener('change', () => { refreshEnabled(); if (!busy) clearResults(); });
$('#save').addEventListener('click', saveDraft);
$('#saved-set').addEventListener('change', () => renderLibrary());
$('#restore').addEventListener('click', () => {
  try {
    const item = readLibrary().find((item) => item.id === $('#saved-set').value);
    if (!item) { loadLibrary(); notice('保存した質問が見つかりません。'); return; }
    restore(item.values);
    $('#set-name').value = item.name;
    notice('質問を復元しました。', true);
  } catch { loadLibrary(); }
});
$('#delete').addEventListener('click', () => {
  try {
    const current = readLibrary();
    const item = current.find((item) => item.id === $('#saved-set').value);
    if (!item || !window.confirm(`「${item.name}」を削除しますか？`)) return;
    if (writeLibrary(current.filter((entry) => entry.id !== item.id))) notice('保存した質問を削除しました。', true);
  } catch { loadLibrary(); }
});
for (const kind of ['choice', 'score']) {
  $(`#add-${kind}`).addEventListener('click', () => {
    addRow(kind, kind === 'choice' ? {key: '', description: ''} : '', true);
    invalidateResults();
  });
}
window.addEventListener('storage', (event) => { if (event.key === storageKey) loadLibrary(); });
addRow('choice', {key: 'manual', description: '手動審査'});
addRow('choice', {key: 'auto', description: '自動承認'});
['低リスク', '中リスク', '高リスク'].forEach((value) => addRow('score', value));
refreshEnabled();
initializeLibrary();
icons();
fetch('/api/config').then((response) => response.ok ? response.json() : Promise.reject()).then((data) => {
  limits = data.limits;
  $('#state').maxLength = limits.state;
  for (const kind of kinds) $(`#${kind}-instructions`).maxLength = limits.instructions;
  refreshEnabled();
}).catch(() => notice('入力制限の設定を取得できません。ページを再読み込みしてください。'));