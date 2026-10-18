"""Generate a private single-file HTML queue for FIR-OCC face labelling (S7).

The operator labels occlusion from pixels. Captions and detector output never
appear in the page. Blind repeats (consistency checks) and known-answer gold
items are inserted under opaque ids; their roles live only in the hidden block
that the page returns with the export. Output must resolve under
``benchmarks/private/`` (``require_private_output_path``), or the CLI refuses.

Union-delta mode (``--union-delta``) shows only proposal boxes from detectors
that are unmatched to ground truth, shuffled and source-blind.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "prototype-description-service"))

from scripts.eval_harness import fir_occ_labels as occ  # noqa: E402
from scripts.eval_harness import firbench_contract as fc  # noqa: E402
from scripts.eval_harness.gate_contract import RUBRIC_VERSION  # noqa: E402

PAGE_SCHEMA = "fir-occ-page/v1"
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}

# Canon v0.26.2: the accepted L1 supplies [INT-25] Map the handoffs
# (Microinteractions, ch. 6). Draw entry/preview/commit/cancel apply [INT-21]
# Specify interaction states (ch. 3) and [INT-23] Limit and mark modes (ch. 5).
# Bounds checks apply [FORM-11] Constrain before error (ch. 3); collection end
# applies [INT-24] Specify loop exits (ch. 5), all from Microinteractions.
_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>FIR-OCC label queue (private)</title>
<style>
body { font-family: system-ui, sans-serif; margin: 0; color: #1d1d1f; background: #fafafa; }
header, main { padding: 10px 16px; }
h1 { font-size: 1.1rem; margin: 0 0 6px; }
button, input { font: inherit; }
button { margin: 2px; padding: 6px 10px; border: 1px solid #6b6b70; border-radius: 4px; background: #fff; cursor: pointer; }
button[aria-pressed="true"] { background: #1d4ed8; color: #fff; border-color: #1d4ed8; }
:focus-visible { outline: 3px solid #f59e0b; outline-offset: 2px; }
.stage { position: relative; display: inline-block; max-width: 100%; }
.stage img { display: block; max-width: 100%; height: auto; user-select: none; }
.stage.drawing { cursor: crosshair; touch-action: none; }
.box.preview { border: 2px dashed #b45309; }
[hidden] { display: none !important; }
#draw-panel { border: 2px solid #b45309; padding: 8px; }
#draw-panel input { width: 5em; }
.box { position: absolute; border: 2px solid #0ea5e9; pointer-events: none; }
.box.added { border-color: #16a34a; }
.group { margin: 6px 0; }
.status { min-height: 1.4em; color: #374151; }
progress { width: 100%; max-width: 480px; }
</style>
</head>
<body>
<header>
<h1>FIR-OCC occlusion labels</h1>
<p><label>Annotator id <input id="annotator" type="text" autocomplete="off"></label>
<label>Observation reference (optional) <input id="observation" type="text" autocomplete="off"></label></p>
<p id="position" aria-live="polite"></p>
<progress id="progress" max="1" value="0"></progress>
</header>
<main>
<div class="stage" id="stage"><img id="image" alt="Item image"></div>
<button type="button" id="retry-image" hidden>Retry image</button>
<p id="item-state" aria-live="polite"></p>
<div id="draw-panel" hidden>
<p role="status">Drawing a box — enter pixel coordinates or drag on the image, then commit or cancel.</p>
<label>Box left <input id="box-left" type="number" min="0" step="any"></label>
<label>Box top <input id="box-top" type="number" min="0" step="any"></label>
<label>Box width <input id="box-width" type="number" min="2" step="any"></label>
<label>Box height <input id="box-height" type="number" min="2" step="any"></label>
<button type="button" data-act="commitbox" aria-keyshortcuts="Enter">Commit box (Enter)</button>
<button type="button" data-act="canceldraw" aria-keyshortcuts="Escape">Cancel draw (Esc)</button>
</div>
<div class="group" id="face-controls">
<button type="button" data-act="mask" data-key="m" aria-keyshortcuts="m">Mask (m)</button>
<button type="button" data-act="sunglasses" data-key="s" aria-keyshortcuts="s">Sunglasses (s)</button>
<button type="button" data-act="hand" data-key="h" aria-keyshortcuts="h">Hand (h)</button>
<button type="button" data-act="other_object" data-key="o" aria-keyshortcuts="o">Other object (o)</button>
<button type="button" data-act="mixed" data-key="x" aria-keyshortcuts="x">Mixed (x)</button>
<button type="button" data-act="none" data-key="n" aria-keyshortcuts="n">No occluder (n)</button>
<button type="button" data-act="cannot" data-key="?" aria-keyshortcuts="?">Cannot tell (?)</button>
</div>
<div class="group" id="region-controls">
<button type="button" data-act="region" data-region="left_eye" aria-pressed="true">Left eye</button>
<button type="button" data-act="region" data-region="right_eye" aria-pressed="false">Right eye</button>
<button type="button" data-act="region" data-region="nose" aria-pressed="false">Nose</button>
<button type="button" data-act="region" data-region="mouth" aria-pressed="false">Mouth</button>
<button type="button" data-act="visibility" data-key="v" aria-keyshortcuts="v">Cycle visibility (v)</button>
<button type="button" data-act="draw" data-key="a" aria-keyshortcuts="a" aria-pressed="false">Add missed face (a)</button>
<button type="button" data-act="unknown" data-key="u" aria-keyshortcuts="u">Unknown person (u)</button>
<button type="button" data-act="nextface" data-key="." aria-keyshortcuts=".">Next face (.)</button>
</div>
<div class="group" id="union-controls" hidden>
<button type="button" data-act="decide_face" data-key="f" aria-keyshortcuts="f" aria-pressed="false">Face (f)</button>
<button type="button" data-act="decide_not" data-key="n" aria-keyshortcuts="n" aria-pressed="false">Not a face (n)</button>
<button type="button" data-act="decide_cannot" data-key="?" aria-keyshortcuts="?" aria-pressed="false">Cannot tell (?)</button>
</div>
<div class="group">
<button type="button" data-nav data-act="skip" data-key="k" aria-keyshortcuts="k">Skip — recorded as nonresponse (k)</button>
<button type="button" data-nav data-act="undo" data-key="Escape" aria-keyshortcuts="Escape">Undo (Esc)</button>
<button type="button" data-nav data-act="next" data-key="Enter" aria-keyshortcuts="Enter">Next item (Enter)</button>
<button type="button" data-nav id="export">Export labels</button>
</div>
<p class="status" id="status" role="status"></p>
</main>
<script id="fir-occ-payload" type="application/json">__PAYLOAD__</script>
<script>
(function () {
  'use strict';
  var payload = JSON.parse(document.getElementById('fir-occ-payload').textContent);
  var items = payload.items;
  var faceMode = payload.mode === 'face';
  var VIS_CYCLE = ['visible', 'occluded', 'out_of_frame', 'uncertain'];
  var OCC_NAMES = {mask: 'mask', sunglasses: 'sunglasses', hand: 'hand', other_object: 'other_object', mixed: 'mixed'};
  var answers = {};
  var index = 0;
  var faces = [];
  var faceIndex = 0;
  var decision = null;
  var region = 'left_eye';
  var drawing = false;
  var history = [];
  var drawState = null;
  var preview = null;
  var pointerStart = null;
  var imageFailed = false;
  var complete = false;
  var drawPanel = document.getElementById('draw-panel');
  var coordinates = ['left', 'top', 'width', 'height'].map(function (name) {
    return document.getElementById('box-' + name);
  });
  var image = document.getElementById('image');
  var stage = document.getElementById('stage');
  var statusLine = document.getElementById('status');
  var faceControls = document.getElementById('face-controls');
  var unionControls = document.getElementById('union-controls');
  var regionControls = document.getElementById('region-controls');
  var drawButton = document.querySelector('[data-act="draw"]');
  if (!faceMode) {
    faceControls.hidden = true;
    regionControls.hidden = true;
    unionControls.hidden = false;
  }

  function say(message) { statusLine.textContent = message; }
  function blankVisibility() { return {left_eye: null, right_eye: null, nose: null, mouth: null}; }
  function freshFaces(item) {
    return item.boxes.map(function (box, number) {
      return {source: 'confirmed', face_key: 'c' + number, box: box.slice(), occluders: null,
        visibility: blankVisibility(), identity_status: 'unresolved'};
    });
  }
  function state() { return JSON.stringify({faces: faces, decision: decision, faceIndex: faceIndex, region: region}); }
  function snapshot() { history.push(state()); }
  function restore(value) {
    var previous = JSON.parse(value); faces = previous.faces; decision = previous.decision;
    faceIndex = previous.faceIndex; region = previous.region;
  }
  function currentFace() {
    if (!faces.length) { say('Add a missed face first (a), or commit with Enter to record no face.'); return null; }
    return faces[faceIndex];
  }
  function loadItem() {
    var item = items[index];
    var saved = answers[item.pid];
    faces = faceMode ? (saved && saved.status === 'answered' ? JSON.parse(JSON.stringify(saved.faces)) : freshFaces(item)) : [];
    faceIndex = 0;
    decision = saved ? saved.decision || null : null;
    history = [];
    complete = false;
    imageFailed = false;
    say('');
    image.src = item.image;
    render();
  }
  function describeFace(face) {
    var occluders = face.occluders === null ? 'cannot tell' : (face.occluders.length ? face.occluders.join(', ') : 'none');
    var parts = ['occluders: ' + occluders, 'identity: ' + face.identity_status];
    Object.keys(face.visibility).forEach(function (name) {
      parts.push(name.replace('_', ' ') + ': ' + (face.visibility[name] || 'unlabelled'));
    });
    return parts.join('; ');
  }
  function layoutBoxes() {
    var old = stage.querySelectorAll('.box');
    for (var i = 0; i < old.length; i++) { old[i].remove(); }
    if (!image.naturalWidth) { return; }
    var boxes = faceMode ? faces.map(function (face) { return {box: face.box, added: face.source === 'added'}; })
      : items[index].boxes.map(function (box) { return {box: box, added: false}; });
    if (drawing && preview) { boxes.push({box: preview, preview: true}); }
    boxes.forEach(function (entry) {
      var div = document.createElement('div');
      div.className = entry.preview ? 'box preview' : (entry.added ? 'box added' : 'box');
      var scaleX = 100 / image.naturalWidth;
      var scaleY = 100 / image.naturalHeight;
      div.style.left = (entry.box[0] * scaleX) + '%';
      div.style.top = (entry.box[1] * scaleY) + '%';
      div.style.width = (entry.box[2] * scaleX) + '%';
      div.style.height = (entry.box[3] * scaleY) + '%';
      stage.appendChild(div);
    });
  }
  function render() {
    var done = items.filter(function (item) { return answers[item.pid] && answers[item.pid].status === 'answered'; }).length;
    var skipped = items.filter(function (item) { return answers[item.pid] && answers[item.pid].status === 'skipped'; }).length;
    document.getElementById('position').textContent = (items.length ? 'Item ' + (index + 1) + ' of ' + items.length : 'Queue empty — no items') +
      ' · done ' + done + ' · skipped ' + skipped;
    document.getElementById('progress').max = Math.max(1, items.length);
    document.getElementById('progress').value = done + skipped;
    document.getElementById('item-state').textContent = items.length && answers[items[index].pid] &&
      answers[items[index].pid].status === 'skipped' ? '○ skipped' : '';
    drawPanel.hidden = !drawing;
    drawButton.hidden = drawing || !items.length || complete;
    Array.prototype.forEach.call(document.querySelectorAll('[data-nav]'), function (button) {
      button.hidden = drawing || (!items.length && button.id !== 'export') || (complete && button.id !== 'export');
    });
    faceControls.hidden = !faceMode || !items.length || complete;
    regionControls.hidden = !faceMode || !items.length || complete;
    unionControls.hidden = faceMode || !items.length || complete;
    stage.classList.toggle('drawing', drawing);
    drawButton.setAttribute('aria-pressed', drawing ? 'true' : 'false');
    Array.prototype.forEach.call(document.querySelectorAll('[data-act="region"]'), function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-region') === region ? 'true' : 'false');
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-act^="decide_"]'), function (button) {
      var value = {decide_face: 'face', decide_not: 'not_face', decide_cannot: 'cannot_tell'}[button.getAttribute('data-act')];
      button.setAttribute('aria-pressed', decision === value ? 'true' : 'false');
    });
    if (!imageFailed && !complete && faceMode && faces.length) {
      say('Face ' + (faceIndex + 1) + ' of ' + faces.length + ': ' + describeFace(faces[faceIndex]));
    }
    if (items.length) { layoutBoxes(); }
  }
  function setOccluder(name) {
    var face = currentFace(); if (!face) { return; }
    snapshot();
    if (face.occluders === null) { face.occluders = []; }
    var at = face.occluders.indexOf(name);
    if (at >= 0) { face.occluders.splice(at, 1); } else { face.occluders.push(name); }
    render();
  }
  function setNone() { var face = currentFace(); if (!face) { return; } snapshot(); face.occluders = []; render(); }
  function setCannot() { var face = currentFace(); if (!face) { return; } snapshot(); face.occluders = null; render(); }
  function cycleVisibility() {
    var face = currentFace(); if (!face) { return; }
    snapshot();
    var next = VIS_CYCLE.indexOf(face.visibility[region]) + 1;
    face.visibility[region] = VIS_CYCLE[next % VIS_CYCLE.length];
    render();
  }
  function toggleUnknown() {
    var face = currentFace(); if (!face) { return; }
    snapshot();
    face.identity_status = face.identity_status === 'unknown' ? 'unresolved' : 'unknown';
    render();
  }
  function nextFace() { if (faces.length) { faceIndex = (faceIndex + 1) % faces.length; render(); } }
  function beginDraw() {
    if (drawing || imageFailed || !image.naturalWidth) { return; }
    drawState = {value: state(), history: history.slice()};
    drawing = true; preview = null; pointerStart = null;
    coordinates.forEach(function (input) { input.value = ''; });
    render(); say('Drawing a box. Enter coordinates or drag, then Commit box or Cancel draw.');
    coordinates[0].focus();
  }
  function leaveDraw() {
    drawing = false; preview = null; pointerStart = null; drawState = null;
    render(); document.querySelector('[data-act="next"]').focus();
  }
  function cancelDraw() {
    if (!drawing) { return; }
    restore(drawState.value); history = drawState.history;
    leaveDraw(); say('Drawing cancelled; item unchanged.');
  }
  function readBox() {
    var box = coordinates.map(function (input) { return input.value === '' ? NaN : Number(input.value); });
    if (box.some(function (v) { return !Number.isFinite(v); }) || box[0] < 0 || box[1] < 0 ||
      box[2] < 2 || box[3] < 2 || box[0] + box[2] > image.naturalWidth || box[1] + box[3] > image.naturalHeight) { return null; }
    return box;
  }
  function commitBox() {
    if (!drawing) { return; }
    var box = readBox();
    if (!box || imageFailed) { say('Enter a box within the image bounds, at least 2 by 2 pixels. Your work is kept.'); return; }
    history = drawState.history.slice(); history.push(drawState.value);
    faces.push({source: 'added', face_key: 'a' + faces.length, box: box, occluders: null,
      visibility: blankVisibility(), identity_status: 'unresolved'});
    faceIndex = faces.length - 1;
    leaveDraw();
  }
  coordinates.forEach(function (input) {
    input.addEventListener('input', function () { preview = readBox(); layoutBoxes(); });
  });
  function decide(value) { snapshot(); decision = value; render(); }
  function skip() {
    answers[items[index].pid] = faceMode ? {status: 'skipped', faces: []} : {status: 'skipped', decision: null};
    advance();
  }
  function commit() {
    if (drawing) { commitBox(); return; }
    if (imageFailed || !image.naturalWidth) { say('Image unavailable; item and labels kept. Retry loading the image.'); return; }
    var item = items[index];
    if (faceMode) {
      answers[item.pid] = {status: 'answered', faces: faces.map(function (face) { return JSON.parse(JSON.stringify(face)); })};
    } else {
      if (decision === null) { say('Choose face, not a face, or cannot tell first (f, n, ?).'); return; }
      answers[item.pid] = {status: 'answered', decision: decision};
    }
    advance();
  }
  function advance() {
    if (index < items.length - 1) { index += 1; loadItem(); }
    else { complete = true; render(); say('Last item reached. Export labels to finish.'); }
  }
  function undo() {
    if (!history.length) { return; }
    restore(history.pop());
    render();
  }
  function act(name) {
    if (!items.length || complete) { return; }
    if (drawing && name === 'next') { commitBox(); return; }
    if (drawing && name === 'undo') { cancelDraw(); return; }
    if (drawing && (name === 'skip' || name === 'draw')) { return; }
    if (name === 'commitbox') { commitBox(); return; }
    if (name === 'canceldraw') { cancelDraw(); return; }
    if (name === 'mask' || name === 'sunglasses' || name === 'hand' || name === 'other_object' || name === 'mixed') {
      if (faceMode) { setOccluder(OCC_NAMES[name]); }
    } else if (name === 'none') { if (faceMode) { setNone(); } else { decide('not_face'); } }
    else if (name === 'cannot') { if (faceMode) { setCannot(); } else { decide('cannot_tell'); } }
    else if (name === 'region') { region = arguments[1]; render(); }
    else if (name === 'visibility') { if (faceMode) { cycleVisibility(); } }
    else if (name === 'draw') { if (faceMode) { beginDraw(); } }
    else if (name === 'unknown') { if (faceMode) { toggleUnknown(); } }
    else if (name === 'nextface') { if (faceMode) { nextFace(); } }
    else if (name === 'decide_face') { decide('face'); }
    else if (name === 'decide_not') { decide('not_face'); }
    else if (name === 'decide_cannot') { decide('cannot_tell'); }
    else if (name === 'skip') { skip(); }
    else if (name === 'undo') { undo(); }
    else if (name === 'next') { commit(); }
  }
  var FACE_KEYS = {m: 'mask', s: 'sunglasses', h: 'hand', o: 'other_object', x: 'mixed', n: 'none', '?': 'cannot',
    v: 'visibility', a: 'draw', u: 'unknown', '.': 'nextface', k: 'skip', Escape: 'undo', Enter: 'next'};
  var UNION_KEYS = {f: 'decide_face', n: 'decide_not', '?': 'decide_cannot', k: 'skip', Escape: 'undo', Enter: 'next'};
  document.addEventListener('keydown', function (event) {
    var target = event.target;
    if (event.altKey || event.ctrlKey || event.metaKey) { return; }
    if (drawing && (event.key === 'Escape' || (event.key === 'Enter' && target && target.type === 'number'))) {
      event.preventDefault(); act(event.key === 'Escape' ? 'canceldraw' : 'commitbox'); return;
    }
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA')) { return; }
    if (target && target.tagName === 'BUTTON' && (event.key === 'Enter' || event.key === ' ')) { return; }
    var name = (faceMode ? FACE_KEYS : UNION_KEYS)[event.key];
    if (name === undefined) { return; }
    event.preventDefault();
    act(name);
  });
  Array.prototype.forEach.call(document.querySelectorAll('button[data-act]'), function (button) {
    button.addEventListener('click', function () {
      if (button.getAttribute('data-act') === 'region') {
        region = button.getAttribute('data-region');
        render();
        return;
      }
      act(button.getAttribute('data-act'));
    });
  });
  function imagePoint(event) {
    var rect = image.getBoundingClientRect();
    return {x: Math.max(0, Math.min(image.naturalWidth, (event.clientX - rect.left) * image.naturalWidth / rect.width)),
      y: Math.max(0, Math.min(image.naturalHeight, (event.clientY - rect.top) * image.naturalHeight / rect.height))};
  }
  function updatePointer(event) {
    if (!drawing || !pointerStart) { return; }
    var point = imagePoint(event);
    var box = [Math.min(pointerStart.x, point.x), Math.min(pointerStart.y, point.y),
      Math.abs(point.x - pointerStart.x), Math.abs(point.y - pointerStart.y)];
    coordinates.forEach(function (input, i) { input.value = String(box[i]); });
    preview = readBox(); layoutBoxes();
  }
  image.addEventListener('dragstart', function (event) { event.preventDefault(); });
  image.addEventListener('pointerdown', function (event) {
    if (!drawing || !faceMode || event.button !== 0 || imageFailed) { return; }
    event.preventDefault(); pointerStart = imagePoint(event); image.setPointerCapture(event.pointerId);
  });
  image.addEventListener('pointermove', updatePointer);
  image.addEventListener('pointerup', function (event) {
    updatePointer(event); pointerStart = null;
    if (image.hasPointerCapture(event.pointerId)) { image.releasePointerCapture(event.pointerId); }
  });
  image.addEventListener('pointercancel', function () { pointerStart = null; });
  var retryImage = document.getElementById('retry-image');
  retryImage.addEventListener('click', function () {
    say('Retrying image; item and labels kept.');
    image.src = items[index].image;
  });
  image.addEventListener('load', function () { imageFailed = false; retryImage.hidden = true; render(); });
  image.addEventListener('error', function () {
    imageFailed = true; retryImage.hidden = false;
    say('Image failed to load; item and labels kept. Retry loading the image.');
  });
  document.getElementById('export').addEventListener('click', function () {
    if (drawing) { say('Commit box or Cancel draw before export.'); return; }
    var annotator = document.getElementById('annotator').value.trim();
    if (!annotator) { say('Enter an annotator id before export.'); return; }
    var open = items.filter(function (item) { return !answers[item.pid]; }).length;
    if (open > 0) { say(open + ' items still have no decision. Skip or answer them before export.'); return; }
    var observation = document.getElementById('observation').value.trim();
    var doc = {
      schema: 'fir-occ-labels/v1', queue_id: payload.queue_id, queue_sha256: payload.queue_sha256,
      mode: payload.mode, annotator_id: annotator, annotation_tier: payload.annotation_tier,
      rule_id: payload.rule_id, observation_ref: observation || null,
      answers: items.map(function (item) {
        var answer = answers[item.pid];
        var entry = {presented_id: item.pid, status: answer.status};
        if (faceMode) { entry.faces = answer.faces || []; } else { entry.decision = answer.decision || null; }
        return entry;
      }),
      hidden: JSON.parse(atob(payload.hidden))
    };
    var url = null;
    var link = null;
    try {
      url = URL.createObjectURL(new Blob([JSON.stringify(doc, null, 1)], {type: 'application/json'}));
      link = document.createElement('a');
      link.href = url;
      link.download = 'fir-occ-labels-' + payload.queue_id + '.json';
      document.body.appendChild(link);
      link.click();
      say('Export download requested. Keep the downloaded JSON in the private output path.');
    } catch (error) {
      say('Export failed: ' + error.message + '. Labels kept; retry Export labels.');
    } finally {
      if (link) { link.remove(); }
      if (url) { URL.revokeObjectURL(url); }
    }
  });
  if (items.length) { loadItem(); } else { render(); say('Queue empty — no items to label.'); }
})();
</script>
</body>
</html>
"""


def _count(fraction: float, n: int) -> int:
    """Round half up, so 0.10 of 50 items is exactly 5."""
    return int(math.floor(fraction * n + 0.5))


def _pid(seed: str, queue_id: str, role: str, ident: str) -> str:
    return "p" + hashlib.sha256(f"{seed}|{queue_id}|{role}|{ident}".encode()).hexdigest()[:12]


def _data_uri(images: Path, name: str, expected_sha: str) -> str:
    path = images / name
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha:
        raise fc.FrameContractError(f"image {name} does not match its recorded sha256")
    mime = _MIME.get(path.suffix.lower().lstrip("."))
    if mime is None:
        raise fc.FrameContractError(f"image {name} must be png or jpeg")
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def _build(queue: occ.Queue, *, seed: str, repeat_fraction: float | None, images: Path, rule_id: str) -> dict[str, Any]:
    if rule_id != RUBRIC_VERSION:
        raise fc.FrameContractError(f"--rule-id must be {RUBRIC_VERSION!r}")
    configured_repeat = queue.qc.get("repeat_fraction")
    if isinstance(configured_repeat, bool) or not isinstance(configured_repeat, (int, float)) or not 0 <= configured_repeat <= 1:
        raise fc.FrameContractError("queue qc.repeat_fraction must be a number in [0, 1]")
    if repeat_fraction is not None and repeat_fraction != configured_repeat:
        raise fc.FrameContractError("--repeat-fraction must match queue qc.repeat_fraction")
    repeat_fraction = configured_repeat
    presented_items = [item for item in queue.items if not item.matched_gt]
    representatives: list[occ.QueueItem] = []
    seen_groups: set[str] = set()
    for item in presented_items:
        if item.duplicate_group is not None:
            if item.duplicate_group in seen_groups:
                continue
            seen_groups.add(item.duplicate_group)
        representatives.append(item)
    gold_share = queue.qc.get("gold_share")
    if gold_share is not None and len(queue.gold) != _count(float(gold_share), len(representatives)):
        raise fc.FrameContractError(
            f"gold items ({len(queue.gold)}) must equal gold_share x presented items "
            f"({_count(float(gold_share), len(representatives))})"
        )
    repeat_count = _count(repeat_fraction, len(representatives))
    repeat_sources = random.Random(f"{seed}|{queue.queue_id}|repeat").sample(representatives, repeat_count)
    entries: list[tuple[str, str]] = [("primary", item.item_id) for item in representatives]
    entries += [("consistency", item.item_id) for item in repeat_sources]
    entries += [("known_answer", gold.gold_id) for gold in queue.gold]
    random.Random(f"{seed}|{queue.queue_id}|order").shuffle(entries)

    by_item = {item.item_id: item for item in queue.items}
    by_gold = {gold.gold_id: gold for gold in queue.gold}
    hidden: dict[str, dict[str, Any]] = {}
    page_items: list[dict[str, Any]] = []
    for role, ident in entries:
        if role == "known_answer":
            gold = by_gold[ident]
            pid = _pid(seed, queue.queue_id, role, ident)
            hidden[pid] = {"role": role, "item_id": None, "of": None, "gold_id": ident}
            page_items.append({"pid": pid, "image": _data_uri(images, gold.image, gold.item.sha256), "boxes": []})
            continue
        item = by_item[ident]
        pid = _pid(seed, queue.queue_id, role, ident)
        of = _pid(seed, queue.queue_id, "primary", ident) if role == "consistency" else None
        hidden[pid] = {"role": role, "item_id": ident, "of": of, "gold_id": None}
        page_items.append(
            {
                "pid": pid,
                "image": _data_uri(images, item.image, item.image_sha256),
                "boxes": [list(box) for box in item.shown_boxes],
            }
        )
    return {
        "schema": PAGE_SCHEMA,
        "queue_id": queue.queue_id,
        "queue_sha256": queue.sha256,
        "mode": queue.mode,
        "annotation_tier": queue.annotation_tier,
        "rule_id": rule_id,
        "items": page_items,
        "hidden": base64.b64encode(json.dumps({"presented": hidden}, sort_keys=True).encode("utf-8")).decode("ascii"),
    }


def _html(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True).replace("<", "\\u003c")
    return _PAGE_TEMPLATE.replace("__PAYLOAD__", text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--queue", type=Path, help="private face-mode queue JSON (fir-occ-queue/v1)")
    source.add_argument("--union-delta", type=Path, help="private proposals JSON (fir-occ-union-proposals/v1)")
    parser.add_argument("--images", type=Path, required=True, help="directory holding the queue images")
    parser.add_argument("--rule-id", default=RUBRIC_VERSION)
    parser.add_argument("--repeat-fraction", type=float, help="must match queue qc.repeat_fraction if supplied")
    parser.add_argument("--gold", type=Path, required=True, help="private gold JSON (fir-occ-gold/v1)")
    parser.add_argument("--seed", required=True, help="seed for repeat choice, order and opaque ids")
    parser.add_argument("--out", type=Path, required=True, help="output HTML under benchmarks/private/")
    parser.add_argument("--repo-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        out = fc.require_private_output_path(args.out, repo_root=args.repo_root.resolve())
        source = args.union_delta if args.union_delta is not None else args.queue
        queue = occ.load_queue(source, args.gold)
        payload = _build(
            queue,
            seed=args.seed,
            repeat_fraction=args.repeat_fraction,
            images=args.images,
            rule_id=args.rule_id,
        )
        html = _html(payload)
    except (fc.FirBenchError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
