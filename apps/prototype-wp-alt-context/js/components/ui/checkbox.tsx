import * as React from 'react';

interface CheckboxProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}

export const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ checked, onCheckedChange, ariaLabel, disabled, className }, ref) => (
    <button
      ref={ref}
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      className={`acx-checkbox ${className ?? ''}${checked ? ' is-checked' : ''}`}
      onClick={() => onCheckedChange(!checked)}
    >
      <span aria-hidden="true" className="acx-checkbox__box" />
    </button>
  ),
);

Checkbox.displayName = 'Checkbox';
