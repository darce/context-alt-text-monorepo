import { DASHBOARD_FLOW_STATE, buildDashboardPriorityModel } from '../buildDashboardPriorityModel';

const buildInputs = (overrides: Partial<Parameters<typeof buildDashboardPriorityModel>[0]> = {}) => ({
  isSyncStatusLoading: false,
  isSyncStatusError: false,
  effectiveSyncHealth: 'healthy',
  hasSyncHealthWarnings: false,
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
  flowState: DASHBOARD_FLOW_STATE.FIRST_NAMED,
  ...overrides,
});

describe('buildDashboardPriorityModel', () => {
  it('prioritizes sync health when the replay pipeline needs attention', () => {
    const model = buildDashboardPriorityModel(
      buildInputs({
        effectiveSyncHealth: 'conflicts',
        conflictCount: 2,
        pendingClustersCount: 3,
      }),
    );

    expect(model.gridSectionOrder[0]).toBe('syncHealth');
    expect(model.gridSectionOrder[1]).toBe('identityRecognition');
    expect(model.orientationPosition).toBe('hidden');
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
    (effectiveSyncHealth) => {
      const model = buildDashboardPriorityModel(
        buildInputs({
          effectiveSyncHealth,
          pendingClustersCount: 2,
        }),
      );

      expect(model.gridSectionOrder[0]).toBe('syncHealth');
    },
  );

  it('treats sync-health envelope warnings as sync attention even when effective health is healthy', () => {
    const model = buildDashboardPriorityModel(
      buildInputs({
        effectiveSyncHealth: 'healthy',
        hasSyncHealthWarnings: true,
        pendingClustersCount: 2,
      }),
    );

    expect(model.gridSectionOrder[0]).toBe('syncHealth');
  });

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

  it.each([DASHBOARD_FLOW_STATE.UNSCANNED, DASHBOARD_FLOW_STATE.SCANNING, DASHBOARD_FLOW_STATE.CLUSTERS_PENDING])(
    'places orientation above telemetry while the flow is %s',
    (flowState) => {
      const model = buildDashboardPriorityModel(buildInputs({ flowState }));

      expect(model.gridSectionOrder).not.toContain('batchOperations');
      expect(model.orientationPosition).toBe('before_grid');
    },
  );

  it('retires orientation after the first person is named', () => {
    const model = buildDashboardPriorityModel(buildInputs({ flowState: DASHBOARD_FLOW_STATE.FIRST_NAMED }));

    expect(model.orientationPosition).toBe('hidden');
  });

  it.each([{ isIdentityLoading: true }, { isIdentityError: true }, { hasIdentityStats: false }])(
    'does not promote identity recognition for a non-actionable stats state: %o',
    (identityState) => {
      const model = buildDashboardPriorityModel(buildInputs(identityState));

      expect(model.gridSectionOrder[0]).toBe('syncHealth');
      expect(model.gridSectionOrder[1]).toBe('identityRecognition');
    },
  );
});
