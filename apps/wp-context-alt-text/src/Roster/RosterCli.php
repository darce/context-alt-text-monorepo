<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use ContextAltText\Domain\Roster\RosterService;
use ContextAltText\Roster\RosterTaxonomy;
use WP_CLI;
use WP_CLI_Command;
use function sprintf;
use function get_option;
use function delete_option;
use function is_array;
use function get_terms;
use function wp_delete_term;

class RosterCli extends WP_CLI_Command
{
    private RosterService $service;
    private RosterTaxonomy $taxonomy;

    public function __construct(RosterService $service, RosterTaxonomy $taxonomy)
    {
        $this->service = $service;
        $this->taxonomy = $taxonomy;
    }

    /**
     * Display roster sync status metrics.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster status
     */
    public function status(array $args, array $assocArgs): void
    {
        unset($args, $assocArgs);

        $state = get_option('cat_roster_sync_state');

        if (!is_array($state)) {
            $state = [
                'lastSyncAt' => null,
                'created' => 0,
                'updated' => 0,
                'deleted' => 0,
                'errors' => 0,
                'conflicts' => 0,
            ];
        }

        WP_CLI::log('Roster Sync Metrics:');
        WP_CLI::log(sprintf('  Last Sync: %s', $state['lastSyncAt'] ?? 'never'));
        WP_CLI::log(sprintf('  Created: %d', (int) ($state['created'] ?? 0)));
        WP_CLI::log(sprintf('  Updated: %d', (int) ($state['updated'] ?? 0)));
        WP_CLI::log(sprintf('  Deleted: %d', (int) ($state['deleted'] ?? 0)));
        WP_CLI::log(sprintf('  Conflicts: %d', (int) ($state['conflicts'] ?? 0)));
        WP_CLI::log(sprintf('  Errors: %d', (int) ($state['errors'] ?? 0)));

        if (isset($state['lastError']) && is_array($state['lastError'])) {
            WP_CLI::log(sprintf('  Last Error: %s', $state['lastError']['message'] ?? 'Unknown'));
        }

        WP_CLI::success('Roster status fetched.');
    }

    /**
     * Trigger a roster sync from the remote service.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster sync
     */
    public function sync(array $args, array $assocArgs): void
    {
        unset($args, $assocArgs);

        $result = $this->service->syncFromRemote();

        if ($result) {
            WP_CLI::success('Roster sync completed.');
        } else {
            WP_CLI::warning('Roster sync did not report any changes.');
        }
    }

    /**
     * Migrate legacy post tags with cat_roster_ or cat-recognition- prefixes into the dedicated roster taxonomy.
     *
     * ## OPTIONS
     *
     * [--keep-legacy]
     * : Retain the legacy post_tag assignments after migration.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster migrate-tags
     *     wp cat-roster migrate-tags --keep-legacy
     */
    public function migrate_tags(array $args, array $assocArgs): void
    {
        unset($args);

        $keepLegacy = isset($assocArgs['keep-legacy']);
        WP_CLI::log('Migrating roster tags to cat_roster_entity taxonomy...');
        $results = $this->taxonomy->migrateLegacyTags($keepLegacy);

        WP_CLI::log(sprintf('  Processed terms: %d', $results['processed_terms']));
        WP_CLI::log(sprintf('  Created terms: %d', $results['created_terms']));
        WP_CLI::log(sprintf('  Updated terms: %d', $results['updated_terms']));
        WP_CLI::log(sprintf('  Migrated relationships: %d', $results['migrated_relationships']));
        WP_CLI::log(sprintf('  Skipped terms: %d', $results['skipped_terms']));

        if ($keepLegacy) {
            WP_CLI::log('  Legacy post_tag assignments retained.');
        } else {
            WP_CLI::log(sprintf('  Legacy relationships removed: %d', $results['removed_legacy']));
        }

        WP_CLI::success('Roster tag migration completed.');
    }

    /**
     * Repair taxonomy assignments for attachments with matched observations.
     *
     * Re-syncs roster entity taxonomy terms for all attachments that have
     * recognition observations with matched status. Useful after bug fixes
     * or to retroactively apply taxonomy to previously processed images.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster repair-taxonomy
     */
    public function repair_taxonomy(array $args, array $assocArgs): void
    {
        unset($args, $assocArgs);

        if (!function_exists('get_post_meta') || !function_exists('update_post_meta')) {
            WP_CLI::error('Required WordPress functions are not available.');
            return;
        }

        WP_CLI::log('Repairing roster entity taxonomy assignments...');

        global $wpdb;
        $metaKey = '_cat_recognition_observations';

        // Get all attachments with recognition observations
        $results = $wpdb->get_results($wpdb->prepare(
            "SELECT post_id FROM {$wpdb->postmeta} WHERE meta_key = %s",
            $metaKey
        ));

        if (empty($results)) {
            WP_CLI::warning('No attachments with recognition observations found.');
            return;
        }

        $processed = 0;
        $fixed = 0;
        $skipped = 0;

        foreach ($results as $row) {
            $attachmentId = (int) $row->post_id;
            $processed++;

            $record = get_post_meta($attachmentId, $metaKey, true);

            if (!is_array($record) || !isset($record['observations'])) {
                $skipped++;
                continue;
            }

            $observations = is_array($record['observations']) ? $record['observations'] : [];
            $hasMatched = false;

            foreach ($observations as $obs) {
                if (is_array($obs) && ($obs['status'] ?? '') === 'matched') {
                    $hasMatched = true;
                    break;
                }
            }

            if (!$hasMatched) {
                $skipped++;
                continue;
            }

            // Re-save to trigger taxonomy sync
            update_post_meta($attachmentId, $metaKey, $record);
            $fixed++;

            if ($fixed % 10 === 0) {
                WP_CLI::log(sprintf('  Processed %d attachments, fixed %d...', $processed, $fixed));
            }
        }

        WP_CLI::log(sprintf('  Total processed: %d', $processed));
        WP_CLI::log(sprintf('  Taxonomy fixed: %d', $fixed));
        WP_CLI::log(sprintf('  Skipped (no matches): %d', $skipped));
        WP_CLI::success('Taxonomy repair complete.');
    }

    /**
     * Nuclear reset: Delete all recognition and roster data (development only).
     *
     * WARNING: This is a destructive operation that:
     * - Deletes all roster entries (local and remote)
     * - Removes all recognition observations from attachments
     * - Deletes all roster taxonomy terms
     * - Clears sync state and indexes
     * - Archives existing roster entries
     *
     * Use this command only in development when you need a clean slate.
     *
     * ## OPTIONS
     *
     * [--yes]
     * : Skip confirmation prompt.
     *
     * [--keep-remote]
     * : Only clean local WordPress data, preserve remote backend roster.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster nuclear-reset
     *     wp cat-roster nuclear-reset --yes
     *     wp cat-roster nuclear-reset --yes --keep-remote
     */
    public function nuclear_reset(array $args, array $assocArgs): void
    {
        unset($args);

        $skipConfirmation = isset($assocArgs['yes']);
        $keepRemote = isset($assocArgs['keep-remote']);

        if (!$skipConfirmation) {
            WP_CLI::warning('This will DELETE ALL recognition and roster data!');
            WP_CLI::error('Add --yes flag to confirm this destructive operation.');
            return;
        }

        WP_CLI::log('Starting nuclear reset...');

        $stats = [
            'roster_entries_deleted' => 0,
            'remote_entries_deleted' => 0,
            'observations_removed' => 0,
            'taxonomy_terms_deleted' => 0,
            'options_cleared' => 0,
        ];

        // Step 1: Delete remote roster entries (unless --keep-remote)
        if (!$keepRemote) {
            WP_CLI::log('Deleting remote roster entries...');
            $entries = get_option('cat_roster_entries', []);

            if (is_array($entries) && !empty($entries)) {
                foreach ($entries as $remoteId => $entry) {
                    try {
                        $this->service->deleteAndArchive((string) $remoteId);
                        $stats['remote_entries_deleted']++;
                        $stats['roster_entries_deleted']++;
                    } catch (\Exception $e) {
                        WP_CLI::warning(sprintf('Failed to delete remote entry %s: %s', $remoteId, $e->getMessage()));
                    }
                }
                WP_CLI::log(sprintf('  Deleted %d remote roster entries', $stats['remote_entries_deleted']));
            } else {
                WP_CLI::log('  No remote roster entries found');
            }
        }

        // Step 2: Clear WordPress options
        WP_CLI::log('Clearing WordPress options...');
        $optionsToDelete = [
            'cat_roster_entries',
            'cat_roster_entries_archived',
            'cat_roster_sync_state',
            'cat_recognition_observation_index',
            'cat_recognition_retry_log',
        ];

        foreach ($optionsToDelete as $option) {
            if (delete_option($option)) {
                $stats['options_cleared']++;
            }
        }
        WP_CLI::log(sprintf('  Cleared %d WordPress options', $stats['options_cleared']));

        // Step 3: Remove all recognition observations from attachments
        WP_CLI::log('Removing recognition observations from attachments...');
        global $wpdb;

        $metaKeys = [
            '_cat_recognition_observations',
            '_cat_recognition_roster_ids',
            '_context_alt_text_recognition_observations',
        ];

        foreach ($metaKeys as $metaKey) {
            $deleted = $wpdb->query($wpdb->prepare(
                "DELETE FROM {$wpdb->postmeta} WHERE meta_key = %s",
                $metaKey
            ));

            if ($deleted !== false) {
                $stats['observations_removed'] += (int) $deleted;
            }
        }
        WP_CLI::log(sprintf('  Removed %d observation meta entries', $stats['observations_removed']));

        // Step 4: Delete all roster taxonomy terms and relationships
        WP_CLI::log('Deleting roster taxonomy terms...');
        $taxonomy = RosterTaxonomy::TAXONOMY;

        if (!function_exists('get_terms') || !function_exists('wp_delete_term')) {
            WP_CLI::warning('WordPress taxonomy functions not available, skipping taxonomy cleanup');
        } else {
            $terms = get_terms([
                'taxonomy' => $taxonomy,
                'hide_empty' => false,
                'fields' => 'ids',
            ]);

            if (is_array($terms) && !empty($terms)) {
                foreach ($terms as $termId) {
                    if (wp_delete_term((int) $termId, $taxonomy)) {
                        $stats['taxonomy_terms_deleted']++;
                    }
                }
                WP_CLI::log(sprintf('  Deleted %d taxonomy terms', $stats['taxonomy_terms_deleted']));
            } else {
                WP_CLI::log('  No taxonomy terms found');
            }
        }

        // Step 5: Clear orphaned taxonomy relationships (belt and suspenders)
        WP_CLI::log('Cleaning orphaned taxonomy relationships...');
        $orphanedRelationships = $wpdb->query($wpdb->prepare(
            "DELETE tr FROM {$wpdb->term_relationships} tr
             WHERE tr.term_taxonomy_id IN (
                 SELECT tt.term_taxonomy_id 
                 FROM {$wpdb->term_taxonomy} tt 
                 WHERE tt.taxonomy = %s
             )",
            $taxonomy
        ));

        if ($orphanedRelationships !== false && $orphanedRelationships > 0) {
            WP_CLI::log(sprintf('  Removed %d orphaned relationships', $orphanedRelationships));
        }

        // Summary
        WP_CLI::log('');
        WP_CLI::log('Nuclear reset completed:');
        WP_CLI::log(sprintf('  Roster entries deleted: %d', $stats['roster_entries_deleted']));
        if (!$keepRemote) {
            WP_CLI::log(sprintf('  Remote entries deleted: %d', $stats['remote_entries_deleted']));
        } else {
            WP_CLI::log('  Remote entries preserved (--keep-remote)');
        }
        WP_CLI::log(sprintf('  Observation meta entries removed: %d', $stats['observations_removed']));
        WP_CLI::log(sprintf('  Taxonomy terms deleted: %d', $stats['taxonomy_terms_deleted']));
        WP_CLI::log(sprintf('  WordPress options cleared: %d', $stats['options_cleared']));

        WP_CLI::success('All recognition and roster data has been deleted. You can now start fresh.');
    }
}
