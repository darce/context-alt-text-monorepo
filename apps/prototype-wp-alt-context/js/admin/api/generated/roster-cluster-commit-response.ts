// This file is generated from packages/shared-contracts/schemas/roster-cluster-commit-response.schema.json.

/**
 * Response from POST /acx/v1/roster/clusters/{cluster_id}/commit.
 * Bound person identity is present for both create and rebind outcomes.
 */
export interface RosterClusterCommitResponse {
  cluster_id: string;
  person_id: number | null;
  person_uuid: string | null;
  person_name: string | null;
  updated_at: string;
}
