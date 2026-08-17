<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Command;

use OCP\IConfig;
use OCP\IUserManager;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Helper\Table;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;

/**
 * occ otp-register:pending
 * Lists all registration requests that are waiting for manual admin approval.
 */
class PendingRegistrations extends Command {
	private const PREFIX = 'pending_';

	private IConfig $config;
	private IUserManager $userManager;

	public function __construct(IConfig $config, IUserManager $userManager) {
		parent::__construct();
		$this->config = $config;
		$this->userManager = $userManager;
	}

	protected function configure(): void {
		$this->setName('otp-register:pending')
			->setDescription('List registration requests waiting for admin approval');
	}

	protected function execute(InputInterface $input, OutputInterface $output): int {
		$rows = [];
		foreach ($this->config->getAppKeys('otp-register') as $key) {
			if (strpos($key, self::PREFIX) !== 0) {
				continue;
			}
			$username = substr($key, strlen(self::PREFIX));
			$raw = $this->config->getAppValue('otp-register', $key, '');
			$entry = json_decode($raw, true);
			if (!is_array($entry)) {
				continue;
			}
			$rows[] = [
				'username' => $username,
				'email' => (string) ($entry['email'] ?? ''),
				'verified' => !empty($entry['verified']) ? 'yes' : 'no',
				'requested' => date('Y-m-d H:i:s', (int) ($entry['created'] ?? 0)),
			];
		}

		if ($rows === []) {
			$output->writeln('No pending registration requests.');
			return 0;
		}

		usort($rows, fn ($a, $b) => $a['requested'] <=> $b['requested']);

		$table = new Table($output);
		$table->setHeaders(['Username', 'Email', 'Email verified', 'Requested']);
		$table->setRows(array_map('array_values', $rows));
		$table->render();

		$output->writeln('Approve:  occ otp-register:approve <username>');
		$output->writeln('Reject:   occ otp-register:reject <username>');
		return 0;
	}
}
