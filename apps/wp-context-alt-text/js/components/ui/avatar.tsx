/**
 * Avatar UI Component
 *
 * Wrapper around Radix UI Avatar primitive for displaying user avatars
 * with automatic loading state management and fallback support.
 */

import * as React from "react";
import * as AvatarPrimitive from "@radix-ui/react-avatar";
import "./avatar.css";

export const Avatar = AvatarPrimitive.Root;

export interface AvatarImageProps extends React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Image> {}

export const AvatarImage = React.forwardRef<React.ElementRef<typeof AvatarPrimitive.Image>, AvatarImageProps>(
    ({ className, ...props }, ref) => (
        <AvatarPrimitive.Image ref={ref} className={`cat-avatar-image ${className ?? ""}`.trim()} {...props} />
    ),
);
AvatarImage.displayName = "AvatarImage";

export interface AvatarFallbackProps extends React.ComponentPropsWithoutRef<typeof AvatarPrimitive.Fallback> {}

export const AvatarFallback = React.forwardRef<React.ElementRef<typeof AvatarPrimitive.Fallback>, AvatarFallbackProps>(
    ({ className, ...props }, ref) => (
        <AvatarPrimitive.Fallback ref={ref} className={`cat-avatar-fallback ${className ?? ""}`.trim()} {...props} />
    ),
);
AvatarFallback.displayName = "AvatarFallback";
