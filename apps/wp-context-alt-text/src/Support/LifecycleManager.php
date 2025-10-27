<?php

declare(strict_types=1);

namespace ContextAltText\Support;

use ContextAltText\Infrastructure\Database\UnknownFaceTableInstaller;
use ContextAltText\Services\Scan\MissingAltTextScanner;

class LifecycleManager
{
    private MissingAltTextScanner $scanner;
    private UnknownFaceTableInstaller $unknownFaceTableInstaller;

    public function __construct(MissingAltTextScanner $scanner, UnknownFaceTableInstaller $unknownFaceTableInstaller)
    {
        $this->scanner = $scanner;
        $this->unknownFaceTableInstaller = $unknownFaceTableInstaller;
    }

    public function activate(): void
    {
        update_option('context_alt_text_version', CONTEXT_ALT_TEXT_VERSION);
        $this->unknownFaceTableInstaller->install();
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
