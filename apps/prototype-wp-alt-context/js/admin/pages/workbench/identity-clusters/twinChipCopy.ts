/**
 * Twin-chip copy (WBUX-6/C3). One gettext authority for the live chip and
 * the uxmap twin_pending SSOT test.
 */

import { __ } from '@wordpress/i18n';

export const TWIN_CHIP_PROMPT_TEMPLATE = __('Same person as %s?', 'alt-context');
export const TWIN_CHIP_ACCEPT_TEMPLATE = __('Merge into %s', 'alt-context');
export const TWIN_CHIP_REJECT_LABEL = __('Not the same', 'alt-context');
export const TWIN_CHIP_PENDING_STATUS = __('Saving merge suggestion…', 'alt-context');

/** uxmap uses an explicit placeholder instead of sprintf `%s`. */
export const uxmapTwinPendingPlaceholder = (template: string): string =>
  template.replace('%s', '<survivor label>');
