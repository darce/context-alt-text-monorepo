import { __ } from '@wordpress/i18n';

export interface RemoteActionGateProps {
  disabled: boolean;
  'aria-disabled': true | undefined;
  title: string | undefined;
}

/**
 * Presentational-agnostic disabled-with-reason props for remote-compute buttons
 * (rg-004 role semantics, UI-02/sr-004 never-color-alone via title).
 */
export const useRemoteActionGate = (offline: boolean): RemoteActionGateProps =>
  offline
    ? {
        disabled: true,
        'aria-disabled': true,
        title: __('Unavailable while the recognition service is offline', 'alt-context'),
      }
    : {
        disabled: false,
        'aria-disabled': undefined,
        title: undefined,
      };
