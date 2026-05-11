import type { RosterEntry } from '../../../api/rosterApi';
import { selectDeterministicDefaultWorkspaceEntry } from '../rosterRoute';

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
