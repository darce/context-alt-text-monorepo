/**
 * Scan/Analyze API Types
 *
 * These types match the backend JobStatusResponse schema exactly.
 */

import type { JobProgress, RecognitionJob } from '../../generated';

export type { JobProgress, RecognitionJob };

export interface AnalyzeRequest {
  mediaIds: number[];
  sensitivity?: 'standard' | 'high';
  clusterId?: string;
}

/**
 * Response from POST /recognition/analyze
 * Matches backend JobStatusResponse schema.
 */
export type AnalyzeResponse = RecognitionJob;

/**
 * Response from GET /recognition/jobs/{job_id}
 * Same structure as AnalyzeResponse.
 */
export type JobStatusResponse = RecognitionJob;

/**
 * Response from POST /recognition/clustering/jobs
 * Extends JobStatusResponse with clustering-specific fields.
 */
export interface ClusterResponse extends AnalyzeResponse {
  clusters_created: number;
  total_identities_clustered: number;
}
