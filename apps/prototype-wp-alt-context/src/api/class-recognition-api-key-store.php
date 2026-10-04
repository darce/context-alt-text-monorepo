<?php

declare(strict_types=1);

namespace AltContext\Api;

/**
 * Encrypt and decrypt the recognition API key stored in the options table.
 */
final class RecognitionApiKeyStore {
	public const OPTION_NAME = 'acx_recognition_api_key';

	public const PREFIX = 'acxenc:v1:';

	/**
	 * Whether the sodium functions needed by this store are available.
	 */
	public static function is_available(): bool {
		return \function_exists( 'sodium_crypto_generichash' )
			&& \function_exists( 'sodium_crypto_secretbox' )
			&& \function_exists( 'sodium_crypto_secretbox_open' );
	}

	/**
	 * Encrypt a non-empty recognition API key for storage.
	 *
	 * @throws \RuntimeException When the key is empty or sodium is unavailable.
	 */
	public static function encrypt( string $plaintext ): string {
		if ( '' === trim( $plaintext ) ) {
			throw new \RuntimeException( 'The recognition API key must not be empty.' );
		}

		if ( ! self::is_available() ) {
			throw new \RuntimeException( 'Sodium is required to encrypt the recognition API key.' );
		}

		$nonce = random_bytes( SODIUM_CRYPTO_SECRETBOX_NONCEBYTES );
		$key   = sodium_crypto_generichash(
			'acx_recognition_api_key|' . wp_salt( 'auth' ),
			'',
			SODIUM_CRYPTO_SECRETBOX_KEYBYTES
		);

		try {
			$ciphertext = sodium_crypto_secretbox( $plaintext, $nonce, $key );
			return self::PREFIX . base64_encode( $nonce . $ciphertext );
		} finally {
			if ( \function_exists( 'sodium_memzero' ) ) {
				sodium_memzero( $key );
			}
		}
	}

	/**
	 * Decrypt a stored API key, returning null for invalid or legacy values.
	 *
	 * @param mixed $stored Stored option value.
	 */
	public static function decrypt( mixed $stored ): ?string {
		if ( ! is_string( $stored ) || '' === $stored || ! str_starts_with( $stored, self::PREFIX ) ) {
			return null;
		}

		if ( ! self::is_available() ) {
			return null;
		}

		$payload = base64_decode( substr( $stored, strlen( self::PREFIX ) ), true );
		if (
			false === $payload
			|| strlen( $payload ) < SODIUM_CRYPTO_SECRETBOX_NONCEBYTES + SODIUM_CRYPTO_SECRETBOX_MACBYTES
		) {
			return null;
		}

		$nonce      = substr( $payload, 0, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES );
		$ciphertext = substr( $payload, SODIUM_CRYPTO_SECRETBOX_NONCEBYTES );
		$key        = sodium_crypto_generichash(
			'acx_recognition_api_key|' . wp_salt( 'auth' ),
			'',
			SODIUM_CRYPTO_SECRETBOX_KEYBYTES
		);

		try {
			$plaintext = sodium_crypto_secretbox_open( $ciphertext, $nonce, $key );
			return false === $plaintext ? null : $plaintext;
		} finally {
			if ( \function_exists( 'sodium_memzero' ) ) {
				sodium_memzero( $key );
			}
		}
	}

	private function __construct() {}
}
