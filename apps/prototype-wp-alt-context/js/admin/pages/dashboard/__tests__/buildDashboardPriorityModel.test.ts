import {
  DASHBOARD_FLOW_STATE,
  DASHBOARD_ORIENTATION_POSITION,
  buildDashboardPriorityModel,
  type DashboardPriorityInputs,
  type DashboardSectionId,
} from '../buildDashboardPriorityModel';

const DEFAULT_SECTION_ORDER: DashboardSectionId[] = [
  'syncHealth',
  'identityRecognition',
  'libraryCoverage',
  'recentActivity',
  'retentionPosture',
];

const REVIEW_FIRST_SECTION_ORDER: DashboardSectionId[] = [
  'identityRecognition',
  'syncHealth',
  'libraryCoverage',
  'recentActivity',
  'retentionPosture',
];

const buildInputs = (overrides: Partial<DashboardPriorityInputs> = {}): DashboardPriorityInputs => ({
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

const syncAttentionCases: [string, Partial<DashboardPriorityInputs>][] = [
  ['sync status loading', { isSyncStatusLoading: true }],
  ['sync status error', { isSyncStatusError: true }],
  ['mirror divergence', { showMirrorDivergenceBanner: true }],
  ['sync-health warning', { hasSyncHealthWarnings: true }],
  ['non-healthy effective health', { effectiveSyncHealth: 'conflicts' }],
  ['pending replay', { pendingReplayCount: 1 }],
  ['curation conflict', { conflictCount: 1 }],
  ['failed replay', { failedReplayCount: 1 }],
  ['pending topology command', { topologyPending: 1 }],
  ['failed topology command', { topologyFailed: 1 }],
  ['topology conflict', { topologyConflicts: 1 }],
];

describe('buildDashboardPriorityModel', () => {
  it.each(syncAttentionCases)('keeps the complete default order for the %s trigger', (_label, trigger) => {
    const model = buildDashboardPriorityModel(buildInputs({ pendingClustersCount: 2, ...trigger }));

    expect(model.gridSectionOrder).toEqual(DEFAULT_SECTION_ORDER);
    expect(model.orientationPosition).toBe(DASHBOARD_ORIENTATION_POSITION.HIDDEN);
  });

  it.each([
    ['pending cluster', { pendingClustersCount: 1 }],
    ['unassigned person', { unassignedPersonsCount: 1 }],
  ] satisfies [string, Partial<DashboardPriorityInputs>][])('promotes review for the %s trigger', (_label, trigger) => {
    const model = buildDashboardPriorityModel(buildInputs(trigger));

    expect(model.gridSectionOrder).toEqual(REVIEW_FIRST_SECTION_ORDER);
    expect(model.orientationPosition).toBe(DASHBOARD_ORIENTATION_POSITION.HIDDEN);
  });

  it.each(['queued', 'failures', 'offline', 'stale'])('treats %s health as sync attention', (effectiveSyncHealth) => {
    const model = buildDashboardPriorityModel(buildInputs({ effectiveSyncHealth, unassignedPersonsCount: 1 }));

    expect(model.gridSectionOrder).toEqual(DEFAULT_SECTION_ORDER);
  });

  it.each([DASHBOARD_FLOW_STATE.UNSCANNED, DASHBOARD_FLOW_STATE.SCANNING, DASHBOARD_FLOW_STATE.CLUSTERS_PENDING])(
    'places orientation above telemetry while the flow is %s',
    (flowState) => {
      const model = buildDashboardPriorityModel(buildInputs({ flowState }));

      expect(model.gridSectionOrder).toEqual(DEFAULT_SECTION_ORDER);
      expect(model.gridSectionOrder).not.toContain('batchOperations');
      expect(model.orientationPosition).toBe(DASHBOARD_ORIENTATION_POSITION.BEFORE_GRID);
    },
  );

  it('retires orientation after the first person is named', () => {
    const model = buildDashboardPriorityModel(buildInputs({ flowState: DASHBOARD_FLOW_STATE.FIRST_NAMED }));

    expect(model.gridSectionOrder).toEqual(DEFAULT_SECTION_ORDER);
    expect(model.orientationPosition).toBe(DASHBOARD_ORIENTATION_POSITION.HIDDEN);
  });

  it.each([{ isIdentityLoading: true }, { isIdentityError: true }, { hasIdentityStats: false }])(
    'does not promote identity recognition for a non-actionable stats state: %o',
    (identityState) => {
      const model = buildDashboardPriorityModel(buildInputs({ pendingClustersCount: 1, ...identityState }));

      expect(model.gridSectionOrder).toEqual(DEFAULT_SECTION_ORDER);
    },
  );
});
