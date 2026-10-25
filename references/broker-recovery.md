# Isolated broker recovery (candidate)

Run `vv-auth-admin` in a trusted administrative environment as the owner of the
config/vault files, never in the agent container. The `age` / `age-keygen` programs
are external administrative dependencies; the ordinary broker image does not
include them. The server only needs the public age recipient. Keep its private
identity on the owner's Mac/off-host protected recovery storage.

## Consistent encrypted backup

```sh
vv-auth-admin backup --config /private/broker.json \
  --output /private/backups/jarvis-20261017.age --recipient age1PUBLIC_RECIPIENT
```

The command acquires the same cross-process vault lock as OAuth/bridge, uses the
SQLite backup API into memory, verifies integrity and decryptability, then encrypts
the recovery envelope with `age` through stdin. There is no plaintext temporary
archive or secret in process arguments. The output is exclusive-create 0600; it
does not overwrite earlier backups. A failure removes only a newly incomplete
output, not an existing backup. Lock acquisition is bounded to five seconds.

The envelope contains configuration, encryption/bridge keys and durable encrypted
records (identity, account and public context). Browser sessions, pending codes and
Telegram replay entries are deliberately not restored. Keep archives and their
checksums off-host; set retention through the existing protected backup system.
Configuration/image/Compose/Caddy/menu rollback metadata still needs its own
verified infrastructure backup. A broker backup does not back up Hermes baskets.

## Restore to a new private directory

```sh
vv-auth-admin restore --archive /private/backups/jarvis-20261017.age \
  --identity-file /private/off-host-recovery.key --directory /private/restored-jarvis
```

Never overwrite an active vault. Decryption stays in memory, record/owner binding
is checked, files are staged privately, readiness is verified, and the directory
is published only after validation. A nonempty or existing destination is refused.
Use an absolute destination. The restored config points to the restored local
vault path; change it to the container's mount path only in the reviewed deployment
copy, not in the sole recovery copy. Repair UID ownership for the target container
privately before starting it. Keep the same owner/bot; never repurpose a backup
for another person's service.

Restoring a refresh token already rotated at VkusVill may require new consent.
No token failure silently falls back to public access. An in-progress/uncertain
refresh is durably marked `reconnect_required` before network exchange and is not
replayed after restart. Reconnect through the user's browser, not a token in chat.

## Rotation and rollback

1. Take and verify an encrypted backup, then stop only this broker in an approved
   window. No other Hermes/OpenViking/Caddy container should be stopped for rotation.
2. Run `vv-auth-admin rotate-copy --offline --config /private/old/broker.json
   --directory /private/new-generation` in the trusted environment. `--offline`
   acknowledges an operator prerequisite; it does not stop services automatically.
3. The new copy has a fresh Fernet key and bridge key, re-encrypted durable records,
   and the same account context/expiry. Old config/vault remain untouched. Install
   the matching new broker config/vault and bridge-only Hermes capability together.
4. Check status/read-only requests, preserve rollback metadata, then retire old
   material according to retention. Do not restore the old generation after new
   refresh activity without considering token rotation at the provider.

Encryption is not protection from host root or the running broker. Deleting local
state does not revoke provider grants and does not erase earlier encrypted backups.
Use VkusVill's revocation process after a suspected credential compromise.

## Bounds and diagnostics

One process/worker per owner. Eight admitted concurrent requests; 12 session starts,
20 callbacks, 60 browser API requests, 120 bridge calls and 120 page requests per
minute, in separate in-memory buckets. These limits reset at service restart and
are not DDoS protection. Extra work receives `RATE_LIMITED`/429 with `Retry-After`.
JSON input: 32 KiB and a five-second body deadline; callback query: 8 KiB. MCP batch:
at most 20 calls, existing 90-second SDK deadline, 30-second per-read limit. Bridge
results larger than 2 MiB after SDK parsing are rejected; container RAM/PID/CPU
limits remain necessary because this is not an upstream streaming-memory bound.

Responses include a random safe request ID; access logs and raw exception details
are disabled. Never enable debug traces/HAR or export request bodies for a live
credential flow. Alert on readiness/5xx/429 counts without recording request data.
