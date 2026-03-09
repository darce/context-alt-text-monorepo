// This file is generated from packages/shared-contracts/schemas/recognition-job.schema.json.

export interface JobProgress {
  completed: number;
  total: number;
  phase?: 'queued' | 'detecting' | 'clustering' | 'awaiting_projection' | 'complete';
  images_processed?: number;
  faces_found?: number;
  clusters_created?: number;
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
