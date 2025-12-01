/**
 * Scan/Analyze API Types
 */

export interface AnalyzeRequest {
  mediaIds: number[];
  sensitivity?: 'standard' | 'high';
  clusterId?: string;
}

export interface AnalyzeResponse {
  job_id: string | null;
  job_ids?: string[];
  status: string;
  total_media: number;
}

export interface ScanStatus {
  job_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  total_media: number;
  processed_media: number;
  identities_detected: number;
  faces_detected?: number;
  error_message?: string;
  created_at?: string;
  completed_at?: string;
}

export interface ClusterRequest {
  similarity_threshold?: number;
}

export interface ClusterResponse {
  clusters_created: number;
  total_identities_clustered: number;
  total_faces_clustered?: number;
}
