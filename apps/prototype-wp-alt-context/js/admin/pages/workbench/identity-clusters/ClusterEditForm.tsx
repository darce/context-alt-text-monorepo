/**
 * Cluster label edit form with direct text input and floating suggestions.
 */

import React, { useEffect, useRef } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';
import { NAMING_GROUP_SUGGESTED, parseNamingOptionValue, unwrapClusterOptionId } from './buildNamingOptions';

/** Similarity at-or-above this threshold uses the high match-score band. */
const MATCH_BAND_HIGH_THRESHOLD = 0.7;

const sourceBadgeLabel = (option: ComboboxOption): string | null => {
  const source =
    option.source === 'person' || option.source === 'cluster'
      ? option.source
      : parseNamingOptionValue(String(option.value))?.source;
  if (source === 'person') {
    return __('Person', 'alt-context');
  }
  // Include source on Suggested and All Labels cluster rows (A11Y-04 / FIX-7).
  if (source === 'cluster') {
    return __('Cluster', 'alt-context');
  }
  return null;
};

/** Max overlay rows; Suggested budget first so persons/All Labels are not starved (FIX-6). */
export const OVERLAY_OPTIONS_LIMIT = 5;
export const OVERLAY_SUGGESTED_BUDGET = 3;

/**
 * Budget overlay rows: up to OVERLAY_SUGGESTED_BUDGET Suggested, remainder from union, total ≤ limit.
 */
export const budgetOverlayOptions = (
  options: readonly ComboboxOption[],
  limit = OVERLAY_OPTIONS_LIMIT,
  suggestedBudget = OVERLAY_SUGGESTED_BUDGET,
): ComboboxOption[] => {
  const suggested: ComboboxOption[] = [];
  const union: ComboboxOption[] = [];
  for (const option of options) {
    if (option.group === NAMING_GROUP_SUGGESTED) {
      suggested.push(option);
    } else {
      union.push(option);
    }
  }
  const suggestedSlice = suggested.slice(0, suggestedBudget);
  const remainder = Math.max(0, limit - suggestedSlice.length);
  return [...suggestedSlice, ...union.slice(0, remainder)];
};

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
  /** Filtered at-rest page size after excluding the editable cluster. */
  atRestShown?: number;
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
  atRestShown = 0,
  isAtRestMode = false,
}: ClusterEditFormProps): React.JSX.Element => {
  void isLoading;
  const inputRef = useRef<HTMLInputElement>(null);

  // Autofocus on mount
  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  // Handle keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      onSave();
    } else if (e.key === 'Escape') {
      onCancel();
    }
  };

  // Per-group budget so Suggested rows cannot starve persons / All Labels (FIX-6).
  const displayedOptions = React.useMemo(() => budgetOverlayOptions(options), [options]);

  const saveButtonLabel = saveLabel ?? (isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context'));
  const showAtRestTruncationHint = atRestTruncated && isAtRestMode;

  // Live-region status (A11Y-21): announce save progress/success at the field (PERC-05 fovea).
  // saveLabel carries "Saving…" / "Saved!" from the parent save-status pipeline.
  const resultCountAnnouncement = React.useMemo(() => {
    if (isPending) {
      return saveButtonLabel;
    }
    return sprintf(
      /* translators: %d: number of naming suggestions shown */
      __('%d naming options', 'alt-context'),
      displayedOptions.length,
    );
  }, [displayedOptions.length, isPending, saveButtonLabel]);

  const handleSuggestionSelect = React.useCallback(
    (label: string) => () => {
      onLabelChange(label);
    },
    [onLabelChange],
  );

  const handleConfirmSuggestionClick = React.useCallback(
    (option: ComboboxOption) => (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      const parsed = parseNamingOptionValue(String(option.value));
      // Person selection uses the dedicated person path — never merge/assign (PR-16 / FIX-1).
      if (parsed?.source === 'person' || option.source === 'person') {
        if (onPersonSelect) {
          onPersonSelect(option.label);
        } else {
          onSave(option.label);
        }
        return;
      }
      // Namespaced cluster: values only (no bare-id fallback — FIX-10).
      const clusterId = unwrapClusterOptionId(String(option.value));
      if (onConfirmSuggestion && clusterId) {
        // BR-16 / L1R-01: thread suggestion_id so confirm resolves the pending row by id.
        const suggestionId =
          typeof option.suggestion_id === 'string' && option.suggestion_id.length > 0
            ? option.suggestion_id
            : undefined;
        onConfirmSuggestion(clusterId, option.label, suggestionId);
      } else {
        onSave(option.label);
      }
    },
    [onConfirmSuggestion, onPersonSelect, onSave],
  );

  const handleRejectSuggestionClick = React.useCallback(
    (suggestionId: string) => (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      onRejectSuggestion?.(suggestionId);
    },
    [onRejectSuggestion],
  );

  return (
    <div className="acx-identity-cluster__edit">
      <div className="acx-identity-cluster__input-wrapper">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={displayedOptions.length > 0}
          aria-haspopup="listbox"
          className="acx-identity-cluster__label-input"
          value={labelInput}
          onChange={(e) => onLabelChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={__('Enter a name…', 'alt-context')}
          disabled={isPending}
          aria-label={__('Cluster label', 'alt-context')}
        />

        {displayedOptions.length > 0 && !isPending && (
          <div className="acx-identity-cluster__suggestions-overlay">
            <div className="acx-identity-cluster__suggestions-header">{__('Suggested', 'alt-context')}</div>
            {displayedOptions.map((option) => (
              <div key={option.value} className="acx-identity-cluster__suggestion-row">
                <button
                  type="button"
                  className="acx-identity-cluster__suggestion-item"
                  onClick={handleSuggestionSelect(option.label)}
                  title={sprintf(__('Use label "%s"', 'alt-context'), option.label)}
                  aria-label={
                    sourceBadgeLabel(option)
                      ? sprintf(
                          /* translators: 1: person/cluster name, 2: source (Person or Cluster) */
                          __('%1$s (%2$s)', 'alt-context'),
                          option.label,
                          sourceBadgeLabel(option) ?? '',
                        )
                      : option.label
                  }
                >
                  <span className="acx-identity-cluster__suggestion-label">{option.label}</span>
                  {sourceBadgeLabel(option) && (
                    <span className="acx-badge acx-badge--source" data-source={option.source ?? ''}>
                      {sourceBadgeLabel(option)}
                    </span>
                  )}
                  {option.similarity !== undefined && (
                    <span
                      className={`acx-identity-cluster__match-score ${
                        (option.similarity as number) >= MATCH_BAND_HIGH_THRESHOLD
                          ? 'acx-identity-cluster__match-score--high'
                          : 'acx-identity-cluster__match-score--medium'
                      }`}
                    >
                      {Math.round((option.similarity as number) * 100)}%{' '}
                      <span className="acx-identity-cluster__match-score-band">
                        {(option.similarity as number) >= MATCH_BAND_HIGH_THRESHOLD
                          ? __('high', 'alt-context')
                          : __('medium', 'alt-context')}
                      </span>
                    </span>
                  )}
                </button>
                <div className="acx-identity-cluster__suggestion-actions">
                  <button
                    type="button"
                    className="acx-identity-cluster__suggestion-confirm"
                    onClick={handleConfirmSuggestionClick(option)}
                    title={__('Confirm match', 'alt-context')}
                    aria-label={__('Confirm match', 'alt-context')}
                  >
                    ✓
                  </button>
                  {!!option.suggestion_id && !!onRejectSuggestion && (
                    <button
                      type="button"
                      className="acx-identity-cluster__suggestion-reject"
                      onClick={handleRejectSuggestionClick(option.suggestion_id as string)}
                      title={__('Reject suggestion', 'alt-context')}
                      aria-label={__('Reject suggestion', 'alt-context')}
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
        {showAtRestTruncationHint && (
          <p className="acx-identity-cluster__at-rest-hint">
            {sprintf(
              /* translators: 1: number of labels currently shown, 2: total labelled clusters */
              __('Showing %1$d of %2$d labels — type to search for more', 'alt-context'),
              atRestShown,
              atRestTotal,
            )}
          </p>
        )}
      </div>

      <p className="acx-identity-cluster__result-count" role="status" aria-live="polite">
        {resultCountAnnouncement}
      </p>

      <div className="acx-identity-cluster__edit-actions">
        <button
          type="button"
          className="acx-identity-cluster__save"
          onClick={() => onSave()}
          disabled={isPending || !labelInput.trim()}
        >
          {saveButtonLabel}
        </button>
        <button type="button" className="acx-identity-cluster__cancel" onClick={onCancel}>
          {__('Cancel', 'alt-context')}
        </button>
      </div>
    </div>
  );
};
