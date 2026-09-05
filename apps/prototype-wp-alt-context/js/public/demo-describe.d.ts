export const POLL_TIMEOUT_MESSAGE: string;

export const PUBLIC_DEMO_ERROR_CODE: Readonly<{
  POLL_TIMEOUT: 'acx_public_demo_poll_timeout';
  REQUEST_ABORTED: 'acx_public_demo_request_aborted';
  INVALID_RESPONSE: 'acx_public_demo_invalid_response';
  INCOMPLETE_RESULT: 'acx_public_demo_incomplete_result';
  PIPELINE_FAILED: 'acx_public_demo_pipeline_failed';
}>;

export type PublicDemoStatus = 'pending' | 'running' | 'completed' | 'completed_with_errors' | 'failed' | 'cancelled';
export type PublicDemoPhase = 'queued' | 'warming' | 'describing' | 'complete' | 'failed' | 'cancelled';
export type PublicDemoGpuState = 'unknown' | 'stopped' | 'starting' | 'warming' | 'ready' | 'degraded';

export interface PublicDemoEnvelope {
  run_id: string;
  status: PublicDemoStatus;
  phase: PublicDemoPhase;
  gpu_state: PublicDemoGpuState;
  progress: { done: number; total: number };
  deadline_seconds?: number;
  description?: string;
  error?: { code: string; message: string };
}

export class PublicDemoClientError extends Error {
  constructor(code: string, message: string, status?: number);
  code: string;
  status: number;
}

export interface PollRunOptions {
  statusUrl: string;
  nonce: string;
  fetchImpl?: typeof fetch;
  sleep?: (milliseconds: number) => void | Promise<void>;
  now?: () => number;
  timeoutMs?: number;
  navigationSignal?: AbortSignal;
  onUpdate?: (body: PublicDemoEnvelope) => void;
}

export function parsePublicDemoEnvelope(body: unknown): PublicDemoEnvelope;
export function pollRun(options: PollRunOptions): Promise<PublicDemoEnvelope & { description: string }>;
export function statusPresentation(body: PublicDemoEnvelope): {
  state: 'queued' | 'warming' | 'describing' | 'completed' | 'failed';
  message: string;
};
export function initializeDemo(root: HTMLElement): void;
