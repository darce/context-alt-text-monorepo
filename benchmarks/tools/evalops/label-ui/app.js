'use strict';
const $ = id => document.getElementById(id);
let session, index = 0, pending = false;
const drafts = new Map();
function status(message, error = false) { $('status').textContent = message; $('status').className = error ? 'error' : ''; }
function screen(id) { for (const name of ['session', 'finding', 'complete']) $(name).hidden = name !== id; history.replaceState(null, '', '#' + id); }
async function api(path, payload) {
  const options = payload === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf_token}, body: JSON.stringify(payload)};
  const response = await fetch(path, {...options, cache: 'no-store'});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed. Your draft is retained.');
  return result;
}
function current() { return session.packet.items[index]; }
function draft() {
  const id = current().presentation_id;
  if (!drafts.has(id)) { const saved = session.answers[id]; drafts.set(id, {label: saved?.label || '', note: saved?.note || '', dirty: false, retry: null}); }
  return drafts.get(id);
}
function busy(value) {
  pending = value; $('fields').disabled = value; $('previous').disabled = value || index === 0;
  $('skip').disabled = value; $('save').disabled = value || !draft().label;
  $('save').textContent = value ? 'Saving judgment…' : 'Save judgment and continue';
}
function render(focus = false) {
  if (index >= session.packet.items.length) {
    screen('complete'); const total = session.packet.items.length, answered = Object.keys(session.answers).length;
    $('summary').textContent = `${answered} of ${total} findings answered · ${total - answered} unanswered. You can return to any item and correct a judgment.`;
    $('review-unanswered').disabled = answered === total;
    if (focus) $('complete-title').focus();
    return;
  }
  screen('finding'); const item = current(), d = draft();
  $('position').textContent = `Item ${index + 1} / ${session.packet.items.length}`;
  $('progress').textContent = `${Object.keys(session.answers).length} saved / ${session.packet.items.length}`;
  $('claim').textContent = item.description;
  $('location').textContent = (item.file_path || 'Source path not supplied') + (item.line_start ? ` · line ${item.line_start}${item.line_end ? '–' + item.line_end : ''}` : '');
  $('missing').hidden = item.context_status !== 'unavailable';
  $('source').hidden = item.context_status === 'unavailable'; $('code').textContent = item.source_context || '';
  $('context-note').textContent = item.context_note || (item.context_status === 'verified_recorded_commit' ? 'Context verified against the recorded commit.' : '');
  for (const radio of document.querySelectorAll('[name=label]')) radio.checked = radio.value === d.label;
  $('note').value = d.note; busy(false);
  if (focus) $('claim').focus();
}
async function load() {
  $('retry').hidden = true; status('Loading your session…');
  try {
    session = await api('/api/session');
    if (!session.packet.items.length) { status('This packet has no findings. Ask the coordinator for a nonempty public packet.', true); return; }
    $('role').textContent = session.role; $('rubric').textContent = session.packet.rubric;
    if (!session.annotator) { screen('session'); status('Enter your name to begin. No label is selected for you.'); $('annotator').focus(); }
    else { const unanswered = session.packet.items.findIndex(i => !session.answers[i.presentation_id]); index = unanswered < 0 ? session.packet.items.length : unanswered; render(); status(`Resumed as ${session.annotator}. Saved answers are retained.`); }
  } catch (error) { status(`Unable to load the local session. ${error.message}`, true); $('retry').hidden = false; }
}
$('retry').addEventListener('click', load);
$('start-form').addEventListener('submit', async event => {
  event.preventDefault(); const name = $('annotator').value.trim(); if (!name) return status('Enter a nonempty name.', true);
  $('start').disabled = true;
  try { session = await api('/api/session', {annotator: name}); render(true); status(`Reviewing as ${session.annotator}.`); }
  catch (error) { status(error.message, true); }
  finally { $('start').disabled = false; }
});
function changed() {
  const d = draft(); d.label = document.querySelector('[name=label]:checked')?.value || ''; d.note = $('note').value; d.dirty = true;
  // Keep a failed request's ID and payload until it is acknowledged. Edits are
  // allowed after failure; resolve the prior request before submitting edits.
  busy(false);
}
$('fields').addEventListener('input', changed);
$('decision-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pending || !draft().label) return;
  const item = current(), d = draft();
  if (!d.retry) d.retry = {presentation_id: item.presentation_id, label: d.label, note: d.note, client_id: crypto.randomUUID()};
  busy(true); status('Saving your judgment…');
  try {
    const saved = await api('/api/decision', d.retry); session.answers[item.presentation_id] = saved;
    d.retry = null;
    if (d.label !== saved.label || d.note !== saved.note) { status('Earlier save confirmed. Your edited draft is retained; save again to record the correction.'); busy(false); return; }
    d.dirty = false; index++; render(true); status('Judgment saved durably.');
  } catch (error) { busy(false); status(`${error.message} Draft retained. Save again to retry the same request.`, true); }
});
$('previous').addEventListener('click', () => { if (!pending && index > 0) { index--; render(true); status('Drafts are preserved while navigating.'); } });
$('skip').addEventListener('click', () => { if (!pending) { index++; render(true); status('Moved on without saving. Any draft is retained in this tab.'); } });
$('review-unanswered').addEventListener('click', () => { index = session.packet.items.findIndex(i => !session.answers[i.presentation_id]); if (index < 0) index = 0; render(true); });
$('review-all').addEventListener('click', () => { index = 0; render(true); });
window.addEventListener('beforeunload', event => { if (pending || [...drafts.values()].some(d => d.dirty || d.retry)) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('offline', () => status('Connection unavailable. Keep this tab open; your draft is retained. Retry saving when the local tool is reachable.', true));
window.addEventListener('online', () => status('Connection restored. Retry your last save to confirm it.'));
load();
