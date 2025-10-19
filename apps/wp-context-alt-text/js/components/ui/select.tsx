import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import "./select.css";

/**
 * Select component wrapping Radix UI Select primitive.
 *
 * Provides accessible, customizable dropdown selection with keyboard navigation,
 * typeahead search, and full styling control.
 *
 * @example
 * <Select value={value} onValueChange={setValue}>
 *   <SelectTrigger>
 *     <SelectValue placeholder="Select an option" />
 *   </SelectTrigger>
 *   <SelectContent>
 *     <SelectItem value="option1">Option 1</SelectItem>
 *     <SelectItem value="option2">Option 2</SelectItem>
 *   </SelectContent>
 * </Select>
 *
 * @see https://www.radix-ui.com/primitives/docs/components/select
 */

export const Select = SelectPrimitive.Root;
export const SelectGroup = SelectPrimitive.Group;
export const SelectValue = SelectPrimitive.Value;

export const SelectTrigger = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Trigger>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
    <SelectPrimitive.Trigger ref={ref} className={`cat-select-trigger ${className ?? ""}`.trim()} {...props}>
        {children}
        <SelectPrimitive.Icon asChild>
            <span className="cat-select-icon" aria-hidden="true">
                ▼
            </span>
        </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

export const SelectScrollUpButton = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.ScrollUpButton>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.ScrollUpButton
        ref={ref}
        className={`cat-select-scroll-button ${className ?? ""}`.trim()}
        {...props}
    >
        <span aria-hidden="true">▲</span>
    </SelectPrimitive.ScrollUpButton>
));
SelectScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

export const SelectScrollDownButton = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.ScrollDownButton>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.ScrollDownButton
        ref={ref}
        className={`cat-select-scroll-button ${className ?? ""}`.trim()}
        {...props}
    >
        <span aria-hidden="true">▼</span>
    </SelectPrimitive.ScrollDownButton>
));
SelectScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

export const SelectContent = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>
>(({ className, children, position = "popper", ...props }, ref) => (
    <SelectPrimitive.Portal>
        <SelectPrimitive.Content
            ref={ref}
            className={`cat-select-content ${className ?? ""}`.trim()}
            position={position}
            {...props}
        >
            <SelectScrollUpButton />
            <SelectPrimitive.Viewport
                className={`cat-select-viewport ${position === "popper" ? "cat-select-viewport--popper" : ""}`.trim()}
            >
                {children}
            </SelectPrimitive.Viewport>
            <SelectScrollDownButton />
        </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
));
SelectContent.displayName = SelectPrimitive.Content.displayName;

export const SelectLabel = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.Label ref={ref} className={`cat-select-label ${className ?? ""}`.trim()} {...props} />
));
SelectLabel.displayName = SelectPrimitive.Label.displayName;

export const SelectItem = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, ...props }, ref) => (
    <SelectPrimitive.Item ref={ref} className={`cat-select-item ${className ?? ""}`.trim()} {...props}>
        <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
        <SelectPrimitive.ItemIndicator asChild>
            <span className="cat-select-item-indicator" aria-hidden="true">
                ✓
            </span>
        </SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
));
SelectItem.displayName = SelectPrimitive.Item.displayName;

export const SelectSeparator = React.forwardRef<
    React.ElementRef<typeof SelectPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.Separator ref={ref} className={`cat-select-separator ${className ?? ""}`.trim()} {...props} />
));
SelectSeparator.displayName = SelectPrimitive.Separator.displayName;
