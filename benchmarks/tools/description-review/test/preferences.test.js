'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const f=require('./fixture');
const cross=require('../operator-crossmodel');
const review=require('../operator-review');
const {manifest,contract,state:initial}=f.loadReport(),rule=f.loadRule();
const seeded=()=>structuredClone(initial);
const first=Object.entries(cross.order(manifest,rule,initial.blind_seed)).find(([,keys])=>keys.length===3);

test('A/B/C top choice binds all displayed outputs and survives raw JSON import',()=>{
 const s=seeded(),[id,keys]=first,prior=JSON.stringify(s.pairs),before=JSON.stringify(s.reviews);
 cross.setPreference(manifest,rule,s,id,keys[2]);
 const p=s.model_preferences.ballots[0];
 assert.deepEqual(p.candidate_keys,keys);
 assert.equal(p.selected_key,keys[2]);assert.equal(p.choice,'preferred');
 assert.equal(p.reviewer_id,s.reviewer_id);assert.equal(p.seed,s.blind_seed);
 for(const k of keys)assert.equal(s.reviews[k].output_sha256,manifest.cells.find(c=>c.key===k).output_sha256);
 for(const [k,r] of Object.entries(JSON.parse(before)))assert.deepEqual(s.reviews[k],r);
 assert.equal(JSON.stringify(s.pairs),prior);
 assert.equal(review.validate(manifest,contract,s),s);
 const restored=review.importState(manifest,contract,review.empty(manifest,s.blind_seed),JSON.parse(JSON.stringify(s)));
 assert.deepEqual(restored.model_preferences,s.model_preferences);
 cross.setPreference(manifest,rule,s,id,keys[0]);assert.equal(s.model_preferences.ballots.length,1);
 assert.equal(s.model_preferences.ballots[0].selected_key,keys[0]);
 cross.setPreference(manifest,rule,s,id,'');assert.equal(s.model_preferences.ballots.length,0);
});

test('top-choice ranking keeps different candidate rosters separate and ties explicit',()=>{
 const s=seeded(),orders=cross.order(manifest,rule,s.blind_seed);
 const ids=Object.keys(orders).filter(id=>orders[id].length===3);
 const winner='qwen3-vl-8b-f16';
 for(const id of ids.slice(0,2))cross.setPreference(manifest,rule,s,id,orders[id].find(k=>manifest.cells.find(c=>c.key===k).physical_model_id===winner));
 cross.setPreference(manifest,rule,s,ids[2],'tie');
 cross.setPreference(manifest,rule,s,ids[3],'all_unusable');
 cross.setPreference(manifest,rule,s,ids[4],'unjudgeable');
 const partial=Object.keys(orders).find(id=>orders[id].length===2);
 cross.setPreference(manifest,rule,s,partial,orders[partial][0]);
 const result=cross.summarizePreferences(manifest,rule,s);
 assert.equal(result.groups.length,2);
 const group=result.groups.find(g=>g.models.length===3);
 assert.equal(group.available_images,28);assert.equal(group.recorded,5);assert.equal(group.unscored,23);
 assert.equal(group.ties,1);assert.equal(group.all_unusable,1);assert.equal(group.unjudgeable,1);
 assert.equal(group.models[0].physical_model_id,winner);assert.equal(group.models[0].wins,2);
 assert.equal(group.models[0].rank,1);
 assert.equal(group.models[1].rank,2);assert.equal(group.models[2].rank,2);
 assert.equal(group.models[0].selection_rate,0.5); // 2 picks / 4 judgeable ballots, not 2/2
 const empty=cross.summarizePreferences(manifest,rule,seeded());
 assert.ok(empty.groups.flatMap(g=>g.models).every(m=>m.rank===null&&m.selection_rate===null));
});

test('ties, unusable and cannot judge round-trip without inventing a model winner',()=>{
 for(const choice of ['tie','all_unusable','unjudgeable']){
  const s=seeded();cross.setPreference(manifest,rule,s,first[0],choice);
  review.validate(manifest,contract,s);
  assert.equal(s.model_preferences.ballots[0].selected_key,null);
  assert.ok(cross.summarizePreferences(manifest,rule,s).groups.flatMap(g=>g.models).every(m=>m.rank===null));
 }
});

test('invalid preference provenance, order, duplicates and hash mismatches are refused',()=>{
 const s=seeded();cross.setPreference(manifest,rule,s,first[0],first[1][0]);
 for(const change of [
  x=>x.model_preferences.ballots.push(structuredClone(x.model_preferences.ballots[0])),
  x=>x.model_preferences.ballots[0].candidate_keys.reverse(),
  x=>x.model_preferences.ballots[0].selected_key='not-a-candidate',
  x=>x.model_preferences.ballots[0].reviewer_id='someone else',
  x=>x.model_preferences.ballots[0].seed='other',
  x=>x.model_preferences.ballots[0].choice='bogus',
  x=>delete x.reviews[first[1][1]],
  x=>x.reviews[first[1][0]].output_sha256='stale'
 ]){const bad=structuredClone(s);change(bad);assert.throws(()=>review.validate(manifest,contract,bad));}
 const anonymous=seeded();anonymous.reviewer_id='';assert.throws(()=>cross.setPreference(manifest,rule,anonymous,first[0],first[1][0]),/reviewer/i);
});

test('ranking export is self-contained and imports without dropping preference judgments',()=>{
 const s=seeded();cross.setPreference(manifest,rule,s,first[0],first[1][1]);
 const output=cross.rankingExport(manifest,rule,s);
 assert.equal(output.schema,'description-review-ranking/v1');
 assert.deepEqual(output.manifest,manifest);assert.deepEqual(output.annotations,s);
 assert.deepEqual(output.preference_ranking,cross.summarizePreferences(manifest,rule,s));
 assert.deepEqual(review.importState(manifest,contract,review.empty(manifest,s.blind_seed),JSON.parse(JSON.stringify(output))),s);
 const incoming=structuredClone(s);incoming.model_preferences.ballots=[];
 assert.throws(()=>review.importState(manifest,contract,s,incoming),/conflict/i);
 assert.equal(review.validate(manifest,contract,seeded()).schema,'bakeoff-operator-reviews/v1');
});
