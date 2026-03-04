import { fetchApi, fetchRequiredApi, stripTrailingSlash } from '../utils/http';
import { getEndpoint, getConfig } from './config';
import type { RosterEntry } from './generated';

export type { RosterEntry } from './generated';

export const listRosterEntries = async (): Promise<RosterEntry[]> => {
  const endpoint = getEndpoint('rosterEntries');
  return fetchRequiredApi<RosterEntry[]>(endpoint, { method: 'GET', restNonce: getConfig().nonce });
};

export interface CommitClusterRequest {
  clusterId: string;
  rosterEntryId?: number;
  newEntryName?: string;
}

export const createPerson = async (name: string, tags: string[] = []): Promise<RosterEntry> => {
  const endpoint = getEndpoint('rosterPersons');
  return fetchRequiredApi<RosterEntry>(endpoint, {
    method: 'POST',
    body: { name, tags },
    restNonce: getConfig().nonce,
  });
};

export const updatePerson = async (id: number, name?: string, tags?: string[]): Promise<RosterEntry> => {
  const base = getEndpoint('rosterPersons');
  const url = `${stripTrailingSlash(base)}/${id}`;
  return fetchRequiredApi<RosterEntry>(url, {
    method: 'PUT',
    body: { name, tags },
    restNonce: getConfig().nonce,
  });
};

export const deletePerson = async (id: number): Promise<void> => {
  const base = getEndpoint('rosterPersons');
  const url = `${stripTrailingSlash(base)}/${id}`;
  await fetchApi(url, {
    method: 'DELETE',
    restNonce: getConfig().nonce,
  });
};

export const commitClusterToRosterEntry = async ({
  clusterId,
  rosterEntryId,
  newEntryName,
}: CommitClusterRequest): Promise<void> => {
  let base: string;
  try {
    base = getEndpoint('rosterClusters');
  } catch {
    throw new Error('Roster cluster endpoint is not configured.');
  }

  const url = `${stripTrailingSlash(base)}/${clusterId}/commit`;
  await fetchApi(url, {
    method: 'POST',
    body: {
      roster_entry_id: rosterEntryId ?? null,
      new_entry_name: newEntryName ?? null,
    },
    restNonce: getConfig().nonce,
  });
};
