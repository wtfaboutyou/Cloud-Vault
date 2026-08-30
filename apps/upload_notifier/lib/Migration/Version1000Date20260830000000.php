<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Migration;

use Closure;
use OCP\DB\ISchemaWrapper;
use OCP\DB\Types;
use OCP\Migration\IOutput;
use OCP\Migration\SimpleMigrationStep;

/**
 * Creates oc_upload_notifier_pending to track in-flight uploads.
 */
class Version1000Date20260830000000 extends SimpleMigrationStep {
	#[\Override]
	public function changeSchema(IOutput $output, Closure $schemaClosure, array $options): ?ISchemaWrapper {
		$schema = $schemaClosure();

		if (!$schema->hasTable('upload_notifier_pending')) {
			$table = $schema->createTable('upload_notifier_pending');
			$table->addColumn('id', Types::BIGINT, [
				'autoincrement' => true,
				'notnull' => true,
			]);
			$table->addColumn('node_path', Types::STRING, [
				'length' => 512,
				'notnull' => true,
			]);
			$table->addColumn('owner', Types::STRING, [
				'length' => 255,
				'notnull' => false,
				'default' => '',
			]);
			$table->addColumn('event', Types::STRING, [
				'length' => 32,
				'notnull' => false,
				'default' => 'write',
			]);
			$table->addColumn('started_at', Types::BIGINT, [
				'notnull' => true,
			]);
			$table->setPrimaryKey(['id']);
			$table->addIndex(['node_path'], 'un_pending_path_idx');
		}

		return $schema;
	}
}