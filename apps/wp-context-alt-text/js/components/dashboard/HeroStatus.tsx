import React from "react";
import type { HeroStatus } from "@/admin/types";

interface HeroStatusProps {
    data: HeroStatus;
}

export const HeroStatusSection = ({ data }: HeroStatusProps): React.JSX.Element => {
    return (
        <section className={`cat-hero cat-hero--${data.state}`}>
            <div className="cat-hero__content">
                <p className="cat-hero__message">{data.message}</p>
                {data.last_updated_human && (
                    <p className="cat-hero__timestamp">
                        {`Last updated ${data.last_updated_human} ago`}
                    </p>
                )}
            </div>
            <div className="cat-hero__actions">
                <a className="cat-button cat-button--primary" href={data.cta_url}>
                    {data.cta_label}
                </a>
            </div>
        </section>
    );
};
