/**
 * SPA session-expired copy leaf (REF-19) — the single owner of both strings.
 *
 * `__()` sits at the declaration site so gettext extraction can see the literals,
 * matching the established copy-module idiom (pages/workbench/confirmTabCopy.ts:4,
 * pages/retention/retentionDialogCopy.ts:13). Consumers — appError.toUserMessage,
 * userFacingError.formatUserFacingError, and components/ui/UserFacingErrorNotice —
 * read these values and must NOT re-declare the literal or re-wrap it in `__()`:
 * `__(SPA_SESSION_EXPIRED_COPY.sessionExpired)` is not statically extractable and
 * puts the copy decision back into two modules (FEBT-1-W1-E-03).
 *
 * Imported by appError and re-exported from userFacingError so the old path stays valid.
 */

import { __ } from '@wordpress/i18n';

export const SPA_SESSION_EXPIRED_COPY: {
  readonly sessionExpired: string;
  readonly reloadPage: string;
} = {
  sessionExpired: __('Your session expired — reload the page and sign in again.', 'alt-context'),
  reloadPage: __('Reload page', 'alt-context'),
};
