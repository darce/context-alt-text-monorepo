/**
 * Identity Operations API barrel.
 */

export {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
} from './identityQueriesApi';

export { acceptSuggestion, acceptMergeSuggestion, rejectSuggestion, rejectMergeSuggestion } from './identityActionsApi';
