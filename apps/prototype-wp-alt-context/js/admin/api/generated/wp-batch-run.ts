// This file is generated from packages/shared-contracts/schemas/wp-batch-run.schema.json.

export interface WpBatchRunFailedBatch {
  batch_index: number;
  media_ids: number[];
  error_code: string;
  error_message: string;
}

export interface WpBatchRun {
  id: string;
  submitted_total: number;
  accepted_total: number;
  completed_total: number;
  failed_total: number;
  cancelled_total: number;
  unreadable_media_ids: number[];
  failed_batches: WpBatchRunFailedBatch[];
  child_job_ids: string[];
  terminal_state: boolean;
}
