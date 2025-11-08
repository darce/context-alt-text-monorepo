<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

/**
 * Account Center admin page.
 *
 * Renders the React-based interface for managing recognition service settings and API keys.
 *
 * @since 1.0.0
 */
class AccountCenterPage extends AbstractSpaPage
{
    public const ROOT_ID = 'context-alt-text-account-root';

    protected function getRootId(): string
    {
        return self::ROOT_ID;
    }

    protected function getRootClass(): string
    {
        return 'context-alt-text-account-root';
    }

    protected function getPageTitle(): string
    {
        return __('Account Center', 'context-alt-text');
    }

    protected function getLoadingMessage(): string
    {
        return __('Account center UI loading…', 'context-alt-text');
    }
}

