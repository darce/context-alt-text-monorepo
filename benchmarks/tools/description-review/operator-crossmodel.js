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
const api={order,progress};
if(typeof module==='object'&&module.exports)module.exports=api;else root.OperatorCrossModel=api;
})(typeof globalThis!=='undefined'?globalThis:this);
