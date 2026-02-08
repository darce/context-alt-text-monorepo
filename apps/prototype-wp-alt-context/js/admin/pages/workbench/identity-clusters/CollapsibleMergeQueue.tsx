import React, { useState, useEffect } from 'react';
import { __ } from '@wordpress/i18n';
import { MergeSuggestionCard } from './MergeSuggestionCard';
import type { PendingMergeSuggestion } from '../../../api/recognition';

interface CollapsibleMergeQueueProps {
  suggestions: PendingMergeSuggestion[];
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  isPending: boolean;
}

export const CollapsibleMergeQueue = ({
  suggestions,
  onAccept,
  onReject,
  isPending,
}: CollapsibleMergeQueueProps): React.JSX.Element | null => {
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem('AltContext:MergeQueue:Open');
    if (saved === 'true') {
      setIsOpen(true);
    }
  }, []);

  const toggle = () => {
    const newState = !isOpen;
    setIsOpen(newState);
    localStorage.setItem('AltContext:MergeQueue:Open', String(newState));
  };

  if (!suggestions || suggestions.length === 0) {
    return null;
  }

  return (
    <div className="acx-merge-queue">
      <button type="button" className="acx-merge-queue__header" onClick={toggle} aria-expanded={isOpen}>
        <span className={`acx-merge-queue__toggle-icon ${isOpen ? 'is-open' : ''}`}>▼</span>
        <span className="acx-merge-queue__title">{__('Merge Candidates', 'alt-context')}</span>
        <span className="acx-badge acx-badge--count">{suggestions.length}</span>
      </button>

      {isOpen && (
        <div className="acx-merge-queue__list">
          {suggestions.map((suggestion) => (
            <MergeSuggestionCard
              key={suggestion.id}
              suggestion={suggestion}
              onAccept={() => onAccept(suggestion.id)}
              onReject={() => onReject(suggestion.id)}
              isPending={isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
};
