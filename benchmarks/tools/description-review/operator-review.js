/* Offline human annotation layer. No generated judgments or network requests. */
(function (root) {
'use strict';
const TEXT = {
 crossModel:'Cross-model blind review',
 exitCrossModel:'Exit cross-model blind review (reveal labels)',
 crossModelUnavailable:'Cross-model blind review unavailable: decision rule or operator-crossmodel.js missing.',
 candidates:['Candidate 1','Candidate 2','Candidate 3'],
 decisionReviewed:'Decision reviewed',
 progressUnavailable:'Decision progress unavailable',
 decisionTitle:'Description-model decision',
 decisionUnavailable:'Decision panel unavailable',
 assessmentsRequired:'Select severity and OCR assessment before marking Reviewed.',
 ocrRequired:'select OCR assessment',
 crossModelHint:'Cross-model blind review: compare the same image and all present surfaces; source remains inspectable.'
};
const CROSS_MODEL_IDENTIFIERS='.state,.model-meta,.timing,.run-accounting,.provenance-details,a';
const SCHEMA = 'bakeoff-operator-reviews/v1';
const clone = x => JSON.parse(JSON.stringify(x));
const same = (a,b) => stable(a) === stable(b);
function stable(x) { if (Array.isArray(x)) return '['+x.map(stable).join(',')+']'; if(x && typeof x==='object') return '{'+Object.keys(x).sort().map(k=>JSON.stringify(k)+':'+stable(x[k])).join(',')+'}'; return JSON.stringify(x); }
function hash(s) { let h=2166136261; for (const ch of s) { h^=ch.charCodeAt(0); h=Math.imul(h,16777619); } return h>>>0; }
function orders(manifest, seed) {
 const result={}; const active=manifest.images.filter(i=>manifest.cells.some(c=>c.image_id===i.image_id && c.scope==='full120')); const legacy=active.filter(i=>manifest.cells.some(c=>c.image_id===i.image_id && c.scope==='full120' && c.evaluation_partition!=='reviewed17_extension')).map(i=>i.image_id).sort(); const ids=legacy.concat(active.map(i=>i.image_id).filter(id=>!legacy.includes(id)).sort());
 ids.forEach((id,index)=>{
  const cells=manifest.cells.filter(c=>c.image_id===id && c.scope==='full120');
  const models=[...new Set(cells.map(c=>c.model_key))].sort((a,b)=>hash(seed+id+a)-hash(seed+id+b)||a.localeCompare(b));
  result[id]=models.flatMap(model=>{const pair=cells.filter(c=>c.model_key===model); if(manifest.blind_pair_policy==='complete_model_arm_pairs' && (pair.length!==2 || pair.some(c=>c.generation_error)))return []; const first=(index+hash(seed+model))%2?'on':'off'; return pair.sort((a,b)=>(a.arm===first?-1:1)-(b.arm===first?-1:1)).map(c=>c.key);});
 }); return result;
}
function empty(manifest, seed) { return {schema:SCHEMA,dataset_id:manifest.dataset_id,manifest_sha256:manifest.manifest_sha256,rubric_version:manifest.rubric_version,reviewer_id:'',blind_seed:seed,blind_orders:orders(manifest,seed),gold:{},reviews:{},pairs:[]}; }
function snapshot(g) { return JSON.stringify({facts:g.facts,ocr_state:g.ocr_state,ocr_truth:g.ocr_truth}); }
function fresh(c) { return {output_sha256:c.output_sha256,image_id:c.image_id,input_sha256:c.input_sha256,reviewed:false,severity:'not_assessed',issues:[],affected_surfaces:[],ocr:'not_assessed',notes:'',claims:[],covered_fact_ids:[],gold_snapshot:'',ocr_prediction:null,updated_at:new Date().toISOString()}; }
function validReview(c,r,reviewer) { return !!(reviewer.trim() && !c.generation_error && c.surfaces.length && r.severity!=='not_assessed' && !(r.severity==='none' && r.issues.length)); }
function invalidateReview(r) { r.reviewed=false; r.updated_at=new Date().toISOString(); }
function invalidateGold(state,id,g) { const previous=state.gold[id]; if(previous && same({facts:previous.facts,ocr_state:previous.ocr_state,ocr_truth:previous.ocr_truth},{facts:g.facts,ocr_state:g.ocr_state,ocr_truth:g.ocr_truth})) return false; g.revision=(previous?previous.revision:0)+1; state.gold[id]=g; Object.values(state.reviews).filter(r=>r.image_id===id).forEach(r=>{r.reviewed=false;r.covered_fact_ids=[];r.gold_snapshot='';}); return true; }
function validate(manifest, contract, s) {
 const fail = m=>{throw Error(m);};
 const exact=(o,keys)=>{if(!o||typeof o!=='object'||Array.isArray(o)||!same(Object.keys(o).sort(),keys.slice().sort())) fail('Unexpected or missing fields');};
 const str=x=>typeof x==='string'; const enums=(x,allowed)=>str(x)&&allowed.includes(x);
 const arr=(x,p)=>Array.isArray(x)&&x.every(p); const unique=x=>new Set(x).size===x.length;
 exact(s,['schema','dataset_id','manifest_sha256','rubric_version','reviewer_id','blind_seed','blind_orders','gold','reviews','pairs']);
 if(s.schema!==SCHEMA || s.dataset_id!==manifest.dataset_id || s.manifest_sha256!==manifest.manifest_sha256 || s.rubric_version!==manifest.rubric_version) fail('Schema/dataset/manifest/rubric mismatch');
 if(!str(s.reviewer_id)||!str(s.blind_seed)||!s.blind_seed.length||!same(s.blind_orders,orders(manifest,s.blind_seed))) fail('Invalid reviewer or blind mapping');
 const images=new Map(manifest.images.map(i=>[i.image_id,i])); const cells=new Map(manifest.cells.map(c=>[c.key,c]));
 for(const field of ['gold','reviews']) if(!s[field]||typeof s[field]!=='object'||Array.isArray(s[field])) fail('Invalid '+field);
 for(const [id,g] of Object.entries(s.gold)) {
  exact(g,['input_sha256','facts','ocr_state','ocr_truth','revision']);
  if(!images.has(id)||g.input_sha256!==images.get(id).input_sha256||!arr(g.facts,x=>str(x)&&x.trim().length>0)||!enums(g.ocr_state,['not_assessed','present','none','unreadable'])||!str(g.ocr_truth)||!Number.isInteger(g.revision)||g.revision<1) fail('Invalid ground truth');
 }
 const iso=x=>str(x)&&/^\d{4}-\d\d-\d\dT/.test(x)&&Number.isFinite(Date.parse(x));
 for(const [key,r] of Object.entries(s.reviews)) {
  exact(r,['output_sha256','image_id','input_sha256','reviewed','severity','issues','affected_surfaces','ocr','notes','claims','covered_fact_ids','gold_snapshot','ocr_prediction','updated_at']);
  const c=cells.get(key); if(!c||r.output_sha256!==c.output_sha256||r.image_id!==c.image_id||r.input_sha256!==c.input_sha256) fail('Unknown/stale output or image');
  if(typeof r.reviewed!=='boolean'||!enums(r.severity,contract.severity)||!enums(r.ocr,contract.ocr)||!arr(r.issues,x=>contract.issues.includes(x))||!unique(r.issues)||!arr(r.affected_surfaces,x=>c.surfaces.some(s=>s.name===x))||!unique(r.affected_surfaces)||!str(r.notes)||!str(r.gold_snapshot)||!(r.ocr_prediction===null||str(r.ocr_prediction))||!iso(r.updated_at)) fail('Invalid review fields');
  if(!arr(r.claims,x=>{exact(x,['text','surface','verdict']);return str(x.text)&&x.text.trim().length>0&&c.surfaces.some(s=>s.name===x.surface)&&contract.claim_verdicts.includes(x.verdict);})) fail('Invalid claims');
  const g=s.gold[c.image_id];
  if(!arr(r.covered_fact_ids,x=>Number.isInteger(x)&&x>=0&&g&&x<g.facts.length)||!unique(r.covered_fact_ids)) fail('Invalid fact coverage');
  if(r.covered_fact_ids.length && (!g||r.gold_snapshot!==snapshot(g))) fail('Stale gold coverage');
  if(r.gold_snapshot && (!g||r.gold_snapshot!==snapshot(g))) fail('Stale gold snapshot');
  if(r.reviewed&&!validReview(c,r,s.reviewer_id)) fail('Reviewed requires human, explicit assessments and no contradiction');
 }
 if(!Array.isArray(s.pairs)) fail('Invalid pairs'); const pairKeys=new Set();
 for(const p of s.pairs) {
  exact(p,['image_id','model_key','scope','left_key','right_key','choice','reviewer_id','seed','updated_at']);
  const l=cells.get(p.left_key),r=cells.get(p.right_key); const order=s.blind_orders[p.image_id]||[];
  if(!l||!r||l.image_id!==p.image_id||r.image_id!==p.image_id||l.model_key!==p.model_key||r.model_key!==p.model_key||l.arm===r.arm||l.scope!=='full120'||r.scope!=='full120'||p.scope!=='full120'||order.indexOf(l.key)<0||order.indexOf(r.key)!==order.indexOf(l.key)+1||!contract.pair_choices.includes(p.choice)||!str(p.reviewer_id)||!p.reviewer_id.trim()||p.reviewer_id!==s.reviewer_id||p.seed!==s.blind_seed||!iso(p.updated_at)) fail('Invalid pair provenance/order');
  // Reviews above already match current output hashes; a preference without both records cannot prove which outputs were compared.
  if(!Object.hasOwn(s.reviews,l.key)||!Object.hasOwn(s.reviews,r.key)) fail('Pair judgment lacks hash-bound output records for both candidates');
  const pk=p.image_id+':'+p.model_key; if(pairKeys.has(pk)) fail('Duplicate pair'); pairKeys.add(pk);
 }
 return s;
}
function setPair(state,left,right,choice) {
 state.pairs=state.pairs.filter(p=>!(p.image_id===left.image_id&&p.model_key===left.model_key)); if(!choice) return;
 // Bind both judged outputs with unscored drafts; existing reviews stay unchanged and nothing becomes Reviewed.
 for(const c of [left,right]) if(!Object.hasOwn(state.reviews,c.key)) state.reviews[c.key]=fresh(c);
 state.pairs.push({image_id:left.image_id,model_key:left.model_key,scope:'full120',left_key:left.key,right_key:right.key,choice,reviewer_id:state.reviewer_id,seed:state.blind_seed,updated_at:new Date().toISOString()});
}
function importState(manifest,contract,current,incoming) {
 validate(manifest,contract,incoming);
 let conflicts=0;
 for(const field of ['gold','reviews']) for(const [k,v] of Object.entries(current[field])) if(!Object.hasOwn(incoming[field],k)||!same(v,incoming[field][k])) conflicts++;
 for(const p of current.pairs) if(!incoming.pairs.some(q=>same(p,q))) conflicts++;
 if((Object.keys(current.reviews).length||Object.keys(current.gold).length||current.pairs.length) && (current.blind_seed!==incoming.blind_seed||current.reviewer_id!==incoming.reviewer_id)) conflicts++;
 if(conflicts) throw Error('Import refused: '+conflicts+' conflicting existing records. Use a fresh report session to restore this file.');
 return clone(incoming);
}

function mergeInitialState(manifest,contract,saved,initial) {
 const current=clone(validate(manifest,contract,saved)), seed=validate(manifest,contract,initial);
 if(current.reviewer_id && current.reviewer_id!==seed.reviewer_id)return current;
 if(!current.reviewer_id && (Object.keys(current.reviews).length||current.pairs.length))return current;
 if(!current.reviewer_id)current.reviewer_id=seed.reviewer_id;
 for(const [id,g] of Object.entries(seed.gold))if(!Object.hasOwn(current.gold,id))current.gold[id]=clone(g);
 for(const [key,value] of Object.entries(seed.reviews)) {
  const prior=current.reviews[key];const untouched=prior && !prior.reviewed && prior.severity==='not_assessed' && !prior.issues.length && !prior.affected_surfaces.length && prior.ocr==='not_assessed' && !prior.notes && !prior.claims.length && !prior.covered_fact_ids.length && !prior.gold_snapshot && prior.ocr_prediction===null;if(prior && !untouched && Date.parse(prior.updated_at)>=Date.parse(value.updated_at))continue;
  const r=clone(value),g=current.gold[r.image_id];
  if(r.gold_snapshot && (!g||r.gold_snapshot!==snapshot(g))){r.covered_fact_ids=[];r.gold_snapshot='';}
  current.reviews[key]=r;
 }
 // Preferences from the active current session remain authoritative; historical preferences are archived separately.
 return validate(manifest,contract,current);
}
function migrateState(manifest,contract,previousManifest,saved,onUnmatchedPair=null) {
 if(!Array.isArray(saved.pairs))throw Error('Invalid previous pairs');
 const previousPairs=clone(saved.pairs), migrated=clone(saved);migrated.pairs=[];
 validate(previousManifest,contract,migrated);
 migrated.dataset_id=manifest.dataset_id;migrated.manifest_sha256=manifest.manifest_sha256;migrated.rubric_version=manifest.rubric_version;migrated.blind_orders=orders(manifest,migrated.blind_seed);
 for(const pair of previousPairs){
  migrated.pairs.push(clone(pair));
  try{validate(manifest,contract,migrated);}
  catch(error){migrated.pairs.pop();if(onUnmatchedPair)onUnmatchedPair(clone(pair),error.message);}
 }
 return validate(manifest,contract,migrated);
}

const api={orders,empty,fresh,snapshot,validate,setPair,importState,validReview,invalidateGold,invalidateReview,stable,mergeInitialState,migrateState};
if(typeof module!=='undefined'&&module.exports) module.exports=api;
root.OperatorReview=api;
if(typeof document==='undefined') return;
const mnode=document.getElementById('operator-review-manifest'); if(!mnode) return;
const manifest=JSON.parse(mnode.textContent), contract=JSON.parse(document.getElementById('operator-review-contract').textContent);
function decisionBlock(id) {const node=document.getElementById(id);try{return node?JSON.parse(node.textContent):null;}catch(e){return null;}}
const rule=decisionBlock('operator-decision-rule'),perf=decisionBlock('operator-decision-performance');
const decisionKeys=new Set(rule?manifest.cells.filter(c=>Object.entries(rule.filter).every(([k,v])=>c[k]===v)).map(c=>c.key):[]);
const storageKey='operator-review:'+manifest.dataset_id+':'+manifest.manifest_sha256+':'+manifest.rubric_version+':'+hash(stable(manifest.cells));
const initialStateNode=document.getElementById('operator-review-initial-state');
const initialState=initialStateNode?validate(manifest,contract,JSON.parse(initialStateNode.textContent)):empty(manifest,'review-1');
let state=clone(initialState),blind=false,crossBlind=false,unsealed=false,storageOK=true,storageDisabled=false,startup='';const unmatchedPriorPairs=[];
try {
 const saved=root.localStorage.getItem(storageKey);
 if(saved){state=mergeInitialState(manifest,contract,JSON.parse(saved),initialState);startup='Restored local annotations and saved historical reviews';}
 const previousNodes=document.getElementById('operator-review-previous-manifests');
 const previousList=previousNodes?JSON.parse(previousNodes.textContent):[];
 let restored=Boolean(saved);
 for(const previous of previousList.slice().reverse()){
  const previousKey='operator-review:'+previous.dataset_id+':'+previous.manifest_sha256+':'+previous.rubric_version+':'+hash(stable(previous.cells));
  const prior=root.localStorage.getItem(previousKey);
  if(!prior)continue;
  const migrated=migrateState(manifest,contract,previous,JSON.parse(prior),(pair,reason)=>unmatchedPriorPairs.push({pair,reason,source_storage_key:previousKey,source_manifest_sha256:previous.manifest_sha256}));
  if(!restored){state=mergeInitialState(manifest,contract,migrated,initialState);restored=true;}
  else {
   state=mergeInitialState(manifest,contract,state,migrated);
   if(state.reviewer_id===migrated.reviewer_id && state.blind_seed===migrated.blind_seed){
    for(const pair of migrated.pairs){
     const index=state.pairs.findIndex(p=>p.image_id===pair.image_id&&p.model_key===pair.model_key);
     if(index<0)state.pairs.push(clone(pair));
     else if(Date.parse(state.pairs[index].updated_at)<Date.parse(pair.updated_at))state.pairs[index]=clone(pair);
    }
    state=validate(manifest,contract,state);
   }
  }
  startup='Preserved earlier browser annotations and merged saved historical reviews';
 }
} catch(e){storageOK=false;storageDisabled=true;startup='Saved annotations retained without overwrite; local restore needs attention. Export JSON to keep this session. '+e.message;}
if(unmatchedPriorPairs.length)startup+=' Unmatched prior preferences remain in their unchanged browser saves; use Export unmatched prior preferences to keep a portable copy.';
function el(tag,text,attrs={}) {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;}
function button(text,fn) {const b=el('button',text,{type:'button'});b.addEventListener('click',fn);return b;}
function field(parent,label,node) {const l=el('label');l.append(el('span',label),node);parent.append(l);return node;}
function select(values,value) {const n=el('select');for(const v of values)n.append(el('option',v.replaceAll('_',' '),{value:v}));n.value=value;return n;}
function textarea(value) {const n=el('textarea');n.value=value; n.rows=2; return n;}
const toolbar=document.getElementById('operator-toolbar'); toolbar.append(el('strong','Human accuracy review'));
const reviewer=field(toolbar,'Reviewer name',el('input',undefined,{type:'text',autocomplete:'name'})); reviewer.value=state.reviewer_id;
const status=el('p',startup,{'aria-live':'polite',role:'status'}), count=el('span');
const seed=field(toolbar,'Blind order seed',el('input',undefined,{type:'text'}));seed.value=state.blind_seed;
const blindButton=button('Enter blind A/B',()=>{blind=!blind;crossBlind=false;applyBlind();});toolbar.append(blindButton);
const crossButton=button(TEXT.crossModel,()=>{crossBlind=!crossBlind;blind=false;applyBlind();});toolbar.append(crossButton);
crossButton.disabled=!rule||!root.OperatorCrossModel;
if(crossButton.disabled)crossButton.title=TEXT.crossModelUnavailable;
toolbar.append(button('Export JSON',()=>{const blob=new Blob([JSON.stringify(state,null,2)],{type:'application/json'}); const a=el('a',undefined,{download:'operator-reviews.json',href:URL.createObjectURL(blob)});a.click();setTimeout(()=>URL.revokeObjectURL(a.href),0);}));
if(unmatchedPriorPairs.length)toolbar.append(button('Export unmatched prior preferences ('+unmatchedPriorPairs.length+')',()=>{const blob=new Blob([JSON.stringify({schema:'operator-review-unmatched-prior-preferences/v1',source_custody:'Original browser saves retained unchanged',records:unmatchedPriorPairs},null,2)],{type:'application/json'});const link=el('a',undefined,{download:'unmatched-prior-preferences.json',href:URL.createObjectURL(blob)});link.click();setTimeout(()=>URL.revokeObjectURL(link.href),0);}));
const file=field(toolbar,'Import JSON',el('input',undefined,{type:'file',accept:'.json,application/json'}));
const metrics=el('details');metrics.append(el('summary','Accuracy and paired lexicon metrics')); const metricBody=el('div');metrics.append(metricBody);toolbar.append(count,status,metrics);
const decisionPanel=el('details',undefined,{id:'operator-decision'}),decisionHost=el('div');
decisionPanel.append(el('summary',TEXT.decisionTitle),decisionHost);toolbar.append(decisionPanel);
function renderDecision() {
 if(blind||crossBlind)unsealed=false;
 decisionHost.replaceChildren();
 if(!rule||!perf||!root.OperatorDecision||typeof root.OperatorDecision.render!=='function') {decisionHost.append(el('p',TEXT.decisionUnavailable));return;}
 try {root.OperatorDecision.render(decisionHost,{manifest,state:clone(state),perf,rule,contract,unsealed,onUnseal:()=>{if(blind||crossBlind)return;unsealed=true;renderDecision();}});}
 catch(e) {decisionHost.replaceChildren(el('p',TEXT.decisionUnavailable));}
}
const cellNodes=new Map(), cardNodes=new Map(), summaries=new Map(), cellFeedback=new Map();
function persist(message='') {
 let saved=false;
 try {if(storageDisabled)throw Error('Persistence disabled after invalid or inaccessible stored data');root.localStorage.setItem(storageKey,JSON.stringify(state));saved=true;storageOK=true;} catch(e) {storageOK=false;}
 status.textContent=(message?message+'. ':'')+(saved?'Saved locally. Export JSON for a portable copy.':'In-memory only: local persistence unavailable. Export JSON before closing.');
 updateCounts();renderMetrics();cellFeedback.forEach(update=>update());renderDecision();
}
function updateCounts() {
 if(crossBlind) {
  try {const progress=root.OperatorCrossModel.progress(manifest,rule,state,contract);count.textContent=TEXT.decisionReviewed+' '+progress.done+' / '+progress.total;}
  catch(e) {count.textContent=TEXT.progressUnavailable;}
  return;
 }
 const rs=Object.values(state.reviews);count.textContent='Reviewed '+rs.filter(r=>r.reviewed).length+' / '+manifest.cells.length+' observed cells; uncertain '+rs.filter(r=>r.reviewed&&(r.severity==='uncertain'||r.ocr==='uncertain')).length;
}
const SCOPES=[["full120", "Latest high-precision round \u00b7 matched A/B groups"], ["reference_pilot", "reference_pilot"], ["generation_failure_pilot", "generation_failure_pilot"], ["historical_full120", "Historical 120-image human assessments (archive)"], ["historical_caption_reference", "Historical caption references (archive)"], ["historical_pilot", "Historical development/pilot (archive)"], ["historical_diagnostic30", "Historical diagnostic subset (archive)"]];
const scopeNames={full120:'Full 120',diagnostic30:'UD diagnostic',caption_reference:'Caption reference',pilot:'Pilot'},modeNames={off:'Lexicon off',on:'Lexicon on',caption:'Caption only'};
const ARM_HEAD=['Model','Mode','Scope','Reviewed of N','Confirmed error-free n/N (%)','Major issues n/N','Unsupported n/N','OCR errors n/N','Salient recall (% with gold n)'];
const PAIR_HEAD=['Model','Paired n','On wins','Off wins','Ties','Both unusable','Cannot judge','Net preference, on − off (%, 95% CI)','Confirmed accuracy Δ, on − off (pp, 95% CI)'];
// Display only: library values are rounded for reading, never recomputed; empty denominators read N/A.
const round1=x=>String(Math.round(x*1000)/10), pct=x=>x==null?'N/A':round1(x)+'%', signed=(x,unit)=>x==null?'N/A':(x>0?'+':'')+round1(x)+unit;
const interval=(x,unit)=>x?'95% CI '+signed(x[0],unit)+' to '+signed(x[1],unit):'CI N/A';
const ratio=(n,d,rate)=>!d?'N/A':typeof n==='number'?n+'/'+d:pct(rate)+' of '+d;
const modelNames=new Map(manifest.cells.map(c=>[c.model_key,c.model_label]));
function armCells(t) {const g=t.generation_errors;return [t.model_label,modeNames[t.arm]||t.arm,scopeNames[t.scope]||t.scope,t.reviewed+' of '+t.total+(g?' ('+g+' generation error'+(g>1?'s':'')+')':''),t.reviewed?ratio(t.confirmed_error_free,t.reviewed,t.confirmed_error_free_rate)+' ('+pct(t.confirmed_error_free_rate)+')':'N/A',ratio(t.major_issues,t.reviewed,t.major_issue_rate),ratio(t.unsupported_count,t.reviewed,t.unsupported_rate),ratio(t.ocr_errors,t.ocr_assessed,t.ocr_error_rate),t.salient_images?pct(t.salient_recall)+' (gold n='+t.salient_images+')':'N/A'];}
function pairCells(p) {return [modelNames.get(p.model_key)||p.model_key,...[p.n_pairs,p.on_better,p.off_better,p.ties,p.both_unusable,p.unjudgeable].map(String),p.n_pairs?signed(p.net_preference,'%')+' ('+interval(p.net_preference_ci95,'%')+')':'N/A',p.accuracy_matched_n?signed(p.accuracy_delta,' pp')+' ('+interval(p.accuracy_delta_ci95,' pp')+'; n='+p.accuracy_matched_n+')':'N/A'];}
function metricTable(headers,rows) {const wrap=el('div',undefined,{class:'operator-metrics-scroll'}),table=el('table'),head=el('tr');headers.forEach(h=>head.append(el('th',h,{scope:'col'})));table.append(head);rows.forEach(cells=>{const tr=el('tr');cells.forEach(v=>tr.append(el('td',v)));table.append(tr);});wrap.append(table);return wrap;}
function machineTable(rows) {const fields=[...new Set(rows.flatMap(Object.keys))];return metricTable(fields,rows.map(row=>fields.map(f=>row[f]==null?'N/A':typeof row[f]==='object'?JSON.stringify(row[f]):String(row[f]))));}
function renderMetrics() {
 metrics.hidden=blind||crossBlind;
 metricBody.replaceChildren();if(blind||crossBlind) {metricBody.append(el('p','Exit blind mode to see model metrics.'));return;}
 if(!root.OperatorMetrics || typeof root.OperatorMetrics.summarize!=='function') {metricBody.append(el('p','Metrics unavailable: operator-metrics.js has not been supplied.'));return;}
 try {
 const result=root.OperatorMetrics.summarize(manifest,clone(state));
 for(const [scope,title] of SCOPES) {
  const arms=(result.arms||[]).filter(t=>t.scope===scope),paired=(result.paired||[]).filter(p=>p.scope===scope);if(!arms.length&&!paired.length)continue;
  const section=el('section',undefined,{class:'operator-metrics-section'});section.append(el('h3',title));
  if(arms.length)section.append(metricTable(ARM_HEAD,arms.map(armCells)));
  if(paired.length)section.append(el('h4','Paired lexicon off/on: same image and model'),metricTable(PAIR_HEAD,paired.map(pairCells)));
  const audit=el('details',undefined,{class:'operator-audit'});audit.append(el('summary','Audit details: claim precision and all machine fields'));
  audit.append(metricTable(['Model','Mode','Claim precision (macro, cells n)'],arms.map(t=>[t.model_label,modeNames[t.arm]||t.arm,t.claims_assessed?pct(t.claim_precision)+' (cells n='+t.claims_assessed+')':'N/A'])));
  for(const rows of [arms,paired]) if(rows.length)audit.append(machineTable(rows));
  section.append(audit);metricBody.append(section);
 } (result.notes||[]).forEach(note=>metricBody.append(el('p',String(note))));
 } catch(e) {metricBody.append(el('p','Metrics unavailable: '+e.message));}
}
reviewer.addEventListener('change',()=>{if(Object.values(state.reviews).some(r=>r.reviewed)||state.pairs.length){reviewer.value=state.reviewer_id;status.textContent='Reviewer is bound to recorded judgments. Export and use a fresh session for another reviewer.';return;}state.reviewer_id=reviewer.value.trim();persist();});
seed.addEventListener('change',()=>{if(state.pairs.length){seed.value=state.blind_seed;status.textContent='Seed is bound to pair judgments; use a fresh session to change it.';return;}state.blind_seed=seed.value.trim()||'review-1';seed.value=state.blind_seed;state.blind_orders=orders(manifest,state.blind_seed);applyBlind();persist();});
file.addEventListener('change',async()=>{try {const incoming=JSON.parse(await file.files[0].text());const next=importState(manifest,contract,state,incoming);state=next;reviewer.value=state.reviewer_id;seed.value=state.blind_seed;build();applyBlind();persist('Import restored');}catch(e){status.textContent='Import refused: '+e.message;}file.value='';});
const issueLabels=['Invented / unsupported','Wrong subject / object','Attributes / counts','Action / relation','Wrong OCR','Omitted relevant text','Missing essential fact','Wrong context / identity'];
function buildCell(c,host) {
 host.replaceChildren();const r=state.reviews[c.key]||fresh(c);
 const details=el('details',undefined,{class:'operator-details'}), summary=el('summary');details.append(summary);host.append(details);summaries.set(c.key,summary);
 const updateSummary=()=>{summary.textContent=!r.reviewed?'Unreviewed':r.severity==='uncertain'||r.ocr==='uncertain'?'Needs adjudication':'Reviewed';};updateSummary();
 const active=!c.generation_error&&c.surfaces.length>0;
 const check=el('input',undefined,{type:'checkbox'});check.checked=r.reviewed;check.disabled=!active;
 const clean=el('input',undefined,{type:'checkbox'});clean.disabled=!active;field(details,'No issues with this description',clean);
 if(!active) details.append(el('p',c.generation_error?'Pipeline generation error — factual scoring disabled; retained in denominator.':'No observed description surface — factual scoring disabled; retained in denominator.'));
 const feedback=el('p',undefined,{role:'status','aria-live':'polite',id:'review-feedback-'+c.key});details.append(feedback);
 [check,clean].forEach(n=>n.setAttribute('aria-describedby','review-feedback-'+c.key));
 const severity=field(details,'Severity',select(contract.severity,r.severity));severity.disabled=!active;
 const ocr=field(details,'OCR assessment',select(contract.ocr,r.ocr));ocr.disabled=!active;
 const completion=el('fieldset');completion.append(el('legend','Complete review'));details.append(completion);
 field(completion,'Reviewed: all present surfaces assessed',check);
 function updateFeedback() {
  clean.checked=r.severity==='none';severity.value=r.severity;
  const incomplete=crossBlind&&decisionKeys.has(c.key)&&(r.severity==='not_assessed'||r.ocr==='not_assessed');
  check.disabled=!active||incomplete;
  if(!active) {feedback.textContent='Factual scoring disabled.';return;}
  const missing=[];
  if(!state.reviewer_id.trim())missing.push('enter reviewer name in the toolbar');
  if(r.severity==='not_assessed')missing.push('select severity');
  if(crossBlind&&decisionKeys.has(c.key)&&r.ocr==='not_assessed')missing.push(TEXT.ocrRequired);
  if(r.severity==='none'&&r.issues.length)missing.push('resolve conflict: uncheck issue flags only if incorrect, or change severity from none');
  const recorded=Object.hasOwn(state.reviews,c.key);
  // Severity none covers factual issues only: OCR errors and uncertainty stay visible, reviewed or pending.
  // Existing A/B reviews permit unknown OCR; cross-model reviews require an explicit assessment.
  const unsure=[r.severity==='uncertain'&&'severity',r.ocr==='uncertain'&&'OCR'].filter(Boolean);
  const caveats=(unsure.length?'Needs adjudication: '+unsure.join(' and ')+' uncertain; not confirmed error-free. ':'')+
   (r.ocr==='wrong'?'OCR wrong: OCR error recorded; not error-free. ':r.ocr==='omitted'?'OCR omitted: OCR error recorded; incomplete even if factually accurate. ':
    r.ocr==='not_assessed'?(crossBlind&&decisionKeys.has(c.key)?TEXT.assessmentsRequired+' ':'OCR not assessed (optional; not required for Reviewed)'+(r.severity==='none'?': text accuracy unknown, so not confirmed error-free. ':'. ')):'');
  const noIssues=r.severity==='none'&&!caveats&&!r.issues.length;
  feedback.textContent=(r.reviewed?(noIssues?'Reviewed — no issues. ':r.severity==='none'?'Reviewed — severity none. ':'Reviewed. '):r.severity==='none'?(caveats?'No issues selected (severity none) — Unreviewed. ':'No issues selected — Unreviewed. '):'Unreviewed. ')+caveats+
   (recorded?(storageOK?'Saved locally. ':'In-memory only; export JSON before closing. '):'')+
   (missing.length?'To mark Reviewed: '+missing.join('; ')+'.':r.reviewed?'All present surfaces assessed.':'Reconfirm Reviewed after assessing all present surfaces.');
 }
 cellFeedback.set(c.key,updateFeedback);updateFeedback();
 clean.addEventListener('change',()=>{r.severity=clean.checked?'none':'not_assessed';changed();});
 function changed() {invalidateReview(r);check.checked=false;state.reviews[c.key]=r;updateSummary();persist();}
 severity.addEventListener('change',()=>{r.severity=severity.value;changed();});ocr.addEventListener('change',()=>{r.ocr=ocr.value;changed();});
 const issues=el('fieldset');issues.append(el('legend','Factual issues'));details.append(issues);
 contract.issues.forEach((issue,i)=>{const n=el('input',undefined,{type:'checkbox'});n.checked=r.issues.includes(issue);n.disabled=!active;field(issues,issueLabels[i],n);n.addEventListener('change',()=>{r.issues=contract.issues.filter(x=>x===issue?n.checked:r.issues.includes(x));if(n.checked&&r.severity==='none')r.severity='not_assessed';changed();});});
 const surfaces=el('fieldset');surfaces.append(el('legend','Affected surfaces'));details.append(surfaces);
 c.surfaces.forEach(s=>{const n=el('input',undefined,{type:'checkbox'});n.checked=r.affected_surfaces.includes(s.name);n.disabled=!active;field(surfaces,s.name,n);n.addEventListener('change',()=>{r.affected_surfaces=c.surfaces.map(s=>s.name).filter(x=>x===s.name?n.checked:r.affected_surfaces.includes(x));changed();});});
 const notes=field(details,'Corrected facts / exact quote / notes',textarea(r.notes));notes.addEventListener('change',()=>{r.notes=notes.value;changed();});
 const advanced=el('details');advanced.append(el('summary','Optional claim and gold coverage audit'));details.append(advanced);
 const prediction=field(advanced,'OCR prediction (required model text span only; blank means unassessed)',textarea(r.ocr_prediction||''));prediction.disabled=!active;prediction.addEventListener('change',()=>{r.ocr_prediction=prediction.value===''?null:prediction.value;changed();});
 const claims=el('div');advanced.append(claims);
 function claimRow(claim) {
  const row=el('fieldset'),t=field(row,'Claim',textarea(claim.text)),s=field(row,'Surface',select(c.surfaces.map(s=>s.name),claim.surface)),v=field(row,'Verdict',select(['',...contract.claim_verdicts],claim.verdict));
  function sync(){
   Object.assign(claim,{text:t.value,surface:s.value,verdict:v.value});
   const complete=!!(t.value.trim()&&v.value);
   // Keep the visible draft row, but export only complete claims and reconfirm every edit.
   if(complete){if(!r.claims.includes(claim))r.claims.push(claim);}else r.claims=r.claims.filter(x=>x!==claim);
   changed();
   if(!complete)status.textContent='Claim needs nonempty text and explicit verdict before it can be recorded. '+status.textContent;
  }
  [t,s,v].forEach(n=>{n.addEventListener('input',sync);n.addEventListener('change',sync);});row.append(button('Remove claim',()=>{r.claims=r.claims.filter(x=>x!==claim);row.remove();changed();}));claims.append(row);
 }
 r.claims.forEach(claimRow);const add=button('Add manual claim',()=>claimRow({text:'',surface:c.surfaces[0].name,verdict:''}));add.disabled=!active;advanced.append(add);
 const g=state.gold[c.image_id]; if(g&&g.facts.length) {
  advanced.append(el('p','Mark only human gold facts covered by this output. Reconfirm Reviewed after changes.'));
  g.facts.forEach((fact,i)=>{const n=el('input',undefined,{type:'checkbox'});n.checked=r.gold_snapshot===snapshot(g)&&r.covered_fact_ids.includes(i);n.disabled=!active;field(advanced,fact,n);n.addEventListener('change',()=>{if(r.gold_snapshot!==snapshot(g))r.covered_fact_ids=[];r.gold_snapshot=snapshot(g);r.covered_fact_ids=g.facts.map((_,j)=>j).filter(j=>j===i?n.checked:r.covered_fact_ids.includes(j));changed();});});
 }
 check.addEventListener('change',()=>{
  if(check.checked&&crossBlind&&decisionKeys.has(c.key)&&(r.severity==='not_assessed'||r.ocr==='not_assessed')) {check.checked=false;updateFeedback();status.textContent=TEXT.assessmentsRequired;return;}
  if(check.checked&&!validReview(c,r,state.reviewer_id)) {check.checked=false;updateFeedback();status.textContent='Reviewed refused: enter reviewer name, select severity, and resolve severity none with issue flags.';return;}
  r.reviewed=check.checked;if(r.reviewed&&state.gold[c.image_id])r.gold_snapshot=snapshot(state.gold[c.image_id]);r.updated_at=new Date().toISOString();state.reviews[c.key]=r;updateSummary();persist();
 });
}
function buildGold(image,card) {
 const old=card.querySelector('.operator-gold');if(old)old.remove();
 const details=el('details',undefined,{class:'operator-gold'});details.append(el('summary','Shared image-first ground truth'));
 details.append(el('p','Inspect image pixels first. Record salient facts and literal OCR independently of candidate descriptions.'));
 const hide=el('input',undefined,{type:'checkbox'});field(details,'Hide descriptions while editing ground truth',hide);hide.checked=card.classList.contains('operator-hide-descriptions');hide.addEventListener('change',()=>card.classList.toggle('operator-hide-descriptions',hide.checked));
 const g=state.gold[image.image_id]||{input_sha256:image.input_sha256,facts:[],ocr_state:'not_assessed',ocr_truth:'',revision:0};
 const facts=field(details,'Salient facts (one per line)',textarea(g.facts.join('\n'))),ocrState=field(details,'Image OCR state',select(['not_assessed','present','none','unreadable'],g.ocr_state)),truth=field(details,'Exact OCR text (preserve characters and line breaks)',textarea(g.ocr_truth));
 details.append(button('Save ground truth',()=>{const next={input_sha256:image.input_sha256,facts:facts.value.split(/\r?\n/).filter(s=>s.trim()),ocr_state:ocrState.value,ocr_truth:truth.value,revision:g.revision};if(invalidateGold(state,image.image_id,next)){manifest.cells.filter(c=>c.image_id===image.image_id).forEach(c=>buildCell(c,cellNodes.get(c.key)));persist('Ground truth changed; old coverage cleared and reviews require reconfirmation');}else status.textContent='Ground truth unchanged; revision retained.';}));
 card.querySelector('.image-pane').append(details);
}
function build() {
 manifest.cells.forEach(c=>{const host=document.querySelector('[data-review-key="'+c.key+'"]');if(!host)throw Error('Missing cell '+c.key);cellNodes.set(c.key,host);buildCell(c,host);});
 manifest.images.forEach(i=>{const card=document.querySelector('[data-image-id="'+i.image_id+'"]');cardNodes.set(i.image_id,card);buildGold(i,card);});
 renderDecision();
}
const originals=new Map();
function restoreAttribute(node,name,value) {if(value===null)node.removeAttribute(name);else node.setAttribute(name,value);}
function applyBlind() {
 if(blind||crossBlind)unsealed=false;
 document.body.classList.toggle('operator-blind',blind||crossBlind);
 document.body.classList.toggle('operator-crossmodel',crossBlind);
 blindButton.textContent=blind?'Exit blind A/B (reveal labels)':'Enter blind A/B';
 crossButton.textContent=crossBlind?TEXT.exitCrossModel:TEXT.crossModel;
 const crossOrders=crossBlind?root.OperatorCrossModel.order(manifest,rule,state.blind_seed):{};
 manifest.images.forEach(image=>{
  const card=cardNodes.get(image.image_id),table=card.querySelector('.description-table'),hr=table.tHead.rows[0],tr=table.tBodies[0].rows[0];
  if(!originals.has(image.image_id))originals.set(image.image_id,{heads:[...hr.children],cells:[...tr.children],headNodes:[...hr.childNodes],cellNodes:[...tr.childNodes],contents:[...hr.children].map(n=>[...n.childNodes]),attributes:[card,...hr.children,...tr.children].map(n=>[n,n.getAttribute('hidden'),n.getAttribute('class')]),identifiers:[...table.querySelectorAll(CROSS_MODEL_IDENTIFIERS)].map(n=>[n,n.getAttribute('hidden')])});
  const original=originals.get(image.image_id);for(const added of ['.operator-pairs','.operator-blind-hint'])card.querySelectorAll(added).forEach(n=>n.remove());
  original.heads.forEach((h,i)=>h.replaceChildren(...original.contents[i]));
  hr.replaceChildren(...original.headNodes);tr.replaceChildren(...original.cellNodes);
  original.attributes.forEach(([n,hidden,classes])=>{restoreAttribute(n,'hidden',hidden);if(n!==card)restoreAttribute(n,'class',classes);});
  original.identifiers.forEach(([n,hidden])=>restoreAttribute(n,'hidden',hidden));
  if(!blind&&!crossBlind)return;
  if(crossBlind) {
   const keys=crossOrders[image.image_id]||[];
   card.hidden=!keys.length;
   original.identifiers.forEach(([n])=>n.hidden=true);
   original.heads.forEach(h=>h.hidden=true);original.cells.forEach(td=>td.hidden=true);
   keys.forEach((key,index)=>{
    const td=cellNodes.get(key).closest('td'),i=original.cells.indexOf(td),h=original.heads[i];
    h.textContent=TEXT.candidates[index];h.hidden=false;td.hidden=false;
    h.classList.add('operator-crossmodel-neutral');td.classList.add('operator-crossmodel-neutral');
    hr.append(h);tr.append(td);
   });
   if(keys.length)(card.querySelector('.comparison-row')||card.querySelector('.description-scroll')).before(el('p',TEXT.crossModelHint,{class:'operator-blind-hint'}));
   return;
  }
  const keys=state.blind_orders[image.image_id]||[];const panel=el('div',undefined,{class:'operator-pairs'});
  // Source hints count every observed column; describe only the visible blinded columns and leave source hints untouched.
  const hint=el('p','Blind A/B: image stays at left; scroll across '+keys.length+' blinded full-comparison columns →',{class:'operator-blind-hint'});panel.append(el('p','Blind presentation only; source remains inspectable. Compare the same image and all present surfaces.'));
  original.heads.forEach(h=>h.hidden=true);original.cells.forEach(td=>td.hidden=true);
  keys.forEach((key,index)=>{const td=cellNodes.get(key).closest('td'),i=original.cells.indexOf(td),h=original.heads[i];h.textContent='Group '+(Math.floor(index/2)+1)+' · '+(index%2?'B':'A');h.hidden=false;td.hidden=false;hr.append(h);tr.append(td);});
  for(let j=0;j<keys.length;j+=2) {
   const left=manifest.cells.find(c=>c.key===keys[j]),right=manifest.cells.find(c=>c.key===keys[j+1]);if(!right)continue;
   const existing=state.pairs.find(p=>p.image_id===image.image_id&&p.model_key===left.model_key);
   const choice=select(['','left','right','tie','both_unusable','unjudgeable'],existing?existing.choice:'');
   [...choice.options].forEach(o=>{o.textContent=({'':'Unscored','left':'A','right':'B',tie:'Tie',both_unusable:'Both unusable',unjudgeable:'Cannot judge'})[o.value];});
   field(panel,'Group '+(j/2+1)+' preference',choice);
   choice.addEventListener('change',()=>{if(choice.value&&!state.reviewer_id.trim()){choice.value=existing?existing.choice:'';status.textContent='Enter reviewer name before recording a pair judgment.';return;}setPair(state,left,right,choice.value);persist();});
  }// Outside the two-column image/description grid, so the panel cannot displace the description strip.
  (card.querySelector('.comparison-row')||card.querySelector('.description-scroll')).before(hint,panel);
 });updateCounts();renderMetrics();cellFeedback.forEach(update=>update());renderDecision();
}
build();updateCounts();renderMetrics();
if(!startup)status.textContent='Blank reviews are unscored. Local persistence is best effort; export JSON to keep work.';
// Probe storage immediately so blocked file origins never display a false persistence claim.
try {if(storageDisabled)throw Error('Persistence disabled');root.localStorage.setItem(storageKey,JSON.stringify(state));}catch(e){storageOK=false;status.textContent='In-memory only: local persistence unavailable. Export JSON before closing.';}
cellFeedback.forEach(update=>update());
})(typeof window!=='undefined'?window:globalThis);
