<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

require_once __DIR__ . '/../../src/api/class-recognition-api-key-store.php';

use AltContext\Api\RecognitionApiKeyStore;
use AltContext\Tests\TestCase;

/**
 * @covers \AltContext\Api\RecognitionApiKeyStore
 */
class RecognitionApiKeyStoreTest extends TestCase {
	public function testEncryptRoundTripsAndStoresAnEncryptedValue(): void {
		$plaintext = '  sk-test-key-abcdef123456  ';
		$stored    = RecognitionApiKeyStore::encrypt( $plaintext );

		$this->assertTrue( RecognitionApiKeyStore::is_available() );
		$this->assertSame( RecognitionApiKeyStore::PREFIX, substr( $stored, 0, strlen( RecognitionApiKeyStore::PREFIX ) ) );
		$this->assertStringNotContainsString( $plaintext, $stored );

		$this->setOption( RecognitionApiKeyStore::OPTION_NAME, $stored );
		$this->assertSame( $plaintext, RecognitionApiKeyStore::decrypt( get_option( RecognitionApiKeyStore::OPTION_NAME ) ) );
	}

	public function testEncryptUsesANewNonceForEachEncryption(): void {
		$plaintext = 'same-recognition-key';
		$first     = RecognitionApiKeyStore::encrypt( $plaintext );
		$second    = RecognitionApiKeyStore::encrypt( $plaintext );

		$this->assertNotSame( $first, $second );
		$this->assertSame( $plaintext, RecognitionApiKeyStore::decrypt( $first ) );
		$this->assertSame( $plaintext, RecognitionApiKeyStore::decrypt( $second ) );
	}

	public function testDecryptReturnsNullForMalformedAndUnauthenticatedValues(): void {
		$encrypted = RecognitionApiKeyStore::encrypt( 'valid-recognition-key' );
		$payload   = base64_decode( substr( $encrypted, strlen( RecognitionApiKeyStore::PREFIX ) ), true );
		$last_byte = strlen( $payload ) - 1;
		$payload[ $last_byte ] = chr( ord( $payload[ $last_byte ] ) ^ 1 );

		$invalid_values = array(
			null,
			42,
			'',
			'legacy-plaintext-key',
			'acxenc:v2:' . substr( $encrypted, strlen( RecognitionApiKeyStore::PREFIX ) ),
			RecognitionApiKeyStore::PREFIX . '%%%not-base64%%%',
			RecognitionApiKeyStore::PREFIX . base64_encode(
				str_repeat( 'x', SODIUM_CRYPTO_SECRETBOX_NONCEBYTES + SODIUM_CRYPTO_SECRETBOX_MACBYTES - 1 )
			),
			RecognitionApiKeyStore::PREFIX . base64_encode( $payload ),
		);

		foreach ( $invalid_values as $stored ) {
			$this->assertNull( RecognitionApiKeyStore::decrypt( $stored ) );
		}
	}

	public function testDecryptReturnsNullWhenTheAuthSaltChanges(): void {
		$encrypted          = RecognitionApiKeyStore::encrypt( 'salt-bound-recognition-key' );
		$had_salt_overrides = isset( $GLOBALS['__ac_wp_salt'] ) && is_array( $GLOBALS['__ac_wp_salt'] );
		$previous_overrides = $had_salt_overrides ? $GLOBALS['__ac_wp_salt'] : null;

		try {
			if ( ! isset( $GLOBALS['__ac_wp_salt'] ) || ! is_array( $GLOBALS['__ac_wp_salt'] ) ) {
				$GLOBALS['__ac_wp_salt'] = array();
			}
			$GLOBALS['__ac_wp_salt']['auth'] = 'changed-test-auth-salt';

			$this->assertNull( RecognitionApiKeyStore::decrypt( $encrypted ) );
		} finally {
			if ( $had_salt_overrides ) {
				$GLOBALS['__ac_wp_salt'] = $previous_overrides;
			} else {
				unset( $GLOBALS['__ac_wp_salt'] );
			}
		}
	}

	public function testEncryptRejectsAnEmptyKey(): void {
		$this->expectException( \RuntimeException::class );
		RecognitionApiKeyStore::encrypt( '' );
	}

	public function testEncryptRejectsAWhitespaceOnlyKey(): void {
		$this->expectException( \RuntimeException::class );
		RecognitionApiKeyStore::encrypt( ' ' );
	}
}
