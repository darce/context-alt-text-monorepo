<?php

declare(strict_types=1);

namespace ContextAltText\Commands;

use ContextAltText\Infrastructure\Repositories\UnknownFaceRepository;
use WP_CLI;
use WP_CLI_Command;

/**
 * Manage unknown faces for assisted face identification.
 *
 * @package ContextAltText\Commands
 */
final class FacesCommand extends WP_CLI_Command
{
    private UnknownFaceRepository $repository;

    public function __construct(?UnknownFaceRepository $repository = null)
    {
        $this->repository = $repository ?? new UnknownFaceRepository();
    }

    /**
     * Clear all unknown faces from the database.
     *
     * ## OPTIONS
     *
     * [--yes]
     * : Skip confirmation prompt.
     *
     * ## EXAMPLES
     *
     *     # Clear unknown faces (with confirmation)
     *     $ wp cat-faces clear_unknown
     *
     *     # Clear unknown faces (skip confirmation)
     *     $ wp cat-faces clear_unknown --yes
     *
     * @when after_wp_load
     */
    public function clear_unknown($args, $assoc_args): void
    {
        global $wpdb;

        $tableName = $wpdb->prefix . 'cat_unknown_faces';

        // Get current count
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $count = $wpdb->get_var("SELECT COUNT(*) FROM {$tableName}");

        if ($count === null || (int) $count === 0) {
            WP_CLI::success('No unknown faces found.');
            return;
        }

        WP_CLI::line(sprintf('Found %d unknown face(s) in database.', $count));

        // Confirm deletion
        if (!isset($assoc_args['yes'])) {
            WP_CLI::confirm('Are you sure you want to delete all unknown faces?');
        }

        // Truncate table (faster than DELETE)
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching, WordPress.DB.DirectDatabaseQuery.SchemaChange
        $result = $wpdb->query("TRUNCATE TABLE {$tableName}");

        if ($result === false) {
            WP_CLI::error('Failed to clear unknown faces.');
            return;
        }

        WP_CLI::success(sprintf('Deleted %d unknown face(s).', $count));
    }

    /**
     * Show statistics about unknown faces.
     *
     * ## EXAMPLES
     *
     *     $ wp cat-faces stats
     *
     * @when after_wp_load
     */
    public function stats($args, $assoc_args): void
    {
        global $wpdb;

        $tableName = $wpdb->prefix . 'cat_unknown_faces';

        // Total faces
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $total = $wpdb->get_var("SELECT COUNT(*) FROM {$tableName}");

        // Faces with embeddings
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $withEmbeddings = $wpdb->get_var(
            "SELECT COUNT(*) FROM {$tableName} WHERE embedding_id IS NOT NULL"
        );

        // Faces with vectors
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $withVectors = $wpdb->get_var(
            "SELECT COUNT(*) FROM {$tableName} WHERE embedding_vector IS NOT NULL"
        );

        // Faces with cluster assignments
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $withClusters = $wpdb->get_var(
            "SELECT COUNT(*) FROM {$tableName} WHERE cluster_id IS NOT NULL"
        );

        // Faces with roster assignments (labeled)
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $withRoster = $wpdb->get_var(
            "SELECT COUNT(*) FROM {$tableName} WHERE roster_id IS NOT NULL"
        );

        // Unique attachments
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $uniqueAttachments = $wpdb->get_var(
            "SELECT COUNT(DISTINCT attachment_id) FROM {$tableName}"
        );

        // Unique clusters
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery.DirectQuery, WordPress.DB.DirectDatabaseQuery.NoCaching
        $uniqueClusters = $wpdb->get_var(
            "SELECT COUNT(DISTINCT cluster_id) FROM {$tableName} WHERE cluster_id IS NOT NULL"
        );

        WP_CLI::line('Unknown Faces Statistics:');
        WP_CLI::line('');
        WP_CLI::line(sprintf('  Total faces:           %d', $total ?: 0));
        WP_CLI::line(sprintf('  With embedding IDs:    %d (%.1f%%)', $withEmbeddings ?: 0, $total > 0 ? ($withEmbeddings / $total) * 100 : 0));
        WP_CLI::line(sprintf('  With embedding vectors: %d (%.1f%%)', $withVectors ?: 0, $total > 0 ? ($withVectors / $total) * 100 : 0));
        WP_CLI::line(sprintf('  Clustered:             %d (%.1f%%)', $withClusters ?: 0, $total > 0 ? ($withClusters / $total) * 100 : 0));
        WP_CLI::line(sprintf('  Labeled:               %d (%.1f%%)', $withRoster ?: 0, $total > 0 ? ($withRoster / $total) * 100 : 0));
        WP_CLI::line('');
        WP_CLI::line(sprintf('  Unique attachments:    %d', $uniqueAttachments ?: 0));
        WP_CLI::line(sprintf('  Unique clusters:       %d', $uniqueClusters ?: 0));

        if ($uniqueClusters > 0 && $total > 0) {
            $avgFacesPerCluster = $total / $uniqueClusters;
            WP_CLI::line(sprintf('  Avg faces per cluster: %.1f', $avgFacesPerCluster));
        }
    }
}
