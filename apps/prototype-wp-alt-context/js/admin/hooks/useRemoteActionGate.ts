import { __ } from '@wordpress/i18n';

export interface RemoteActionGateProps {
  disabled: boolean;
  'aria-disabled': true | undefined;
  title: string | undefined;
}

/** Single source for the offline fail-fast reason shown on gated CTAs and thrown by gated mutations (sr-007). */
export const offlineActionReason = (): string =>
  __('Unavailable while the recognition service is offline', 'alt-context');

/**
 * Presentational-agnostic disabled-with-reason props for remote-compute buttons
 * (rg-004 role semantics, UI-02/sr-004 never-color-alone via title).
 */
export const useRemoteActionGate = (offline: boolean): RemoteActionGateProps =>
  offline
    ? {
        disabled: true,
        'aria-disabled': true,
        title: offlineActionReason(),
      }
    : {
        disabled: false,
        'aria-disabled': undefined,
        title: undefined,
      };
