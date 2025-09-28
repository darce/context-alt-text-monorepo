<?php

declare(strict_types=1);

namespace ContextAltText\Services\Scan;

class MissingAltTextScanner
{
    public const CRON_HOOK = 'context_alt_text/run_first_scan';
    private const OPTION_KEY = 'context_alt_text_missing_counts';

    public function register(): void
    {
        add_action(self::CRON_HOOK, [$this, 'handle']);
        add_action('admin_init', [$this, 'maybe_prime_counts']);
    }

    public function schedule_first_run(): void
    {
        if (!wp_next_scheduled(self::CRON_HOOK)) {
            wp_schedule_single_event(time() + 20, self::CRON_HOOK);
        }
    }

    public function clear_schedule(): void
    {
        wp_clear_scheduled_hook(self::CRON_HOOK);
    }

    public function handle(): void
    {
        $counts = $this->scan_missing_alt_text();
        $counts['updated_at'] = time();

        update_option(self::OPTION_KEY, $counts);
        $this->recordCoverageHistory($counts);
    }

    public function get_summary(): array
    {
        $defaults = [
            'total' => 0,
            'with_alt' => 0,
            'missing' => 0,
            'updated_at' => null,
        ];

        $counts = get_option(self::OPTION_KEY, $defaults);

        if (!is_array($counts)) {
            return $defaults;
        }

        return array_merge($defaults, $counts);
    }

    public function cleanup(): void
    {
        delete_option(self::OPTION_KEY);
        $this->clear_schedule();
    }

    public function maybe_prime_counts(): void
    {
        if (!is_admin()) {
            return;
        }

        $summary = $this->get_summary();
        $updatedAt = $summary['updated_at'] ?? null;

        if (!empty($updatedAt)) {
            return;
        }

        $this->handle();
    }

    protected function scan_missing_alt_text(): array
    {
        global $wpdb;

        $query = <<<SQL
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN COALESCE(pm.meta_value, '') <> '' THEN 1 ELSE 0 END) AS with_alt
            FROM {$wpdb->posts} p
            LEFT JOIN {$wpdb->postmeta} pm
                ON pm.post_id = p.ID AND pm.meta_key = '_wp_attachment_image_alt'
            WHERE p.post_type = 'attachment'
                AND p.post_mime_type LIKE 'image/%'
            SQL;

        $row = $wpdb->get_row($query, ARRAY_A);

        if (!$row) {
            return [
                'total' => 0,
                'with_alt' => 0,
                'missing' => 0,
            ];
        }

        $total = (int) ($row['total'] ?? 0);
        $withAlt = (int) ($row['with_alt'] ?? 0);
        $missing = max($total - $withAlt, 0);

        return [
            'total' => $total,
            'with_alt' => $withAlt,
            'missing' => $missing,
        ];
    }

    /**
     * Persist coverage history for dashboard visualisations.
     *
     * @param array<string,mixed> $counts
     */
    private function recordCoverageHistory(array $counts): void
    {
        $total = max((int) ($counts['total'] ?? 0), 0);
        $withAlt = max((int) ($counts['with_alt'] ?? 0), 0);
        $missing = max((int) ($counts['missing'] ?? 0), 0);

        if ($total <= 0) {
            return;
        }

        $coverage = $total > 0 ? round(($withAlt / $total) * 100, 2) : 0.0;

        $history = get_option('context_alt_text_coverage_history', []);
        if (!is_array($history)) {
            $history = [];
        }

        $history[] = [
            'timestamp' => time(),
            'coverage' => $coverage,
            'total' => $total,
            'with_alt' => $withAlt,
            'missing' => $missing,
        ];

        if (count($history) > 50) {
            $history = array_slice($history, -50);
        }

        update_option('context_alt_text_coverage_history', $history);
    }
}
