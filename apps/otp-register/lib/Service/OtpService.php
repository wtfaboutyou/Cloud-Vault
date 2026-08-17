<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Service;

use OCP\IConfig;
use OCP\AppFramework\Http;
use OCP\IRequest;

class OtpService {
	public const SETTING_API_KEY = 'resend_api_key';
	public const SETTING_FROM = 'resend_from';
	public const SETTING_EXPIRY = 'otp_ttl_seconds';
	public const SETTING_REUSE = 'otp_reuse_minutes';

	private IConfig $config;

	public function __construct(IConfig $config) {
		$this->config = $config;
	}

	/**
	 * Generate a cryptographically random 6-digit code for a given email.
	 * The code is stored in Nextcloud app config keyed per-user (hashed) so no
	 * custom database table is required. Expires after TTL.
	 */
	public function generate(string $email, string $userId): string {
		$code = (string) random_int(100000, 999999);
		$store = [
			'code' => $code,
			'created' => time(),
			'email' => $email,
			'attempts' => 0,
		];
		$this->config->setAppValue('otp-register', 'otp_' . sha1(strtolower($email)), json_encode($store));
		return $code;
	}

	/**
	 * Validate a submitted code. Returns true when correct and still valid.
	 */
	public function verify(string $email, string $code): bool {
		$ttl = (int) $this->config->getAppValue('otp-register', self::SETTING_EXPIRY, '600');
		$raw = $this->config->getAppValue('otp-register', 'otp_' . sha1(strtolower($email)), '');
		if ($raw === '') {
			return false;
		}
		$store = json_decode($raw, true);
		if (!is_array($store)) {
			return false;
		}
		if (time() - (int) $store['created'] > $ttl) {
			$this->config->deleteAppValue('otp-register', 'otp_' . sha1(strtolower($email)));
			return false;
		}
		if (hash_equals((string) $store['code'], trim($code))) {
			$this->config->deleteAppValue('otp-register', 'otp_' . sha1(strtolower($email)));
			return true;
		}
		$store['attempts'] = (int) $store['attempts'] + 1;
		$this->config->setAppValue('otp-register', 'otp_' . sha1(strtolower($email)), json_encode($store));
		return false;
	}

	/**
	 * Send the code via Resend HTTP API (reliable email delivery, no SMTP needed).
	 */
	public function send(string $email, string $code): array {
		$apiKey = $this->config->getAppValue('otp-register', self::SETTING_API_KEY, '');
		$from = $this->config->getAppValue('otp-register', self::SETTING_FROM, 'CloudVault <verify@example.com>');
		if ($apiKey === '') {
			return ['ok' => false, 'error' => 'resend_api_key not configured'];
		}

		$payload = [
			'from' => $from,
			'to' => [$email],
			'subject' => 'Your CloudVault verification code',
			'html' => '<p>Your verification code is:</p>'
				. '<h2 style="letter-spacing:6px;font-size:28px;font-weight:700">' . htmlspecialchars($code) . '</h2>'
				. '<p>This code expires in a few minutes. If you did not request this, ignore this email.</p>',
			'text' => 'Your CloudVault verification code is: ' . $code,
		];

		$ch = curl_init('https://api.resend.com/emails');
		curl_setopt_array($ch, [
			CURLOPT_POST => true,
			CURLOPT_RETURNTRANSFER => true,
			CURLOPT_TIMEOUT => 15,
			CURLOPT_HTTPHEADER => [
				'Authorization: Bearer ' . $apiKey,
				'Content-Type: application/json',
			],
			CURLOPT_POSTFIELDS => json_encode($payload),
		]);
		$resp = curl_exec($ch);
		$httpCode = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
		$err = curl_error($ch);
		curl_close($ch);

		if ($resp === false || $httpCode >= 400) {
			return ['ok' => false, 'error' => $err ?: ('Resend HTTP ' . $httpCode . ': ' . (string) $resp)];
		}
		return ['ok' => true, 'id' => json_decode((string) $resp, true)['id'] ?? null];
	}
}
