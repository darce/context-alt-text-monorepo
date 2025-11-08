import * as React from "react";
import * as ToastPrimitive from "@radix-ui/react-toast";
import "./toast.scss";

export const ToastProvider = ToastPrimitive.Provider;

export const ToastViewport = React.forwardRef<
    React.ElementRef<typeof ToastPrimitive.Viewport>,
    React.ComponentPropsWithoutRef<typeof ToastPrimitive.Viewport>
>(({ className, ...props }, ref) => (
    <ToastPrimitive.Viewport ref={ref} className={`cat-toast-viewport ${className ?? ""}`} {...props} />
));
ToastViewport.displayName = "ToastViewport";

export const Toast = React.forwardRef<
    React.ElementRef<typeof ToastPrimitive.Root>,
    React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root>
>(({ className, ...props }, ref) => (
    <ToastPrimitive.Root ref={ref} className={`cat-toast ${className ?? ""}`} {...props} />
));
Toast.displayName = "Toast";

export const ToastAction = React.forwardRef<
    React.ElementRef<typeof ToastPrimitive.Action>,
    React.ComponentPropsWithoutRef<typeof ToastPrimitive.Action>
>(({ className, ...props }, ref) => (
    <ToastPrimitive.Action ref={ref} className={`cat-toast__action ${className ?? ""}`} {...props} />
));
ToastAction.displayName = "ToastAction";

export const ToastClose = React.forwardRef<
    React.ElementRef<typeof ToastPrimitive.Close>,
    React.ComponentPropsWithoutRef<typeof ToastPrimitive.Close>
>(({ className, ...props }, ref) => (
    <ToastPrimitive.Close ref={ref} className={`cat-toast__close ${className ?? ""}`} {...props} />
));
ToastClose.displayName = "ToastClose";

export const ToastTitle = React.forwardRef<
    React.ElementRef<typeof ToastPrimitive.Title>,
    React.ComponentPropsWithoutRef<typeof ToastPrimitive.Title>
>(({ className, ...props }, ref) => (
    <ToastPrimitive.Title ref={ref} className={`cat-toast__title ${className ?? ""}`} {...props} />
));
ToastTitle.displayName = "ToastTitle";

export const ToastDescription = React.forwardRef<
    React.ElementRef<typeof ToastPrimitive.Description>,
    React.ComponentPropsWithoutRef<typeof ToastPrimitive.Description>
>(({ className, ...props }, ref) => (
    <ToastPrimitive.Description ref={ref} className={`cat-toast__description ${className ?? ""}`} {...props} />
));
ToastDescription.displayName = "ToastDescription";

export type ToastProps = React.ComponentPropsWithoutRef<typeof Toast>;
export type ToastActionElement = React.ReactElement<typeof ToastAction>;
