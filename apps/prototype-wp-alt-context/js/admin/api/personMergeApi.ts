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

const post = <T>(suffix: string, body: PersonMergeRequest | { undo_token: string }): Promise<T> =>
  fetchRequiredApi<T>(`${stripTrailingSlash(getEndpoint('rosterPersons'))}/merge${suffix}`, {
    method: 'POST', body, restNonce: getConfig().nonce,
  });
export const previewPersonMerge = (body: PersonMergeRequest) => post<PersonMergePreview>('/preview', body);
export const commitPersonMerge = (body: PersonMergeRequest) => post<PersonMergeResult>('', body);
export const undoPersonMerge = (undo_token: string) => post<PersonMergeUndoResult>('/undo', { undo_token });

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
