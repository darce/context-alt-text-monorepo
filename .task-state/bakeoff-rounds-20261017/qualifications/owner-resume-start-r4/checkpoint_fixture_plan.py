"""Private Root checkpoint qualification contract; --plan has no effects.

Root invocation: python3 -I -B checkpoint_fixture_coordinator.py --run
  --input-root /root/SEALED_INPUT --manifest-sha256 SHA256
Inputs: root0700 ancestry; root0400 single-link files; input-manifest.json
{schema: acx-checkpoint-fixture-input/v1, files: {relative_name: sha256}}.
Include both drivers, root_fixture_plan.py, OWNER-FLOW-CONTROLS-R2.py,
old-procedure/{seven scripts,approved-scripts.json}, new-procedure/{same},
and the complete source-bundle. Old stage is the already-qualified 991aa72e manifest (corrected START parser);
source-bundle pins are independently fixed by OWNER-FLOW-CONTROLS-R2.py; Source A's final new-stage pins come from the protected
manifest. No stage replacement and no source-only qualification claim.
The pinned old stage and source bundle reproduce four-environment history only.
After that history, Root extends only the proven private /run fixture with
dev-auraface: Root:GID10001 mode0770 directory, exclusively created no-follow
Root:GID10001 mode0660 persistent intent/load fences, and fresh UID/GID10001
mode0644 zero load. No fifth intent publication is created. Existing history,
authority, publications and four-environment fences must remain identical.
New source requires ENVS exactly (dev, dev-fir, prod, staging, dev-auraface).

The predecessor receipt uses EXACTLY the agreed seven fields, generated only
inside private tmpfs by Root after creating the legacy fixture window. No extra
identity fields are assumed. Source A must verify old-stage descriptor identities
and hashes itself. If Source A requires extra fields this driver must refuse,
not guess authority. Receipt is outside approved-scripts.json's code inventory.
UNKNOWN: PID1 writes custody evidence; ancestor launcher SIGSTOPs exact PID1
through its pidfd and returns124
without killing, retrying, adopting or cleaning up. Operator retains supervisor,
namespace and native children for explicit reconciliation. Never CONT/retry
without that reconciliation. Total launcher validation deadline is 180 seconds.
"""
import argparse
import json

FLOW_SHA = '369c120b901b1ee3faeb642d6d498ef2ae0e5b98904c44d0b1a9c64c3a51e062'
PROOF_FIELDS = ('schema', 'window_id', 'window_path', 'procedure', 'manifest_sha256',
                'owner_window_sha256', 'owner_custody_sha256')
PLAN = {
    'status': 'PLAN_ONLY_ROOT_PENDING', 'budget_seconds': 180,
    'exit_codes': {'77': 'actual Root required', '65': 'setup refusal',
                   '124': 'UNKNOWN; retain PID1 and all custody'},
    'isolation': ['fresh MNT/PID/NET', 'recursive-private mounts', 'private proc',
                  'fresh tmpfs /run /var/lib /var/log /tmp /opt',
                  'pinned fixture adapters hide /usr/local/bin; no host services'],
    'credentials': 'real ubuntu UID/GID1001 -> sudo; real native writer UID/GID10001',
    'new_environments': ['dev', 'dev-fir', 'prod', 'staging', 'dev-auraface'],
    'fifth_setup': 'After legacy history, before every new-stage case; sealed overlay mount proof, exact private prefix and owner/mode/inode evidence; no existing fence replacement',
    'proof': {'schema': 'acx-owner-procedure-predecessor/v1', 'fields': PROOF_FIELDS,
              'mode': 'Root0400, Root0700 new stage, nofollow ancestry'},
    'cases': ['legacy 32 successful alternating START/AUTO, refused33, reconcile33 RED',
              'invalid predecessor receipt refuses checkpoint without mutation',
              'protected new stage checkpoint SAME window; unchanged authority/publications/source',
              'fifth nonzero demand refuses actual public START with no writer or sequence/publication/authority change; only a diagnostic operation may be added',
              'fifth demand restored to fresh zero; next native START/AUTO keeps same actor and next sequence',
              'next native START/AUTO; all guardians and writers reaped',
              'independent pending and real foreign-current refusal without mutation',
              'independent real UID10001 live writer blocked at persistent fence; refusal without mutation'],
    'required_remaining_controls': ['crash injection'],
    'limits': ['No privileged result from --plan or AST checks.',
               'Selected Root pass does not establish crash safety or a live qualification.',
               'No live paths; no installed controller changes; no fake ACK.',
               'No crash injection qualification in this selected driver.',
               'Archive checks preserve byte multiplicity and current proof identity; archive manifest schema needs Source A gate.',
               'Root must prove ancestor pidfd SIGSTOP retention and rendezvous under the fixed budget before accepting the driver.'],
}

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', action='store_true', required=True)
    p.parse_args()
    print(json.dumps(PLAN, sort_keys=True, indent=2))
