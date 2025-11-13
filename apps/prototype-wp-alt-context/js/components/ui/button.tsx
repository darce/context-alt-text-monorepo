import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';

export type ButtonVariant = 'default' | 'primary' | 'subtle';
export type ButtonSize = 'sm' | 'md' | 'lg';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  asChild?: boolean;
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const variantClassName: Record<ButtonVariant, string> = {
  default: 'alt-context-button alt-context-button--default',
  primary: 'alt-context-button alt-context-button--primary',
  subtle: 'alt-context-button alt-context-button--subtle',
};

const sizeClassName: Record<ButtonSize, string> = {
  sm: 'alt-context-button--sm',
  md: 'alt-context-button--md',
  lg: 'alt-context-button--lg',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ asChild = false, type = 'button', className = '', variant = 'default', size = 'md', ...props }, ref) => {
    const classes = [variantClassName[variant], sizeClassName[size], className].filter(Boolean).join(' ');
    const { children, ...restProps } = props;

    if (asChild) {
      return (
        <Slot ref={ref} className={classes} {...restProps}>
          {children}
        </Slot>
      );
    }

    return (
      <button ref={ref} type={type} className={classes} {...restProps}>
        {children}
      </button>
    );
  },
);

Button.displayName = 'Button';
