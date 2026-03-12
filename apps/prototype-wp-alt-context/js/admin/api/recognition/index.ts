/**
 * Recognition API
 *
 * Barrel export for all recognition service API modules.
 * This provides a clean import path while keeping the implementation modular.
 */

// Types
export type {
  AnalyzeRequest,
  AnalyzeResponse,
  JobProgress,
  JobStatusResponse,
  ClusterResponse,
  RepresentativeBounds,
  BoundingBox,
  ClusterIdentity,
  DebugMetrics,
  DetectedIdentity,
  MediaIdentitiesResponse,
  ClusterSummary,
  ClusterListParams,
  ClusterSuggestion,
  IdentitySuggestionsResponse,
  // Cluster operation types
  UpdateClusterLabelRequest,
  MergeClusterRequest,
  MergeClusterResponse,
  AssignOutlierRequest,
  AssignOutlierResponse,
  ReassignClusterIdentityRequest,
  RevertMergeRequest,
  RevertMergeResponse,
  SplitClusterResponse,
  AsyncSplitClusterResponse,
  CreateClusterForIdentityRequest,
  CreateClusterForIdentityResponse,
  // Suggestion types
  PendingSuggestion,
  PendingSuggestionsResponse,
  PendingMergeSuggestion,
  PendingMergeSuggestionsResponse,
  SuggestionActionResponse,
  SyncHealth,
  SyncStatusResponse,
  SyncTriggerResponse,
  RetentionMode,
  RetentionPolicy,
  AuditEvent,
  RetentionStatusResponse,
  UpdateRetentionPolicyRequest,
  RetentionExportResponse,
  PurgeTenantDataRequest,
  PurgeTenantDataResponse,
  ConflictResolutionChoice,
  ConflictRecord,
  ConflictListResponse,
  ConflictDetailResponse,
  ResolveConflictRequest,
  ResolveConflictResponse,
  OutboxOperation,
  OutboxListResponse,
  OutboxMutationResponse,
  WorkbenchOverlay,
} from './types';

export type { ConflictListParams, FailedOutboxListParams, OutboxListParams } from './conflictApi';

// Scan operations
export { scanFaces, scanFacesBatched, fetchScanStatus, cancelScanJob, clusterFaces, acknowledgeProjection } from './scanApi';

// Cluster operations
export {
  updateClusterLabel,
  mergeCluster,
  assignOutlierToCluster,
  listRecognitionClusters,
  getRecognitionCluster,
  reassignClusterIdentity,
  revertMergeCluster,
  splitCluster,
  createClusterForIdentity,
  dismissCluster,
  undismissCluster,
  fetchClusterMembers,
  removeClusterMember,
  fetchTopUnlabeledClusters,
} from './clusterApi';

// Identity operations
export {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
  acceptSuggestion,
  acceptMergeSuggestion,
  rejectSuggestion,
  rejectMergeSuggestion,
} from './identityApi';

// Sync status
export { fetchSyncStatus, triggerSync } from './syncApi';

// Retention
export { fetchRetentionStatus, updateRetentionPolicy, exportTenantData, purgeTenantData } from './retentionApi';

// Conflict and dead-letter operations
export {
  fetchConflicts,
  fetchConflictDetail,
  resolveConflict,
  fetchOutboxOperations,
  fetchFailedOutboxOperations,
  retryFailedOperation,
  discardFailedOperation,
} from './conflictApi';
