(function(root){
'use strict';
function hash(s) { let h=2166136261; for (const ch of s) { h^=ch.charCodeAt(0); h=Math.imul(h,16777619); } return h>>>0; }
function cells(manifest, rule) { return manifest.cells.filter(c=>Object.entries(rule.filter).every(([key,value])=>c[key]===value)); }
function order(manifest, rule, seed) {
 const result={};
 for(const cell of cells(manifest,rule)) {
  if(!Object.hasOwn(result,cell.image_id))Object.defineProperty(result,cell.image_id,{value:[],enumerable:true});
  result[cell.image_id].push(cell.key);
 }
 for(const [id,keys] of Object.entries(result))keys.sort((a,b)=>hash(seed+'|'+id+'|'+a)-hash(seed+'|'+id+'|'+b)||a.localeCompare(b));
 return result;
}
function progress(manifest, rule, state, contract, predicate) {
 const reviewed=predicate||(root.OperatorMetrics&&root.OperatorMetrics.decisionReviewed);
 const decision=cells(manifest,rule);
 const pending_keys=decision.filter(c=>!reviewed(c,state.reviews[c.key],contract,state.reviewer_id)).map(c=>c.key);
 return {done:decision.length-pending_keys.length,total:decision.length,pending_keys};
}
const PREFERENCE_SCHEMA='description-model-preferences/v1';
const clone=value=>JSON.parse(JSON.stringify(value));
const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const check=(condition,message)=>{if(!condition)throw Error(message);};
const ballots=state=>state.model_preferences?state.model_preferences.ballots:[];
function preferenceFilter(filter) {
 check(filter&&Object.keys(filter).sort().join(',')==='arm,extraction_lexicon,scope,writing_lexicon'&&filter.scope==='full120'&&typeof filter.extraction_lexicon==='boolean'&&typeof filter.writing_lexicon==='boolean'&&filter.arm===(filter.writing_lexicon?'on':'off'),'Invalid model preference filter');
}
function validatePreferences(manifest,state,rule) {
 const extension=state.model_preferences;if(extension===undefined)return state;
 check(extension&&Object.keys(extension).sort().join(',')==='ballots,filter,schema'&&extension.schema===PREFERENCE_SCHEMA&&Array.isArray(extension.ballots),'Invalid model preference extension');
 preferenceFilter(extension.filter);
 if(rule)for(const key of Object.keys(extension.filter))check(extension.filter[key]===rule.filter[key],'Model preference comparison filter mismatch');
 const orders=order(manifest,{filter:extension.filter},state.blind_seed),byKey=new Map(manifest.cells.map(c=>[c.key,c])),seen=new Set();
 for(const p of extension.ballots) {
  check(p&&Object.keys(p).sort().join(',')==='candidate_keys,choice,image_id,reviewer_id,seed,selected_key,updated_at','Invalid model preference fields');
  check(!seen.has(p.image_id),'Duplicate model preference');seen.add(p.image_id);
  check(Array.isArray(p.candidate_keys)&&p.candidate_keys.length>=2&&equal(p.candidate_keys,orders[p.image_id]),'Invalid model preference candidate order');
  check(typeof p.reviewer_id==='string'&&p.reviewer_id.trim()&&p.reviewer_id===state.reviewer_id&&p.seed===state.blind_seed,'Invalid model preference reviewer/seed');
  check(typeof p.updated_at==='string'&&/^\d{4}-\d\d-\d\dT/.test(p.updated_at)&&Number.isFinite(Date.parse(p.updated_at)),'Invalid model preference timestamp');
  check(['preferred','tie','all_unusable','unjudgeable'].includes(p.choice),'Invalid model preference choice');
  check(p.choice==='preferred'?p.candidate_keys.includes(p.selected_key)&&!byKey.get(p.selected_key).generation_error:p.selected_key===null,'Invalid preferred candidate');
  for(const key of p.candidate_keys) {
   const c=byKey.get(key),r=state.reviews[key];
   check(r&&r.output_sha256===c.output_sha256&&r.input_sha256===c.input_sha256&&r.image_id===c.image_id,'Model preference lacks hash-bound output records');
  }
 }
 return state;
}
function setPreference(manifest,rule,state,imageId,choice) {
 const keys=order(manifest,rule,state.blind_seed)[imageId]||[];
 check(keys.length>=2,'Model preference requires at least two candidates');
 if(choice)check(typeof state.reviewer_id==='string'&&state.reviewer_id.trim(),'Enter reviewer name before recording a model preference');
 check(!choice||keys.includes(choice)||['tie','all_unusable','unjudgeable'].includes(choice),'Invalid model preference choice');
 const byKey=new Map(manifest.cells.map(c=>[c.key,c]));
 if(keys.includes(choice))check(!byKey.get(choice).generation_error,'A failed generation cannot be preferred');
 preferenceFilter(rule.filter);validatePreferences(manifest,state,rule);
 if(!state.model_preferences)state.model_preferences={schema:PREFERENCE_SCHEMA,filter:clone(rule.filter),ballots:[]};
 state.model_preferences.ballots=ballots(state).filter(p=>p.image_id!==imageId);
 if(!choice)return;
 // Draft records bind what was compared without marking any output Reviewed.
 for(const key of keys)if(!Object.hasOwn(state.reviews,key)) {
  const c=byKey.get(key);state.reviews[key]={output_sha256:c.output_sha256,image_id:c.image_id,input_sha256:c.input_sha256,reviewed:false,severity:'not_assessed',issues:[],affected_surfaces:[],ocr:'not_assessed',notes:'',claims:[],covered_fact_ids:[],gold_snapshot:'',ocr_prediction:null,updated_at:new Date().toISOString()};
 }
 state.model_preferences.ballots.push({image_id:imageId,candidate_keys:keys.slice(),choice:keys.includes(choice)?'preferred':choice,selected_key:keys.includes(choice)?choice:null,reviewer_id:state.reviewer_id,seed:state.blind_seed,updated_at:new Date().toISOString()});
 validatePreferences(manifest,state,rule);
}
function summarizePreferences(manifest,rule,state) {
 validatePreferences(manifest,state,rule);
 const byKey=new Map(manifest.cells.map(c=>[c.key,c])),groups=new Map(),byImage=new Map();
 const identity=c=>c.physical_model_id||c.model_key;
 for(const [id,keys] of Object.entries(order(manifest,rule,state.blind_seed))) {
  if(keys.length<2)continue;
  const ids=keys.map(k=>identity(byKey.get(k))).sort();
  check(new Set(ids).size===ids.length,'Multiple candidates for the same physical model');
  const roster=JSON.stringify(ids);
  if(!groups.has(roster))groups.set(roster,{candidate_models:ids,available_images:0,recorded:0,unscored:0,preferred:0,ties:0,all_unusable:0,unjudgeable:0,models:ids.map(id=>({physical_model_id:id,label:(rule.candidate_labels||{})[id]||id,wins:0,rank:null,selection_rate:null}))});
  const group=groups.get(roster);group.available_images++;byImage.set(id,group);
 }
 for(const p of ballots(state)) {
  const g=byImage.get(p.image_id);g.recorded++;g[p.choice==='tie'?'ties':p.choice]++;
  if(p.choice==='preferred')g.models.find(m=>m.physical_model_id===identity(byKey.get(p.selected_key))).wins++;
 }
 for(const g of groups.values()) {
  g.unscored=g.available_images-g.recorded;g.judgeable=g.preferred+g.ties+g.all_unusable;
  g.models.sort((a,b)=>b.wins-a.wins||a.physical_model_id.localeCompare(b.physical_model_id));
  for(const m of g.models){m.selection_rate=g.judgeable?m.wins/g.judgeable:null;m.rank=g.preferred?1+g.models.filter(other=>other.wins>m.wins).length:null;}
 }
 return {schema:'description-preference-ranking/v1',status:ballots(state).length?'descriptive':'no_preferences',groups:[...groups.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([,value])=>value),notes:[
  'Ranks are explicit top-choice counts within an identical candidate roster and filter, with tied counts sharing rank; no population or factual-quality winner is established.',
  'Selection rate = chosen ballots / (preferred + tie + all-unusable ballots). Cannot-judge and unscored images are reported separately.',
  'Different two- and three-candidate rosters are separate comparisons. Lexicon OFF/ON preferences and historical quality reviews are not cross-model ballots.',
  'Each image contributes at most one ballot per reviewer and comparison. Re-exporting a session does not create independent evidence.'
 ]};
}
function rankingExport(manifest,rule,state) {
 check(state.dataset_id===manifest.dataset_id&&state.manifest_sha256===manifest.manifest_sha256&&state.rubric_version===manifest.rubric_version,'Ranking export provenance mismatch');
 return {schema:'description-review-ranking/v1',manifest:clone(manifest),comparison_rule:clone(rule),annotations:clone(state),preference_ranking:summarizePreferences(manifest,rule,state)};
}
const api={order,progress,setPreference,validatePreferences,summarizePreferences,rankingExport};
if(typeof module==='object'&&module.exports)module.exports=api;else root.OperatorCrossModel=api;
})(typeof globalThis!=='undefined'?globalThis:this);
