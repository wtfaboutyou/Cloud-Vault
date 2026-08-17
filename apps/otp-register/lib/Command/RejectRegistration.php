<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Command;

use OCP\IConfig;
use OCP\IUserManager;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;

/**
 * occ otp-register:reject <username>
 * Rejects a pending registration request and removes the account.
 */
class RejectRegistration extends Command {
	private const PREFIX = 'pending_';

	private IConfig $config;
	private IUserManager $userManager;

	public function __construct(IConfig $config, IUserManager $userManager) {
		parent::__construct();
		$this->config = $config;
		$this->userManager = $userManager;
	}

	protected function configure(): void {
		$this->setName('otp-register:reject')
			->setDescription('Reject a pending registration request and remove the account')
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

		$this->config->deleteAppValue('otp-register', $configKey);

		$user = $this->userManager->get($username);
		if ($user !== null) {
			$user->delete();
		}

		$output->writeln('Rejected registration for <info>' . $username . '</info>. Account removed.');
		return 0;
	}
}
