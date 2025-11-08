import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import React from "react";

export const TooltipProvider = TooltipPrimitive.Provider;

export const TooltipRoot = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export const TooltipContent = ({
    className,
    side = "top",
    children,
    ...props
}: TooltipPrimitive.TooltipContentProps): React.JSX.Element => {
    return (
        <TooltipPrimitive.Content side={side} className={`cat-tooltip ${className ?? ""}`.trim()} {...props}>
            {children}
            <TooltipPrimitive.Arrow className="cat-tooltip__arrow" />
        </TooltipPrimitive.Content>
    );
};
