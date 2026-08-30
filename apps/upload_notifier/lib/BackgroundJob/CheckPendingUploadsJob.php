<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\BackgroundJob;

use OCA\UploadNotifier\Service\UploadTracker;
use OCA\UploadNotifier\Service\WatchtowerNotifier;
use OCP\AppFramework\Utility\ITimeFactory;
use OCP\BackgroundJob\TimedJob;
use Psr\Log\LoggerInterface;

/**
 * Periodically checks pending uploads and emits UPLOAD_FAILED for writes
 * that started but never completed within the configured TTL.
 */
class CheckPendingUploadsJob extends TimedJob {
	public function __construct(
		ITimeFactory $time,
		private UploadTracker $tracker,
		private WatchtowerNotifier $notifier,
		private LoggerInterface $logger,
	) {
		parent::__construct($time);
		$this->setInterval(60);
	}

	#[\Override]
	protected function run($argument): void {
		try {
			$this->tracker->failStale($this->notifier);
			$this->tracker->reportAntivirusRejections($this->notifier);
		} catch (\Throwable $e) {
			$this->logger->debug('upload_notifier: check pending uploads failed: ' . $e->getMessage(), ['app' => 'upload_notifier']);
		}
	}
}