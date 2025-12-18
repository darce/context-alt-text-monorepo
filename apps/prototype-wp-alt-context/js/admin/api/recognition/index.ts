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
  ScanStatus,
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
  ReassignClusterFaceRequest,
  RevertMergeRequest,
  RevertMergeResponse,
  SplitClusterResponse,
  CreateClusterForIdentityRequest,
  CreateClusterForIdentityResponse,
  // Suggestion types
  PendingSuggestion,
  PendingSuggestionsResponse,
  SuggestionActionResponse,
} from './types';

// Scan operations
export { scanFaces, scanFacesBatched, fetchScanStatus, cancelScanJob, clusterFaces } from './scanApi';

// Cluster operations
export {
  updateClusterLabel,
  mergeCluster,
  listRecognitionClusters,
  getRecognitionCluster,
  fetchClusterLabels,
  reassignClusterIdentity,
  reassignClusterFace,
  revertMergeCluster,
  splitCluster,
  createClusterForIdentity,
} from './clusterApi';

// Identity operations
export {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  fetchTrainingStage,
  fetchPendingSuggestions,
  acceptSuggestion,
  rejectSuggestion,
} from './identityApi';
