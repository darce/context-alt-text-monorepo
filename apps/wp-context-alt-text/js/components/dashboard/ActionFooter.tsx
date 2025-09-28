import React from "react";
import type { DashboardFooter } from "@/admin/types";

interface ActionFooterProps {
    data: DashboardFooter;
}

export const ActionFooter = ({ data }: ActionFooterProps): React.JSX.Element => {
    return (
        <footer className="cat-footer">
            <div className="cat-footer__actions">
                {data.actions.map((action) => (
                    <a key={action.label} className="cat-button" href={action.url}>
                        {action.label}
                    </a>
                ))}
            </div>
            <p className="cat-footer__status">{data.statusText}</p>
        </footer>
    );
};
