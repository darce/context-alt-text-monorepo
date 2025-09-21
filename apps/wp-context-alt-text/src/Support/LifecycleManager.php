<?php

declare(strict_types=1);

namespace ContextAltText\Support;

use ContextAltText\Services\Scan\MissingAltTextScanner;

class LifecycleManager
{
    private MissingAltTextScanner $scanner;

    public function __construct(MissingAltTextScanner $scanner)
    {
        $this->scanner = $scanner;
    }

    public function activate(): void
    {
        update_option('context_alt_text_version', CONTEXT_ALT_TEXT_VERSION);
        $this->scanner->handle();
        $this->scanner->schedule_first_run();
    }

    public function deactivate(): void
    {
        $this->scanner->clear_schedule();
    }

    public function uninstall(): void
    {
        delete_option('context_alt_text_version');
        $this->scanner->cleanup();
    }
}
