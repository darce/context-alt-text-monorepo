# Phase 4: Recognition UX Polish

## Problem Statement

Cluster review is the most frequent operator workflow, but it remains ergonomically incomplete. While Phase 2 delivered multi-select (`useClusterSelection`), bulk merge/dismiss (`BulkActionBar` + `useClusterActions`), keyboard navigation in `ClusterGrid`, and roster-aware labeling via `Combobox` in `ClusterDrawerPanel`, several refinements are needed to make the experience production-ready: confirmation dialogs for bulk actions use `window.confirm` instead of accessible modal dialogs, the bulk action bar has no loading/disabled state during mutations, there is no "select all" capability, and the cluster labeling combobox does not create a person inline (it still uses a separate text input for "Create new"). This phase polishes these surfaces into a cohesive, accessible cluster review workflow.

## Workflow Principles

- **TDD**: write a failing test before each change. Red -> Green -> Refactor.
- **Curation-first**: roster assignments override backend suggestions. Person creation from labeling flow is a curation operation.
- **Sovereign model**: all data reads come from local projection. No live backend dependency for rendering.
- **Accessibility**: all interactive surfaces must be keyboard-operable. Confirmation dialogs must trap focus. Use grouped card semantics (`role="group"` container with button cards), not ARIA grid semantics.
- **Small vertical slices**: each deliverable is independently shippable and testable.

## Terminology

- **Bulk action**: an operation applied to multiple selected clusters at once (merge, dismiss).
- **Confirmation dialog**: accessible modal (Radix Dialog, reusing existing `dialog.tsx` wrapper and `useClusterConfirmDialog` pattern) shown before destructive bulk operations, replacing `window.confirm`.
- **Select all**: toggle to select/deselect all visible clusters in the grid.
- **Roster-aware labeling**: cluster labeling combobox searches existing persons. `onCreate` callback triggers atomic person creation + assignment via `commitClusterToRosterEntry`.
- **Label derivation**: when `person_id IS NOT NULL`, cluster display label = person name from `wp_acx_persons`.
- **Toast**: brief notification shown after mutation outcomes via Radix Toast (already wired via `ToastContext`).
- **Drawer**: `ClusterDrawerPanel` slide-out panel showing cluster detail and assignment controls.

## Current State Analysis

### What Works

- `useClusterSelection` hook (46 lines) provides `toggle`, `selectRange`, `clear`, `isSelected`, `count` with `Set<string>` state.
- `ClusterGrid` (248 lines) renders cluster cards with:
  - Checkbox per card (via Radix Checkbox component).
  - Shift+click range selection using `selectRange`.
  - Keyboard navigation: ArrowRight/Left/Up/Down moves focus, Enter opens drawer, Space toggles selection, Escape clears selection.
  - Visual selection state (`is-selected` class, `aria-pressed`).
  - `tabIndex={0}` and `role="button"` on cards.
- `BulkActionBar` (59 lines) shows selected count, merge button (disabled when < 2), dismiss button, and clear button.
- `useClusterActions` hook (133 lines) provides `bulkMergeMutation` (sequential merge to first cluster) and `bulkDismissMutation` (parallel dismiss) with toast notifications via `useToast`.
- `ClusterDrawerPanel` (273 lines) has:
  - Combobox for roster-aware labeling (searches existing persons by name).
  - "Create new person" option in combobox triggers inline text input.
  - Commit button wired to `commitClusterToRosterEntry`.
  - Metadata display: face count, confidence score, creation date.
  - Drag-and-drop face reassignment with discard dropzone.
- `RosterPage` (243 lines) orchestrates selection, drag-drop, and actions, with `window.confirm` for bulk merge/dismiss.
- `ToastContext` (Radix Toast) provides `success`, `error`, `info` toast methods.
- Core hooks and component flows have Vitest test coverage.

### What's Missing / Needs Polish

- **`window.confirm` for bulk operations**: `handleBulkMerge` and `handleBulkDismiss` in `RosterPage.tsx` use `window.confirm()`. This is not accessible (no focus trap, not styleable, not testable in JSDOM). Should use Radix Dialog (reusing existing `dialog.tsx` wrapper and `useClusterConfirmDialog` pattern from workbench).
- **No loading state on bulk bar**: when `bulkMergeMutation` or `bulkDismissMutation` is pending, the `BulkActionBar` buttons are not disabled and show no spinner.
- **No "select all" toggle**: operators processing large batches must Shift+click from first to last. A "Select all" checkbox in the grid header or bulk bar would be faster.
- **Inline person creation in combobox incomplete**: the `ClusterDrawerPanel` uses a separate `<input>` for new person name when "Create new" is selected. The create flow should be integrated into the combobox via the existing `onCreate` callback (type a name not in the list -> "Create [name]" button appears -> clicking it sets the sentinel `selectedEntryId='create'` + `newEntryName`, preserving the atomic `commitClusterToRosterEntry` path). The Combobox already supports `onCreate`.
- **No batch progress for bulk operations**: merging 10 clusters fires 9 sequential API calls with no per-step progress. A progress indicator or "merging N of M" text would improve confidence.
- **Drawer focus management**: opening the drawer does not trap focus or auto-focus the close button. Pressing Tab can leave the drawer.
- **Grid ARIA grouping missing**: cards correctly use `role="button"` with `aria-pressed` for toggle semantics, but the grid container has no grouping role or label. Add `role="group"` and `aria-label` to the container. Note: `role="grid"`/`role="gridcell"` is NOT appropriate -- these cards are interactive toggle widgets, not spreadsheet cells.
- **No empty selection feedback** (optional/backlog): when selection count drops to 0, `BulkActionBar` disappears. A subtle animation or transition would be smoother. Low priority -- no measurable UX or reliability impact.

## Proposed Solution

Four vertical slices:

1. **Accessible confirmation dialogs**: replace `window.confirm` with Radix Dialog (reusing existing `dialog.tsx` wrapper and `useClusterConfirmDialog` pattern from workbench). Wire `onOpenChange` for ESC/overlay dismiss. Wire loading/disabled state to mutation pending.
2. **Select all and bulk bar polish**: add "Select all" checkbox in always-visible cluster section header (NOT inside conditionally-rendered `BulkActionBar`). Disable action buttons during pending mutations. Show progress text for sequential merge. Support indeterminate state on header checkbox.
3. **Inline person creation in combobox**: wire existing Combobox `onCreate` callback to set the sentinel (`selectedEntryId='create'` + `newEntryName`), preserving the atomic `commitClusterToRosterEntry` path. Remove separate "Create new" input. Do NOT use `useCreatePerson` in the drawer commit flow.
4. **Accessibility hardening**: drawer focus trap, container grouping via `role="group"` (NOT `role="grid"`/`role="gridcell"`).

## Patterns to Follow

### Accessible Confirmation Dialog (Reuse Existing Pattern)

Reuse existing `dialog.tsx` wrapper (`DialogRoot`, `DialogOverlay`, `DialogContent`, etc.) and follow the `ClusterConfirmDialog` + `useClusterConfirmDialog` pattern from `workbench/identity-clusters/`. This provides:

- `onOpenChange` wiring for ESC/overlay dismiss (single source of truth for open state)
- Promise-based `requestConfirm()` for clean async flow in handlers
- Unmount cleanup to prevent stale resolver leaks
- BEM class names (`acx-dialog__overlay`, `acx-dialog__content`) matching existing styles

Add `isPending` prop for mutation loading state (not present in workbench version).

```tsx
// js/admin/pages/roster/ConfirmDialog.tsx
// Extends workbench pattern with isPending support
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from "../../../components/ui/dialog";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description: string;
  confirmLabel: string;
  isPending?: boolean;
}

export const ConfirmDialog = ({
  open,
  onOpenChange,
  onConfirm,
  onCancel,
  title,
  description,
  confirmLabel,
  isPending,
}: ConfirmDialogProps): React.JSX.Element => (
  <DialogRoot open={open} onOpenChange={onOpenChange}>
    <DialogPortal>
      <DialogOverlay />
      <DialogContent>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
        <div className="acx-dialog__actions">
          <button
            type="button"
            className="acx-button acx-button--secondary"
            onClick={onCancel}
            disabled={isPending}
          >
            {__("Cancel", "alt-context")}
          </button>
          <button
            type="button"
            className="acx-button acx-button--danger"
            onClick={onConfirm}
            disabled={isPending}
          >
            {isPending ? __("Processing...", "alt-context") : confirmLabel}
          </button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
);
```

### Select All in useClusterSelection

```typescript
// Extend useClusterSelection hook
const selectAll = useCallback((allIds: string[]) => {
  setSelectedIds(new Set(allIds));
}, []);

const isAllSelected = useCallback(
  (allIds: string[]) =>
    allIds.length > 0 && allIds.every((id) => selectedIds.has(id)),
  [selectedIds],
);
```

### BulkActionBar with Loading State

`BulkActionBar` is conditionally rendered (`selection.count > 0`), so select-all controls do NOT belong here. Only add loading state props.

```tsx
interface BulkActionBarProps {
  count: number;
  onMerge: () => void;
  onDismiss: () => void;
  onClear: () => void;
  isMerging?: boolean;
  isDismissing?: boolean;
}
```

### Select-All Checkbox in Cluster Header

Place select-all in the always-visible cluster section header in `RosterPage`, outside the `selection.count > 0` conditional. Use indeterminate state when some (but not all) are selected.

```tsx
// In RosterPage, inside the cluster tab header (always visible)
<div className="acx-roster__tab-header">
  <Checkbox
    checked={selection.isAllSelected(clusterIds)
      ? true
      : selection.count > 0
        ? 'indeterminate'
        : false}
    onCheckedChange={() =>
      selection.isAllSelected(clusterIds) ? selection.clear() : selection.selectAll(clusterIds)
    }
    ariaLabel={__('Select all clusters', 'alt-context')}
  />
  <h2>{ROSTER_TABS.clusters.label}</h2>
  {selection.count > 0 && (
    <BulkActionBar ... />
  )}
</div>
```

### Inline Person Creation via Combobox onCreate (Atomic Path)

Wire Combobox `onCreate` to set the existing sentinel values. The backend `commitClusterToRosterEntry` endpoint handles person creation + assignment atomically via `new_entry_name`. Do NOT introduce `useCreatePerson` here.

```tsx
// In ClusterDrawerPanel: wire onCreate to sentinel pattern
// onCreate fires when user types a name not in the list and clicks "Create [name]"
const handleCreate = (name: string) => {
  const trimmed = name.trim();
  if (!trimmed) return;
  setSelectedEntryId("create"); // Sentinel value -- triggers newEntryName branch in handleCommit
  setNewEntryName(trimmed);
};

// onSelect fires when user picks an existing person
const handleSelect = (id: string) => {
  setSelectedEntryId(id);
  setNewEntryName(""); // Clear create state on select
};

<Combobox
  options={rosterEntries.map((e) => ({
    value: e.id.toString(),
    label: e.name,
  }))}
  value={selectedEntryId}
  onSelect={handleSelect}
  onCreate={handleCreate}
  placeholder={__("Assign to...", "alt-context")}
/>;
// Remove the separate "Create new" sentinel option and <input> field.
// handleCommit already branches on isCreatingEntry (selectedEntryId === 'create').
```

### Drawer Focus Trap

Use the existing `@radix-ui/react-dialog` (already installed) in modal mode, or a manual focus-trap implementation. Do NOT add `@radix-ui/react-focus-trap` as a new dependency.

```tsx
// Option A: Wrap drawer in Radix Dialog (modal mode provides focus trap)
<DialogRoot
  open={!!cluster}
  onOpenChange={(open) => {
    if (!open) onClose();
  }}
>
  <DialogPortal>
    <DialogOverlay />
    <DialogContent className="acx-cluster-drawer">
      {/* drawer content */}
    </DialogContent>
  </DialogPortal>
</DialogRoot>

// Option B: Manual focus trap with useEffect + focusin listener
```

### Container Grouping (ARIA)

Add `role="group"` and `aria-label` to the grid container. Keep `role="button"` + `aria-pressed` on cards. Do NOT use `role="grid"`/`role="gridcell"` -- the interaction pattern is a selectable card collection, not a spreadsheet-like data grid.

```tsx
// In ClusterGrid, on the container div:
<div
  className="acx-cluster-grid"
  ref={gridRef}
  role="group"
  aria-label={__("Cluster cards", "alt-context")}
>
  {/* cards keep role="button" + aria-pressed={isSelected} */}
</div>
```

## Functions to Change

| File                                           | Line     | Change                                                                                                                                                                                             |
| ---------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `js/admin/pages/roster/ConfirmDialog.tsx`      | new      | Create accessible confirmation dialog using existing `dialog.tsx` wrapper with `onOpenChange`, extending workbench `ClusterConfirmDialog` pattern. Add `isPending` prop.                           |
| `js/admin/pages/RosterPage.tsx`                | L117-135 | Replace `window.confirm` in `handleBulkMerge` with `ConfirmDialog` state. Follow `useClusterConfirmDialog` pattern (promise-based `requestConfirm`).                                               |
| `js/admin/pages/RosterPage.tsx`                | L137-153 | Replace `window.confirm` in `handleBulkDismiss` with `ConfirmDialog` state.                                                                                                                        |
| `js/admin/pages/RosterPage.tsx`                | L186-194 | Add select-all `Checkbox` in cluster section header (always visible, outside `selection.count > 0` conditional). Wire to `selection.selectAll`/`selection.clear`. Support indeterminate state.     |
| `js/admin/pages/RosterPage.tsx`                | L73-76   | Pass `isMerging`/`isDismissing` state from `actions.bulkMergeMutation.isPending` to `BulkActionBar`.                                                                                               |
| `js/admin/pages/roster/BulkActionBar.tsx`      | L5-9     | Add `isMerging`, `isDismissing` props (NOT `onSelectAll`/`isAllSelected`).                                                                                                                         |
| `js/admin/pages/roster/BulkActionBar.tsx`      | L44-55   | Disable merge/dismiss buttons when corresponding mutation is pending; show spinner.                                                                                                                |
| `js/admin/hooks/useClusterSelection.ts`        | L6-45    | Add `selectAll(allIds)` and `isAllSelected(allIds)` methods.                                                                                                                                       |
| `js/admin/pages/roster/ClusterGrid.tsx`        | L186     | Add `role="group"` and `aria-label` to grid container div. Keep `role="button"` on cards.                                                                                                          |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx` | L228-249 | Remove separate "Create new" sentinel option and `<input>` field. Wire Combobox `onCreate` to set sentinel (`selectedEntryId='create'` + `newEntryName`). Wire `onSelect` to clear `newEntryName`. |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx` | L119-120 | Add focus trap around drawer when `cluster` is non-null (via Radix Dialog modal mode or manual).                                                                                                   |

## Related Files

| File                                                                    | Note                                                                                                                         |
| ----------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `js/components/ui/dialog.tsx`                                           | Existing Radix Dialog wrapper with BEM class names (`acx-dialog__overlay`, `acx-dialog__content`). Reused for ConfirmDialog. |
| `js/admin/pages/workbench/identity-clusters/ClusterConfirmDialog.tsx`   | Existing confirm dialog pattern to follow. Has `onOpenChange`, promise-based flow, cleanup.                                  |
| `js/admin/pages/workbench/identity-clusters/useClusterConfirmDialog.ts` | Existing confirm dialog state hook. Clone/adapt for roster bulk actions.                                                     |
| `js/components/ui/combobox.tsx`                                         | Existing Combobox component. Already supports `onCreate` callback.                                                           |
| `js/components/ui/checkbox.tsx`                                         | Used for per-card selection and header select-all. Supports indeterminate state.                                             |
| `js/admin/hooks/useRosterHooks.ts`                                      | `useCreatePerson` mutation hook. NOT used in drawer commit flow (atomic path via commit endpoint).                           |
| `js/admin/pages/roster/hooks/useClusterActions.ts`                      | Provides `bulkMergeMutation`, `bulkDismissMutation`. Not changed but `isPending` state consumed.                             |
| `js/admin/context/ToastContext.tsx`                                     | Toast notifications. Already wired to all mutations. Not changed.                                                            |
| `js/admin/pages/roster/hooks/useClusterDragDrop.ts`                     | Drag-drop logic. Not changed.                                                                                                |
| `js/admin/hooks/__tests__/useClusterSelection.test.ts`                  | Existing selection hook tests. Will be extended for `selectAll`/`isAllSelected`.                                             |
| `js/admin/pages/__tests__/RosterPage.test.tsx`                          | Existing page tests. Will be updated for dialog-based confirms and header select-all.                                        |
| `js/admin/pages/roster/__tests__/`                                      | Test directory for roster sub-components.                                                                                    |

---

# Consolidated Checklist

## Phase 4a: Accessible Confirmation Dialogs

- [x] **Implement**: create `ConfirmDialog` component in `js/admin/pages/roster/ConfirmDialog.tsx` using existing `dialog.tsx` wrapper (`DialogRoot`, `DialogOverlay`, `DialogContent`, etc.) with `onOpenChange` wiring, title, description, confirm/cancel buttons, and `isPending` state. Follow `ClusterConfirmDialog` pattern from workbench.
- [x] **Test (red)**: `ConfirmDialog` -- renders title, description, and buttons when open; confirm button calls `onConfirm`; cancel button calls `onCancel`; confirm button shows "Processing..." when `isPending`; ESC dismiss calls `onOpenChange(false)`.
- [x] **Test (green)**: dialog renders and callbacks fire correctly, including ESC/overlay dismiss.
- [x] **Implement**: replace `window.confirm` in `RosterPage.handleBulkMerge` with `ConfirmDialog` state. Adapt `useClusterConfirmDialog` pattern (promise-based `requestConfirm`, `handleOpenChange`, unmount cleanup).
- [x] **Implement**: replace `window.confirm` in `RosterPage.handleBulkDismiss` with `ConfirmDialog` state.
- [x] **Test (red)**: `RosterPage` -- clicking merge opens dialog; confirming triggers `bulkMergeMutation`; canceling closes dialog; ESC closes dialog.
- [x] **Test (green)**: merge and dismiss flows work through dialog.

## Phase 4b: Select All and Bulk Bar Polish

- [x] **Test (red)**: `useClusterSelection` -- `selectAll` sets all IDs; `isAllSelected` returns true when all selected.
- [x] **Implement**: add `selectAll(allIds)` and `isAllSelected(allIds)` methods to `useClusterSelection`.
- [x] **Test (green)**: `selectAll` and `isAllSelected` work correctly.
- [x] **Implement**: add "Select all" `Checkbox` in cluster section header in `RosterPage` (always visible, outside `selection.count > 0` conditional), wired to `selection.selectAll(clusterIds)` / `selection.clear()`. Support indeterminate state.
- [x] **Implement**: add `isMerging`/`isDismissing` props to `BulkActionBar`; disable buttons and show spinner when pending.
- [x] **Test (red)**: `BulkActionBar` -- merge button disabled and shows spinner when `isMerging` is true.
- [x] **Test (green)**: loading states render correctly.
- [x] **Implement**: pass `bulkMergeMutation.isPending` and `bulkDismissMutation.isPending` from `RosterPage` to `BulkActionBar`.

## Phase 4c: Inline Person Creation in Combobox

- [x] **Test (red)**: `ClusterDrawerPanel` -- typing an unknown name in combobox shows "Create [name]" button; clicking it sets sentinel state (`selectedEntryId='create'`, `newEntryName`); committing sends `newEntryName` via atomic commit endpoint.
- [x] **Test (red)**: `ClusterDrawerPanel` -- selecting an existing person after `onCreate` clears `newEntryName` and sets `selectedEntryId` to the person ID.
- [x] **Implement**: wire Combobox `onCreate` in `ClusterDrawerPanel` to set sentinel (`selectedEntryId='create'` + `newEntryName`). Wire `onSelect` to clear `newEntryName`.
- [x] **Implement**: remove separate "Create new" sentinel option (`{ value: 'create' }`) and `<input>` field from `ClusterDrawerPanel`.
- [x] **Test (green)**: inline person creation from combobox preserves atomic commit path; select-after-create and create-after-select transitions work correctly.

## Phase 4d: Accessibility Hardening

- [x] **Implement**: add `role="group"` and `aria-label` to `ClusterGrid` container div. Keep `role="button"` + `aria-pressed` on cards.
- [x] **Implement**: add focus trap to `ClusterDrawerPanel` when open (Radix Dialog modal mode or manual implementation). Auto-focus close button on open.
- [x] **Test (red)**: `ClusterGrid` -- grid container has `role="group"` and `aria-label`; cards retain `role="button"`.
- [x] **Test (green)**: ARIA attributes present on rendered elements.
- [x] **Test (red)**: `ClusterDrawerPanel` -- focus moves to drawer on open; Tab does not leave drawer.
- [x] **Test (green)**: focus trap works as expected.
- [x] Review all new copy uses `__()` / `_x()` with `'alt-context'` text domain.

## Success Criteria

- [x] Bulk merge/dismiss uses accessible Radix Dialog (with `onOpenChange`) instead of `window.confirm`.
- [x] Confirmation dialog shows loading state during mutation.
- [x] "Select all" checkbox in always-visible cluster header selects/deselects all visible clusters. Supports indeterminate state.
- [x] Bulk action bar buttons are disabled with spinner during pending mutations.
- [x] Inline person creation from combobox: typing unknown name -> "Create [name]" button -> sets sentinel -> atomic commit creates person + assigns. No separate `useCreatePerson` call.
- [x] Cluster grid container has `role="group"` with `aria-label`. Cards retain `role="button"` + `aria-pressed`.
- [x] Cluster drawer traps focus when open.
- [x] All new components and behaviors have Vitest test coverage.
- [x] Existing test suite continues passing.
