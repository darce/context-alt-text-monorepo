/**
 * Cluster label edit form with direct text input and floating suggestions.
 */

import React, { useEffect, useRef } from 'react';
import { __, sprintf } from '@wordpress/i18n';

import type { ComboboxOption } from '../../../../components/ui/combobox';

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
  /** Called when a suggestion is confirmed */
  onConfirmSuggestion?: (clusterId: string, label: string) => void;
  /** Called when cancel button is clicked */
  onCancel: () => void;
  /** Called when a suggested match is rejected */
  onRejectSuggestion?: (suggestionId: string) => void;
}

/**
 * Edit form for cluster label with autofocus input and quick suggestions.
 */
export const ClusterEditForm = ({
  labelInput,
  onLabelChange,
  options,
  isPending,
  saveLabel,
  onSave,
  onConfirmSuggestion,
  onCancel,
  onRejectSuggestion,
}: ClusterEditFormProps): React.JSX.Element => {
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

  // Display up to 5 options from the hook (which already handles search/filtering)
  const displayedOptions = options.slice(0, 5);

  const saveButtonLabel = saveLabel ?? (isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context'));

  const handleSuggestionSelect = React.useCallback(
    (label: string) => () => {
      onLabelChange(label);
    },
    [onLabelChange],
  );

  const handleConfirmSuggestionClick = React.useCallback(
    (option: ComboboxOption) => (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      if (onConfirmSuggestion) {
        onConfirmSuggestion(option.value, option.label);
      } else {
        onSave(option.label);
      }
    },
    [onConfirmSuggestion, onSave],
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
                >
                  <span className="acx-identity-cluster__suggestion-label">{option.label}</span>
                  {option.similarity !== undefined && (
                    <span
                      className={`acx-identity-cluster__match-score ${
                        (option.similarity as number) >= 0.7
                          ? 'acx-identity-cluster__match-score--high'
                          : 'acx-identity-cluster__match-score--medium'
                      }`}
                    >
                      {Math.round((option.similarity as number) * 100)}%{' '}
                      <span className="acx-identity-cluster__match-score-band">
                        {(option.similarity as number) >= 0.7
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
      </div>

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
