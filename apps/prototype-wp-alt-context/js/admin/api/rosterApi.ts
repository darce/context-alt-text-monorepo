import { fetchApi, stripTrailingSlash } from '../utils/http';
import { getEndpoint, getConfig } from './config';

export interface RosterEntry {
  id: number;
  name: string;
  tags: string[];
  cluster_count: number;
  updated_at: string;
}

export const listRosterEntries = async (): Promise<RosterEntry[]> => {
  const endpoint = getEndpoint('rosterEntries');
  return fetchApi(endpoint, { method: 'GET', restNonce: getConfig().nonce });
};

export interface CommitClusterRequest {
  clusterId: string;
  rosterEntryId?: number;
  newEntryName?: string;
}

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
