<?php

declare(strict_types=1);

namespace AltContext\Media;

use DOMDocument;
use DOMElement;

use function is_array;
use function is_numeric;
use function rtrim;
use function sprintf;
use function trim;

class XmpImageRegionPacketBuilder {
	public const XMP_NS = 'adobe:ns:meta/';
	public const RDF_NS = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#';
	public const IPTC_NS = 'http://iptc.org/std/Iptc4xmpExt/2008-02-29/';
	public const ACX_NS = 'http://alt-context.dev/ns/1.0/';

	/**
	 * @param array<int,array<string,mixed>> $regions
	 */
	public function build_packet( array $regions, ?string $existing_packet = null ): string {
		$document = $this->load_or_create_document( $existing_packet );
		$description = $this->get_or_create_description_node( $document );

		$description->setAttribute( 'xmlns:Iptc4xmpExt', self::IPTC_NS );
		$description->setAttribute( 'xmlns:acx', self::ACX_NS );

		$this->remove_existing_image_region_nodes( $description );
		$this->append_image_regions( $document, $description, $regions );

		$xml = $document->saveXML( $document->documentElement );
		return false === $xml ? '' : $xml;
	}

	private function load_or_create_document( ?string $existing_packet ): DOMDocument {
		if ( is_string( $existing_packet ) && '' !== trim( $existing_packet ) ) {
			$document = new DOMDocument( '1.0', 'UTF-8' );
			$document->formatOutput = false;

			if ( @ $document->loadXML( $existing_packet, LIBXML_NONET ) ) {
				$root = $document->documentElement;
				if ( $root instanceof DOMElement ) {
					return $document;
				}
			}
		}

		return $this->create_base_document();
	}

	private function create_base_document(): DOMDocument {
		$document = new DOMDocument( '1.0', 'UTF-8' );
		$document->formatOutput = false;

		$xmpmeta = $document->createElementNS( self::XMP_NS, 'x:xmpmeta' );
		$rdf = $document->createElementNS( self::RDF_NS, 'rdf:RDF' );
		$description = $document->createElementNS( self::RDF_NS, 'rdf:Description' );
		$description->setAttribute( 'xmlns:Iptc4xmpExt', self::IPTC_NS );
		$description->setAttribute( 'xmlns:acx', self::ACX_NS );

		$rdf->appendChild( $description );
		$xmpmeta->appendChild( $rdf );
		$document->appendChild( $xmpmeta );

		return $document;
	}

	private function get_or_create_description_node( DOMDocument $document ): DOMElement {
		$descriptions = $document->getElementsByTagNameNS( self::RDF_NS, 'Description' );
		if ( $descriptions->length > 0 ) {
			$description = $descriptions->item( 0 );
			if ( $description instanceof DOMElement ) {
				return $description;
			}
		}

		$root = $document->documentElement;
		if ( ! ( $root instanceof DOMElement ) ) {
			$xmpmeta = $document->createElementNS( self::XMP_NS, 'x:xmpmeta' );
			$rdf = $document->createElementNS( self::RDF_NS, 'rdf:RDF' );
			$description = $document->createElementNS( self::RDF_NS, 'rdf:Description' );
			$rdf->appendChild( $description );
			$xmpmeta->appendChild( $rdf );
			$document->appendChild( $xmpmeta );
			return $description;
		}

		$rdf = $document->createElementNS( self::RDF_NS, 'rdf:RDF' );
		$description = $document->createElementNS( self::RDF_NS, 'rdf:Description' );
		$rdf->appendChild( $description );
		$root->appendChild( $rdf );

		return $description;
	}

	private function remove_existing_image_region_nodes( DOMElement $description ): void {
		$to_remove = array();

		foreach ( $description->childNodes as $child ) {
			if ( ! ( $child instanceof DOMElement ) ) {
				continue;
			}

			if ( self::IPTC_NS === (string) $child->namespaceURI && 'ImageRegion' === (string) $child->localName ) {
				$to_remove[] = $child;
			}
		}

		foreach ( $to_remove as $child ) {
			$description->removeChild( $child );
		}
	}

	/**
	 * @param array<int,array<string,mixed>> $regions
	 */
	private function append_image_regions( DOMDocument $document, DOMElement $description, array $regions ): void {
		if ( empty( $regions ) ) {
			return;
		}

		$image_region = $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:ImageRegion' );
		$bag = $document->createElementNS( self::RDF_NS, 'rdf:Bag' );

		foreach ( $regions as $region ) {
			if ( ! is_array( $region ) ) {
				continue;
			}

			$name = trim( (string) ( $region['name'] ?? '' ) );
			if ( '' === $name ) {
				continue;
			}

			$li = $document->createElementNS( self::RDF_NS, 'rdf:li' );
			$region_boundary = $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:RegionBoundary' );
			$region_boundary->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:rbShape', 'rectangle' ) );
			$region_boundary->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:rbX', $this->format_decimal( $region['rbX'] ?? 0 ) ) );
			$region_boundary->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:rbY', $this->format_decimal( $region['rbY'] ?? 0 ) ) );
			$region_boundary->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:rbW', $this->format_decimal( $region['rbW'] ?? 0 ) ) );
			$region_boundary->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:rbH', $this->format_decimal( $region['rbH'] ?? 0 ) ) );
			$region_boundary->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:rbUnit', 'relative' ) );
			$li->appendChild( $region_boundary );

			$li->appendChild( $document->createElementNS( self::IPTC_NS, 'Iptc4xmpExt:Name', $name ) );

			$this->append_optional_metric( $document, $li, 'acx:Pitch', $region['acx_pitch'] ?? null );
			$this->append_optional_metric( $document, $li, 'acx:Yaw', $region['acx_yaw'] ?? null );
			$this->append_optional_metric( $document, $li, 'acx:Roll', $region['acx_roll'] ?? null );
			$this->append_optional_metric( $document, $li, 'acx:DetScore', $region['acx_det_score'] ?? null );
			$this->append_optional_metric( $document, $li, 'acx:LandmarkQuality', $region['acx_landmark_quality'] ?? null );

			$bag->appendChild( $li );
		}

		if ( ! $bag->hasChildNodes() ) {
			return;
		}

		$image_region->appendChild( $bag );
		$description->appendChild( $image_region );
	}

	/**
	 * @param mixed $value
	 */
	private function append_optional_metric( DOMDocument $document, DOMElement $parent, string $qualified_name, $value ): void {
		if ( ! is_numeric( $value ) ) {
			return;
		}

		$parent->appendChild( $document->createElementNS( self::ACX_NS, $qualified_name, $this->format_decimal( $value ) ) );
	}

	/**
	 * @param mixed $value
	 */
	private function format_decimal( $value ): string {
		$formatted = rtrim( rtrim( sprintf( '%.6F', (float) $value ), '0' ), '.' );
		if ( '' === $formatted || '-0' === $formatted ) {
			return '0';
		}

		return $formatted;
	}
}
