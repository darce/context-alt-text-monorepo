/**
 * Identity Operations API barrel.
 */

export {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
  type PendingNameSuggestionsResponse,
} from './identityQueriesApi';

export {
  acceptSuggestion,
  acceptMergeSuggestion,
  rejectSuggestion,
  rejectMergeSuggestion,
  acceptNameSuggestion,
  rejectNameSuggestion,
  bulkAcceptSuggestions,
} from './identityActionsApi';
