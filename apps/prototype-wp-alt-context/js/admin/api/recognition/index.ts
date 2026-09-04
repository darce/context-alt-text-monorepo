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
  IdentityBatchSuggestionsResponse,
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
  LastSyncResult,
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
  BulkRetryResponse,
  WorkbenchOverlay,
} from './types';

export type { ConflictListParams, FailedOutboxListParams, OutboxListParams } from './conflictApi';
export { DATA_SOURCE, PROJECTION_STATUS, LAST_SYNC_RESULT } from './types';

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
  reassignClusterIdentity,
  revertMergeCluster,
  pinRepresentative,
  splitCluster,
  createClusterForIdentity,
  dismissCluster,
} from './clusterApiMutations';
export { fetchClusterMembers, removeClusterMember } from './clusterApiMembers';
export type { FetchClusterMembersParams } from './clusterApiMembers';
export { listRecognitionClusters, getRecognitionCluster, fetchTopUnlabeledClusters } from './clusterApiQueries';

// Identity operations
export {
  fetchMediaIdentities,
  fetchIdentitiesSuggestions,
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
} from './identityQueriesApi';
export type { PendingNameSuggestionsResponse } from './types';
export {
  acceptSuggestion,
  acceptMergeSuggestion,
  rejectSuggestion,
  rejectMergeSuggestion,
  acceptNameSuggestion,
  rejectNameSuggestion,
  bulkAcceptSuggestions,
} from './identityActionsApi';
// The types `acceptMergeSuggestion` traffics in ship with the function, so a
// barrel consumer can narrow the accept result and pin a survivor without a deep
// import (DOM-03: one export surface per concept, not one per file path).
export type { AcceptedMergeSuggestion, AcceptMergeSuggestionRequest } from './identityActionsApi';

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
  // `downloadExportJobData` fails loud on a non-conforming envelope. Shipping the
  // error class and the collection-key list through the same barrel keeps that
  // fail-closed contract narrowable by barrel consumers instead of degrading to a
  // generic catch (ARCH-13: structural support for a property that must hold).
  RetentionExportResponseError,
  EXPORT_COLLECTION_KEYS,
} from './retentionApi';

// Conflict and dead-letter operations
export {
  fetchConflicts,
  fetchConflictDetail,
  resolveConflict,
  fetchOutboxOperations,
  fetchFailedOutboxOperations,
  retryFailedOperation,
  bulkRetryFailedOperations,
  discardFailedOperation,
} from './conflictApi';
