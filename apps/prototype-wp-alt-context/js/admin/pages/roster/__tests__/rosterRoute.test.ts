import { describe, expect, it, vi } from 'vitest';

import type { RosterEntry } from '../../../api/rosterApi';
import { ROSTER_TABS, selectDeterministicDefaultWorkspaceEntry } from '../rosterRoute';

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

describe('ROSTER_TABS (UXP-4 slice 5)', () => {
  it('keeps tab ids/routes stable while using people-first labels', () => {
    expect(ROSTER_TABS.entries.id).toBe('entries');
    expect(ROSTER_TABS.clusters.id).toBe('clusters');
    expect(ROSTER_TABS.entries.label).toBe('People');
    expect(ROSTER_TABS.clusters.label).toBe('Face groups');
  });
});
