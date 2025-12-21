/**
 * Identity Clusters module.
 *
 * Components for displaying and editing identity clusters in the workbench.
 *
 * @example
 * ```tsx
 * import { IdentityClusterList } from './identity-clusters';
 *
 * <IdentityClusterList identities={identities} mediaId={mediaId} />
 * ```
 */

// Main component
export { IdentityClusterList } from './IdentityClusterList';

// Sub-components (for testing/Storybook)
export { IdentityClusterItem } from './IdentityClusterItem';
export { ClusterPreview } from './ClusterPreview';
export { ClusterActions } from './ClusterActions';
export { ClusterEditForm } from './ClusterEditForm';
export { MergeUndoBanner } from './MergeUndoBanner';
export { SuggestionReviewPanel } from './SuggestionReviewPanel';
export { InlineSuggestionPrompt } from './InlineSuggestionPrompt';
export { AnchorSelectionModal } from './AnchorSelectionModal';

// Hooks
export { useClusterEditState } from './useClusterEditState';
export { useClusterMutations } from './useClusterMutations';
export { useClusterSuggestions } from './useClusterSuggestions';

// Utils
export { formatClusterLabel, groupIdentitiesByClusters, getEditableClusterId } from './utils';

// Types
export type { ClusterGroup, ClusterEditState, ClusterEditAction } from './types';
