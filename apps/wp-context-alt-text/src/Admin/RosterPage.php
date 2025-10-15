<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Security\Security;
use ContextAltText\Services\Scan\MissingAltTextScanner;
use ContextAltText\Roster\RosterSyncScheduler;
use function __;
use function sanitize_text_field;
use function wp_send_json_error;
use function wp_send_json_success;

class RosterPage
{
    private RosterService $rosterService;
    private Security $security;
    private MissingAltTextScanner $scanner;
    private RosterSyncScheduler $scheduler;

    public function __construct(
        RosterService $rosterService,
        Security $security,
        MissingAltTextScanner $scanner,
        RosterSyncScheduler $scheduler
    ) {
        $this->rosterService = $rosterService;
        $this->security = $security;
        $this->scanner = $scanner;
        $this->scheduler = $scheduler;
    }

    public function init(): void
    {
        add_action('admin_enqueue_scripts', [$this, 'enqueue_scripts']);
        add_action('wp_ajax_context_alt_text_roster', [$this, 'handle_ajax_actions']);
    }

    public function enqueue_scripts(string $hook): void
    {
        if ($hook !== Admin::DASHBOARD_HOOK) {
            return;
        }

        // Placeholder for roster-specific asset loading once the SPA ships.
    }

    public function render_page(): void
    {
?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Context Alt Text', 'context-alt-text'); ?></h1>
            <div id="<?php echo esc_attr(DashboardPage::ROOT_ID); ?>" class="context-alt-text-admin__app">
                <noscript>
                    <?php esc_html_e('Roster management requires JavaScript. Please enable JavaScript in your browser.', 'context-alt-text'); ?>
                </noscript>
            </div>
        </div>
<?php
    }

    public function handle_ajax_actions(): void
    {
        if (!$this->security->can_manage_roster()) {
            wp_send_json_error(['message' => __('You are not allowed to manage the roster.', 'context-alt-text')], 403);
            return;
        }

        if (!$this->security->verify_admin_nonce('context-alt-text-roster', '_wpnonce', $_REQUEST)) {
            wp_send_json_error(['message' => __('Invalid request nonce.', 'context-alt-text')], 400);
            return;
        }

        $commandRaw = $_REQUEST['command'] ?? 'sync';
        $command = sanitize_text_field((string) $commandRaw);

        if ($command !== 'sync') {
            wp_send_json_error(['message' => __('Unknown roster action.', 'context-alt-text')], 400);
            return;
        }

        $result = $this->scheduler->runManualSync();

        wp_send_json_success([
            'changesApplied' => $result['changesApplied'],
            'state' => $result['state'],
        ]);
    }
}
