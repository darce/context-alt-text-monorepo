/**
 * Canonical missing-representative copy for cluster preview surfaces.
 * TopClusterCard and ClusterPreview must both read this module.
 */
import { __ } from '@wordpress/i18n';

export const REPRESENTATIVE_VOCABULARY = {
  imageUnavailable: __('Representative image unavailable', 'alt-context'),
} as const;
