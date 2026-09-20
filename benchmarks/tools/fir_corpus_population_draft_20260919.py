"""Planning-only population lists from existing metadata; no pixel inference or gold labels."""
from pathlib import Path
import collections,csv,hashlib,json,random
root=Path.cwd(); mp=root/'benchmarks/manifests/corpus-manifest-v3r-20260814.json';cp=root/'benchmarks/reports/fir-occlusion-caption-mining-20260904.json'
m=json.loads(mp.read_text()); mining=json.loads(cp.read_text()); entries=m['entries']; by={e['media_id']:e for e in entries}
parent={i:i for i in by}
def find(x):
 while parent[x]!=x: parent[x]=parent[parent[x]];x=parent[x]
 return x
def union(a,b):
 a,b=find(a),find(b)
 if a!=b:parent[max(a,b)]=min(a,b)
seen={}
for e in entries:
 for h in (e.get('sha256'),e.get('sha256_source')):
  if not h:continue
  if h in seen:union(e['media_id'],seen[h])
  else:seen[h]=e['media_id']
canonical={i:find(i) for i in by};groups=collections.defaultdict(list)
for i,c in canonical.items():groups[c].append(i)
def canon(ids):return {canonical[i] for i in ids}
personal={i for i,e in by.items() if e['bucket']=='personal'};editorial=set(by)-personal
frame=canon(personal);caption=canon(x['media_id'] for x in mining['candidates'] if x['bucket']=='personal');tags=canon(i for i in personal if set(by[i]['slice_tags'])&{'masked','sunglasses','occlusion_other'});hard=caption|tags
failed=canon(i for i in mining['failed_run_media_ids'] if i in personal)
keyword_neg=canon(mining['personal_keyword_negative_audit_frame'])-caption-failed
sample=set(random.Random(20260919).sample(sorted(frame),120));negative_sample=set(random.Random(20260920).sample(sorted(keyword_neg),60))
unknown=canon(i for i in personal if not by[i]['named_identities']);zero=canon(i for i in personal if by[i]['detected_face_count']==0);noface=canon(i for i in personal if 'no_faces' in by[i]['flags'])
oldgold={i for i,e in by.items() if e['slice_tags_known']}
# Conservative minimum dependence components from recorded identity links and exact hashes only.
for e in entries:
 for identity in e['named_identities']:
  key=('identity',identity)
  if key in seen:union(e['media_id'],seen[key])
  else:seen[key]=e['media_id']
components=collections.defaultdict(list)
for i in by:components[find(i)].append(i)
coidentity={i:find(i) for i in by}
identity_ids=collections.defaultdict(set)
for e in entries:
 if e['bucket']=='personal':
  for identity in e['named_identities']:identity_ids[identity].add(canonical[e['media_id']])
mate_map={}
for i in sorted(hard):
 names={n for alias in groups[i] for n in by[alias]['named_identities']}
 mate_map[str(i)]=sorted(set().union(*(identity_ids[n] for n in names))-{i}) if names else []
mate_review=set().union(*(set(v) for v in mate_map.values()))
quality_controls=canon(i for i in personal if set(by[i]['slice_tags'])&{'profile','blur','low_res'})-hard
roles={'keyword_negative_frame':keyword_neg,'gallery_mate_review':mate_review,'quality_control_review':quality_controls,'personal_frame':frame,'probability_review_pilot120':sample,'challenge_review_candidates':hard,'caption_failure_audit':failed,'keyword_negative_audit60':negative_sample,'unknown_label_audit':unknown,'zero_detection_audit':zero,'no_face_flag_audit':noface,'historical_golden150':oldgold,'editorial_research_only':editorial}
rows=[]
for e in sorted(entries,key=lambda x:x['media_id']):
 i=e['media_id'];c=canonical[i]
 # Aliases preserve lineage but do not become additional scored observations.
 memberships=[k for k,s in roles.items() if (i in s if k in ['historical_golden150','editorial_research_only'] else c in s)]
 rows.append({'media_id':i,'path':e['path'],'bucket':e['bucket'],'canonical_media_id':c,'duplicate_alias':i!=c,'source_sha256':e.get('sha256_source'),'downscaled_sha256':e['sha256'],'population_memberships':memberships,'population_membership_basis':'existing_metadata_only','source_tags':e['slice_tags'],'caption_candidate_terms':next((list(x['matched_terms']) for x in mining['candidates'] if x['media_id']==i),[]),'recorded_named_identity_count':len(e['named_identities']),'recorded_detected_face_count':e['detected_face_count'],'recorded_dependency_component':coidentity[i],'pixel_identity_verified':False,'face_occlusion_verified':False,'person_sessions_verified':False,'development_use':'legacy_diagnostic','calibration_split':'pending_face_and_session_adjudication','sealed_confirmatory_test_eligible':False,'weight_training_authorized':False,'probability_pilot_inclusion_probability':120/len(frame) if i in personal else None,'keyword_negative_audit_inclusion_probability':60/len(keyword_neg) if c in keyword_neg else None,'scored_observation_eligible_now':False})
summary={'records':len(entries),'personal_records':len(personal),'editorial_records':len(editorial),'personal_unique_content':len(frame),'exact_duplicate_groups':[v for v in groups.values() if len(v)>1],'role_counts':{k:len(v) for k,v in roles.items()},'role_ids':{k:sorted(v) for k,v in roles.items()},'probability_challenge_overlap':sorted(sample&hard),'keyword_audit_probability_overlap':sorted(negative_sample&sample),'first_annotation_wave_unique':len(sample|hard|failed|negative_sample),'known_dependency_components':len(components),'largest_known_dependency_component':max(map(len,components.values())),'minimum_known_component_sizes_desc':sorted(map(len,components.values()),reverse=True),'unresolved_sessions':True,'challenge_candidate_mate_images':mate_map,'challenge_candidates_without_recorded_mates':[int(i) for i,v in mate_map.items() if not v]}
output={'schema':'fir.corpus-population-review-draft.v1','status':'PROVISIONAL_METADATA_REVIEW_LISTS_NOT_GOLD_NOT_EXECUTABLE_EVAL_SPLITS','created':'2026-09-19','inputs':[{'path':str(p.relative_to(root)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}for p in [mp,cp]],'current_source_root_exists':Path(m['images_root']).exists(),'method':{'duplicate_key':'union of source/downscaled sha256; canonical smallest media_id','probability_pilot':'uniform without replacement over sorted 588 canonical personal images; Python Random(20260919), sample 120; planning annotation budget, not power calculation','negative_audit':'uniform without replacement over canonical personal keyword-negative successful-caption frame; Random(20260920), sample 60','challenge':'union of personal saved-caption candidates and personal original image tags masked/sunglasses/occlusion_other; canonicalized','cohort_overlap':'memberships intentionally overlap; annotate once, preserve each estimator frame and inclusion probability; never pool as independent observations','evaluation_splits':'none frozen; labels, sessions and pixel joins needed; all legacy data is diagnostic, no blind-test claim','training':'no weight-training assignment or authorization; personal evaluation-consent metadata does not establish training use scope'},'summary':summary,'entries':rows}
private=root/'benchmarks/private/fir-capacity-20260919';private.mkdir(parents=True,exist_ok=True)
out=private/'fir-occ-population-review-draft-20260919.json';out.write_text(json.dumps(output,indent=2)+'\n')
csvpath=out.with_suffix('.csv')
with csvpath.open('w',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader()
 for row in rows:writer.writerow({k:('|'.join(map(str,v)) if isinstance(v,list) else v) for k,v in row.items()})
(private/'fir-occ-population-review-summary-20260919.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ['role_ids','minimum_known_component_sizes_desc','challenge_candidate_mate_images']},indent=2))
