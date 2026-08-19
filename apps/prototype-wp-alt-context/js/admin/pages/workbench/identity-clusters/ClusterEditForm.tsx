/**
 * Cluster label edit form — Library pane adapter over the shared NameFaceControl
 * (UXW2-3). Save wiring stays identity-anchored in the caller; this adapter maps
 * the control's single-gesture resolution back onto the legacy callbacks.
 */

import React from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { parseNamingOptionValue, unwrapClusterOptionId } from './buildNamingOptions';
import {
  budgetOverlayOptions as budgetRows,
  NameFaceControl,
  normalizeNameFaceLabel,
  type NameFaceResolution,
} from './NameFaceControl';

export {
  budgetOverlayOptions,
  OVERLAY_OPTIONS_LIMIT,
  OVERLAY_SUGGESTED_BUDGET,
} from './NameFaceControl';

interface ClusterEditFormProps {
  /** Current label input value */
  labelInput: string;
  /** Called when label input changes */
  onLabelChange: (value: string) => void;
  /** Combobox options (suggestions + existing labels) */
  options: ComboboxOption[];
  /** Whether suggestions are loading */
  isLoading: boolean;
  /** Whether a mutation is in progress */
  isPending: boolean;
  /** Override label for the save button */
  saveLabel?: string;
  /** Called when save button is clicked */
  onSave: (labelOverride?: string) => void;
  /**
   * Explicit person-source confirm path — rename/create only; never merge (PR-16 / FIX-1).
   * When provided, person-row confirm uses this instead of onSave.
   */
  onPersonSelect?: (label: string) => void;
  /** Called when a suggestion is confirmed (optional suggestionId resolves the pending row by id) */
  onConfirmSuggestion?: (clusterId: string, label: string, suggestionId?: string) => void;
  /** Called when cancel button is clicked */
  onCancel: () => void;
  /** Called when a suggested match is rejected */
  onRejectSuggestion?: (suggestionId: string) => void;
  /** Envelope total from the at-rest labelled-cluster page. */
  atRestTotal?: number;
  /** Envelope truncated flag from the at-rest labelled-cluster page. */
  atRestTruncated?: boolean;
  /** True while the loader is still in at-rest (debounced) mode. */
  isAtRestMode?: boolean;
}

/**
 * Edit form for cluster label with autofocus input and quick suggestions.
 */
export const ClusterEditForm = ({
  labelInput,
  onLabelChange,
  options,
  isLoading,
  isPending,
  saveLabel,
  onSave,
  onPersonSelect,
  onConfirmSuggestion,
  onCancel,
  onRejectSuggestion,
  atRestTotal = 0,
  atRestTruncated = false,
  isAtRestMode = false,
}: ClusterEditFormProps): React.JSX.Element => {
  const prefillRef = React.useRef(labelInput);
  const saveButtonLabel = saveLabel ?? (isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context'));
  const showAtRestTruncationHint = atRestTruncated && isAtRestMode;
  const atRestHintId = `acx-identity-cluster-at-rest-hint-${React.useId()}`;

  const displayedCount = React.useMemo(() => budgetRows(options).length, [options]);

  // Enter / Save: exact person match routes to the person path (rename/create,
  // never merge); anything else saves the typed label (PR-16 / FIX-1).
  const handleCommit = React.useCallback(
    (resolution: NameFaceResolution) => {
      if (resolution.kind === 'ambiguous') {
        return;
      }
      if (resolution.kind === 'roster') {
        const folded = normalizeNameFaceLabel(resolution.name);
        const sameFoldCount = options.filter(
          (option) =>
            (option.source === 'person' ||
              parseNamingOptionValue(String(option.value))?.source === 'person') &&
            normalizeNameFaceLabel(option.label) === folded,
        ).length;
        // Prefill no-op stays for a single exact match (R1-13). Same-fold
        // row confirm must still bind the chosen roster id (R3-12).
        if (sameFoldCount <= 1 && folded === normalizeNameFaceLabel(prefillRef.current)) {
          return;
        }
        if (onPersonSelect) {
          onPersonSelect(resolution.name);
        } else {
          onSave(resolution.name);
        }
        return;
      }
      if (normalizeNameFaceLabel(resolution.name) === normalizeNameFaceLabel(prefillRef.current)) {
        return;
      }
      onSave(resolution.name);
    },
    [onPersonSelect, onSave, options],
  );

  // Row ✓: cluster/suggestion rows unwrap the namespaced id and thread
  // suggestion_id (BR-16 / L1R-01). Person rows bind via onCommit.
  const handleOptionConfirm = React.useCallback(
    (option: ComboboxOption) => {
      // Namespaced cluster: values only (no bare-id fallback — FIX-10).
      const clusterId = unwrapClusterOptionId(String(option.value));
      if (onConfirmSuggestion && clusterId) {
        const suggestionId =
          typeof option.suggestion_id === 'string' && option.suggestion_id.length > 0
            ? option.suggestion_id
            : undefined;
        onConfirmSuggestion(clusterId, option.label, suggestionId);
      } else {
        onSave(option.label);
      }
    },
    [onConfirmSuggestion, onSave],
  );

  return (
    <NameFaceControl
      options={options}
      value={labelInput}
      onValueChange={onLabelChange}
      onCommit={handleCommit}
      onOptionConfirm={handleOptionConfirm}
      onRejectSuggestion={onRejectSuggestion}
      onCancel={onCancel}
      isPending={isPending}
      isLoading={isLoading}
      searchPlaceholder={__('Enter a name…', 'alt-context')}
      commitLabel={saveButtonLabel}
      pendingLabel={saveButtonLabel}
      placeholder={__('Enter a name…', 'alt-context')}
      ariaLabel={__('Person name', 'alt-context')}
      className="acx-identity-cluster__edit"
      classPrefix="acx-identity-cluster"
      hintId={showAtRestTruncationHint ? atRestHintId : undefined}
      hint={
        showAtRestTruncationHint ? (
          <p
            id={atRestHintId}
            className="acx-identity-cluster__at-rest-hint"
          >
            {sprintf(
              /* translators: 1: number of labels currently shown, 2: total labelled clusters */
              __('Showing %1$d of %2$d labels — type to search for more', 'alt-context'),
              displayedCount,
              atRestTotal,
            )}
          </p>
        ) : null
      }
    />
  );
};
