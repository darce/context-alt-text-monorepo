<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use WP_Term;
use function __;
use function _update_generic_term_count;
use function absint;
use function add_action;
use function get_objects_in_term;
use function get_post_type;
use function get_terms;
use function is_wp_error;
use function register_taxonomy;
use function register_taxonomy_for_object_type;
use function strpos;
use function term_exists;
use function taxonomy_exists;
use function wp_delete_term;
use function wp_insert_term;
use function wp_remove_object_terms;
use function wp_set_object_terms;
use function wp_update_term;

class RosterTaxonomy
{
    public const TAXONOMY = 'cat_roster_entity';
    public const LEGACY_TAXONOMY = 'post_tag';
    /**
     * @var array<int,string>
     */
    public const LEGACY_PREFIXES = ['cat_roster_', 'cat-recognition-'];

    public function init(): void
    {
        add_action('init', [$this, 'register'], 5);
    }

    public function register(): void
    {
        if (taxonomy_exists(self::TAXONOMY)) {
            return;
        }

        register_taxonomy(
            self::TAXONOMY,
            ['attachment'],
            [
                'labels' => [
                    'name' => __('Roster Entities', 'context-alt-text'),
                    'singular_name' => __('Roster Entity', 'context-alt-text'),
                    'search_items' => __('Search Roster Entities', 'context-alt-text'),
                    'all_items' => __('All Roster Entities', 'context-alt-text'),
                    'edit_item' => __('Edit Roster Entity', 'context-alt-text'),
                    'update_item' => __('Update Roster Entity', 'context-alt-text'),
                    'add_new_item' => __('Add New Roster Entity', 'context-alt-text'),
                    'new_item_name' => __('New Roster Entity Name', 'context-alt-text'),
                    'menu_name' => __('Roster Entities', 'context-alt-text'),
                ],
                'public' => false,
                'hierarchical' => false,
                'show_ui' => true,
                'show_in_menu' => true,
                'show_in_rest' => true,
                'rest_base' => 'cat-roster-entities',
                'show_admin_column' => true,
                'rewrite' => false,
                'query_var' => true,
                'show_tagcloud' => false,
                'update_count_callback' => '_update_generic_term_count',
                'capabilities' => [
                    'manage_terms' => 'manage_options',
                    'edit_terms' => 'manage_options',
                    'delete_terms' => 'manage_options',
                    'assign_terms' => 'upload_files',
                ],
            ]
        );

        register_taxonomy_for_object_type(self::TAXONOMY, 'attachment');
    }

    /**
     * @return array{processed_terms:int,created_terms:int,updated_terms:int,migrated_relationships:int,skipped_terms:int,removed_legacy:int,kept_legacy:bool}
     */
    public function migrateLegacyTags(bool $keepLegacy = false): array
    {
        if (!taxonomy_exists(self::TAXONOMY)) {
            $this->register();
        }

        $results = [
            'processed_terms' => 0,
            'created_terms' => 0,
            'updated_terms' => 0,
            'migrated_relationships' => 0,
            'skipped_terms' => 0,
            'removed_legacy' => 0,
            'kept_legacy' => $keepLegacy,
        ];

        $terms = get_terms([
            'taxonomy' => self::LEGACY_TAXONOMY,
            'hide_empty' => false,
            'number' => 0,
        ]);

        if (is_wp_error($terms) || empty($terms)) {
            return $results;
        }

        foreach ($terms as $term) {
            if (!$term instanceof WP_Term) {
                $results['skipped_terms']++;
                continue;
            }

            $hasLegacyPrefix = false;
            foreach (self::LEGACY_PREFIXES as $prefix) {
                if (strpos($term->slug, $prefix) === 0) {
                    $hasLegacyPrefix = true;
                    break;
                }
            }

            if (!$hasLegacyPrefix) {
                $results['skipped_terms']++;
                continue;
            }

            $results['processed_terms']++;

            $targetTermId = null;
            $existing = term_exists($term->slug, self::TAXONOMY);

            if (is_array($existing) && !empty($existing['term_id'])) {
                $targetTermId = absint($existing['term_id']);
            } elseif (is_int($existing)) {
                $targetTermId = absint($existing);
            }

            if ($targetTermId) {
                $updated = wp_update_term(
                    $targetTermId,
                    self::TAXONOMY,
                    [
                        'name' => $term->name !== '' ? $term->name : $term->slug,
                        'description' => $term->description ?? '',
                    ]
                );

                if (!is_wp_error($updated)) {
                    $results['updated_terms']++;
                }
            } else {
                $created = wp_insert_term(
                    $term->name !== '' ? $term->name : $term->slug,
                    self::TAXONOMY,
                    [
                        'slug' => $term->slug,
                        'description' => $term->description ?? '',
                    ]
                );

                if (is_wp_error($created)) {
                    $results['skipped_terms']++;
                    continue;
                }

                $targetTermId = absint($created['term_id'] ?? 0);
                if ($targetTermId <= 0) {
                    $results['skipped_terms']++;
                    continue;
                }

                $results['created_terms']++;
            }

            $objectIds = get_objects_in_term($term->term_id, self::LEGACY_TAXONOMY);

            if (is_wp_error($objectIds) || empty($objectIds)) {
                if (!$keepLegacy) {
                    wp_delete_term($term->term_id, self::LEGACY_TAXONOMY);
                }
                continue;
            }

            foreach ($objectIds as $objectId) {
                $objectId = absint($objectId);
                if ($objectId <= 0) {
                    continue;
                }

                if (get_post_type($objectId) !== 'attachment') {
                    continue;
                }

                $assignment = wp_set_object_terms($objectId, $targetTermId, self::TAXONOMY, true);

                if (is_wp_error($assignment)) {
                    continue;
                }

                $results['migrated_relationships']++;

                if (!$keepLegacy) {
                    $removed = wp_remove_object_terms($objectId, [$term->term_id], self::LEGACY_TAXONOMY);
                    if (!is_wp_error($removed)) {
                        $results['removed_legacy']++;
                    }
                }
            }

            if (!$keepLegacy) {
                wp_delete_term($term->term_id, self::LEGACY_TAXONOMY);
            }
        }

        return $results;
    }
}
