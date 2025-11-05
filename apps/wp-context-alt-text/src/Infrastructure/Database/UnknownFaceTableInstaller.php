<?php

declare(strict_types=1);

namespace ContextAltText\Infrastructure\Database;

/**
 * Installs the unknown faces table used during assisted face identification.
 */
class UnknownFaceTableInstaller
{
    /** @var \wpdb */
    private $wpdb;

    /**
     * @param \wpdb|null $database Optional WordPress database instance.
     */
    public function __construct($database = null)
    {
        if ($database === null) {
            global $wpdb;
            $database = $wpdb;
        }

        $this->wpdb = $database;
    }

    public function install(): void
    {
        $table = $this->wpdb->prefix . 'cat_unknown_faces';
        $charset = method_exists($this->wpdb, 'get_charset_collate')
            ? $this->wpdb->get_charset_collate()
            : 'DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci';

        $sql = "CREATE TABLE IF NOT EXISTS {$table} (
            id BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
            attachment_id BIGINT(20) UNSIGNED NOT NULL,
            bbox_json LONGTEXT NOT NULL,
            embedding_id VARCHAR(255) NULL,
            embedding_vector MEDIUMTEXT NULL COMMENT '512-dim embedding as JSON array',
            thumbnail MEDIUMTEXT NULL COMMENT 'Base64-encoded face thumbnail from recognition service',
            cluster_id VARCHAR(255) NULL,
            detected_at DATETIME NOT NULL,
            resolved_at DATETIME NULL,
            roster_id VARCHAR(255) NULL,
            PRIMARY KEY  (id),
            KEY attachment_id (attachment_id),
            KEY cluster_id (cluster_id),
            KEY resolved_at (resolved_at)
        ) {$charset};";

        $this->wpdb->query($sql);
        
        // Add embedding_vector column if it doesn't exist (migration for existing tables)
        $this->addEmbeddingVectorColumn($table);
        
        // Add thumbnail column if it doesn't exist (migration for existing tables)
        $this->addThumbnailColumn($table);
    }

    /**
     * Add embedding_vector column to existing tables that don't have it.
     */
    private function addEmbeddingVectorColumn(string $table): void
    {
        // Check if column exists
        $column = $this->wpdb->get_results(
            $this->wpdb->prepare(
                "SHOW COLUMNS FROM {$table} LIKE %s",
                'embedding_vector'
            )
        );

        // Add column if it doesn't exist
        if (empty($column)) {
            $sql = "ALTER TABLE {$table} ADD COLUMN embedding_vector MEDIUMTEXT NULL COMMENT '512-dim embedding as JSON array' AFTER embedding_id";
            $this->wpdb->query($sql);
        }
    }

    /**
     * Add thumbnail column to existing tables that don't have it.
     */
    private function addThumbnailColumn(string $table): void
    {
        // Check if column exists
        $column = $this->wpdb->get_results(
            $this->wpdb->prepare(
                "SHOW COLUMNS FROM {$table} LIKE %s",
                'thumbnail'
            )
        );

        // Add column if it doesn't exist
        if (empty($column)) {
            $sql = "ALTER TABLE {$table} ADD COLUMN thumbnail MEDIUMTEXT NULL COMMENT 'Base64-encoded face thumbnail from recognition service' AFTER embedding_vector";
            $this->wpdb->query($sql);
        }
    }
}
