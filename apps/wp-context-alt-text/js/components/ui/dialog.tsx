/**
 * Dialog Component - Radix UI Dialog Primitive Wrapper
 *
 * Provides accessible modal dialog components with proper focus management,
 * keyboard navigation, and screen reader support.
 *
 * @see https://www.radix-ui.com/primitives/docs/components/dialog
 */

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import "./dialog.css";

/**
 * Dialog root component - Controls open/closed state
 */
export const Dialog = DialogPrimitive.Root;

/**
 * Dialog trigger - Button that opens the dialog
 */
export const DialogTrigger = DialogPrimitive.Trigger;

/**
 * Dialog portal - Renders dialog content in a portal (outside DOM hierarchy)
 */
export const DialogPortal = DialogPrimitive.Portal;

/**
 * Dialog close - Button that closes the dialog
 */
export const DialogClose = DialogPrimitive.Close;

/**
 * Dialog overlay - Semi-transparent backdrop behind the dialog
 */
export const DialogOverlay = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Overlay>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
    <DialogPrimitive.Overlay ref={ref} className={`cat-dialog-overlay ${className ?? ""}`.trim()} {...props} />
));
DialogOverlay.displayName = "DialogOverlay";

/**
 * Dialog content - Main dialog container with title and description
 */
export const DialogContent = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, ...props }, ref) => (
    <DialogPortal>
        <DialogOverlay />
        <DialogPrimitive.Content ref={ref} className={`cat-dialog-content ${className ?? ""}`.trim()} {...props}>
            {children}
        </DialogPrimitive.Content>
    </DialogPortal>
));
DialogContent.displayName = "DialogContent";

/**
 * Dialog title - Accessible title for the dialog (required for a11y)
 */
export const DialogTitle = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Title>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
    <DialogPrimitive.Title ref={ref} className={`cat-dialog-title ${className ?? ""}`.trim()} {...props} />
));
DialogTitle.displayName = "DialogTitle";

/**
 * Dialog description - Accessible description for the dialog (optional but recommended)
 */
export const DialogDescription = React.forwardRef<
    React.ElementRef<typeof DialogPrimitive.Description>,
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
    <DialogPrimitive.Description ref={ref} className={`cat-dialog-description ${className ?? ""}`.trim()} {...props} />
));
DialogDescription.displayName = "DialogDescription";
