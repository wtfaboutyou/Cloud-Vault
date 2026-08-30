<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Service;

use OCA\UploadNotifier\AppInfo\Application;
use OCP\Http\Client\IClientService;
use OCP\IConfig;
use Psr\Log\LoggerInterface;

/**
 * Sends operational events to the CloudVault Watchtower event endpoint.
 *
 * The default endpoint (http://127.0.0.1:9191/api/events) is loopback-only so
 * no API key is required from Nextcloud. Delivery is best-effort: a failure
 * to reach Watchtower must never break a file upload.
 */
class WatchtowerNotifier {
	public const EVENT_UPLOAD_COMPLETED = 'UPLOAD_COMPLETED';
	public const EVENT_UPLOAD_FAILED = 'UPLOAD_FAILED';

	private const DEFAULT_URL = 'http://127.0.0.1:9191/api/events';

	public function __construct(
		private IClientService $clientService,
		private IConfig $config,
		private LoggerInterface $logger,
	) {
	}

	/**
	 * Whether a given event type is enabled.
	 */
	public function enabled(string $eventType): bool {
		if ($this->config->getSystemValue('upload_notifier_enabled', 'yes') === 'no') {
			return false;
		}
		if ($this->config->getAppValue(Application::APP_ID, 'enabled', 'yes') === 'no') {
			return false;
		}
		return $this->config->getAppValue(Application::APP_ID, 'event_' . $eventType, 'yes') !== 'no';
	}

	public function getWatchtowerUrl(): string {
		$url = $this->config->getSystemValue('upload_notifier_url', '');
		if ($url === '') {
			$url = $this->config->getAppValue(Application::APP_ID, 'watchtower_url', '');
		}
		return $url !== '' ? $url : self::DEFAULT_URL;
	}

	public function getFailureTtl(): int {
		$ttl = (int) $this->config->getAppValue(Application::APP_ID, 'failure_ttl', '600');
		return $ttl > 0 ? $ttl : 600;
	}

	/**
	 * Fire-and-forget notification to Watchtower.
	 *
	 * Extra named fields (label, size, ...) can be passed through $extra and
	 * will be merged into the JSON payload.
	 */
	public function notify(string $eventType, string $status, string $detail, array $extra = []): void {
		if (!$this->enabled($eventType)) {
			return;
		}

		$url = $this->getWatchtowerUrl();

		$payload = array_merge([
			'event_type' => $eventType,
			'status' => $status,
			'detail' => $detail,
			// WIB (Asia/Jakarta, UTC+7): match timestamps sent by the bash producers
			'timestamp' => (new \DateTime('now', new \DateTimeZone('Asia/Jakarta')))->format('Y-m-d H:i:s T'),
		], $extra);

		try {
			$client = $this->clientService->newClient();
			$client->post($url, [
				'headers' => ['Content-Type' => 'application/json'],
				'body' => json_encode($payload, JSON_UNESCAPED_SLASHES),
				'timeout' => 5,
				// Watchtower runs on the same host (loopback). Nextcloud blocks
				// requests to local addresses by default (SSRF protection), so
				// the app must explicitly opt into the loopback-only endpoint.
				'nextcloud' => ['allow_local_address' => true],
			]);
		} catch (\Throwable $e) {
			$this->logger->debug('upload_notifier: watchtower notify failed: ' . $e->getMessage(), ['app' => Application::APP_ID]);
		}
	}
}