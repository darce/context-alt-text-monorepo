<?php

declare(strict_types=1);

namespace AltContext\Media;

use function ord;
use function pack;
use function str_starts_with;
use function strlen;
use function substr;
use function unpack;

class JpegXmpInjector {
	private const XMP_HEADER = "http://ns.adobe.com/xap/1.0/\x00";

	public function extract_packet( string $jpeg_binary ): ?string {
		if ( ! $this->is_jpeg_binary( $jpeg_binary ) ) {
			return null;
		}

		$offset = 2;
		$total_length = strlen( $jpeg_binary );

		while ( $offset + 4 <= $total_length ) {
			if ( "\xFF" !== $jpeg_binary[ $offset ] ) {
				break;
			}

			$marker = ord( $jpeg_binary[ $offset + 1 ] );
			if ( 0xDA === $marker || 0xD9 === $marker ) {
				break;
			}

			if ( $this->is_standalone_marker( $marker ) ) {
				$offset += 2;
				continue;
			}

			$segment_length = $this->read_segment_length( $jpeg_binary, $offset + 2 );
			if ( $segment_length < 2 ) {
				break;
			}

			$segment_total_length = 2 + $segment_length;
			if ( $offset + $segment_total_length > $total_length ) {
				break;
			}

			$segment_payload = substr( $jpeg_binary, $offset + 4, $segment_length - 2 );
			if ( 0xE1 === $marker && str_starts_with( $segment_payload, self::XMP_HEADER ) ) {
				return substr( $segment_payload, strlen( self::XMP_HEADER ) );
			}

			$offset += $segment_total_length;
		}

		return null;
	}

	public function inject_packet( string $jpeg_binary, string $xmp_packet ): string {
		if ( ! $this->is_jpeg_binary( $jpeg_binary ) ) {
			return $jpeg_binary;
		}

		$xmp_segment = $this->build_xmp_app1_segment( $xmp_packet );
		if ( '' === $xmp_segment ) {
			return $jpeg_binary;
		}

		$offset = 2;
		$insertion_offset = 2;
		$total_length = strlen( $jpeg_binary );

		while ( $offset + 4 <= $total_length ) {
			if ( "\xFF" !== $jpeg_binary[ $offset ] ) {
				break;
			}

			$marker = ord( $jpeg_binary[ $offset + 1 ] );
			if ( 0xDA === $marker || 0xD9 === $marker ) {
				break;
			}

			if ( $this->is_standalone_marker( $marker ) ) {
				$offset += 2;
				continue;
			}

			$segment_length = $this->read_segment_length( $jpeg_binary, $offset + 2 );
			if ( $segment_length < 2 ) {
				break;
			}

			$segment_total_length = 2 + $segment_length;
			if ( $offset + $segment_total_length > $total_length ) {
				break;
			}

			$segment_payload = substr( $jpeg_binary, $offset + 4, $segment_length - 2 );
			if ( 0xE1 === $marker && str_starts_with( $segment_payload, self::XMP_HEADER ) ) {
				return substr( $jpeg_binary, 0, $offset ) . $xmp_segment . substr( $jpeg_binary, $offset + $segment_total_length );
			}

			if ( 0xE0 === $marker && $offset === $insertion_offset ) {
				$insertion_offset = $offset + $segment_total_length;
			}

			$offset += $segment_total_length;
		}

		return substr( $jpeg_binary, 0, $insertion_offset ) . $xmp_segment . substr( $jpeg_binary, $insertion_offset );
	}

	private function is_jpeg_binary( string $jpeg_binary ): bool {
		return strlen( $jpeg_binary ) >= 4
			&& "\xFF\xD8" === substr( $jpeg_binary, 0, 2 )
			&& "\xFF\xD9" === substr( $jpeg_binary, -2 );
	}

	private function is_standalone_marker( int $marker ): bool {
		return ( $marker >= 0xD0 && $marker <= 0xD7 ) || 0x01 === $marker;
	}

	private function read_segment_length( string $jpeg_binary, int $offset ): int {
		$bytes = substr( $jpeg_binary, $offset, 2 );
		if ( strlen( $bytes ) < 2 ) {
			return 0;
		}

		$unpacked = unpack( 'nlength', $bytes );
		return (int) ( $unpacked['length'] ?? 0 );
	}

	private function build_xmp_app1_segment( string $xmp_packet ): string {
		$payload = self::XMP_HEADER . $xmp_packet;
		$segment_length = strlen( $payload ) + 2;
		if ( $segment_length > 0xFFFF ) {
			return '';
		}

		return "\xFF\xE1" . pack( 'n', $segment_length ) . $payload;
	}
}
