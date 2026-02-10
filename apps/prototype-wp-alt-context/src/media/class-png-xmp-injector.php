<?php

declare(strict_types=1);

namespace AltContext\Media;

use function crc32;
use function function_exists;
use function gzuncompress;
use function ord;
use function pack;
use function sprintf;
use function strlen;
use function strpos;
use function substr;
use function unpack;

class PngXmpInjector {
	private const PNG_SIGNATURE = "\x89PNG\r\n\x1A\n";
	private const XMP_KEYWORD = 'XML:com.adobe.xmp';

	public function extract_packet( string $png_binary ): ?string {
		if ( ! $this->is_png_binary( $png_binary ) ) {
			return null;
		}

		$offset = 8;
		$total_length = strlen( $png_binary );

		while ( $offset + 12 <= $total_length ) {
			$chunk_length = $this->read_chunk_length( $png_binary, $offset );
			$chunk_type = substr( $png_binary, $offset + 4, 4 );
			$data_offset = $offset + 8;
			$chunk_total_length = 12 + $chunk_length;

			if ( $offset + $chunk_total_length > $total_length ) {
				break;
			}

			$chunk_data = substr( $png_binary, $data_offset, $chunk_length );
			if ( 'iTXt' === $chunk_type ) {
				$xmp_text = $this->extract_xmp_itxt_text( $chunk_data );
				if ( null !== $xmp_text ) {
					return $xmp_text;
				}
			}

			if ( 'IEND' === $chunk_type ) {
				break;
			}

			$offset += $chunk_total_length;
		}

		return null;
	}

	public function inject_packet( string $png_binary, string $xmp_packet ): string {
		if ( ! $this->is_png_binary( $png_binary ) ) {
			return $png_binary;
		}

		$itxt_chunk = $this->build_xmp_itxt_chunk( $xmp_packet );
		if ( '' === $itxt_chunk ) {
			return $png_binary;
		}

		$offset = 8;
		$total_length = strlen( $png_binary );
		$insert_offset = $total_length;

		while ( $offset + 12 <= $total_length ) {
			$chunk_length = $this->read_chunk_length( $png_binary, $offset );
			$chunk_type = substr( $png_binary, $offset + 4, 4 );
			$data_offset = $offset + 8;
			$chunk_total_length = 12 + $chunk_length;

			if ( $offset + $chunk_total_length > $total_length ) {
				break;
			}

			$chunk_data = substr( $png_binary, $data_offset, $chunk_length );
			if ( 'iTXt' === $chunk_type && null !== $this->extract_xmp_itxt_text( $chunk_data ) ) {
				return substr( $png_binary, 0, $offset ) . $itxt_chunk . substr( $png_binary, $offset + $chunk_total_length );
			}

			if ( 'IEND' === $chunk_type ) {
				$insert_offset = $offset;
				break;
			}

			$offset += $chunk_total_length;
		}

		return substr( $png_binary, 0, $insert_offset ) . $itxt_chunk . substr( $png_binary, $insert_offset );
	}

	private function is_png_binary( string $png_binary ): bool {
		return strlen( $png_binary ) >= 12 && self::PNG_SIGNATURE === substr( $png_binary, 0, 8 );
	}

	private function read_chunk_length( string $png_binary, int $offset ): int {
		$bytes = substr( $png_binary, $offset, 4 );
		if ( strlen( $bytes ) < 4 ) {
			return 0;
		}

		$unpacked = unpack( 'Nlength', $bytes );
		return (int) ( $unpacked['length'] ?? 0 );
	}

	private function build_xmp_itxt_chunk( string $xmp_packet ): string {
		$itxt_payload = self::XMP_KEYWORD . "\0\x00\x00\0\0" . $xmp_packet;
		return $this->build_chunk( 'iTXt', $itxt_payload );
	}

	private function build_chunk( string $type, string $data ): string {
		$length = strlen( $data );
		$crc = (int) sprintf( '%u', crc32( $type . $data ) );

		return pack( 'N', $length ) . $type . $data . pack( 'N', $crc );
	}

	private function extract_xmp_itxt_text( string $chunk_data ): ?string {
		$keyword_end = strpos( $chunk_data, "\0" );
		if ( false === $keyword_end ) {
			return null;
		}

		$keyword = substr( $chunk_data, 0, $keyword_end );
		if ( self::XMP_KEYWORD !== $keyword ) {
			return null;
		}

		$cursor = $keyword_end + 1;
		if ( $cursor + 2 > strlen( $chunk_data ) ) {
			return null;
		}

		$compression_flag = ord( $chunk_data[ $cursor ] );
		$cursor += 2; // Compression flag + method.

		$language_end = strpos( $chunk_data, "\0", $cursor );
		if ( false === $language_end ) {
			return null;
		}
		$cursor = $language_end + 1;

		$translated_end = strpos( $chunk_data, "\0", $cursor );
		if ( false === $translated_end ) {
			return null;
		}
		$cursor = $translated_end + 1;

		$text = substr( $chunk_data, $cursor );
		if ( 1 === $compression_flag ) {
			if ( ! function_exists( 'gzuncompress' ) ) {
				return null;
			}

			$decompressed = @gzuncompress( $text );
			if ( false === $decompressed ) {
				return null;
			}

			return $decompressed;
		}

		return $text;
	}
}
