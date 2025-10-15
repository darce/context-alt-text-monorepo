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
        const classes = [variantClassName[variant], sizeClassName[size], className]
            .filter(Boolean)
            .join(" ");
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

Button.displayName = "Button";
