import * as React from 'react';
import * as CheckboxPrimitive from '@radix-ui/react-checkbox';

interface CheckboxProps {
  checked: boolean | 'indeterminate';
  onCheckedChange: (checked: boolean) => void;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
}

export const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ checked, onCheckedChange, ariaLabel, disabled, className }, ref) => (
    <CheckboxPrimitive.Root
      ref={ref}
      checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      className={`acx-checkbox ${className ?? ''}${checked === true ? ' is-checked' : ''}${checked === 'indeterminate' ? ' is-indeterminate' : ''}`}
      onCheckedChange={(nextChecked) => onCheckedChange(nextChecked === true)}
    >
      <span aria-hidden="true" className="acx-checkbox__box" />
    </CheckboxPrimitive.Root>
  ),
);

Checkbox.displayName = 'Checkbox';
