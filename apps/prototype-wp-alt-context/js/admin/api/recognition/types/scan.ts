/**
 * Scan/Analyze API Types
 *
 * These types match the backend JobStatusResponse schema exactly.
 */

export interface AnalyzeRequest {
  mediaIds: number[];
  sensitivity?: 'standard' | 'high';
  clusterId?: string;
}

/**
 * Progress tracking for a job.
 */
export interface JobProgress {
  completed: number;
  total: number;
}

/**
 * Response from POST /recognition/analyze
 * Matches backend JobStatusResponse schema.
 */
export interface AnalyzeResponse {
  id: string;
  type: 'analyze' | 'clustering';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: JobProgress | null;
  started_at: string;
  finished_at: string | null;
  message?: string | null;
}

/**
 * Response from GET /recognition/jobs/{job_id}
 * Same structure as AnalyzeResponse.
 */
export type JobStatusResponse = AnalyzeResponse;

/**
 * Legacy ScanStatus - prefer JobStatusResponse for new code.
 * @deprecated Use JobStatusResponse instead
 */
export interface ScanStatus {
  id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: JobProgress | null;
  started_at: string;
  finished_at: string | null;
  message?: string | null;
}

/**
 * Response from POST /recognition/clustering/jobs
 * Extends JobStatusResponse with clustering-specific fields.
 */
export interface ClusterResponse extends AnalyzeResponse {
  clusters_created: number;
  total_identities_clustered: number;
}
