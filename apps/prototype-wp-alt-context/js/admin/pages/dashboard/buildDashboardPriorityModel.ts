export type DashboardSectionId =
  | 'syncHealth'
  | 'identityRecognition'
  | 'libraryCoverage'
  | 'recentActivity'
  | 'retentionPosture';

export const DASHBOARD_FLOW_STATE = {
  UNSCANNED: 'unscanned',
  SCANNING: 'scanning',
  CLUSTERS_PENDING: 'clusters_pending',
  FIRST_NAMED: 'first_named',
} as const;

export type DashboardFlowState = (typeof DASHBOARD_FLOW_STATE)[keyof typeof DASHBOARD_FLOW_STATE];

export interface DashboardPriorityInputs {
  isSyncStatusLoading: boolean;
  isSyncStatusError: boolean;
  effectiveSyncHealth: string | null;
  hasSyncHealthWarnings: boolean;
  pendingReplayCount: number;
  conflictCount: number;
  failedReplayCount: number;
  topologyPending: number;
  topologyFailed: number;
  topologyConflicts: number;
  showMirrorDivergenceBanner: boolean;
  isIdentityLoading: boolean;
  isIdentityError: boolean;
  hasIdentityStats: boolean;
  pendingClustersCount: number;
  unassignedPersonsCount: number;
  flowState: DashboardFlowState;
}

export interface DashboardPriorityModel {
  gridSectionOrder: DashboardSectionId[];
  orientationPosition: 'before_grid' | 'hidden';
}

const DEFAULT_SECTION_ORDER: DashboardSectionId[] = [
  'syncHealth',
  'identityRecognition',
  'libraryCoverage',
  'recentActivity',
  'retentionPosture',
];

const hasSyncAttention = (inputs: DashboardPriorityInputs): boolean => {
  if (inputs.isSyncStatusLoading || inputs.isSyncStatusError || inputs.showMirrorDivergenceBanner) {
    return true;
  }

  if (inputs.hasSyncHealthWarnings) {
    return true;
  }

  if (inputs.effectiveSyncHealth !== 'healthy') {
    return true;
  }

  return (
    inputs.pendingReplayCount > 0 ||
    inputs.conflictCount > 0 ||
    inputs.failedReplayCount > 0 ||
    inputs.topologyPending > 0 ||
    inputs.topologyFailed > 0 ||
    inputs.topologyConflicts > 0
  );
};

const hasActiveReviewWork = (inputs: DashboardPriorityInputs): boolean => {
  if (inputs.isIdentityLoading || inputs.isIdentityError || !inputs.hasIdentityStats) {
    return false;
  }

  return inputs.pendingClustersCount > 0 || inputs.unassignedPersonsCount > 0;
};

export const buildDashboardPriorityModel = (inputs: DashboardPriorityInputs): DashboardPriorityModel => {
  const gridSectionOrder = [...DEFAULT_SECTION_ORDER];

  if (!hasSyncAttention(inputs) && hasActiveReviewWork(inputs)) {
    gridSectionOrder.splice(gridSectionOrder.indexOf('identityRecognition'), 1);
    gridSectionOrder.unshift('identityRecognition');
  }

  return {
    gridSectionOrder,
    orientationPosition: inputs.flowState === DASHBOARD_FLOW_STATE.FIRST_NAMED ? 'hidden' : 'before_grid',
  };
};
