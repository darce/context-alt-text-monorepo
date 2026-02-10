<?php

declare(strict_types=1);

namespace AltContext\Cli;

use AltContext\Media\AttachmentXmpMetricsPersistor;
use AltContext\Media\XmpPersistenceFactory;

use function absint;
use function array_unique;
use function array_values;
use function class_exists;
use function count;
use function function_exists;
use function get_posts;
use function in_array;
use function is_array;
use function is_numeric;
use function sprintf;

class XmpBackfillCommand extends \WP_CLI_Command {
	private AttachmentXmpMetricsPersistor $persistor;

	public function __construct( ?AttachmentXmpMetricsPersistor $persistor = null ) {
		$this->persistor = $persistor ?? XmpPersistenceFactory::create_attachment_xmp_metrics_persistor();
	}

	/**
	 * Backfill face XMP metrics for existing attachments.
	 *
	 * ## OPTIONS
	 *
	 * [<media-id>...]
	 * : One or more attachment IDs.
	 *
	 * [--all]
	 * : Backfill all image attachments.
	 *
	 * [--limit=<number>]
	 * : Maximum number of image attachments to process with --all.
	 *
	 * ## EXAMPLES
	 *
	 *     wp acx xmp-backfill 101 102 103
	 *     wp acx xmp-backfill --all --limit=250
	 *
	 * @param string[] $args
	 * @param array<string,mixed> $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! class_exists( '\\WP_CLI' ) ) {
			return;
		}

		$all = isset( $assoc_args['all'] ) && in_array( (string) $assoc_args['all'], array( '1', 'true', 'yes', 'on' ), true );
		if ( isset( $assoc_args['all'] ) && true === $assoc_args['all'] ) {
			$all = true;
		}

		$media_ids = $this->normalize_media_ids( $args );

		if ( $all ) {
			$limit = $this->normalize_limit( $assoc_args['limit'] ?? null );
			$media_ids = array_values( array_unique( array_merge( $media_ids, $this->collect_all_image_attachment_ids( $limit ) ) ) );
		}

		if ( empty( $media_ids ) ) {
			\WP_CLI::error( 'No media IDs provided. Pass IDs directly or use --all.' );
			return;
		}

		\WP_CLI::log( sprintf( 'Embedding XMP metrics for %d attachments...', count( $media_ids ) ) );
		$summary = $this->persistor->embed_for_media_ids( $media_ids );

		\WP_CLI::success(
			sprintf(
				'XMP backfill complete. processed=%d skipped=%d failed=%d',
				(int) ( $summary['processed'] ?? 0 ),
				(int) ( $summary['skipped'] ?? 0 ),
				(int) ( $summary['failed'] ?? 0 )
			)
		);
	}

	/**
	 * @param string[] $args
	 * @return int[]
	 */
	private function normalize_media_ids( array $args ): array {
		$media_ids = array();
		foreach ( $args as $arg ) {
			if ( ! is_numeric( $arg ) ) {
				continue;
			}

			$media_id = absint( $arg );
			if ( $media_id > 0 ) {
				$media_ids[] = $media_id;
			}
		}

		return array_values( array_unique( $media_ids ) );
	}

	/**
	 * @return int[]
	 */
	private function collect_all_image_attachment_ids( int $limit ): array {
		if ( ! function_exists( 'get_posts' ) ) {
			return array();
		}

		$ids = get_posts(
			array(
				'post_type'      => 'attachment',
				'post_status'    => 'inherit',
				'post_mime_type' => 'image',
				'fields'         => 'ids',
				'posts_per_page' => $limit,
				'orderby'        => 'ID',
				'order'          => 'ASC',
			)
		);

		if ( ! is_array( $ids ) ) {
			return array();
		}

		$media_ids = array();
		foreach ( $ids as $id ) {
			$media_id = absint( $id );
			if ( $media_id > 0 ) {
				$media_ids[] = $media_id;
			}
		}

		return array_values( array_unique( $media_ids ) );
	}

	/**
	 * @param mixed $value
	 */
	private function normalize_limit( $value ): int {
		$limit = absint( $value );
		if ( $limit <= 0 ) {
			return -1;
		}

		return $limit;
	}
}
