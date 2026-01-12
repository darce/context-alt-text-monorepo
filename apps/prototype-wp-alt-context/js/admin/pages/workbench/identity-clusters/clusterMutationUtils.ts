export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export const isAbortError = (err: unknown): boolean =>
  Boolean(err && typeof err === 'object' && 'name' in err && (err as { name: string }).name === 'AbortError');
