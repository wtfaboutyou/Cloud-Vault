<?php

declare(strict_types=1);

namespace OCA\OtpRegister\AppInfo;

use OCA\OtpRegister\Listener\NewUserListener;
use OCP\AppFramework\App;
use OCP\AppFramework\Bootstrap\IBootContext;
use OCP\AppFramework\Bootstrap\IBootstrap;
use OCP\AppFramework\Bootstrap\IRegistrationContext;
use OCP\User\Events\UserCreatedEvent;

class Application extends App implements IBootstrap {
	public const APP_ID = 'otp-register';

	public function __construct(array $urlParams = []) {
		parent::__construct(self::APP_ID, $urlParams);
	}

	public function register(IRegistrationContext $context): void {
		// Auto-send a verification code whenever a new user account is created.
		// occ commands are declared in appinfo/info.xml <commands>.
		$context->registerEventListener(UserCreatedEvent::class, NewUserListener::class);
	}

	public function boot(IBootContext $context): void {
	}
}