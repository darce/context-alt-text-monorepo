"""Execute emitted repository SELECTs, not a reimplementation of their predicates.

SQLite is an in-memory SQL oracle only; MySQL execution remains a coordinator gate.
Column shapes: class-life-cycle-manager.php clusters/persons/identity_members DDL;
attachment_id=0 is produced by class-identity-member-snapshot-merger.php:122.
"""
import json
import sqlite3
import sys

payload = json.load(sys.stdin)
db = sqlite3.connect(':memory:')
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE wp_acx_clusters (cluster_uuid TEXT PRIMARY KEY, tenant_id TEXT,
 label TEXT, person_id INTEGER, identity_count INTEGER, updated_at TEXT);
CREATE TABLE wp_acx_persons (id INTEGER PRIMARY KEY, person_uuid TEXT, name TEXT);
CREATE TABLE wp_acx_identity_members (identity_uuid TEXT PRIMARY KEY,
 cluster_uuid TEXT NOT NULL, attachment_id INTEGER NOT NULL);
INSERT INTO wp_acx_persons VALUES (1, 'wp-person', 'Local Alice');
''')
for cluster, tenant, person, faces, stamp in [
 ('duplicate', 'tenant-1', 1, 99, '2026-10-31 05:00:00'),
 ('two-a', 'tenant-1', 1, 3, '2026-10-31 04:00:00'),
 ('two-b', 'tenant-1', 1, 3, '2026-10-31 03:00:00'),
 ('unknown', 'tenant-1', None, 9, '2026-10-31 02:00:00'),
 ('empty', 'tenant-1', None, 0, '2026-10-31 01:00:00'),
 ('foreign', 'tenant-2', 1, 5, '2026-10-31 06:00:00')]:
 db.execute('INSERT INTO wp_acx_clusters VALUES (?, ?, ?, ?, ?, ?)',
            (cluster, tenant, 'Alice', person, faces, stamp))
for cluster, photos in [('duplicate', [10, 10, 10]), ('two-a', [10, 20, 20]),
                        ('two-b', [30, 40, 40]), ('unknown', [0, 50]),
                        ('foreign', [11, 22, 33, 44, 55])]:
 for n, media in enumerate(photos):
  db.execute('INSERT INTO wp_acx_identity_members VALUES (?, ?, ?)',
             (f'{cluster}-{n}', cluster, media))
cursor = db.execute(payload['sql'])
# mysqli associative fetch uses the last occurrence of duplicate column names.
# sqlite3.Row lookup uses the first, so zip positional values with descriptions.
columns = [column[0] for column in cursor.description]
print(json.dumps([dict(zip(columns, row)) for row in cursor]))
