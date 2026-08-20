/**
 * Single reserved-label gate for every naming surface (UXW2-3 / REF-26).
 * Machine-shaped auto IDs (`cluster-7`, hex labels) are reserved; users must
 * pick a descriptive name. Previously duplicated across four call sites.
 */

import { __ } from '@wordpress/i18n';

import { isHumanLabeledTarget } from './suggestionProjection';

export const getReservedLabelMessage = (): string =>
  __('This label format is reserved for automatic group IDs. Choose a descriptive name.', 'alt-context');

export const isReservedLabel = (label: string): boolean => !isHumanLabeledTarget(label);
