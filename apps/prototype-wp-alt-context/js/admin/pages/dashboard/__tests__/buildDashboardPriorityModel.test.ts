import { buildDashboardPriorityModel } from '../buildDashboardPriorityModel';

const buildInputs = (overrides: Partial<Parameters<typeof buildDashboardPriorityModel>[0]> = {}) => ({
  isSyncStatusLoading: false,
  isSyncStatusError: false,
  syncHealth: 'healthy',
  pendingReplayCount: 0,
  conflictCount: 0,
  failedReplayCount: 0,
  topologyPending: 0,
  topologyFailed: 0,
  topologyConflicts: 0,
  showMirrorDivergenceBanner: false,
  isIdentityLoading: false,
  isIdentityError: false,
  hasIdentityStats: true,
  pendingClustersCount: 0,
  unassignedPersonsCount: 0,
  ...overrides,
});

describe('buildDashboardPriorityModel', () => {
  it('prioritizes sync health when the replay pipeline needs attention', () => {
    const model = buildDashboardPriorityModel(
      buildInputs({
        syncHealth: 'conflicts',
        conflictCount: 2,
        pendingClustersCount: 3,
      }),
    );

    expect(model.gridSectionOrder[0]).toBe('syncHealth');
    expect(model.gridSectionOrder[1]).toBe('identityRecognition');
    expect(model.orientationPosition).toBe('after_grid');
  });

  it('prioritizes review work when sync health is healthy', () => {
    const model = buildDashboardPriorityModel(
      buildInputs({
        pendingClustersCount: 4,
      }),
    );

    expect(model.gridSectionOrder[0]).toBe('identityRecognition');
    expect(model.gridSectionOrder[1]).toBe('syncHealth');
  });

  it.each(['queued', 'failures', 'offline', 'stale'])(
    'treats %s as sync attention that outranks review work',
    (syncHealth) => {
      const model = buildDashboardPriorityModel(
        buildInputs({
          syncHealth,
          pendingClustersCount: 2,
        }),
      );

      expect(model.gridSectionOrder[0]).toBe('syncHealth');
    },
  );

  it('treats topology backlog as sync attention even when the health label is healthy', () => {
    const model = buildDashboardPriorityModel(
      buildInputs({
        topologyPending: 3,
        pendingClustersCount: 2,
      }),
    );

    expect(model.gridSectionOrder[0]).toBe('syncHealth');
  });

  it('treats partial sync loading as a top-priority attention state', () => {
    const model = buildDashboardPriorityModel(
      buildInputs({
        isSyncStatusLoading: true,
        pendingClustersCount: 2,
      }),
    );

    expect(model.gridSectionOrder[0]).toBe('syncHealth');
  });
});
