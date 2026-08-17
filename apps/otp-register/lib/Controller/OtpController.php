<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Controller;

use OCA\OtpRegister\Service\OtpService;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\JSONResponse;
use OCP\AppFramework\Http\TemplateResponse;
use OCP\IRequest;
use OCP\IUserManager;
use OCP\IConfig;
use OCP\IUser;
use OCP\Util;

class OtpController extends Controller {
	private OtpService $otp;
	private IUserManager $userManager;
	private IConfig $config;

	public function __construct(string $appName, IRequest $request, OtpService $otp, IUserManager $userManager, IConfig $config) {
		parent::__construct($appName, $request);
		$this->otp = $otp;
		$this->userManager = $userManager;
		$this->config = $config;
	}

	/**
	 * Public registration page.
	 * GET /apps/otp-register/
	 * @PublicPage
	 * @NoCSRFRequired
	 */
	public function registerPage(): TemplateResponse {
		Util::addScript('otp-register', 'register');
		return new TemplateResponse('otp-register', 'register', [], TemplateResponse::RENDER_AS_GUEST);
	}

	/**
	 * Sends a verification for the user's email (email + creates a pending user).
	 * POST /apps/otp-register/send  { username, email }
	 * @PublicPage
	 * @NoCSRFRequired
	 */
	public function send(): JSONResponse {
		$body = $this->request->getParams();
		$username = trim((string) ($body['username'] ?? ''));
		$email = trim((string) ($body['email'] ?? ''));
		if ($username === '' || $email === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
			return new JSONResponse(['error' => 'Valid username and email are required'], 400);
		}

		// Create (or fetch) the user with disabled state until verified.
		$user = $this->userManager->get($username);
		$createdNow = false;
		if ($user === null) {
			$user = $this->userManager->createUser($username, bin2hex(random_bytes(16)));
			if ($user === null) {
				return new JSONResponse(['error' => 'Could not create user'], 500);
			}
			$createdNow = true;
			// mark user is not enabled until OTP verified
			if (method_exists($user, 'setEnabled')) {
				$user->setEnabled(false);
			}
		}

		$code = $this->otp->generate($email, $username);
		$sent = $this->otp->send($email, $code);
		if (!$sent['ok']) {
			// roll back the freshly-created pending user so a failed send doesn't leak users
			if ($createdNow) {
				$this->userManager->delete($user->getUID());
			}
			return new JSONResponse(['error' => 'Failed to send email: ' . ($sent['error'] ?? 'unknown')], 500);
		}
		return new JSONResponse(['ok' => true, 'sent_to' => $email]);
	}

	/**
	 * Verifies the submitted code. The account stays DISABLED until an admin
	 * manually approves it with `occ otp-register:approve <username>`.
	 * POST /apps/otp-register/verify  { username, email, code }
	 * @PublicPage
	 * @NoCSRFRequired
	 */
	public function verify(): JSONResponse {
		$body = $this->request->getParams();
		$username = trim((string) ($body['username'] ?? ''));
		$email = trim((string) ($body['email'] ?? ''));
		$code = trim((string) ($body['code'] ?? ''));

		if ($username === '' || $email === '' || $code === '') {
			return new JSONResponse(['error' => 'username, email and code are required'], 400);
		}

		if (!$this->otp->verify($email, $code)) {
			return new JSONResponse(['error' => 'Invalid or expired verification code'], 400);
		}

		// Code verified -> mark the request as pending admin approval.
		// The account is NOT enabled here; `occ otp-register:approve` does that.
		$user = $this->userManager->get($username);
		if (!$user instanceof IUser) {
			return new JSONResponse(['error' => 'User not found'], 404);
		}

		$this->config->setAppValue('otp-register', 'pending_' . $username, json_encode([
			'email' => $email,
			'verified' => true,
			'created' => time(),
		]));

		return new JSONResponse(['ok' => true, 'verified' => true, 'pending' => true]);
	}
}