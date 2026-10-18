import { fetchRequiredApi, stripTrailingSlash } from '../utils/http';
import { getConfig, getEndpoint } from './config';

export interface PersonMergeRequest { survivor_id: number; loser_id: number }
export interface PersonMergePerson { id: number; name: string; cluster_count: number }
export interface PersonMergePreview {
  survivor: PersonMergePerson;
  loser: PersonMergePerson;
  tags: string[];
  conflicts: unknown[];
}
export interface PersonMergeResult { survivor_id: number; merged_cluster_ids: string[]; undo_token: string }
export interface PersonMergeUndoResult { restored_person_id: number; restored_cluster_ids: string[] }

/**
 * IDCHIP-1-MUI-R-03: fetchRequiredApi only casts the wire body to the declared
 * generic. Without an explicit boundary check every field below is trusted
 * blindly, so malformed responses must fail loudly here instead of reaching
 * the dialog/undo banner as unchecked assumptions.
 */
export class MalformedPersonMergeResponseError extends Error {
  constructor(field: string) {
    super(`Person merge response is missing or malformed: ${field}`);
    this.name = 'MalformedPersonMergeResponseError';
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every(item => typeof item === 'string');

const isPersonMergePerson = (value: unknown): value is PersonMergePerson =>
  isRecord(value) &&
  typeof value.id === 'number' &&
  typeof value.name === 'string' &&
  typeof value.cluster_count === 'number';

const parsePersonMergePreview = (payload: unknown): PersonMergePreview => {
  if (!isRecord(payload)) throw new MalformedPersonMergeResponseError('response body');
  if (!isPersonMergePerson(payload.survivor)) throw new MalformedPersonMergeResponseError('survivor');
  if (!isPersonMergePerson(payload.loser)) throw new MalformedPersonMergeResponseError('loser');
  if (!isStringArray(payload.tags)) throw new MalformedPersonMergeResponseError('tags');
  if (!Array.isArray(payload.conflicts)) throw new MalformedPersonMergeResponseError('conflicts');
  return payload as unknown as PersonMergePreview;
};

const parsePersonMergeResult = (payload: unknown): PersonMergeResult => {
  if (!isRecord(payload)) throw new MalformedPersonMergeResponseError('response body');
  if (typeof payload.survivor_id !== 'number') throw new MalformedPersonMergeResponseError('survivor_id');
  if (!isStringArray(payload.merged_cluster_ids)) throw new MalformedPersonMergeResponseError('merged_cluster_ids');
  if (typeof payload.undo_token !== 'string' || payload.undo_token.length === 0) {
    throw new MalformedPersonMergeResponseError('undo_token');
  }
  return payload as unknown as PersonMergeResult;
};

const parsePersonMergeUndoResult = (payload: unknown): PersonMergeUndoResult => {
  if (!isRecord(payload)) throw new MalformedPersonMergeResponseError('response body');
  if (typeof payload.restored_person_id !== 'number') throw new MalformedPersonMergeResponseError('restored_person_id');
  if (!isStringArray(payload.restored_cluster_ids)) throw new MalformedPersonMergeResponseError('restored_cluster_ids');
  return payload as unknown as PersonMergeUndoResult;
};

const post = (suffix: string, body: PersonMergeRequest | { undo_token: string }): Promise<unknown> =>
  fetchRequiredApi<unknown>(`${stripTrailingSlash(getEndpoint('rosterPersons'))}/merge${suffix}`, {
    method: 'POST', body, restNonce: getConfig().nonce,
  });

export const previewPersonMerge = async (body: PersonMergeRequest): Promise<PersonMergePreview> =>
  parsePersonMergePreview(await post('/preview', body));
export const commitPersonMerge = async (body: PersonMergeRequest): Promise<PersonMergeResult> =>
  parsePersonMergeResult(await post('', body));
export const undoPersonMerge = async (undo_token: string): Promise<PersonMergeUndoResult> =>
  parsePersonMergeUndoResult(await post('/undo', { undo_token }));

export const isPersonMergeConflict = (error: unknown): boolean =>
  typeof error === 'object' && error !== null && 'status' in error && error.status === 409;

export const personMergeErrorMessage = (error: unknown): string => {
  if (typeof error === 'object' && error !== null && 'bodyPreview' in error && typeof error.bodyPreview === 'string') {
    try {
      const body: unknown = JSON.parse(error.bodyPreview);
      if (typeof body === 'object' && body !== null && 'message' in body && typeof body.message === 'string') return body.message;
    } catch { /* Use the transport message when the response preview is truncated. */ }
  }
  return error instanceof Error ? error.message : 'Unable to complete the merge request.';
};
