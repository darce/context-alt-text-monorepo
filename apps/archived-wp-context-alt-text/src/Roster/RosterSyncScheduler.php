<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use ContextAltText\Domain\Roster\RosterService;
use function add_action;
use function get_option;
use function is_array;
use function time;
use function wp_clear_scheduled_hook;
use function wp_next_scheduled;
use function wp_schedule_single_event;

final class RosterSyncScheduler
{
    public const HOOK = 'context_alt_text_roster_sync';

    private RosterService $service;
    private int $intervalSeconds;

    public function __construct(RosterService $service, int $intervalSeconds = 900)
    {
        $this->service = $service;
        $this->intervalSeconds = max(300, $intervalSeconds);
    }

    public function register(): void
    {
        add_action('init', [$this, 'ensureSchedule']);
        add_action(self::HOOK, [$this, 'handleScheduledSync']);
    }

    public function ensureSchedule(): void
    {
        if (wp_next_scheduled(self::HOOK)) {
            return;
        }

        $this->scheduleNextRun();
    }

    public function handleScheduledSync(): void
    {
        $this->service->syncFromRemote();
        $this->scheduleNextRun();
    }

    public function activate(): void
    {
        $this->ensureSchedule();
    }

    public function deactivate(): void
    {
        wp_clear_scheduled_hook(self::HOOK);
    }

    /**
     * @return array{changesApplied:bool,state:array<string,mixed>}
     */
    public function runManualSync(): array
    {
        $changesApplied = (bool) $this->service->syncFromRemote();
        $state = get_option('cat_roster_sync_state');

        if (!is_array($state)) {
            $state = [];
        }

        return [
            'changesApplied' => $changesApplied,
            'state' => $state,
        ];
    }

    private function scheduleNextRun(): void
    {
        $timestamp = time() + $this->intervalSeconds;
        wp_schedule_single_event($timestamp, self::HOOK);
    }
}
