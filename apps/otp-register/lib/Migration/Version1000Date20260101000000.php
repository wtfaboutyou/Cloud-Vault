<?php

declare(strict_types=1);

namespace OCA\OtpRegister\Migration;

use Closure;
use OCP\DB\ISchemaWrapper;
use OCP\Migration\IOutput;
use OCP\Migration\SimpleMigrationStep;

class Version1000Date20260101000000 extends SimpleMigrationStep {
	/**
	 * No schema change needed; OTP records live in appconfig.
	 */
	public function changeSchema(IOutput $output, Closure $schemaClosure, array $options): ?ISchemaWrapper {
		return null;
	}
}