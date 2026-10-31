"""Execute actual emitted top-unlabeled SQL against independent membership cases."""
import json, sqlite3, sys
payload=json.load(sys.stdin)
db=sqlite3.connect(':memory:')
db.executescript("""
CREATE TABLE wp_acx_clusters(cluster_uuid TEXT PRIMARY KEY, tenant_id TEXT, label TEXT,
 person_id INTEGER, identity_count INTEGER, updated_at TEXT, is_user_confirmed INTEGER, curation_state TEXT);
CREATE TABLE wp_acx_persons(id INTEGER PRIMARY KEY, person_uuid TEXT, name TEXT);
CREATE TABLE wp_acx_identity_members(identity_uuid TEXT PRIMARY KEY, cluster_uuid TEXT, attachment_id INTEGER);
""")
for group,tenant,label,confirmed,state,photos in [
 ('duplicate','tenant-1',None,0,None,[10,10,10,10]),
 ('two-a','tenant-1',None,0,None,[10,20,20]),
 ('two-b','tenant-1',None,0,None,[30,40,40]),
 ('unknown','tenant-1',None,0,None,[0,50]),
 ('named','tenant-1','Alice',0,None,[1,2,3,4,5]),
 ('confirmed','tenant-1',None,1,None,[1,2,3,4,5]),
 ('dismissed','tenant-1',None,0,'dismissed',[1,2,3,4,5]),
 ('foreign','tenant-2',None,0,None,[1,2,3,4,5]),
 ('singleton','tenant-1',None,0,None,[1])]:
 db.execute('INSERT INTO wp_acx_clusters VALUES(?,?,?,?,?,?,?,?)',(group,tenant,label,None,len(photos),'2026-10-31',confirmed,state))
 for i,photo in enumerate(photos):
  db.execute('INSERT INTO wp_acx_identity_members VALUES(?,?,?)',(f'{group}-{i}',group,photo))
cur=db.execute(payload['sql']); columns=[c[0] for c in cur.description]
print(json.dumps([dict(zip(columns,row)) for row in cur]))
