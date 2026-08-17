<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Command;

use OCP\IConfig;
use OCP\IUser;
use OCP\IUserManager;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;

/**
 * occ otp-register:approve <username>
 * Manually approves a pending registration request and enables the account.
 */
class ApproveRegistration extends Command {
	private const PREFIX = 'pending_';

	private IConfig $config;
	private IUserManager $userManager;

	public function __construct(IConfig $config, IUserManager $userManager) {
		parent::__construct();
		$this->config = $config;
		$this->userManager = $userManager;
	}

	protected function configure(): void {
		$this->setName('otp-register:approve')
			->setDescription('Approve a pending registration request and enable the account')
			->addArgument('username', InputArgument::REQUIRED, 'Username of the pending registration');
	}

	protected function execute(InputInterface $input, OutputInterface $output): int {
		$username = (string) $input->getArgument('username');
		$configKey = self::PREFIX . $username;

		$raw = $this->config->getAppValue('otp-register', $configKey, '');
		if ($raw === '') {
			$output->writeln('<error>No pending registration request for "' . $username . '".</error>');
			return 1;
		}

		$user = $this->userManager->get($username);
		if (!$user instanceof IUser) {
			$output->writeln('<error>User "' . $username . '" no longer exists.</error>');
			return 1;
		}

		if (method_exists($user, 'setEnabled')) {
			$user->setEnabled(true);
		}
		$this->config->deleteAppValue('otp-register', $configKey);

		$entry = json_decode($raw, true);
		$output->writeln('Approved registration for <info>' . $username . '</info>'
			. (is_array($entry) && !empty($entry['email']) ? ' (' . $entry['email'] . ')' : '')
			. '. Account is now enabled.');
		return 0;
	}
}
