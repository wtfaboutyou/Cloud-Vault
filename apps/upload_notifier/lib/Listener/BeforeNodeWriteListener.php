<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Listener;

use OCA\UploadNotifier\Service\UploadTracker;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OC\Files\Node\NonExistingFile;
use OCP\Files\Events\Node\BeforeNodeCreatedEvent;
use OCP\Files\Events\Node\BeforeNodeWrittenEvent;
use OCP\Files\File;

/**
 * Records that a file write/creation has started, so the background job can
 * detect uploads that never completed.
 *
 * For brand-new uploads Nextcloud fires the create hooks on a
 * NonExistingFile (the target does not exist yet), so both File and
 * NonExistingFile are accepted here.
 *
 * @template-implements IEventListener<BeforeNodeCreatedEvent|BeforeNodeWrittenEvent>
 */

/**
 * Records that a file write/creation has started, so the background job can
 * detect uploads that never completed.
 *
 * @template-implements IEventListener<BeforeNodeCreatedEvent|BeforeNodeWrittenEvent>
 */
class BeforeNodeWriteListener implements IEventListener {
	public function __construct(
		private UploadTracker $tracker,
	) {
	}

	public function handle(Event $event): void {
		if ($event instanceof BeforeNodeCreatedEvent) {
			$node = $event->getNode();
			if (!$this->isFile($node) || !$this->tracker->isUserFilePath($node->getPath())) {
				return;
			}
			$this->tracker->beginWrite($node->getPath(), UploadTracker::EVENT_CREATE);
			return;
		}

		if ($event instanceof BeforeNodeWrittenEvent) {
			$node = $event->getNode();
			if (!$this->isFile($node) || !$this->tracker->isUserFilePath($node->getPath())) {
				return;
			}
			$this->tracker->beginWrite($node->getPath(), UploadTracker::EVENT_WRITE);
		}
	}

	private function isFile(object $node): bool {
		return $node instanceof File || $node instanceof NonExistingFile;
	}
}