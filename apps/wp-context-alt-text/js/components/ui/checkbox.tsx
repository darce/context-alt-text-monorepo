import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import "./checkbox.css";

/**
 * Checkbox component wrapping Radix UI Checkbox primitive.
 *
 * Provides accessible, customizable checkbox with keyboard navigation,
 * screen reader support, and full styling control.
 *
 * @example
 * ```tsx
 * <Checkbox
 *   checked={isChecked}
 *   onCheckedChange={setIsChecked}
 *   aria-label="Accept terms"
 * />
 * ```
 * @see https://www.radix-ui.com/primitives/docs/components/checkbox
 */

export const Checkbox = React.forwardRef<
    React.ElementRef<typeof CheckboxPrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
    <CheckboxPrimitive.Root ref={ref} className={`cat-checkbox ${className ?? ""}`.trim()} {...props}>
        <CheckboxPrimitive.Indicator className="cat-checkbox-indicator">
            <span className="cat-checkbox-icon" aria-hidden="true">
                ✓
            </span>
        </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
));
Checkbox.displayName = CheckboxPrimitive.Root.displayName;
