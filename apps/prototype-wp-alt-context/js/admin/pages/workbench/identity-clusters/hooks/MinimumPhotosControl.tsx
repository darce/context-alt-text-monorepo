import React from 'react';
import { __ } from '@wordpress/i18n';

interface MinimumPhotosControlProps {
  value?: number;
  onChange: (value: number | undefined) => void;
}

/** Controlled by the producer-list owner. All deliberately omits min_photos. */
export const MinimumPhotosControl = ({ value, onChange }: MinimumPhotosControlProps): React.JSX.Element => {
  const id = React.useId();
  return (
    <div>
      <label htmlFor={id}>{__('Minimum photos (optional)', 'alt-context')}</label>{' '}
      <select
        aria-describedby={`${id}-hint`}
        id={id}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value === '' ? undefined : Number(event.target.value))}
      >
        <option value="">{__('All', 'alt-context')}</option>
        {[1, 2, 3, 5, 10].map((minimum) => (
          <option key={minimum} value={minimum}>
            {minimum}
          </option>
        ))}
        {value !== undefined && ![1, 2, 3, 5, 10].includes(value) ? <option value={value}>{value}</option> : null}
      </select>
      <p id={`${id}-hint`}>
        {__(
          'Counts distinct photos in each face group, not the number of faces. Unavailable counts do not match a minimum.',
          'alt-context',
        )}
      </p>
    </div>
  );
};
