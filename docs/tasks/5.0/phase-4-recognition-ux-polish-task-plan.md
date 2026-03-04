# Phase 4: Recognition UX Polish

## Problem Statement

Cluster review is the most frequent operator workflow, but it remains ergonomically incomplete. While Phase 2 delivered multi-select (`useClusterSelection`), bulk merge/dismiss (`BulkActionBar` + `useClusterActions`), keyboard navigation in `ClusterGrid`, and roster-aware labeling via `Combobox` in `ClusterDrawerPanel`, several refinements are needed to make the experience production-ready: confirmation dialogs for bulk actions use `window.confirm` instead of accessible modal dialogs, the bulk action bar has no loading/disabled state during mutations, there is no "select all" capability, and the cluster labeling combobox does not create a person inline (it still uses a separate text input for "Create new"). This phase polishes these surfaces into a cohesive, accessible cluster review workflow.

## Workflow Principles

- **TDD**: write a failing test before each change. Red -> Green -> Refactor.
- **Curation-first**: roster assignments override backend suggestions. Person creation from labeling flow is a curation operation.
- **Sovereign model**: all data reads come from local projection. No live backend dependency for rendering.
- **Accessibility**: all interactive surfaces must be keyboard-operable. Confirmation dialogs must trap focus. ARIA grid pattern for cluster grid.
- **Small vertical slices**: each deliverable is independently shippable and testable.

## Terminology

- **Bulk action**: an operation applied to multiple selected clusters at once (merge, dismiss).
- **Confirmation dialog**: accessible modal (Radix AlertDialog) shown before destructive bulk operations, replacing `window.confirm`.
- **Select all**: toggle to select/deselect all visible clusters in the grid.
- **Roster-aware labeling**: cluster labeling combobox searches existing persons. "Create new" option inline-creates a person.
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
- All hooks and components have Vitest test coverage.

### What's Missing / Needs Polish

- **`window.confirm` for bulk operations**: `handleBulkMerge` and `handleBulkDismiss` in `RosterPage.tsx` use `window.confirm()`. This is not accessible (no focus trap, not styleable, not testable in JSDOM). Should use Radix AlertDialog.
- **No loading state on bulk bar**: when `bulkMergeMutation` or `bulkDismissMutation` is pending, the `BulkActionBar` buttons are not disabled and show no spinner.
- **No "select all" toggle**: operators processing large batches must Shift+click from first to last. A "Select all" checkbox in the grid header or bulk bar would be faster.
- **Inline person creation in combobox incomplete**: the `ClusterDrawerPanel` uses a separate `<input>` for new person name when "Create new" is selected. The create flow should be integrated into the combobox via the `onCreate` callback pattern (type a name not in the list -> "Create [name]" option appears -> selecting it creates the person and assigns).
- **No batch progress for bulk operations**: merging 10 clusters fires 9 sequential API calls with no per-step progress. A progress indicator or "merging N of M" text would improve confidence.
- **Drawer focus management**: opening the drawer does not trap focus or auto-focus the close button. Pressing Tab can leave the drawer.
- **Grid ARIA pattern incomplete**: cards use `role="button"` but the grid container has no `role="grid"` or `role="listbox"`. For proper ARIA grid patterns, each card should be a gridcell and the container a grid with `aria-label`.
- **No empty selection feedback**: when selection count drops to 0, `BulkActionBar` disappears. A subtle animation or transition would be smoother.

## Proposed Solution

Four vertical slices:

1. **Accessible confirmation dialogs**: replace `window.confirm` with Radix AlertDialog for bulk merge and dismiss. Wire loading/disabled state to mutation pending.
2. **Select all and bulk bar polish**: add "Select all" toggle, disable buttons during pending mutations, show progress text for sequential merge.
3. **Inline person creation in combobox**: integrate "Create new" into combobox flow using `useCreatePerson` mutation. On create success, auto-assign.
4. **Accessibility hardening**: drawer focus trap, ARIA grid pattern, transition animations for bulk bar.

## Patterns to Follow

### Accessible Confirmation Dialog (Radix AlertDialog)

```tsx
// js/admin/pages/roster/ConfirmDialog.tsx
import * as AlertDialog from '@radix-ui/react-alert-dialog';

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  description: string;
  confirmLabel: string;
  isPending?: boolean;
}

export const ConfirmDialog = ({
  open,
  onConfirm,
  onCancel,
  title,
  description,
  confirmLabel,
  isPending,
}: ConfirmDialogProps): React.JSX.Element => (
  <AlertDialog.Root open={open}>
    <AlertDialog.Portal>
      <AlertDialog.Overlay className="acx-dialog-overlay" />
      <AlertDialog.Content className="acx-dialog-content">
        <AlertDialog.Title>{title}</AlertDialog.Title>
        <AlertDialog.Description>{description}</AlertDialog.Description>
        <div className="acx-dialog-actions">
          <AlertDialog.Cancel asChild>
            <button type="button" className="acx-button acx-button--secondary" onClick={onCancel} disabled={isPending}>
              {__('Cancel', 'alt-context')}
            </button>
          </AlertDialog.Cancel>
          <AlertDialog.Action asChild>
            <button type="button" className="acx-button acx-button--danger" onClick={onConfirm} disabled={isPending}>
              {isPending ? __('Processing...', 'alt-context') : confirmLabel}
            </button>
          </AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Portal>
  </AlertDialog.Root>
);
```

### Select All in useClusterSelection

```typescript
// Extend useClusterSelection hook
const selectAll = useCallback((allIds: string[]) => {
  setSelectedIds(new Set(allIds));
}, []);

const isAllSelected = useCallback(
  (allIds: string[]) => allIds.length > 0 && allIds.every((id) => selectedIds.has(id)),
  [selectedIds],
);
```

### BulkActionBar with Loading State

```tsx
interface BulkActionBarProps {
  count: number;
  onMerge: () => void;
  onDismiss: () => void;
  onClear: () => void;
  isMerging?: boolean;
  isDismissing?: boolean;
  onSelectAll?: () => void;
  isAllSelected?: boolean;
}
```

### Inline Person Creation via Combobox onCreate

```tsx
// In ClusterDrawerPanel, wire Combobox onCreate to useCreatePerson
const createPerson = useCreatePerson();

const handleCreateAndAssign = (name: string) => {
  createPerson.mutate(
    { name },
    {
      onSuccess: (newPerson) => {
        // Auto-select the new person for commit
        setSelectedEntryId(newPerson.id.toString());
      },
    },
  );
};

<Combobox
  options={personOptions}
  value={selectedEntryId}
  onSelect={setSelectedEntryId}
  onCreate={handleCreateAndAssign}
  placeholder={__('Assign to...', 'alt-context')}
/>
```

### Drawer Focus Trap

```tsx
// Use Radix Dialog or FocusTrap for drawer
import { FocusTrap } from '@radix-ui/react-focus-trap'; // or manual implementation

// Wrap drawer aside in focus trap when open
<FocusTrap asChild>
  <aside className="acx-cluster-drawer" aria-live="polite">
    {/* drawer content */}
  </aside>
</FocusTrap>
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `js/admin/pages/roster/ConfirmDialog.tsx` | new | Create accessible confirmation dialog using Radix AlertDialog |
| `js/admin/pages/RosterPage.tsx` | L117-135 | Replace `window.confirm` in `handleBulkMerge` with `ConfirmDialog` state management |
| `js/admin/pages/RosterPage.tsx` | L137-153 | Replace `window.confirm` in `handleBulkDismiss` with `ConfirmDialog` state management |
| `js/admin/pages/roster/BulkActionBar.tsx` | L5-9 | Add `isMerging`, `isDismissing`, `onSelectAll`, `isAllSelected` props |
| `js/admin/pages/roster/BulkActionBar.tsx` | L44-55 | Disable merge/dismiss buttons when corresponding mutation is pending; show spinner |
| `js/admin/hooks/useClusterSelection.ts` | L6-45 | Add `selectAll(allIds)` and `isAllSelected(allIds)` methods |
| `js/admin/pages/roster/ClusterGrid.tsx` | L186-189 | Add `role="grid"` and `aria-label` to grid container; add `role="gridcell"` to cards |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx` | L99-105 | Remove separate "Create new" input; wire Combobox `onCreate` to `useCreatePerson` for inline person creation |
| `js/admin/pages/roster/ClusterDrawerPanel.tsx` | L119-120 | Add focus trap around drawer when `cluster` is non-null |
| `js/admin/pages/RosterPage.tsx` | L73-76 | Pass `isMerging`/`isDismissing` state from `actions.bulkMergeMutation.isPending` to `BulkActionBar` |

## Related Files

| File | Note |
| --- | --- |
| `js/components/ui/dialog.tsx` | Existing Radix Dialog wrapper. May be reused/extended for AlertDialog. |
| `js/components/ui/combobox.tsx` | Existing Combobox component. Must support `onCreate` callback for inline person creation. |
| `js/components/ui/checkbox.tsx` | Used for per-card selection. Not changed. |
| `js/admin/hooks/useRosterHooks.ts` | `useCreatePerson` mutation hook. Consumed by drawer for inline create. Not changed. |
| `js/admin/pages/roster/hooks/useClusterActions.ts` | Provides `bulkMergeMutation`, `bulkDismissMutation`. Not changed but `isPending` state consumed. |
| `js/admin/context/ToastContext.tsx` | Toast notifications. Already wired to all mutations. Not changed. |
| `js/admin/pages/roster/hooks/useClusterDragDrop.ts` | Drag-drop logic. Not changed. |
| `js/admin/hooks/__tests__/useClusterSelection.test.ts` | Existing selection hook tests. Will be extended. |
| `js/admin/pages/__tests__/RosterPage.test.tsx` | Existing page tests. Will be updated for dialog-based confirms. |
| `js/admin/pages/roster/__tests__/` | Test directory for roster sub-components. |

---

# Consolidated Checklist

## Phase 4a: Accessible Confirmation Dialogs

- [ ] **Implement**: create `ConfirmDialog` component in `js/admin/pages/roster/ConfirmDialog.tsx` using Radix AlertDialog with focus trap, title, description, confirm/cancel buttons, and pending state.
- [ ] **Test (red)**: `ConfirmDialog` -- renders title, description, and buttons when open; confirm button calls `onConfirm`; cancel button calls `onCancel`; confirm button shows "Processing..." when `isPending`.
- [ ] **Test (green)**: dialog renders and callbacks fire correctly.
- [ ] **Implement**: replace `window.confirm` in `RosterPage.handleBulkMerge` with `ConfirmDialog` state. Add `confirmAction` state (`null | 'merge' | 'dismiss'`) to control dialog open/close.
- [ ] **Implement**: replace `window.confirm` in `RosterPage.handleBulkDismiss` with `ConfirmDialog` state.
- [ ] **Test (red)**: `RosterPage` -- clicking merge opens dialog; confirming triggers `bulkMergeMutation`; canceling closes dialog.
- [ ] **Test (green)**: merge and dismiss flows work through dialog.

## Phase 4b: Select All and Bulk Bar Polish

- [ ] **Test (red)**: `useClusterSelection` -- `selectAll` sets all IDs; `isAllSelected` returns true when all selected.
- [ ] **Implement**: add `selectAll(allIds)` and `isAllSelected(allIds)` methods to `useClusterSelection`.
- [ ] **Test (green)**: `selectAll` and `isAllSelected` work correctly.
- [ ] **Implement**: add "Select all" checkbox to `BulkActionBar` or grid header, wired to `selection.selectAll(clusterIds)`.
- [ ] **Implement**: add `isMerging`/`isDismissing` props to `BulkActionBar`; disable buttons and show spinner when pending.
- [ ] **Test (red)**: `BulkActionBar` -- merge button disabled and shows spinner when `isMerging` is true.
- [ ] **Test (green)**: loading states render correctly.
- [ ] **Implement**: pass `bulkMergeMutation.isPending` and `bulkDismissMutation.isPending` from `RosterPage` to `BulkActionBar`.

## Phase 4c: Inline Person Creation in Combobox

- [ ] **Test (red)**: `ClusterDrawerPanel` -- typing an unknown name in combobox shows "Create [name]" option; selecting it creates a person via `useCreatePerson` and auto-selects.
- [ ] **Implement**: verify `Combobox` component supports `onCreate` callback. If not, add it.
- [ ] **Implement**: wire `useCreatePerson` into `ClusterDrawerPanel`; on create success, auto-assign the newly created person.
- [ ] **Implement**: remove separate "Create new" `<input>` field; use combobox `onCreate` flow instead.
- [ ] **Test (green)**: inline person creation from combobox works end-to-end; new person appears in combobox options after creation.

## Phase 4d: Accessibility Hardening

- [ ] **Implement**: add `role="grid"` and `aria-label` to `ClusterGrid` container div.
- [ ] **Implement**: change cluster card `role="button"` to `role="gridcell"` for proper ARIA grid pattern.
- [ ] **Implement**: add focus trap to `ClusterDrawerPanel` when open (Radix FocusTrap or manual implementation). Auto-focus close button on open.
- [ ] **Test (red)**: `ClusterGrid` -- grid container has `role="grid"`; cards have `role="gridcell"`.
- [ ] **Test (green)**: ARIA attributes present on rendered elements.
- [ ] **Test (red)**: `ClusterDrawerPanel` -- focus moves to drawer on open; Tab does not leave drawer.
- [ ] **Test (green)**: focus trap works as expected.
- [ ] Review all new copy uses `__()` / `_x()` with `'alt-context'` text domain.

## Success Criteria

- [ ] Bulk merge/dismiss uses accessible Radix AlertDialog instead of `window.confirm`.
- [ ] Confirmation dialog shows loading state during mutation.
- [ ] "Select all" toggle selects/deselects all visible clusters.
- [ ] Bulk action bar buttons are disabled with spinner during pending mutations.
- [ ] Inline person creation from combobox: typing unknown name -> "Create [name]" option -> creates person -> auto-assigns.
- [ ] Cluster grid has `role="grid"` with proper ARIA grid semantics.
- [ ] Cluster drawer traps focus when open.
- [ ] All new components and behaviors have Vitest test coverage.
- [ ] Existing test suite continues passing.
