(function(root){
'use strict';

const TEXT = Object.freeze({
  statuses: {
    sealed: {label: 'Decision sealed', icon: '🔒'},
    insufficient_reviews: {label: 'Insufficient reviews', icon: '?'},
    decided: {label: 'Decided', icon: '✓'},
    undecided: {label: 'Undecided', icon: '?'},
    coverage_sensitive: {label: 'Coverage sensitive', icon: '⚠'}
  },
  headers: ['Model', 'Accepted rate [bounds]', 'Major or worse rate',
    'Latency (dominant profile)', 'Seconds per accepted'],
  unseal: 'Unseal decision',
  unavailable: 'N/A',
  remaining: n => `${n} cells remain.`,
  headline: (status, detail) => `${status.icon} ${status.label}: ${detail}`,
  coverage: c => `Decision reviewed ${c.reviewed} / ${c.decision_cells}; missing cells: ${c.missing.length}; generation errors: ${c.generation_errors}.`,
  model: m => `${m.label} (${m.physical_model_id})`,
  percent: n => `${n.toFixed(2)}%`,
  bounds: (rate, lo, hi) => `${rate} [${lo}, ${hi}]`,
  seconds: n => `${n} s`,
  latency: (seconds, profile, n) => `p50 ${seconds}; profile ${profile}; n=${n}`,
  qualityPending: 'Quality: pending review completion.',
  performancePending: 'Performance: pending review completion.',
  qualityUndecided: 'Quality: undecided.',
  performanceNone: 'Performance: none.',
  qualityWinner: name => `Quality winner: ${name}.`,
  performanceWinner: name => `Performance winner: ${name}.`,
  qualityReason: reason => `Quality reason: ${reason}`,
  performanceReason: reason => `Performance reason: ${reason}`,
  comparison: (c, accepted, major) => `Comparison ${c.a} - ${c.b} (n=${c.n_images} images): accepted delta CI95 ${accepted}; major delta CI95 ${major}.`,
  interval: (lo, hi) => `[${lo}, ${hi}]`,
  power: (p, width) => `Power ${p.a} - ${p.b}: CI half-width ${width}; images needed ${p.images_needed}.`,
  summaryStatus: label => `Status: ${label}`
});
const COLUMNS = ['model', 'accepted_rate', 'major_or_worse_rate', 'latency', 'seconds_per_accepted'];

function number(value) {
  return Number.isFinite(value) ? value.toFixed(6) : TEXT.unavailable;
}
function percent(value) {
  return Number.isFinite(value) ? TEXT.percent(value * 100) : TEXT.unavailable;
}
function seconds(value) {
  return Number.isFinite(value) ? TEXT.seconds(number(value)) : TEXT.unavailable;
}
function boundedRate(model) {
  const bounds = model.accepted_rate_bounds;
  return bounds ? TEXT.bounds(percent(model.accepted_rate), percent(bounds[0]), percent(bounds[1]))
    : TEXT.unavailable;
}
function modelRows(result) {
  return result.models.map(model => ({
    model: TEXT.model(model),
    accepted_rate: boundedRate(model),
    major_or_worse_rate: percent(model.major_or_worse_rate),
    latency: model.latency ? TEXT.latency(seconds(model.latency.p50_seconds),
      model.latency.profile_sha256.slice(0, 12), model.latency.n) : TEXT.unavailable,
    seconds_per_accepted: seconds(model.seconds_per_accepted)
  }));
}
function modelName(result, id) {
  const model = result.models.find(candidate => candidate.physical_model_id === id);
  return model ? TEXT.model(model) : id;
}
function verdicts(result) {
  const quality = result.quality;
  const performance = result.performance;
  return [
    !quality ? TEXT.qualityPending : quality.winner
      ? TEXT.qualityWinner(modelName(result, quality.winner)) : TEXT.qualityUndecided,
    !performance ? TEXT.performancePending : performance.winner
      ? TEXT.performanceWinner(modelName(result, performance.winner)) : TEXT.performanceNone
  ];
}
function details(result) {
  const notes = [];
  if (result.quality) notes.push(TEXT.qualityReason(result.quality.reason));
  if (result.performance) notes.push(TEXT.performanceReason(result.performance.reason));
  for (const comparison of result.comparisons || []) {
    notes.push(TEXT.comparison(comparison,
      TEXT.interval(...comparison.accepted_delta_ci95.map(number)),
      TEXT.interval(...comparison.major_delta_ci95.map(number))));
  }
  for (const power of result.power || []) notes.push(TEXT.power(power, number(power.ci_half_width)));
  return notes.concat(result.notes);
}

function view(result, unsealed) {
  const sealed = result.status === 'insufficient_reviews' || !unsealed;
  // Even a completed verdict's status and free-form notes can reveal the answer.
  const status = sealed ? 'sealed' : result.status;
  return {
    sealed,
    status,
    headline: TEXT.headline(TEXT.statuses[status], sealed
      ? TEXT.remaining(result.coverage.pending_keys.length) : verdicts(result).join(' ')),
    coverage_line: TEXT.coverage(result.coverage),
    rows: sealed ? [] : modelRows(result),
    notes: sealed ? [] : details(result)
  };
}

function render(host, opts) {
  const result = root.OperatorMetrics.decide(opts.manifest, opts.state, opts.perf, opts.rule, opts.contract);
  const panel = view(result, opts.unsealed);
  const document = host.ownerDocument;
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    return node;
  }
  host.textContent = '';
  const summary = element('summary', panel.headline);
  const status = element('span', panel.coverage_line);
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  // The visible status includes an icon and text inside the single live region.
  status.textContent = panel.headline + ' ' + panel.coverage_line;
  summary.textContent = '';
  summary.appendChild(status);
  host.appendChild(summary);
  if (panel.rows.length) {
    const table = element('table');
    const head = element('thead');
    const header = element('tr');
    for (const label of TEXT.headers) {
      const cell = element('th', label);
      cell.setAttribute('scope', 'col');
      header.appendChild(cell);
    }
    head.appendChild(header);
    table.appendChild(head);
    const body = element('tbody');
    for (const row of panel.rows) {
      const line = element('tr');
      for (const key of COLUMNS) line.appendChild(element('td', row[key]));
      body.appendChild(line);
    }
    table.appendChild(body);
    host.appendChild(table);
  }
  if (panel.notes.length) {
    const notes = element('ul');
    for (const note of panel.notes) notes.appendChild(element('li', note));
    host.appendChild(notes);
  }
  if (panel.sealed && result.status !== 'insufficient_reviews' && !result.coverage.pending_keys.length) {
    const button = element('button', TEXT.unseal);
    button.setAttribute('type', 'button');
    button.addEventListener('click', () => {
      if (typeof opts.onUnseal === 'function') opts.onUnseal();
    });
    host.appendChild(button);
  }
}

function asciiSummary(result) {
  const rows = modelRows(result).map(row => COLUMNS.map(key => row[key]));
  const widths = TEXT.headers.map((label, index) =>
    Math.max(label.length, ...rows.map(row => row[index].length)));
  const line = row => '| ' + row.map((cell, index) => cell.padEnd(widths[index])).join(' | ') + ' |';
  const separator = '+' + widths.map(width => '-'.repeat(width + 2)).join('+') + '+';
  return [TEXT.summaryStatus(TEXT.statuses[result.status].label), TEXT.coverage(result.coverage), '',
    separator, line(TEXT.headers), separator, ...rows.map(line), separator, '',
    ...verdicts(result), ...details(result), ''].join('\n');
}

const api={view,render,asciiSummary};
if(typeof module==='object'&&module.exports)module.exports=api;else root.OperatorDecision=api;
})(typeof globalThis!=='undefined'?globalThis:this);
