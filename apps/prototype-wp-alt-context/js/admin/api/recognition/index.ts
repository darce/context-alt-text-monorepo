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
  BatchAnalyzeResponse,
  BatchRunStatus,
  RecentBatchRunActivity,
  RecentBatchRunsResponse,
  DataSource,
  FailedBatchStatus,
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
  ClusterListResponse,
  ClusterMembersResponse,
  ClusterListParams,
  ClusterSuggestion,
  IdentitySuggestionsResponse,
  // Cluster operation types
  UpdateClusterLabelRequest,
  MergeClusterRequest,
  MergeClusterResponse,
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
  ProjectionStatus,
  PendingNameSuggestion,
  PendingMergeSuggestion,
  PendingMergeSuggestionsResponse,
  BulkAcceptRequest,
  BulkAcceptResponse,
  SuggestionActionResponse,
  BreakerState,
  SyncHealth,
  SyncHealthResponse,
  SyncHealthWarning,
  SyncStatusResponse,
  SyncTriggerResponse,
  RetentionMode,
  RetentionPolicy,
  AuditEvent,
  RetentionStatusResponse,
  StartExportJobResponse,
  ExportJobStatusResponse,
  UpdateRetentionPolicyRequest,
  RetentionExportResponse,
  PurgeTenantDataRequest,
  PurgeTenantDataResponse,
  ImportTenantDataRequest,
  ImportTenantDataResponse,
  AuditEventListResponse,
  ApplyRetentionPresetRequest,
  ApplyRetentionPresetResponse,
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
export { DATA_SOURCE, PROJECTION_STATUS } from './types';

// Scan operations
export {
  scanFaces,
  scanFacesBatched,
  fetchBatchRunStatus,
  fetchRecentBatchRuns,
  fetchScanStatus,
  cancelScanJob,
  clusterFaces,
} from './scanApi';

// Cluster operations
export {
  updateClusterLabel,
  mergeCluster,
  listRecognitionClusters,
  getRecognitionCluster,
  reassignClusterIdentity,
  revertMergeCluster,
  pinRepresentative,
  splitCluster,
  createClusterForIdentity,
  dismissCluster,
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
  fetchPendingNameSuggestions,
  type PendingNameSuggestionsResponse,
  acceptSuggestion,
  acceptMergeSuggestion,
  rejectSuggestion,
  rejectMergeSuggestion,
  acceptNameSuggestion,
  rejectNameSuggestion,
  bulkAcceptSuggestions,
} from './identityApi';

// Sync status
export { fetchSyncHealth, fetchSyncStatus, triggerSync, resetMirror } from './syncApi';

// Retention
export {
  fetchRetentionStatus,
  updateRetentionPolicy,
  exportTenantData,
  getExportJobStatus,
  downloadExportJobData,
  purgeTenantData,
  importTenantData,
  fetchAuditEvents,
  applyRetentionPreset,
} from './retentionApi';

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
