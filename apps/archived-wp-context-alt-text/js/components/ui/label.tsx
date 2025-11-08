import * as React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import "./label.css";

/**
 * Label component wrapping Radix UI Label primitive.
 *
 * Automatically handles accessibility when used with form controls.
 * Supports both wrapping pattern and htmlFor association.
 *
 * @example
 * // Wrapping pattern
 * <Label>
 *   {__("Email", "context-alt-text")}
 *   <input type="email" name="email" />
 * </Label>
 *
 * @example
 * // htmlFor pattern
 * <Label htmlFor="email">{__("Email", "context-alt-text")}</Label>
 * <input id="email" type="email" name="email" />
 *
 * @see https://www.radix-ui.com/primitives/docs/components/label
 */
export const Label = React.forwardRef<
    React.ElementRef<typeof LabelPrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
    <LabelPrimitive.Root ref={ref} className={`cat-label ${className ?? ""}`.trim()} {...props} />
));

Label.displayName = "Label";
