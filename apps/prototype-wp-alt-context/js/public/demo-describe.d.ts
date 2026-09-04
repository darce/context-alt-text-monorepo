export const POLL_TIMEOUT_MESSAGE: string;

export const PUBLIC_DEMO_ERROR_CODE: Readonly<{
  POLL_TIMEOUT: 'acx_public_demo_poll_timeout';
  INVALID_RESPONSE: 'acx_public_demo_invalid_response';
}>;

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
  onUpdate?: (body: Record<string, unknown>) => void;
}

export function pollRun(options: PollRunOptions): Promise<Record<string, unknown>>;
