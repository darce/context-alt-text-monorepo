import type { WorkbenchOverlay } from '../../api/recognition';

import type { WorkbenchTab } from './WorkbenchContext';

export const buildWorkbenchOverlayHref = (section: WorkbenchTab, overlay: Exclude<WorkbenchOverlay, null>): string =>
  `#/workbench?tab=${encodeURIComponent(section)}&panel=${encodeURIComponent(overlay)}`;

export const SCAN_CONFLICTS_HREF = buildWorkbenchOverlayHref('scan', 'conflicts');
export const SCAN_DEAD_LETTER_HREF = buildWorkbenchOverlayHref('scan', 'dead-letter');
