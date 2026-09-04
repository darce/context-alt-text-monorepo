import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { describe, expect, it, vi } from 'vitest';

import {
  TWIN_CHIP_ACCEPT_TEMPLATE,
  TWIN_CHIP_PROMPT_TEMPLATE,
  TWIN_CHIP_REJECT_LABEL,
  uxmapTwinPendingPlaceholder,
} from '../twinChipCopy';

vi.mock('@wordpress/i18n', () => ({
  __: (text: string) => text,
  sprintf: (template: string, ...args: (string | number)[]) => {
    let idx = 0;
    return template.replace(/%(\d+\$)?[sd]/g, () => String(args[idx++] ?? ''));
  },
}));

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../../');
const uxmapPath = path.join(pluginRoot, 'docs/ux-maps/workbench-2pane.uxmap.json');

interface UxmapAction {
  id: string;
  verb?: string;
  preview_required?: boolean;
  costly?: boolean;
}

interface UxmapZone {
  id: string;
  label?: string;
  states?: string[];
}

interface UxmapDoc {
  screens?: { zones?: UxmapZone[] }[];
  actions?: UxmapAction[];
}

describe('uxmap twin_pending (S4R2-F3)', () => {
  const uxmap = JSON.parse(readFileSync(uxmapPath, 'utf8')) as UxmapDoc;
  const clusterList = uxmap.screens
    ?.flatMap((screen) => screen.zones ?? [])
    .find((zone) => zone.id === 'z-cluster-list');
  const actions = uxmap.actions ?? [];
  const mergeTwin = actions.find((action) => action.id === 'merge_twin');
  const keepSeparate = actions.find((action) => action.id === 'keep_separate');

  /**
   * `twin_pending` is not a member of the canonical `MapState` enum
   * (`workbay_canvas_mcp/ux_map/models.py`, mirrored in
   * `js/admin/__tests__/uxmap-render-parity.test.ts`). The SSOT models the
   * twin-pending chip as an `edge_input` of `default` on `z-cluster-list` and
   * says so in the zone label, so this guard asserts the modelled state plus
   * the label sentence that binds it to twin-pending — a bare
   * `toContain('twin_pending')` demanded a state the schema rejects.
   */
  it('keeps twin-pending on the cluster-list zone with live chip copy', () => {
    expect(clusterList).toBeDefined();
    expect(clusterList?.states).toContain('edge_input');
    expect(clusterList?.label).toContain('Twin-pending (an edge_input of default)');

    const copy = clusterList?.label ?? '';
    expect(copy).toContain(uxmapTwinPendingPlaceholder(TWIN_CHIP_PROMPT_TEMPLATE));
    expect(copy).toContain(uxmapTwinPendingPlaceholder(TWIN_CHIP_ACCEPT_TEMPLATE));
    expect(copy).toContain(TWIN_CHIP_REJECT_LABEL);
    expect(copy).toContain('IdentityClusterItem.tsx');
  });

  it('maps merge_twin / keep_separate without a preview', () => {
    expect(mergeTwin).toBeDefined();
    expect(keepSeparate).toBeDefined();
    expect(mergeTwin?.verb).toContain('IdentityClusterItem.tsx');
    expect(keepSeparate?.verb).toContain('IdentityClusterItem.tsx');
    expect(mergeTwin?.preview_required).toBe(false);
    expect(mergeTwin?.costly).toBe(false);
    expect(keepSeparate?.preview_required).toBe(false);
    expect(keepSeparate?.costly).toBe(false);
  });
});
