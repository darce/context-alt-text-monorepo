import React from "react";

interface CardProps {
    title: string;
    children: React.ReactNode;
    className?: string;
}

export const Card = React.forwardRef<HTMLElement, CardProps>(
    ({ title, children, className }, ref): React.JSX.Element => {
        return (
            <article ref={ref} className={`cat-card ${className ?? ""}`.trim()}>
                <header className="cat-card__header">
                    <h2>{title}</h2>
                </header>
                <div className="cat-card__body">{children}</div>
            </article>
        );
    },
);

Card.displayName = "Card";
