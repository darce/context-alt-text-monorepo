/**
 * Cluster label edit form with Combobox for suggestions.
 */

import React from 'react';
import { __ } from '@wordpress/i18n';

import { Combobox, type ComboboxOption } from '../../../../components/ui/combobox';

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
 * Renders a suggestion option with similarity score and member count.
 */
const renderSuggestionOption = (option: ComboboxOption): React.JSX.Element => {
  const similarity = option.similarity as number | undefined;
  const count = option.identityCount as number | undefined;

  return (
    <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
      <span>{option.label}</span>
      {(similarity !== undefined || count !== undefined) && (
        <div className="acx-identity-cluster__suggestion-meta">
          {similarity !== undefined && (
            <span
              className={`acx-identity-cluster__match-score ${
                similarity >= 0.7
                  ? 'acx-identity-cluster__match-score--high'
                  : 'acx-identity-cluster__match-score--medium'
              }`}
            >
              {Math.round(similarity * 100)}%
            </span>
          )}
          {count !== undefined && (
            <span className="acx-identity-cluster__member-count">
              ({count} {count === 1 ? __('item', 'alt-context') : __('items', 'alt-context')})
            </span>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * Edit form for cluster label with autocomplete suggestions.
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
  return (
    <div className="acx-identity-cluster__edit">
      <Combobox
        value={labelInput}
        onValueChange={onLabelChange}
        options={options}
        placeholder={__('Enter a name…', 'alt-context')}
        emptyMessage={__('No matching labels. Press Enter to keep your new name.', 'alt-context')}
        ariaLabel={__('Cluster label', 'alt-context')}
        disabled={isPending}
        isLoading={isLoading}
        renderOption={renderSuggestionOption}
      />
      <button type="button" className="acx-identity-cluster__save" onClick={onSave} disabled={isPending}>
        {isPending ? __('Saving…', 'alt-context') : __('Save', 'alt-context')}
      </button>
      <button type="button" className="acx-identity-cluster__cancel" onClick={onCancel}>
        {__('Cancel', 'alt-context')}
      </button>
    </div>
  );
};
