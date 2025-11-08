<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

/**
 * Automation Queue admin page.
 *
 * Renders the React-based interface for monitoring and managing automated alt-text generation.
 *
 * @since 1.0.0
 */
class AutomationQueuePage extends AbstractSpaPage
{
    public const ROOT_ID = 'context-alt-text-automation-root';

    protected function getRootId(): string
    {
        return self::ROOT_ID;
    }

    protected function getRootClass(): string
    {
        return 'context-alt-text-automation-root';
    }

    protected function getPageTitle(): string
    {
        return __('Automation Queue', 'context-alt-text');
    }

    protected function getLoadingMessage(): string
    {
        return __('Automation queue UI loading…', 'context-alt-text');
    }
}

