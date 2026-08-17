<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Listener;

use OCA\OtpRegister\Service\OtpService;
use OCP\EventDispatcher\Event;
use OCP\EventDispatcher\IEventListener;
use OCP\User\Events\UserCreatedEvent;
use OCP\IUser;
use Psr\Log\LoggerInterface;

/**
 * Automatically email a verification code as soon as a new account is created,
 * regardless of the source (occ user:add, admin UI, or Registration app).
 */
class NewUserListener implements IEventListener {
	private OtpService $otp;
	private LoggerInterface $logger;

	public function __construct(OtpService $otp, LoggerInterface $logger) {
		$this->otp = $otp;
		$this->logger = $logger;
	}

	/**
	 * @param UserCreatedEvent $event
	 * @return void
	 */
	public function handle(Event $event): void {
		if (!$event instanceof UserCreatedEvent) {
			return;
		}
		$user = $event->getUser();
		$email = $user->getEMailAddress();

		if ($email === '' || $email === null) {
			$this->logger->warning('OTP not sent: no email on created user ' . $user->getUID());
			return;
		}

		$code = $this->otp->generate($email, $user->getUID());
		$sent = $this->otp->send($email, $code);
		if (!$sent['ok']) {
			$this->logger->error('OTP send failed for ' . $email . ': ' . ($sent['error'] ?? 'unknown'));
		}
	}
}