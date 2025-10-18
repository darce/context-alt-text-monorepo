import * as React from "react";
import * as FormPrimitive from "@radix-ui/react-form";
import "./form.css";

/**
 * Form root component - wraps the entire form
 */
export const Form = FormPrimitive.Root;

/**
 * Form field wrapper - handles id/name and label accessibility
 */
export const FormField = React.forwardRef<
    React.ElementRef<typeof FormPrimitive.Field>,
    React.ComponentPropsWithoutRef<typeof FormPrimitive.Field>
>(({ className, ...props }, ref) => (
    <FormPrimitive.Field ref={ref} className={`cat-field ${className ?? ""}`.trim()} {...props} />
));
FormField.displayName = "FormField";

/**
 * Form label - automatically wired to control when nested in FormField
 */
export const FormLabel = React.forwardRef<
    React.ElementRef<typeof FormPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof FormPrimitive.Label>
>(({ className, ...props }, ref) => (
    <FormPrimitive.Label ref={ref} className={`cat-field__label ${className ?? ""}`.trim()} {...props} />
));
FormLabel.displayName = "FormLabel";

/**
 * Form control - the input/textarea/select element
 */
export const FormControl = React.forwardRef<
    React.ElementRef<typeof FormPrimitive.Control>,
    React.ComponentPropsWithoutRef<typeof FormPrimitive.Control>
>(({ className, ...props }, ref) => (
    <FormPrimitive.Control ref={ref} className={`cat-field__input ${className ?? ""}`.trim()} {...props} />
));
FormControl.displayName = "FormControl";

/**
 * Form validation message - shown when field is invalid
 */
export const FormMessage = React.forwardRef<
    React.ElementRef<typeof FormPrimitive.Message>,
    React.ComponentPropsWithoutRef<typeof FormPrimitive.Message>
>(({ className, children, ...props }, ref) => (
    <FormPrimitive.Message ref={ref} className={`cat-field__error ${className ?? ""}`.trim()} {...props}>
        {children}
    </FormPrimitive.Message>
));
FormMessage.displayName = "FormMessage";

/**
 * Form submit button
 */
export const FormSubmit = React.forwardRef<
    React.ElementRef<typeof FormPrimitive.Submit>,
    React.ComponentPropsWithoutRef<typeof FormPrimitive.Submit>
>(({ className, ...props }, ref) => (
    <FormPrimitive.Submit ref={ref} className={`cat-button cat-button--primary ${className ?? ""}`.trim()} {...props} />
));
FormSubmit.displayName = "FormSubmit";

/**
 * Form validity state - render prop for accessing field validity
 */
export const FormValidityState = FormPrimitive.ValidityState;
