import React from "react";
import type { DashboardFooter } from "@/admin/types";
import { Button } from "@/components/ui/button";

interface ActionFooterProps {
    data: DashboardFooter;
}

export const ActionFooter = ({ data }: ActionFooterProps): React.JSX.Element => {
    return (
        <footer className="cat-footer">
            <div className="cat-footer__actions">
                {data.actions.map((action) => (
                    <Button key={action.label} asChild variant="default" size="md">
                        <a href={action.url}>{action.label}</a>
                    </Button>
                ))}
            </div>
            <p className="cat-footer__status">{data.statusText}</p>
        </footer>
    );
};
