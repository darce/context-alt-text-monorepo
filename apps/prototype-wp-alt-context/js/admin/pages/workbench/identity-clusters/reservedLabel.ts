/**
 * Single reserved-label gate for every naming surface (UXW2-3 / REF-26).
 * Machine-shaped auto IDs (`cluster-7`, hex labels) are reserved; users must
 * pick a descriptive name. Previously duplicated across four call sites.
 */

import { isHumanLabeledTarget } from './suggestionProjection';

export const RESERVED_LABEL_MESSAGE =
  'This label format is reserved for automatic cluster IDs. Choose a descriptive name.';

export const isReservedLabel = (label: string): boolean => !isHumanLabeledTarget(label);
