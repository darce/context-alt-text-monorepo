export type DashboardSectionId =
  | 'syncHealth'
  | 'identityRecognition'
  | 'libraryCoverage'
  | 'recentActivity'
  | 'retentionPosture'
  | 'batchOperations';

export interface DashboardPriorityInputs {
  isSyncStatusLoading: boolean;
  isSyncStatusError: boolean;
  syncHealth: string | null;
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
}

export interface DashboardPriorityModel {
  gridSectionOrder: DashboardSectionId[];
  orientationPosition: 'before_grid' | 'after_grid';
}

const DEFAULT_SECTION_ORDER: DashboardSectionId[] = [
  'syncHealth',
  'identityRecognition',
  'libraryCoverage',
  'recentActivity',
  'retentionPosture',
  'batchOperations',
];

const hasSyncAttention = (inputs: DashboardPriorityInputs): boolean => {
  if (inputs.isSyncStatusLoading || inputs.isSyncStatusError || inputs.showMirrorDivergenceBanner) {
    return true;
  }

  if (inputs.syncHealth !== 'healthy') {
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
    return true;
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
    orientationPosition: 'after_grid',
  };
};
