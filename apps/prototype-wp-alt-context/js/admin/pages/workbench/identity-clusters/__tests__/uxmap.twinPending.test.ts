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
   * WBUX6-W3-L3-06: this guard used to assert that the zone label and the action
   * verbs literally CONTAINED 'IdentityClusterItem.tsx'. That put a source path
   * in operator-visible copy, which is the defect that finding names -- and it
   * was load-bearing in the wrong direction: `.../identity-clusters/Foo.tsx`
   * trips the retired-vocabulary ban on a PATH SEGMENT, so a pure rename turned
   * an unrelated test red. `code_ref` is the sanctioned home for pointers, but
   * the upstream workbay_canvas_mcp Zone/Action models forbid extra keys, so a
   * zone- or action-level code_ref cannot round-trip through the renderer yet.
   *
   * Asserting a path string is in any case the weak form of the claim: it pins
   * the pointer's TEXT, not its TRUTH -- it stays green after the component is
   * gutted. Read the implementation instead and assert it really carries the
   * copy the map attributes to it. That is what the original assertion meant.
   */
  const implementationSource = readFileSync(
    path.join(pluginRoot, 'js/admin/pages/workbench/identity-clusters/IdentityClusterItem.tsx'),
    'utf8',
  );

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
    // The map attributes this zone's twin-pending chip to IdentityClusterItem;
    // assert the component actually renders that copy rather than that the label
    // spells the filename.
    expect(implementationSource).toContain('TWIN_CHIP_PROMPT_TEMPLATE');
    expect(implementationSource).toContain('TWIN_CHIP_REJECT_LABEL');
  });

  it('maps merge_twin / keep_separate without a preview', () => {
    expect(mergeTwin).toBeDefined();
    expect(keepSeparate).toBeDefined();
    // Same substitution as above: the accept/reject affordances these two
    // actions describe are the twin chip's, so pin that the component renders
    // both -- not that the verbs quote a path.
    expect(implementationSource).toContain('TWIN_CHIP_ACCEPT_TEMPLATE');
    expect(implementationSource).toContain('TWIN_CHIP_REJECT_LABEL');
    expect(mergeTwin?.preview_required).toBe(false);
    expect(mergeTwin?.costly).toBe(false);
    expect(keepSeparate?.preview_required).toBe(false);
    expect(keepSeparate?.costly).toBe(false);
  });
});
