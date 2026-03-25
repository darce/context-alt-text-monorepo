// This file is generated from packages/shared-contracts/schemas/recognition-job.schema.json.

export interface JobProgress {
  completed: number;
  total: number;
  phase?: 'queued' | 'detecting' | 'clustering' | 'retrying' | 'awaiting_projection' | 'failed' | 'complete';
  images_processed?: number;
  faces_found?: number;
  clusters_created?: number;
  retry_count?: number;
  current_stage?: string;
  last_successful_processed_identities?: number;
  last_error_code?: string;
  current_chunk_size?: number;
  last_error_at?: string;
}

export interface RecognitionJob {
  id: string;
  type: 'analyze' | 'clustering' | 'curation' | 'split';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: JobProgress | null;
  started_at: string;
  finished_at: string | null;
  message?: string | null;
  snapshot_version?: number | null;
  source_job_id?: string | null;
  projection_acknowledged_at?: string | null;
}
