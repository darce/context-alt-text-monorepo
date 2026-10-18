"""L1 browser contracts on generated pixels; no observation or real-data claims.

Browser tooling is external to the product/dev dependency set. Set
FIR_OCC_PLAYWRIGHT to an available Node Playwright module and optionally
FIR_OCC_BROWSER to a cached Chromium executable to run the event checks.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from scripts.eval_harness import fir_occ_labels as occ
from scripts.eval_harness import firbench_contract as fc

ROOT = Path(__file__).resolve().parents[4]
# Explicit canonical producer contract; do not inherit the core sibling's stale QC_KEYS.
QC = {
    "gold_share": .10, "repeat_fraction": .10,
    "repeat_percent_agreement_floor": .90, "kappa_floor": .80,
    "annotator_gold_accuracy_floor": .90,
    "min_gold_decisions_per_annotator": 20, "min_repeat_decisions_per_field": 20,
}


@pytest.fixture
def generator():
    spec = importlib.util.spec_from_file_location("occ_ui_generator", ROOT / "benchmarks/tools/fir_occ_label_queue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeat_policy_comes_from_canonical_queue(generator, monkeypatch, tmp_path):
    queue = SimpleNamespace(items=(), gold=(), qc=dict(QC), queue_id="fixture", sha256="a" * 64,
                            mode="face", annotation_tier="a")
    assert generator._parser().parse_args([
        "--queue", "q", "--images", "i", "--gold", "g", "--seed", "1", "--out", "o"
    ]).repeat_fraction is None
    generator._build(queue, seed="1", repeat_fraction=None, images=tmp_path, rule_id=generator.RUBRIC_VERSION)
    with pytest.raises(fc.FrameContractError, match="repeat_fraction"):
        generator._build(queue, seed="1", repeat_fraction=.2, images=tmp_path, rule_id=generator.RUBRIC_VERSION)
    # Exercise the real CLI path and guard with the independently declared QC mapping.
    monkeypatch.setattr(generator.occ, "load_queue", lambda *args: queue)
    output = tmp_path / "benchmarks/private/ui.html"
    args = ["--queue", "q", "--images", str(tmp_path), "--gold", "g", "--seed", "1",
            "--repo-root", str(tmp_path), "--out", str(output)]
    assert generator.main(args) == 0 and output.is_file()
    assert generator.main(args + ["--out", str(tmp_path / "benchmarks/reports/no.html")]) == 2


def test_configured_fraction_controls_presentations(generator, monkeypatch, tmp_path):
    items = tuple(SimpleNamespace(item_id=f"i{i}", matched_gt=False, duplicate_group=None,
                                  image="generated.png", image_sha256="a" * 64, shown_boxes=())
                  for i in range(10))
    gold = SimpleNamespace(gold_id="g0", image="generated.png", item=SimpleNamespace(sha256="a" * 64))
    queue = SimpleNamespace(items=items, gold=(gold,), qc={**QC, "repeat_fraction": .2},
                            queue_id="fixture", sha256="a" * 64, mode="face", annotation_tier="a")
    monkeypatch.setattr(generator, "_data_uri", lambda *args: "data:image/png;base64,fixture")
    first = generator._build(queue, seed="1", repeat_fraction=None, images=tmp_path, rule_id=generator.RUBRIC_VERSION)
    second = generator._build(queue, seed="1", repeat_fraction=.2, images=tmp_path, rule_id=generator.RUBRIC_VERSION)
    assert first == second
    roles = json.loads(base64.b64decode(first["hidden"]))["presented"].values()
    assert sum(entry["role"] == "consistency" for entry in roles) == 2
    assert len(first["items"]) == 13


BROWSER_SCRIPT = r"""
const {chromium} = require(process.env.FIR_OCC_PLAYWRIGHT);
const assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.FIR_OCC_BROWSER || undefined,
   args:['--no-sandbox','--disable-dev-shm-usage']});
 try {
 const page = await browser.newPage({viewport:{width:1000,height:800}, acceptDownloads:true});
 page.setDefaultTimeout(3000);
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.argv[2]);
 const scenario=process.argv[3];
 const button = a => page.locator(`[data-act="${a}"]:visible`);
 const key = async k => {await page.locator('h1').click(); await page.keyboard.press(k);};
 const text = async (id,re) => assert.match(await page.locator(id).innerText(),re);
 const geometry = async (values=[10,12,30,24]) => {
   for (const [label,v] of ['Box left','Box top','Box width','Box height'].map((l,i)=>[l,values[i]]))
     await page.getByLabel(label,{exact:true}).fill(String(v));
 };
 const exportDoc = async () => {
   await page.locator('#annotator').fill('fixture-operator');
   const downloadPromise=page.waitForEvent('download');
   await page.locator('#export').click();
   const download=await downloadPromise;
   await download.saveAs(process.argv[4]);
   return JSON.parse(require('fs').readFileSync(process.argv[4],'utf8'));
 };
 const finish = async () => {await key('Enter'); await key('k'); return exportDoc();};
 if(scenario==='draw') {
   await key('a'); await text('#draw-panel',/drawing a box/i);
   const rect=await page.locator('#image').boundingBox();
   await page.mouse.move(rect.x+10,rect.y+12); await page.mouse.down();
   await page.mouse.move(rect.x+40,rect.y+36); await page.mouse.up();
   assert.equal(await page.locator('.box.preview').count(),1);
   assert.equal(await page.locator('.box.added').count(),0);
   await text('#position',/Item 1 of 2/);
   await key('Enter'); assert.equal(await page.locator('#draw-panel').isVisible(),false);
   await text('#position',/Item 1 of 2/);
   const doc=await finish(); assert.deepEqual(doc.answers[0].faces[0].box,[10,12,30,24]);
 } else if(scenario==='keyboard') {
   await key('a'); await geometry();
   await page.getByLabel('Box width',{exact:true}).press('Enter');
   await text('#position',/Item 1 of 2/);
   await key('u'); await key('m');
   const doc=await finish();
   assert.deepEqual(doc.answers[0].faces[0].box,[10,12,30,24]);
   assert.equal(doc.answers[0].faces[0].identity_status,'unknown');
   assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
 } else if(scenario==='cancel') {
   await key('a'); await geometry(); await button('commitbox').click(); await key('m');
   await key('a'); await geometry([1,2,3,4]); await key('u'); await key('Escape');
   await key('a'); await geometry([2,3,4,5]); await button('canceldraw').click();
   assert.equal(await page.locator('#draw-panel').isVisible(),false);
   const doc=await finish(); assert.equal(doc.answers[0].faces.length,1);
   assert.equal(doc.answers[0].faces[0].identity_status,'unresolved');
   assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
 } else if(scenario==='progress') {
   await text('#position',/done 0 · skipped 0/);
   await key('a'); await geometry(); await key('Enter'); await key('Enter');
   await text('#position',/done 1 · skipped 0/);
   await key('k'); await text('#position',/done 1 · skipped 1/);
   await text('#item-state',/○ skipped/);
   assert.equal(await page.locator('#progress').getAttribute('value'),'2');
   const doc=await exportDoc(); assert.equal(doc.answers[1].status,'skipped');
   assert.deepEqual(doc.answers[1].faces,[]);
 } else if(scenario==='recover') {
   await key('a'); await geometry([90,12,30,24]); await key('Enter');
   await text('#status',/within|bounds/i); assert.equal(await page.locator('#draw-panel').isVisible(),true);
   await geometry(); await key('Enter'); await key('m');
   await page.evaluate(()=>{URL.createObjectURL=()=>{throw new Error('fixture disk unavailable');};});
   await key('Enter'); await key('k'); await page.locator('#annotator').fill('fixture-operator');
   await page.locator('#export').click(); await text('#status',/fixture disk unavailable.*retry/i);
   await page.evaluate(()=>{delete URL.createObjectURL;});
   // Restore the native method from a clean same-origin iframe.
   await page.evaluate(()=>{const f=document.createElement('iframe');document.body.append(f);
     URL.createObjectURL=f.contentWindow.URL.createObjectURL.bind(f.contentWindow.URL);});
   const doc=await exportDoc(); assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
 } else if(scenario==='parity') {
   // Tab actually reaches every visible button; native Enter and Space dispatch clicks.
   const checkTab = async () => {
     const expected=await page.locator('button:visible:enabled').count(); const found=new Set();
     await page.locator('#annotator').focus();
     for(let i=0;i<expected+15;i++) {
       await page.keyboard.press('Tab');
       const focused=await page.evaluate(()=>({tag:document.activeElement.tagName,
         key:document.activeElement.outerHTML, outline:getComputedStyle(document.activeElement).outlineStyle}));
       if(focused.tag==='BUTTON') {found.add(focused.key);}
       if(['BUTTON','INPUT'].includes(focused.tag)) {assert.notEqual(focused.outline,'none');}
     }
     assert.equal(found.size,expected);
   };
   await checkTab();
   await button('draw').focus(); await page.keyboard.press('Space'); await geometry();
   await checkTab();
   await button('commitbox').focus(); await page.keyboard.press('Enter');
   // Every face attribute shortcut agrees with both native button activation paths.
   const actions={m:'mask',s:'sunglasses',h:'hand',o:'other_object',x:'mixed',n:'none',
     '?':'cannot',v:'visibility',u:'unknown'};
   for(const [shortcut,act] of Object.entries(actions)) {
     await key(shortcut); const expected=await page.locator('#status').innerText();
     await key('Escape');
     for(const activation of ['Enter','Space']) {
       await button(act).focus(); await page.keyboard.press(activation);
       assert.equal(await page.locator('#status').innerText(),expected);
       await button('undo').focus(); await page.keyboard.press('Space');
     }
   }
   await key('.'); const selected=await page.locator('#status').innerText();
   await button('nextface').focus(); await page.keyboard.press('Space');
   assert.equal(await page.locator('#status').innerText(),selected);
   await button('draw').focus(); await page.keyboard.press('Enter'); await geometry();
   await button('canceldraw').focus(); await page.keyboard.press('Space');
   assert.equal(await page.locator('#draw-panel').isVisible(),false);
   await button('next').focus(); await page.keyboard.press('Space');
   await button('skip').focus(); await page.keyboard.press('Enter');
   await exportDoc();
 } else if(scenario==='image-error') {
   await key('a'); await geometry(); await key('Enter'); await key('m');
   await page.evaluate(()=>{document.getElementById('image').src='data:image/png;base64,bad';});
   await text('#status',/image.*(fail|error|unavailable)/i);
   await key('Enter'); await text('#position',/Item 1 of 2/);
   await page.locator('#export').click(); await text('#status',/image|annotator/i);
   await page.locator('#retry-image').click();
   await page.waitForFunction(()=>document.getElementById('image').naturalWidth>0);
   const doc=await finish(); assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
 } else if(scenario==='empty') {
   await text('#position',/empty|no items/i);
   assert.equal(await button('next').count(),0);
 } else if(scenario==='union') {
   assert.equal(await button('draw').count(),0);
   await key('f'); await key('Escape'); await button('decide_not').focus();
   await page.keyboard.press('Space'); await button('next').click(); await key('k');
   const doc=await exportDoc(); assert.equal(doc.answers[0].decision,'not_face');
 } else if(scenario==='privacy') {
   const visible=await page.locator('body').innerText();
   assert.doesNotMatch(visible,/gold|repeat|blind|caption|detector|modelname/i);
   const attrs=await page.locator('body *:not(script)').evaluateAll(nodes=>nodes.flatMap(n=>[...n.attributes].map(a=>a.value)).join(' '));
   assert.doesNotMatch(attrs,/gold|repeat|blind|caption|detector|modelname/i);
   await page.clock.install();
   const before=await page.locator('#position').innerText();
   await page.clock.fastForward(24*60*60*1000);
   assert.equal(await page.locator('#position').innerText(),before);
   await key('a'); await geometry(); await key('Enter'); await key('Enter'); await key('k');
   const doc=await exportDoc(); assert.ok(doc.hidden.presented);
 }
 assert.deepEqual(errors,[]);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
"""


@pytest.mark.parametrize("scenario", ["draw", "keyboard", "cancel", "progress", "recover", "parity", "image-error", "empty", "union", "privacy"])
def test_l1_actual_browser_events(generator, tmp_path, scenario):
    if not os.environ.get("FIR_OCC_PLAYWRIGHT") or not shutil.which("node"):
        pytest.skip("VM browser check requires external FIR_OCC_PLAYWRIGHT and Node")
    page = _write_page(generator, tmp_path, scenario)
    script = tmp_path / "events.cjs"
    script.write_text(BROWSER_SCRIPT)
    export = tmp_path / "export.json"
    result = subprocess.run(["node", str(script), page.as_uri(), scenario, str(export)],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    if export.exists():
        # Ordinary exported records remain readable by the production schema loader.
        assert occ.load_label_export(export).queue_id == "ui-fixture"


def _write_page(generator, tmp_path, scenario):
    # Controlled generated numpy fixture; reuse only the byte encoder, no core QC shape.
    import numpy as np
    from scene.tests.test_eval_harness_fir_occ_labels import _png
    image = "data:image/png;base64," + base64.b64encode(_png(np.zeros((80, 100, 3), dtype=np.uint8))).decode()
    payload = {"schema": "fir-occ-page/v1", "queue_id": "ui-fixture", "queue_sha256": "a" * 64,
               "mode": "union_delta" if scenario == "union" else "face", "annotation_tier": "a",
               "rule_id": generator.RUBRIC_VERSION,
               "items": [{"pid": f"p{i}", "image": image, "boxes": []} for i in range(2)],
               "hidden": base64.b64encode(json.dumps({"presented": {
                   "p0": {"role": "primary", "item_id": "fixture-0", "of": None, "gold_id": None},
                   "p1": {"role": "consistency", "item_id": "fixture-0", "of": "p0", "gold_id": None},
               }}).encode()).decode()}
    if scenario == "empty":
        payload["items"] = []
    page = tmp_path / "fixture.html"
    page.write_text(generator._html(payload))
    return page


DOM_SCRIPT = r"""
const {JSDOM,VirtualConsole}=require(process.env.FIR_OCC_JSDOM);
const assert=require('node:assert/strict'), fs=require('fs');
(async()=>{
 let captured,failExport=false,loadFailed=false;
 const errors=[],console=new VirtualConsole(); console.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(process.argv[2],'utf8'),{runScripts:'dangerously',virtualConsole:console,
   beforeParse(w){
     Object.defineProperties(w.HTMLImageElement.prototype,{
       naturalWidth:{get:()=>loadFailed?0:100},naturalHeight:{get:()=>loadFailed?0:80}});
     w.HTMLImageElement.prototype.getBoundingClientRect=()=>({left:0,top:0,width:100,height:80});
     w.HTMLImageElement.prototype.setPointerCapture=()=>{};
     w.HTMLImageElement.prototype.hasPointerCapture=()=>false;
     w.HTMLAnchorElement.prototype.click=()=>{};
     w.URL.createObjectURL=blob=>{
       if(failExport)throw Error('fixture unavailable');
       captured=new Promise(resolve=>{const r=new w.FileReader();r.onload=()=>resolve(JSON.parse(r.result));r.readAsText(blob);});
       return 'blob:fixture';
     };
     w.URL.revokeObjectURL=()=>{};
   }});
 try {
 const w=dom.window,d=w.document,scenario=process.argv[3];
 const byId=id=>d.getElementById(id), btn=a=>d.querySelector(`[data-act="${a}"]`);
 const key=(k,target=d.body)=>target.dispatchEvent(new w.KeyboardEvent('keydown',{key:k,bubbles:true,cancelable:true}));
 const click=a=>btn(a).click();
 const box=(values=[10,12,30,24])=>['left','top','width','height'].forEach((n,i)=>{
   byId('box-'+n).value=values[i];byId('box-'+n).dispatchEvent(new w.Event('input',{bubbles:true}));});
 const status=re=>assert.match(byId('status').textContent,re);
 const position=re=>assert.match(byId('position').textContent,re);
 const exportDoc=async()=>{byId('annotator').value='fixture-operator';byId('export').click();
   assert.ok(captured,'Export must request a download');const doc=await captured;
   fs.writeFileSync(process.argv[4],JSON.stringify(doc));return doc;};
 const finish=async()=>{key('Enter');key('k');return exportDoc();};
 if(scenario==='draw') {
   key('a'); assert.equal(byId('draw-panel').hidden,false);
   for(const [type,x,y] of [['pointerdown',10,12],['pointermove',40,36],['pointerup',40,36]])
     byId('image').dispatchEvent(new w.MouseEvent(type,{clientX:x,clientY:y,button:0}));
   assert.equal(d.querySelectorAll('.box.preview').length,1);
   assert.equal(d.querySelectorAll('.box.added').length,0);
   position(/Item 1 of 2/);key('Enter');position(/Item 1 of 2/);
   assert.equal(byId('draw-panel').hidden,true);
   const doc=await finish();assert.deepEqual(doc.answers[0].faces[0].box,[10,12,30,24]);
 } else if(scenario==='keyboard') {
   key('a');box();key('Enter',byId('box-width'));position(/Item 1 of 2/);key('u');key('m');
   const doc=await finish();assert.deepEqual(doc.answers[0].faces[0].box,[10,12,30,24]);
   assert.equal(doc.answers[0].faces[0].identity_status,'unknown');
   assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
 } else if(scenario==='cancel') {
   click('draw');box();click('commitbox');key('m');key('a');box([1,2,3,4]);key('u');
   assert.equal(byId('draw-panel').hidden,false);
   assert.equal(btn('next').hidden,true);assert.equal(btn('undo').hidden,true);
   assert.equal(btn('commitbox').hidden,false);assert.equal(btn('canceldraw').hidden,false);
   key('Escape',byId('box-width'));assert.equal(byId('draw-panel').hidden,true);
   key('a');box();click('canceldraw');
   const doc=await finish();assert.equal(doc.answers[0].faces.length,1);
   assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
   assert.equal(doc.answers[0].faces[0].identity_status,'unresolved');
 } else if(scenario==='progress') {
   position(/done 0 · skipped 0/);key('a');box();key('Enter');key('Enter');
   position(/done 1 · skipped 0/);key('k');position(/done 1 · skipped 1/);
   assert.match(byId('item-state').textContent,/○ skipped/);assert.equal(byId('progress').value,2);
   const doc=await exportDoc();assert.equal(doc.answers[1].status,'skipped');
 } else if(scenario==='recover') {
   key('a');box([90,12,30,24]);key('Enter');status(/within|bounds/i);
   assert.equal(byId('draw-panel').hidden,false);box();key('Enter');key('m');
   loadFailed=true;byId('image').dispatchEvent(new w.Event('error'));key('Enter');position(/Item 1 of 2/);
   assert.equal(byId('retry-image').hidden,false);byId('retry-image').click();
   loadFailed=false;byId('image').dispatchEvent(new w.Event('load'));
   assert.equal(byId('retry-image').hidden,true);key('Enter');key('k');
   byId('annotator').value='fixture-operator';failExport=true;byId('export').click();status(/fixture unavailable.*retry/i);
   failExport=false;const doc=await exportDoc();assert.deepEqual(doc.answers[0].faces[0].occluders,['mask']);
 } else if(scenario==='undo') {
   key('a');box();key('Enter');key('m');key('Escape');
   assert.match(byId('status').textContent,/occluders: cannot tell/);
   click('mask');click('undo');assert.match(byId('status').textContent,/occluders: cannot tell/);
   // Exercise every face shortcut and its click handler from identical undo states.
   const actions={m:'mask',s:'sunglasses',h:'hand',o:'other_object',x:'mixed',n:'none','?':'cannot',v:'visibility',u:'unknown'};
   for(const [k,a] of Object.entries(actions)) {
     key(k);const result=byId('status').textContent;key('Escape');click(a);
     assert.equal(byId('status').textContent,result);click('undo');
   }
   await finish();
 } else if(scenario==='union') {
   assert.equal(byId('region-controls').hidden,true);key('f');click('undo');click('decide_not');key('Enter');key('k');
   const doc=await exportDoc();assert.equal(doc.answers[0].decision,'not_face');
 } else if(scenario==='empty') {
   position(/empty|no items/i);assert.equal(btn('next').hidden,true);key('Enter');key('Escape');key('k');
 } else if(scenario==='privacy') {
   const visible=[...d.body.querySelectorAll('*:not(script)')].map(n=>[...n.attributes].map(a=>a.value).join(' ')).join(' ');
   assert.doesNotMatch(visible,/gold|repeat|blind|caption|detector|modelname/i);
   const walker=d.createTreeWalker(d.body,w.NodeFilter.SHOW_TEXT);let content='',node;
   while((node=walker.nextNode())) {
     if(!node.parentElement.closest('script,style,[hidden]'))content+=node.textContent;
   }
   assert.doesNotMatch(content,/gold|repeat|blind|caption|detector|modelname/i);
   key('a');box();key('Enter');key('Enter');key('k');const doc=await exportDoc();assert.ok(doc.hidden.presented);
 }
 assert.deepEqual(errors,[]);
 } finally {dom.window.close();}
})().catch(e=>{console.error(e);process.exit(1)});
"""


@pytest.mark.parametrize("scenario", ["draw", "keyboard", "cancel", "progress", "recover", "undo", "union", "empty", "privacy"])
def test_l1_dispatched_dom_events(generator, tmp_path, scenario):
    if not os.environ.get("FIR_OCC_JSDOM") or not shutil.which("node"):
        pytest.skip("DOM event check requires external FIR_OCC_JSDOM and Node")
    page = _write_page(generator, tmp_path, scenario)
    script = tmp_path / "dom-events.cjs"
    script.write_text(DOM_SCRIPT)
    export = tmp_path / "export.json"
    result = subprocess.run(["node", str(script), str(page), scenario, str(export)],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    if export.exists():
        assert occ.load_label_export(export).queue_id == "ui-fixture"
