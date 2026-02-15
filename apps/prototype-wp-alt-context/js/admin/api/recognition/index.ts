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
  SyncStatusResponse,
} from './types';

// Scan operations
export { scanFaces, scanFacesBatched, fetchScanStatus, cancelScanJob, clusterFaces } from './scanApi';

// Cluster operations
export {
  updateClusterLabel,
  mergeCluster,
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
export { fetchSyncStatus } from './syncApi';
