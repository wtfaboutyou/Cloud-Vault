<?php

declare(strict_types=1);

namespace OCA\UploadNotifier\Service;

use OCA\UploadNotifier\AppInfo\Application;
use OCP\DB\Exception as DBException;
use OCP\IConfig;
use OCP\IDBConnection;
use Psr\Log\LoggerInterface;

/**
 * Tracks in-flight uploads so a write that starts (a BeforeNode* event) but
 * never completes (no matching NodeCreated/NodeWritten event) can be reported
 * as an UPLOAD_FAILED event by the background job.
 *
 * The same table also records completion markers so a single physical write
 * (which can fire several Node events, e.g. both create and write hooks for a
 * new file) is only reported once.
 *
 * Rows are stored in oc_upload_notifier_pending (see Migration).
 *
 * Antivirus-blocked uploads never produce any Node events (the violation is
 * thrown while writing the internal .part file, before the final target hooks
 * fire), so rejected uploads are additionally detected by watching the
 * files_antivirus Activity records in oc_activity.
 */
class UploadTracker {
	public const EVENT_CREATE = 'create';
	public const EVENT_WRITE = 'write';
	public const EVENT_COMPLETED = 'completed';

	public function __construct(
		private IDBConnection $db,
		private LoggerInterface $logger,
		private IConfig $config,
	) {
	}

	/**
	 * Is this absolute node path a real user file inside a "files" directory?
	 *
	 * Excludes trash, versions, thumbnails, appdata and the internal
	 * "uploads" directory used for chunked transfers.
	 */
	public function isUserFilePath(string $path): bool {
		if ($path === '' || $path[0] !== '/') {
			return false;
		}
		$segments = explode('/', ltrim($path, '/'));
		// /<user>/files/...
		if (count($segments) < 3 || $segments[1] !== 'files') {
			return false;
		}
		// keep only direct children of <user>/files (depth === 3) or deeper
		foreach ($segments as $segment) {
			if ($segment === 'files_trashbin'
				|| $segment === 'files_versions'
				|| $segment === 'thumbnails'
				|| str_starts_with($segment, 'appdata_')
				|| $segment === 'uploads') {
				return false;
			}
		}
		return true;
	}

	/**
	 * Is this path a chunked-upload staging path (harmless to notify on the
	 * target, but the source itself must never be reported)?
	 */
	public function isChunkUploadPath(string $path): bool {
		if ($path === '' || $path[0] !== '/') {
			return false;
		}
		$segments = explode('/', ltrim($path, '/'));
		foreach ($segments as $segment) {
			if ($segment === 'uploads') {
				return true;
			}
		}
		return false;
	}

	/**
	 * Remember that a write for $path has started.
	 *
	 * Keeps a single row per path. A 'create' start is never downgraded to a
	 * 'write' start, so the wording for a brand-new file stays "uploaded".
	 */
	public function beginWrite(string $path, string $event): void {
		$existing = $this->find($path);
		if ($existing !== null
			&& ($existing['event'] === self::EVENT_CREATE || $existing['event'] === self::EVENT_WRITE)) {
			return;
		}

		$qb = $this->db->getQueryBuilder();
		try {
			if ($existing !== null) {
				// Reset a previous completion marker to keep one row per path.
				$qb->update('upload_notifier_pending')
					->set('event', $qb->createNamedParameter($event))
					->set('started_at', $qb->createNamedParameter(time()))
					->where($qb->expr()->eq('node_path', $qb->createNamedParameter($path)))
					->executeStatement();
			} else {
				$qb->insert('upload_notifier_pending')
					->values([
						'node_path' => $qb->createNamedParameter($path),
						'owner' => $qb->createNamedParameter(''),
						'event' => $qb->createNamedParameter($event),
						'started_at' => $qb->createNamedParameter(time()),
					])
					->executeStatement();
			}
		} catch (DBException $e) {
			$this->logger->debug('upload_notifier: failed to begin pending upload: ' . $e->getMessage(), ['app' => 'upload_notifier']);
		}
	}

	/**
	 * Mark a write as completed and decide whether it should be reported.
	 *
	 * Returns ['notify' => bool, 'event' => string] where 'event' is the
	 * original start type ('create' => "uploaded", 'write' => "updated").
	 * A second completion for the same path within $window seconds (e.g. the
	 * duplicate hook pair fired for one physical write) is suppressed.
	 *
	 * @return array{notify: bool, event: string}
	 */
	public function complete(string $path, int $window = 30): array {
		$existing = $this->find($path);
		$now = time();

		if ($existing !== null && $existing['event'] === self::EVENT_COMPLETED
			&& ($now - (int) $existing['started_at']) < $window) {
			return ['notify' => false, 'event' => $existing['event']];
		}

		$startEvent = 'write';
		if ($existing !== null
			&& ($existing['event'] === self::EVENT_CREATE || $existing['event'] === self::EVENT_WRITE)) {
			$startEvent = $existing['event'];
		}

		if ($existing === null) {
			$this->beginWrite($path, $startEvent);
		}
		// stamp the completion marker
		$qb = $this->db->getQueryBuilder();
		try {
			$qb->update('upload_notifier_pending')
				->set('event', $qb->createNamedParameter(self::EVENT_COMPLETED))
				->set('started_at', $qb->createNamedParameter($now))
				->where($qb->expr()->eq('node_path', $qb->createNamedParameter($path)))
				->executeStatement();
		} catch (DBException $e) {
			$this->logger->debug('upload_notifier: failed to mark upload completed: ' . $e->getMessage(), ['app' => 'upload_notifier']);
		}

		return ['notify' => true, 'event' => $startEvent];
	}

	/**
	 * Clear the pending entry for a path once no longer needed.
	 */
	public function clear(string $path): void {
		$qb = $this->db->getQueryBuilder();
		try {
			$qb->delete('upload_notifier_pending')
				->where($qb->expr()->eq('node_path', $qb->createNamedParameter($path)))
				->executeStatement();
		} catch (DBException $e) {
			$this->logger->debug('upload_notifier: failed to clear pending upload: ' . $e->getMessage(), ['app' => 'upload_notifier']);
		}
	}

	/**
	 * Emit UPLOAD_FAILED for uploads that started but never completed.
	 */
	public function failStale(WatchtowerNotifier $notifier): void {
		$ttl = $notifier->getFailureTtl();
		$cutoff = time() - $ttl;

		$qb = $this->db->getQueryBuilder();
		try {
			$qb->select('id', 'node_path')
				->from('upload_notifier_pending')
				->where($qb->expr()->lt('started_at', $qb->createNamedParameter($cutoff)))
				->andWhere($qb->expr()->in('event', $qb->createNamedParameter([self::EVENT_CREATE, self::EVENT_WRITE], \OCP\DB\QueryBuilder\IQueryBuilder::PARAM_STR_ARRAY)));
			$result = $qb->executeQuery();
		} catch (DBException $e) {
			// Table missing on very first runs before migration ran
			return;
		} catch (\Throwable $e) {
			$result = null;
		}

		$rows = $result === null ? [] : $result->fetchAll();
		if ($result !== null) {
			$result->closeCursor();
		}

		foreach ($rows as $row) {
			$path = (string) $row['node_path'];
			if (!$notifier->enabled(WatchtowerNotifier::EVENT_UPLOAD_FAILED)) {
				$this->clear($path);
				continue;
			}
			$notifier->notify(
				WatchtowerNotifier::EVENT_UPLOAD_FAILED,
				'error',
				sprintf('Upload of "%s" failed (never completed)', basename($path)),
				['path' => $path]
			);
			$this->clear($path);
		}

		// Sweep old completion markers so the table does not grow forever.
		$qb = $this->db->getQueryBuilder();
		try {
			$qb->delete('upload_notifier_pending')
				->where($qb->expr()->eq('event', $qb->createNamedParameter(self::EVENT_COMPLETED)))
				->andWhere($qb->expr()->lt('started_at', $qb->createNamedParameter($cutoff)))
				->executeStatement();
		} catch (DBException $e) {
			// best effort
		}
	}

	/**
	 * Report uploads that were rejected by files_antivirus.
	 *
	 * A rejected upload is aborted while writing the internal .part file, so
	 * no Node events fire and the pending tracker never sees it. The only
	 * stable signal is the Activity record files_antivirus publishes
	 * (app = files_antivirus, type = virus_detected). We process those using
	 * a monotonic cursor so nothing is reported twice.
	 */
	public function reportAntivirusRejections(WatchtowerNotifier $notifier): void {
		$appId = Application::APP_ID;
		$cursor = (int) $this->config->getAppValue($appId, 'av_last_activity_id', '0');

		// First run: snapshot the current high-water mark so historical
		// rejections (recorded before this feature existed) are not replayed.
		if ($cursor <= 0) {
			$qb = $this->db->getQueryBuilder();
			try {
				$qb->select($qb->func()->max('activity_id'))->from('activity');
				$result = $qb->executeQuery();
				$max = (int) $result->fetchOne();
				$result->closeCursor();
			} catch (\Throwable) {
				// Activity table not available
				return;
			}
			if ($max > 0) {
				$this->config->setAppValue($appId, 'av_last_activity_id', (string) $max);
			}
			return;
		}

		$qb = $this->db->getQueryBuilder();
		try {
			$qb->select('activity_id', 'affecteduser', 'file', 'subjectparams', 'timestamp')
				->from('activity')
				->where($qb->expr()->eq('app', $qb->createNamedParameter('files_antivirus')))
				->andWhere($qb->expr()->eq('type', $qb->createNamedParameter('virus_detected')))
				->andWhere($qb->expr()->gt('activity_id', $qb->createNamedParameter($cursor)))
				->orderBy('activity_id', 'ASC')
				->setMaxResults(100);
			$result = $qb->executeQuery();
		} catch (\Throwable) {
			return;
		}

		$rows = $result->fetchAll();
		$result->closeCursor();
		if ($rows === []) {
			return;
		}

		$lastId = $cursor;
		foreach ($rows as $row) {
			$lastId = (int) $row['activity_id'];
			$path = (string) ($row['file'] ?? '');
			$user = (string) ($row['affecteduser'] ?? '');
			$signature = $this->virusSignature((string) ($row['subjectparams'] ?? ''));

			if (!$notifier->enabled(WatchtowerNotifier::EVENT_UPLOAD_FAILED)) {
				continue;
			}
			$notifier->notify(
				WatchtowerNotifier::EVENT_UPLOAD_FAILED,
				'error',
				sprintf('Upload of "%s" rejected by antivirus%s', $path !== '' ? basename($path) : 'unknown file', $signature !== '' ? ' (' . $signature . ')' : ''),
				[
					'path' => $path !== '' ? '/' . ltrim($path, '/') : '/unknown',
					'user' => $user,
				]
			);
		}

		$this->config->setAppValue($appId, 'av_last_activity_id', (string) $lastId);
	}

	private function virusSignature(string $subjectParams): string {
		$decoded = json_decode($subjectParams, true);
		if (is_array($decoded) && isset($decoded[0]) && is_string($decoded[0])) {
			return $decoded[0];
		}
		return '';
	}

	/**
	 * @return array{event: string, started_at: int, node_path: string}|null
	 */
	private function find(string $path): ?array {
		$qb = $this->db->getQueryBuilder();
		try {
			$qb->select('event', 'started_at', 'node_path')
				->from('upload_notifier_pending')
				->where($qb->expr()->eq('node_path', $qb->createNamedParameter($path)))
				->setMaxResults(1);
			$result = $qb->executeQuery();
		} catch (DBException $e) {
			return null;
		}
		$row = $result->fetch();
		$result->closeCursor();
		if ($row === false) {
			return null;
		}
		return [
			'event' => (string) $row['event'],
			'started_at' => (int) $row['started_at'],
			'node_path' => (string) $row['node_path'],
		];
	}
}