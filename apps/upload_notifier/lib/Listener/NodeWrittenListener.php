<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Listener;

use OCA\UploadNotifier\Service\UploadTracker;
use OCA\UploadNotifier\Service\WatchtowerNotifier;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Files\Events\Node\NodeWrittenEvent;
use OCP\Files\File;

/**
 * Reports a modified file to Watchtower as UPLOAD_COMPLETED ("updated").
 *
 * @template-implements IEventListener<NodeWrittenEvent>
 */
class NodeWrittenListener implements IEventListener {
	use ReportingTrait;

	public function __construct(
		private UploadTracker $tracker,
		private WatchtowerNotifier $notifier,
	) {
	}

	public function handle(Event $event): void {
		if (!$event instanceof NodeWrittenEvent) {
			return;
		}

		$node = $event->getNode();
		if (!$node instanceof File) {
			return;
		}

		$path = $node->getPath();
		if (!$this->tracker->isUserFilePath($path)) {
			return;
		}

		$result = $this->tracker->complete($path);
		if ($result['notify'] && $result['event'] === UploadTracker::EVENT_CREATE) {
			$this->reportCompleted($node, 'uploaded');
		} elseif ($result['notify']) {
			$this->reportCompleted($node, 'updated');
		}
	}
}