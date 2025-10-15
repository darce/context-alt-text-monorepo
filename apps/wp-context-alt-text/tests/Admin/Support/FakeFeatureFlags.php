<?php

declare(strict_types=1);

use ContextAltText\Support\FeatureFlags;

final class FakeFeatureFlags extends FeatureFlags
{
    /** @var array<string,bool> */
    private array $flags;

    /**
     * @param array<string,bool> $flags
     */
    public function __construct(array $flags = [])
    {
        $this->flags = $flags;
    }

    public function coverageTrendEnabled(): bool
    {
        return $this->flags['coverageTrend'] ?? parent::coverageTrendEnabled();
    }

    public function workbenchEnabled(): bool
    {
        return $this->flags['workbenchEnabled'] ?? parent::workbenchEnabled();
    }

    public function workbenchRecognitionEnabled(): bool
    {
        return $this->flags['workbenchRecognition'] ?? parent::workbenchRecognitionEnabled();
    }

    public function workbenchBulkAIEnabled(): bool
    {
        return $this->flags['workbenchBulkAI'] ?? parent::workbenchBulkAIEnabled();
    }

    public function abilitiesEnabled(): bool
    {
        return $this->flags['abilitiesEnabled'] ?? parent::abilitiesEnabled();
    }

    public function rosterUiEnabled(): bool
    {
        return $this->flags['rosterEnabled'] ?? parent::rosterUiEnabled();
    }
}
