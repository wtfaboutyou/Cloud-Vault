<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Listener;

use OCA\UploadNotifier\Service\UploadTracker;
use OCA\UploadNotifier\Service\WatchtowerNotifier;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\Files\Events\Node\NodeRenamedEvent;
use OCP\Files\File;

/**
 * Reports the finalization of a chunked upload as UPLOAD_COMPLETED.
 *
 * The web UI / files_dav uploads files in chunks into a staging area
 * (<user>/uploads/...) and only the final MOVE into the files directory fires
 * rename hooks rather than create/write hooks, so the normal completion
 * listeners never see those files. This listener only reacts when a file is
 * moved out of the chunked-upload staging area into a real user "files" path.
 *
 * @template-implements IEventListener<NodeRenamedEvent>
 */
class NodeRenamedListener implements IEventListener {
	use ReportingTrait;

	public function __construct(
		private UploadTracker $tracker,
		private WatchtowerNotifier $notifier,
	) {
	}

	public function handle(Event $event): void {
		if (!$event instanceof NodeRenamedEvent) {
			return;
		}

		$target = $event->getTarget();
		if (!$target instanceof File) {
			return;
		}
		if (!$this->tracker->isChunkUploadPath($event->getSource()->getPath())) {
			return;
		}

		$path = $target->getPath();
		if (!$this->tracker->isUserFilePath($path)) {
			return;
		}

		$result = $this->tracker->complete($path);
		if ($result['notify']) {
			$this->reportCompleted($target, 'uploaded');
		}
	}
}