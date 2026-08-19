import { describe, expect, it, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { serializeQueueState } from '../../../hooks/workbenchQueueUrl';
import {
  ROSTER_SURFACE,
  isUnlabeledCluster,
  parseRosterRoute,
  selectDeterministicDefaultWorkspaceEntry,
  workbenchReviewQueueUrl,
  writeRosterFaceParam,
} from '../rosterRoute';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
}));

const projectionEntry = (overrides: Partial<RosterEntry> = {}): RosterEntry => ({
  id: 1,
  person_uuid: 'person-uuid-1',
  name: 'Alice',
  tags: [],
  cluster_count: 2,
  clusters: [],
  queue_memberships: [],
  updated_at: '2026-05-07T12:00:00Z',
  source_version: 11,
  projection_status: 'current',
  projection_refreshed_at: '2026-05-07T12:00:00Z',
  ...overrides,
});

describe('selectDeterministicDefaultWorkspaceEntry', () => {
  it('falls back to person UUID when names are identical', () => {
    const selected = selectDeterministicDefaultWorkspaceEntry([
      projectionEntry({ id: 2, person_uuid: 'person-uuid-2', name: 'Alex' }),
      projectionEntry({ id: 1, person_uuid: 'person-uuid-1', name: 'Alex' }),
    ]);

    expect(selected?.person_uuid).toBe('person-uuid-1');
  });

  it('falls back to numeric row id when name and person UUID are identical', () => {
    const selected = selectDeterministicDefaultWorkspaceEntry([
      projectionEntry({ id: 10, person_uuid: 'person-uuid-1', name: 'Alex' }),
      projectionEntry({ id: 2, person_uuid: 'person-uuid-1', name: 'Alex' }),
    ]);

    expect(selected?.id).toBe(2);
  });
});

describe('ROSTER_SURFACE (E21-9 Slice 5a — clusters tab retired)', () => {
  it('exposes only the people surface label (no clusters tab symbol)', async () => {
    expect(ROSTER_SURFACE.id).toBe('people');
    expect(ROSTER_SURFACE.label).toBe('People');
    // Export-level retirement: ROSTER_TABS must not reappear.
    const mod = await import('../rosterRoute');
    expect('ROSTER_TABS' in mod).toBe(false);
  });
});

describe('parseRosterRoute route compat (E21-9 Slice 5a + E21-10 lands-second)', () => {
  it('lands legacy tab=clusters on the single surface without selecting a cluster', () => {
    const parsed = parseRosterRoute(new URLSearchParams('tab=clusters'));
    expect(parsed.selectedClusterId).toBeNull();
    expect(parsed.requiresProjectionGateNotice).toBe(false);
  });

  it('opens the drawer for cluster= deep links (in place on the single surface)', () => {
    const parsed = parseRosterRoute(new URLSearchParams('cluster=cluster-abc'));
    expect(parsed.selectedClusterId).toBe('cluster-abc');
    expect(parsed.requiresProjectionGateNotice).toBe(false);
  });

  it('ignores tab=clusters when cluster= is also present (drawer still opens)', () => {
    const parsed = parseRosterRoute(new URLSearchParams('tab=clusters&cluster=cluster-1'));
    expect(parsed.selectedClusterId).toBe('cluster-1');
  });

  it('keeps person/queue/face routes on the person surface with projection gate', () => {
    const person = parseRosterRoute(new URLSearchParams('person=p1&tab=clusters'));
    expect(person.selectedClusterId).toBeNull();
    expect(person.requiresProjectionGateNotice).toBe(true);

    const queue = parseRosterRoute(new URLSearchParams('queue=needs-review&tab=clusters'));
    expect(queue.requiresProjectionGateNotice).toBe(true);
  });

  it('reads the face= cursor from person workspace deep links', () => {
    const parsed = parseRosterRoute(new URLSearchParams('person=p1&face=identity-2'));
    expect(parsed.selectedFaceId).toBe('identity-2');
    expect(parsed.requiresProjectionGateNotice).toBe(true);
  });

  it('writes face= with replace-style params and keeps person=', () => {
    const next = writeRosterFaceParam(new URLSearchParams('person=p1'), 'identity-2', 'p1');
    expect(next.get('person')).toBe('p1');
    expect(next.get('face')).toBe('identity-2');
  });

  // E21-10 Slice 4 lands-second: getLegacyTab retired (E21-9); no tab rewrite, no Clusters tab.
  it('does not export getLegacyTab (legacy roster tab parser retired)', async () => {
    const mod = await import('../rosterRoute');
    expect('getLegacyTab' in mod).toBe(false);
    expect('ROSTER_TABS' in mod).toBe(false);
  });
});

describe('isUnlabeledCluster + workbench deep link (E21-9 Slice 5b contract)', () => {
  it('treats empty/absent/whitespace labels as unlabeled', () => {
    expect(isUnlabeledCluster({ label: '' })).toBe(true);
    expect(isUnlabeledCluster({ label: '   ' })).toBe(true);
    expect(isUnlabeledCluster({ label: null })).toBe(true);
    expect(isUnlabeledCluster({})).toBe(true);
    expect(isUnlabeledCluster({ label: 'Ada' })).toBe(false);
  });

  it('deep-links unlabeled clusters into the workbench review queue', () => {
    // cluster= dropped (jobId precedent): workbench has no cluster reader.
    expect(workbenchReviewQueueUrl()).toBe('#/workbench?tab=scan&rq=assignment.all.0');
    expect(workbenchReviewQueueUrl()).not.toContain('cluster=');
  });

  it('encodes rq via serializeQueueState (REF-09, no hand-coded token)', () => {
    const encoded = serializeQueueState({ kind: 'assignment', band: 'all', index: 0 });
    expect(encoded).toBe('assignment.all.0');
    expect(workbenchReviewQueueUrl()).toBe(`#/workbench?tab=scan&rq=${encoded}`);
  });
});
