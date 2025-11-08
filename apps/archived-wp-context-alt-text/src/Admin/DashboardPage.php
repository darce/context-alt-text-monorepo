<?php

declare(strict_types=1);

namespace ContextAltText\Admin;

class DashboardPage
{
    public const ROOT_ID = 'context-alt-text-admin-app';

    private DashboardMetricsService $metrics;

    public function __construct(DashboardMetricsService $metrics)
    {
        $this->metrics = $metrics;
    }

    public function render(): void
    {
        $hero = $this->metrics->getHeroStatus();
        $coverage = $this->metrics->getCoverageCard();
        $latestActivity = $this->metrics->getLatestActivityCard();
        $recognition = $this->metrics->getRecognitionInsightsCard();
        $automation = $this->metrics->getAutomationPipelineCard();
        $footerActions = $this->metrics->getFooterActions();
        $footerStatus = $this->metrics->getFooterStatusText();

        ?>
        <div class="wrap context-alt-text-admin">
            <h1><?php esc_html_e('Context Alt Text Dashboard', 'context-alt-text'); ?></h1>

            <div class="context-alt-text-dashboard" id="<?php echo esc_attr(self::ROOT_ID); ?>">
                <?php $this->renderHero($hero); ?>
                <?php $this->renderDiagnosticCards($coverage, $latestActivity, $recognition, $automation); ?>
                <?php $this->renderFooter($footerActions, $footerStatus); ?>
            </div>
        </div>
        <?php
    }

    /**
     * @param array<string,mixed> $hero
     */
    private function renderHero(array $hero): void
    {
        ?>
        <section class="context-alt-text-dashboard-hero context-alt-text-state-<?php echo esc_attr($hero['state']); ?>">
            <div class="context-alt-text-hero-copy">
                <p class="context-alt-text-hero-message">
                    <?php echo esc_html((string) ($hero['message'] ?? '')); ?>
                </p>
                <?php if (!empty($hero['last_updated_human'])) : ?>
                    <p class="description">
                        <?php
                        printf(
                            /* translators: %s is a human readable time difference. */
                            esc_html__('Last updated %s ago', 'context-alt-text'),
                            esc_html((string) $hero['last_updated_human'])
                        );
                        ?>
                    </p>
                <?php endif; ?>
            </div>
            <div class="context-alt-text-hero-action">
                <a class="button button-primary"
                    href="<?php echo esc_url((string) ($hero['cta_url'] ?? '#')); ?>">
                    <?php echo esc_html((string) ($hero['cta_label'] ?? '')); ?>
                </a>
            </div>
        </section>
        <?php
    }

    /**
     * @param array<string,mixed> $coverage
     * @param array<string,mixed> $latestActivity
     * @param array<string,mixed> $recognition
     * @param array<string,mixed> $automation
     */
    private function renderDiagnosticCards(array $coverage, array $latestActivity, array $recognition, array $automation): void
    {
        ?>
        <section class="context-alt-text-dashboard-cards">
            <article class="context-alt-text-card context-alt-text-card-coverage">
                <header>
                    <h2><?php esc_html_e('Coverage Progress', 'context-alt-text'); ?></h2>
                </header>
                <div class="context-alt-text-chart" data-total="<?php echo esc_attr((string) ($coverage['total'] ?? 0)); ?>"
                    data-missing="<?php echo esc_attr((string) ($coverage['missing'] ?? 0)); ?>"
                    data-with-alt="<?php echo esc_attr((string) ($coverage['with_alt'] ?? 0)); ?>"
                    data-coverage="<?php echo esc_attr((string) ($coverage['coverage_percent'] ?? 0)); ?>">
                    <p class="context-alt-text-coverage-percent">
                        <?php
                        printf(
                            /* translators: %s is the coverage percentage. */
                            esc_html__('%s%% coverage achieved', 'context-alt-text'),
                            esc_html(number_format_i18n((float) ($coverage['coverage_percent'] ?? 0), 1))
                        );
                        ?>
                    </p>
                </div>
                <?php if (!empty($coverage['trend_series']) && is_array($coverage['trend_series'])) : ?>
                    <div class="context-alt-text-coverage-trend"
                        data-series="<?php echo esc_attr(wp_json_encode($coverage['trend_series'])); ?>">
                        <small><?php esc_html_e('Trend (evaluate usefulness before enabling)', 'context-alt-text'); ?></small>
                    </div>
                <?php endif; ?>
            </article>

            <article class="context-alt-text-card context-alt-text-card-activity">
                <header>
                    <h2><?php esc_html_e('Latest Activity', 'context-alt-text'); ?></h2>
                </header>
                <ul>
                    <li>
                        <strong><?php esc_html_e('Recognition', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html($this->formatTimeago($latestActivity['last_recognition'] ?? null)); ?></span>
                    </li>
                    <li>
                        <strong><?php esc_html_e('Alt-text generation', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html($this->formatTimeago($latestActivity['last_alt_text_generation'] ?? null)); ?></span>
                    </li>
                    <li>
                        <strong><?php esc_html_e('Roster sync', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html($this->formatTimeago($latestActivity['last_roster_sync'] ?? null)); ?></span>
                    </li>
                </ul>
            </article>

            <article class="context-alt-text-card context-alt-text-card-recognition">
                <header>
                    <h2><?php esc_html_e('Recognition Insights', 'context-alt-text'); ?></h2>
                </header>
                <ul>
                    <li>
                        <strong><?php esc_html_e('Faces awaiting review', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html((string) ($recognition['pending_faces'] ?? 0)); ?></span>
                    </li>
                    <li>
                        <strong><?php esc_html_e('Brands awaiting review', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html((string) ($recognition['pending_brands'] ?? 0)); ?></span>
                    </li>
                    <li>
                        <strong><?php esc_html_e('Unresolved matches', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html((string) ($recognition['unresolved_matches'] ?? 0)); ?></span>
                    </li>
                </ul>
            </article>

            <article class="context-alt-text-card context-alt-text-card-automation">
                <header>
                    <h2><?php esc_html_e('Automation Pipeline', 'context-alt-text'); ?></h2>
                </header>
                <ul>
                    <li>
                        <strong><?php esc_html_e('Queued', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html((string) ($automation['queued'] ?? 0)); ?></span>
                    </li>
                    <li>
                        <strong><?php esc_html_e('Running', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html((string) ($automation['running'] ?? 0)); ?></span>
                    </li>
                    <li>
                        <strong><?php esc_html_e('Completed (24h)', 'context-alt-text'); ?></strong>
                        <span><?php echo esc_html((string) ($automation['completed'] ?? 0)); ?></span>
                    </li>
                </ul>
                <?php if (!empty($automation['next_run'])) : ?>
                    <p class="description">
                        <?php
                        printf(
                            /* translators: %s is a human readable time difference. */
                            esc_html__('Next scheduled action in %s', 'context-alt-text'),
                            esc_html((string) $automation['next_run'])
                        );
                        ?>
                    </p>
                <?php endif; ?>
            </article>
        </section>
        <?php
    }

    /**
     * @param array<int,array<string,string>> $actions
     */
    private function renderFooter(array $actions, string $statusText): void
    {
        ?>
        <footer class="context-alt-text-dashboard-footer">
            <div class="context-alt-text-footer-actions">
                <?php foreach ($actions as $action) : ?>
                    <a class="button"
                        href="<?php echo esc_url((string) ($action['url'] ?? '#')); ?>">
                        <?php echo esc_html((string) ($action['label'] ?? '')); ?>
                    </a>
                <?php endforeach; ?>
            </div>
            <p class="description context-alt-text-footer-status">
                <?php echo esc_html($statusText); ?>
            </p>
        </footer>
        <?php
    }

    private function formatTimeago($timestamp): string
    {
        if ($timestamp instanceof \DateTimeInterface) {
            $diff = human_time_diff($timestamp->getTimestamp(), time());
            return sprintf(/* translators: %s is a human readable time difference. */ __('%s ago', 'context-alt-text'), $diff);
        }

        if (is_int($timestamp) && $timestamp > 0) {
            $diff = human_time_diff($timestamp, time());
            return sprintf(/* translators: %s is a human readable time difference. */ __('%s ago', 'context-alt-text'), $diff);
        }

        if (is_string($timestamp) && $timestamp !== '') {
            return $timestamp;
        }

        return __('No recent activity', 'context-alt-text');
    }
}
