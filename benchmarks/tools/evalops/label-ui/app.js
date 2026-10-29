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
  if (!drafts.has(id)) { const saved = session.answers[id]; drafts.set(id, {label: saved?.label || '', note: saved?.note || '',
    disposition: saved?.disposition || '', affected_action: saved?.affected_action || '', blocking_reason: saved?.blocking_reason || '',
    provenance: {kind: saved?.provenance?.kind === 'legacy_unknown' ? '' : saved?.provenance?.kind || '',
      exposure: saved?.provenance?.exposure || '', attestation_ref: saved?.provenance?.attestation_ref || '',
      original_ref: saved?.provenance?.original_ref || '', protocol_version: saved?.provenance?.protocol_version || 'evalops-annotation-v2'},
    dirty: false, retry: null}); }
  return drafts.get(id);
}
function busy(value) {
  pending = value; $('fields').disabled = value; $('previous').disabled = value || index === 0;
  $('skip').disabled = value; $('save').disabled = value || !draft().label;
  $('save').textContent = value ? 'Saving judgment…' : 'Save & Next';
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
  $('note').value = d.note;
  for (const [id, value] of [['disposition', d.disposition], ['affected-action', d.affected_action], ['blocking-reason', d.blocking_reason],
    ['provenance-kind', d.provenance.kind], ['exposure', d.provenance.exposure], ['attestation-ref', d.provenance.attestation_ref],
    ['original-ref', d.provenance.original_ref], ['protocol-version', d.provenance.protocol_version]]) $(id).value = value;
  const saved = session.answers[item.presentation_id];
  $('annotation-versions').textContent = `Rubric: ${session.packet.rubric_version}. Protocol identifies the instructions used for this annotation.`;
  $('annotation-history').textContent = saved ? `Saved source: ${saved.provenance.kind}; exposure: ${saved.provenance.exposure}. Original event: ${saved.original_event_id}. Supersedes: ${saved.supersedes || 'none'}.` : 'New annotation. No provenance or exposure is selected.';
  $('decision-error').hidden = true; requirements(); busy(false);
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
function requirements() {
  $('affected-action').required = ['blocks', 'nonblocking'].includes($('disposition').value);
  $('blocking-reason').required = $('disposition').value === 'blocks';
  $('attestation-ref').required = $('provenance-kind').value === 'independent_expert';
}
function annotation(d) {
  return {label: d.label, note: d.note, disposition: d.disposition, affected_action: d.affected_action.trim() || null,
    blocking_reason: d.blocking_reason.trim() || null, provenance: {...d.provenance,
      attestation_ref: d.provenance.attestation_ref.trim() || null, original_ref: d.provenance.original_ref.trim() || null}};
}
function sameAnnotation(d, saved) {
  return ['label', 'note', 'disposition', 'affected_action', 'blocking_reason'].every(key => d[key] === saved[key]) &&
    Object.keys(d.provenance).every(key => d.provenance[key] === saved.provenance[key]);
}
function decisionError(message) {
  $('decision-error').textContent = message; $('decision-error').hidden = false; $('decision-error').focus(); status(message, true);
}
function changed() {
  const d = draft(); d.label = document.querySelector('[name=label]:checked')?.value || ''; d.note = $('note').value; d.dirty = true;
  d.disposition = $('disposition').value; d.affected_action = $('affected-action').value; d.blocking_reason = $('blocking-reason').value;
  d.provenance = {kind: $('provenance-kind').value, exposure: $('exposure').value, attestation_ref: $('attestation-ref').value,
    original_ref: $('original-ref').value, protocol_version: $('protocol-version').value};
  requirements(); $('decision-error').hidden = true;
  // Keep a failed request's ID and payload until it is acknowledged. Edits are
  // allowed after failure; resolve the prior request before submitting edits.
  busy(false);
}
$('fields').addEventListener('input', changed);
$('decision-form').addEventListener('submit', async event => {
  event.preventDefault(); if (pending || !draft().label) return;
  const item = current(), d = draft();
  if (!d.retry) {
    if (!$('decision-form').reportValidity()) return;
    if (!d.provenance.protocol_version.trim() ||
        (['blocks', 'nonblocking'].includes(d.disposition) && !d.affected_action.trim()) ||
        (d.disposition === 'blocks' && !d.blocking_reason.trim()) ||
        (d.provenance.kind === 'independent_expert' && !d.provenance.attestation_ref.trim())) return decisionError('Complete the required fields with nonempty text.');
    if (d.disposition === 'blocks' && d.label !== 'defect') return decisionError('Blocking requires Defect validity. Choose a consistent disposition.');
    if (['blind_human', 'independent_expert'].includes(d.provenance.kind) && d.provenance.exposure !== 'unexposed') return decisionError('Blind or independent expert requires an explicit unexposed attestation. Use assisted, post-review or unknown when appropriate.');
    if (['user_assisted', 'post_review'].includes(d.provenance.kind) && d.provenance.exposure === 'unexposed') return decisionError('Assisted or post-review annotations require exposed or unknown exposure.');
    d.retry = {presentation_id: item.presentation_id, ...annotation(d), client_id: crypto.randomUUID()};
  }
  busy(true); status('Saving your judgment…');
  try {
    const saved = await api('/api/decision', d.retry); session.answers[item.presentation_id] = saved;
    d.retry = null;
    if (!sameAnnotation(annotation(d), saved)) { status('Earlier save confirmed. Your edited draft is retained; save again to record the correction.'); busy(false); return; }
    d.dirty = false; index++; render(true); status('Judgment saved durably.');
  } catch (error) { busy(false); decisionError(`${error.message} Draft retained. Save again to retry the same request.`); }
});
$('previous').addEventListener('click', () => { if (!pending && index > 0) { index--; render(true); status('Drafts are preserved while navigating.'); } });
$('skip').addEventListener('click', () => { if (!pending) { index++; render(true); status('Moved on without saving. Any draft is retained in this tab.'); } });
$('review-unanswered').addEventListener('click', () => { index = session.packet.items.findIndex(i => !session.answers[i.presentation_id]); if (index < 0) index = 0; render(true); });
$('review-all').addEventListener('click', () => { index = 0; render(true); });
window.addEventListener('beforeunload', event => { if (pending || [...drafts.values()].some(d => d.dirty || d.retry)) { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('offline', () => status('Connection unavailable. Keep this tab open; your draft is retained. Retry saving when the local tool is reachable.', true));
window.addEventListener('online', () => status('Connection restored. Retry your last save to confirm it.'));
load();
