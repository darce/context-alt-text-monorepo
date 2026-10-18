/**
 * Closest roster candidates for one cluster (c82 FIR).
 *
 * GET /clusters/{id}/roster-candidates is the source of truth for match bands
 * (strong / possible / none). This adapter only types and fetches the payload;
 * it never recomputes similarity or bands on the client.
 */

import { fetchRequiredApi, stripTrailingSlash } from '../../utils/http';
import { getConfig, getEndpoint } from '../config';

/** Display cap for the on-demand naming read (matches the backend default window). */
export const ROSTER_CANDIDATES_TOP_K = 5;

export type RosterCandidateBand = 'strong' | 'possible' | 'none';
export type RosterCandidateQuality = 'ok' | 'low_quality' | 'occluded';

export class RosterCandidatesReadError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RosterCandidatesReadError';
  }
}

export interface RosterCandidate {
  cluster_id: string;
  name: string;
  similarity: number;
  band: RosterCandidateBand;
  /** Null when the candidate's cluster is not linked to a roster person; never committable. */
  roster_entry_id: number | null;
}

export interface RosterCandidatesResponse {
  model_id: string;
  embedding_model: string;
  computed_at: string;
  probe_face_count: number;
  reference_face_count: number;
  quality_flag: RosterCandidateQuality;
  thresholds: {
    suggestion_floor: number;
    suggestion_ceiling: number;
    similarity_threshold: number;
  };
  candidates: RosterCandidate[];
}

export const fetchClusterRosterCandidates = async (
  clusterId: string,
  topK: number = ROSTER_CANDIDATES_TOP_K,
): Promise<RosterCandidatesResponse> => {
  const base = getEndpoint('recognitionClusters');
  const url = new URL(
    `${stripTrailingSlash(base)}/${encodeURIComponent(clusterId)}/roster-candidates`,
    window.location.origin,
  );
  url.searchParams.set('top_k', String(topK));

  const response = await fetchRequiredApi<RosterCandidatesResponse>(url.toString(), {
    method: 'GET',
    restNonce: getConfig().nonce,
  });
  const quality = response.quality_flag === 'ok' || response.quality_flag === 'occluded'
    ? response.quality_flag
    : 'low_quality';
  if (quality !== 'ok' && response.candidates.some((candidate) => candidate.band === 'strong')) {
    throw new RosterCandidatesReadError('Roster candidate quality must not allow a strong band for a non-ok probe.');
  }
  return { ...response, quality_flag: quality };
};
