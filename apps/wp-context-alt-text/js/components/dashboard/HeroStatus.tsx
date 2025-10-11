import React from "react";
import { __, sprintf } from "@wordpress/i18n";

import type { HeroStatus } from "@/admin/types";
import { Button } from "@/components/ui/button";

interface HeroStatusProps {
    data: HeroStatus;
}

export const HeroStatusSection = ({ data }: HeroStatusProps): React.JSX.Element => {
    return (
        <section className={`cat-hero cat-hero--${data.state}`} aria-live="polite" role="status">
            <div className="cat-hero__content">
                <p className="cat-hero__message">{data.message}</p>
                {data.last_updated_human && (
                    <p className="cat-hero__timestamp">
                        {sprintf(
                            /* translators: %s: human readable duration since last update */
                            __("Last updated %s ago", "context-alt-text"),
                            data.last_updated_human,
                        )}
                    </p>
                )}
            </div>
            <div className="cat-hero__actions">
                <Button asChild variant="primary">
                    <a href={data.cta_url}>{data.cta_label}</a>
                </Button>
            </div>
        </section>
    );
};
