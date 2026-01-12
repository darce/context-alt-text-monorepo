// This file is generated from packages/shared-contracts/schemas/recognition-job.schema.json.

export interface JobProgress {
  completed: number;
  total: number;
}

export interface RecognitionJob {
  id: string;
  type: 'analyze' | 'clustering' | 'curation' | 'split';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: JobProgress | null;
  started_at: string;
  finished_at: string | null;
  message?: string | null;
}
