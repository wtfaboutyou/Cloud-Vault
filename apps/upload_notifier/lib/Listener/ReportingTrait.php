<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Listener;

use OCA\UploadNotifier\Service\WatchtowerNotifier;
use OCP\Files\File;

/**
 * Shared UPLOAD_COMPLETED formatting/reporting for the completion listeners.
 */
trait ReportingTrait {
	protected function reportCompleted(File $node, string $verb): void {
		$owner = $node->getOwner()?->getUID() ?? 'unknown';
		$this->notifier->notify(
			WatchtowerNotifier::EVENT_UPLOAD_COMPLETED,
			'success',
			sprintf('File "%s" %s by %s', $node->getName(), $verb, $owner),
			[
				'path' => $node->getPath(),
				'user' => $owner,
				'size' => $this->formatSize($node->getSize()),
			]
		);
	}

	protected function formatSize(int|float $bytes): string {
		$label = ['B', 'KB', 'MB', 'GB', 'TB'];
		$i = 0;
		$value = (float) $bytes;
		while ($value >= 1024 && $i < count($label) - 1) {
			$value /= 1024;
			$i++;
		}
		return sprintf('%.1f %s', $value, $label[$i]);
	}
}