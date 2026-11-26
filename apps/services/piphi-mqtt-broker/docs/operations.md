# MQTT broker storage and recovery procedures

These procedures preserve the coupled broker database, generated identity
state, TLS copies, and source secrets. They do not qualify a particular host,
orchestrator, disk, or physical deployment.

## Backup

1. Confirm `storage-admin.sh check` reports `ready`, enough free space, and the
   expected `broker_id`.
2. Run `storage-admin.sh flush`. A failure blocks the backup.
3. Stop the container cleanly and wait for Mosquitto to exit successfully. Do
   not snapshot a running database after the flush command returns.
4. Snapshot `/mosquitto/config`, `/mosquitto/data`, and the mounted source-secret
   set as one consistency group. Do not include `/mosquitto/log` unless audit
   retention policy requires it.
5. Encrypt the backup, record image digest, package version, Mosquitto version,
   timestamp, file checksums, owner/mode metadata, and retention expiry.
6. Restart the exact same image digest and require readiness before declaring
   the backup complete.

## Restore drill

1. Stop the broker. Restore into empty replacement config/data/secret paths;
   never merge generations or a database from different snapshots.
2. Verify directories are owned by the runtime broker account and secret or
   generated credential files are no broader than `0640`.
3. Start the exact image digest recorded with the backup, with network exposure
   limited to the synthetic qualification client.
4. Require authenticated readiness, run privacy-safe diagnostics, verify a
   retained synthetic value, and verify a removed credential is still denied.
5. Only then attach normal clients. Upgrade in a separate change after the
   restored version is healthy.

The container contract suite performs this restore sequence with synthetic
Mosquitto clients and a fresh container. It does not claim host backup-system
or disaster-recovery qualification.

## Disk pressure or full disk

- **Above the readiness floor:** capture diagnostics, reduce incoming work,
  flush, cleanly stop, take a coupled encrypted backup, and expand or replace
  the volume.
- **At or below the floor:** readiness fails. Do not truncate `mosquitto.db`,
  remove identity generations, or clear retained data in place. Stop and move
  the coupled state to a volume with sufficient capacity.
- **Write failure:** treat the broker as unavailable even if TCP liveness still
  passes. Preserve logs without application payloads and restore from the last
  verified backup if a clean save cannot be completed.

## Suspected database corruption

1. Stop the broker and preserve a read-only forensic copy and checksums.
2. Do not repeatedly start the production volume or run unreviewed repair tools.
3. Restore the latest verified coupled snapshot to an empty volume and run the
   restore drill.
4. Escalate recovery of newer data as a separate destructive operation requiring
   explicit approval. Corrupt-database repair is not release-qualified.
