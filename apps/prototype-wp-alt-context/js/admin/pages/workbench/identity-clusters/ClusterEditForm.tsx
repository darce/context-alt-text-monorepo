/**
 * Cluster label edit form with direct text input and floating suggestions.
 */

import React, { useEffect, useRef } from 'react';
import { __ } from '@wordpress/i18n';

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
  /** Called when save button is clicked */
  onSave: () => void;
  /** Called when cancel button is clicked */
  onCancel: () => void;
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
  onSave,
  onCancel,
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

  // Filter options based on input for the overlay
  const filteredOptions = options.filter(opt => 
    opt.label.toLowerCase().includes(labelInput.toLowerCase()) && 
    opt.label.toLowerCase() !== labelInput.toLowerCase()
  ).slice(0, 5);

  return (
    <div className="acx-identity-cluster__edit">
      <div className="acx-identity-cluster__input-wrapper">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={filteredOptions.length > 0}
          aria-haspopup="listbox"
          className="acx-identity-cluster__label-input"
          value={labelInput}
          onChange={(e) => onLabelChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={__('Enter a name…', 'alt-context')}
          disabled={isPending}
          aria-label={__('Cluster label', 'alt-context')}
        />
        
        {filteredOptions.length > 0 && !isPending && (
          <div className="acx-identity-cluster__suggestions-overlay">
            <div className="acx-identity-cluster__suggestions-header">
              {__('Suggested', 'alt-context')}
            </div>
            {filteredOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className="acx-identity-cluster__suggestion-item"
                onClick={() => {
                  onLabelChange(option.label);
                  // Trigger save matching the user's intent to Curate
                  setTimeout(onSave, 0);
                }}
              >
                <span className="acx-identity-cluster__suggestion-label">{option.label}</span>
                {option.similarity !== undefined && (
                  <span className={`acx-identity-cluster__match-score ${
                    (option.similarity as number) >= 0.7 ? 'acx-identity-cluster__match-score--high' : 'acx-identity-cluster__match-score--medium'
                  }`}>
                    {Math.round((option.similarity as number) * 100)}%
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="acx-identity-cluster__edit-actions">
        <button 
          type="button" 
          className="acx-identity-cluster__save" 
          onClick={onSave} 
          disabled={isPending || !labelInput.trim()}
        >
          {isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context')}
        </button>
        <button 
          type="button" 
          className="acx-identity-cluster__cancel" 
          onClick={onCancel}
          disabled={isPending}
        >
          {__('Cancel', 'alt-context')}
        </button>
      </div>
    </div>
  );
};
