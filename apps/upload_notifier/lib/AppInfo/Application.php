<?php

declare(strict_types=1);

/**
 * CloudVault Upload Notifier
 *
 * Registers filesystem event listeners so uploads can be reported to the
 * CloudVault Watchtower service (which routes them to Telegram).
 */

namespace OCA\UploadNotifier\AppInfo;

use OCA\UploadNotifier\Listener\BeforeNodeWriteListener;
use OCA\UploadNotifier\Listener\NodeCreatedListener;
use OCA\UploadNotifier\Listener\NodeRenamedListener;
use OCA\UploadNotifier\Listener\NodeWrittenListener;
use OCP\AppFramework\App;
use OCP\AppFramework\Bootstrap\IBootContext;
use OCP\AppFramework\Bootstrap\IBootstrap;
use OCP\AppFramework\Bootstrap\IRegistrationContext;
use OCP\Files\Events\Node\BeforeNodeCreatedEvent;
use OCP\Files\Events\Node\BeforeNodeWrittenEvent;
use OCP\Files\Events\Node\NodeCreatedEvent;
use OCP\Files\Events\Node\NodeRenamedEvent;
use OCP\Files\Events\Node\NodeWrittenEvent;

class Application extends App implements IBootstrap {
	public const APP_ID = 'upload_notifier';

	public function __construct() {
		parent::__construct(self::APP_ID);
	}

	public function register(IRegistrationContext $context): void {
		$context->registerEventListener(
			BeforeNodeCreatedEvent::class,
			BeforeNodeWriteListener::class
		);
		$context->registerEventListener(
			BeforeNodeWrittenEvent::class,
			BeforeNodeWriteListener::class
		);
		$context->registerEventListener(
			NodeCreatedEvent::class,
			NodeCreatedListener::class
		);
		$context->registerEventListener(
			NodeWrittenEvent::class,
			NodeWrittenListener::class
		);
		$context->registerEventListener(
			NodeRenamedEvent::class,
			NodeRenamedListener::class
		);
	}

	public function boot(IBootContext $context): void {
	}
}