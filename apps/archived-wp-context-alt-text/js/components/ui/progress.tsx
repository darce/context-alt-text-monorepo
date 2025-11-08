import * as ProgressPrimitive from "@radix-ui/react-progress";
import React from "react";

export interface ProgressProps extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
    indicatorClassName?: string;
}

type ProgressRef = React.ComponentRef<typeof ProgressPrimitive.Root>;

export const Progress = React.forwardRef<ProgressRef, ProgressProps>(
    ({ indicatorClassName, className, value = 0, role, ...props }, ref) => {
        const clamped = Math.max(0, Math.min(100, Number(value) || 0));

        return (
            <ProgressPrimitive.Root
                ref={ref}
                role={role ?? "progressbar"}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={clamped}
                className={`cat-progress ${className ?? ""}`.trim()}
                value={clamped}
                {...props}
            >
                <ProgressPrimitive.Indicator
                    className={`cat-progress__indicator ${indicatorClassName ?? ""}`.trim()}
                    style={{ width: `${clamped}%`, "--cat-progress-value": clamped } as React.CSSProperties}
                />
            </ProgressPrimitive.Root>
        );
    },
);

Progress.displayName = "Progress";
