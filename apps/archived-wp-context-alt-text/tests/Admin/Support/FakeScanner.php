<?php

declare(strict_types=1);

use ContextAltText\Services\Scan\MissingAltTextScanner;

final class FakeScanner extends MissingAltTextScanner
{
    /** @var array<string,mixed> */
    private array $summary;

    /**
     * @param array<string,mixed> $summary
     */
    public function __construct(array $summary)
    {
        $this->summary = $summary;
    }

    public function get_summary(): array
    {
        return $this->summary;
    }
}
