import * as React from "react";
import { Slot } from "@radix-ui/react-slot";

export type ButtonVariant = "default" | "primary" | "subtle";
export type ButtonSize = "sm" | "md" | "lg";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
    asChild?: boolean;
    variant?: ButtonVariant;
    size?: ButtonSize;
};

const variantClassName: Record<ButtonVariant, string> = {
    default: "cat-button cat-button--default",
    primary: "cat-button cat-button--primary",
    subtle: "cat-button cat-button--subtle",
};

const sizeClassName: Record<ButtonSize, string> = {
    sm: "cat-button--sm",
    md: "cat-button--md",
    lg: "cat-button--lg",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
    (
        {
            asChild = false,
            type = "button",
            className = "",
            variant = "default",
            size = "md",
            ...props
        },
        ref,
    ) => {
        const Component = asChild ? Slot : "button";
        const classes = [variantClassName[variant], sizeClassName[size], className]
            .filter(Boolean)
            .join(" ");

        const componentProps = asChild ? props : { ...props, type };

        return <Component ref={ref as any} className={classes} {...componentProps} />;
    },
);

Button.displayName = "Button";
