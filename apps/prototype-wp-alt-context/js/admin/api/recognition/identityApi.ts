/**
 * Identity Operations API barrel.
 */

export {
  fetchMediaIdentities,
  fetchIdentitySuggestions,
  fetchPendingSuggestions,
  fetchPendingMergeSuggestions,
  fetchPendingNameSuggestions,
} from './identityQueriesApi';

export type { PendingNameSuggestionsResponse } from './types';

export {
  acceptSuggestion,
  acceptMergeSuggestion,
  rejectSuggestion,
  rejectMergeSuggestion,
  acceptNameSuggestion,
  rejectNameSuggestion,
  bulkAcceptSuggestions,
} from './identityActionsApi';
