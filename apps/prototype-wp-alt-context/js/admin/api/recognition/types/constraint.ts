/** Pairwise identity constraint. */
export interface IdentityConstraint {
  id: string;
  tenant_id: string;
  identity_a: string;
  identity_b: string;
  constraint_type: 'must_link' | 'cannot_link';
  source: 'merge' | 'split' | 'wrong_person';
  created_at: string;
  created_by_user_id?: number;
}

/** Request to create constraint when removing identity. */
export interface CreateConstraintsRequest {
  identity_id: string;
  create_constraints: boolean;
}
