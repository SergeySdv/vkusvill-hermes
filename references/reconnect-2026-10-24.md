# Jarvis reconnect and token renewal — 2026-10-24

Observed production status: configured, refresh_available=false, access token
expired. This is independent of the unresolved empty-account SCHEMA_CHANGED.

Public discovery at https://oauth.vkusvill.ru/.well-known/oauth-authorization-server
advertises refresh_token and offline_access (checked 2026-10-24). The previously
requested four business scopes did not include offline_access. Metadata does not
prove that this particular registered client is allowed offline access.

The Mini App now offers explicit reconnect using the encrypted saved client.
No client secret is returned to the browser or Hermes. The optional, visible
offline-access checkbox requests offline_access with prompt=consent, following
https://openid.net/specs/openid-connect-core-1_0.html#OfflineAccess.
The server validates advertised support and never silently retries with broader
scopes. Cancellation, denial, or failed exchange retains the existing account.
Successful exchange atomically replaces it and invalidates the previous context.

Refresh is performed on demand before provider calls, under the existing vault
lock. Rotation is persisted; ambiguous refresh outcomes are not blindly replayed.
No refresh token is synthesized or borrowed from a previous authorization.
If the provider does not issue one, the UI explicitly reports that limitation.
If offline_access is rejected, ask the provider to enable it for this client;
unchecking the box permits a short-lived login, not automatic renewal.

Acceptance after deployment:
1. Existing expired account shows reconnect, not a credentials form.
2. Reconnect reaches VkusVill consent without entering client keys.
3. After consent, auth status reports refresh_available=true. Otherwise renewal
   remains unconfirmed and provider/client settings must be investigated.
4. Execute a read-only query now and after access-token expiry; confirm expiry
   advances and no further login is requested. Do not modify production expiry
   or replay a refresh request manually to accelerate this check.
5. Separately diagnose empty orders/favorite shapes without interpreting auth
   failures as an empty result.

Local tests cover saved-client reuse, browser authentication, override rejection,
consent denial preserving the account, unsupported offline discovery, missing
refresh token, expiry status, refresh serialization/rotation, and browser reentry.
Live renewal has not yet been tested.

## Owner-reported deployment and login

The coordinated update completed with account_preserved=true and
other_containers_unchanged=true. The expired account now reports reconnect_required.
After initial stalled consent attempts, the owner completed login without entering
client keys again. At 2026-10-24 23:20 Asia/Shanghai the supplied Mini App screenshot
showed automatic renewal available, which corresponds to refresh_available=true.
This is UI evidence of a stored refresh token, not a completed live refresh test.

At 15:22 UTC the bot reported SCHEMA_CHANGED for orders and favorite, rather than
AUTH_REQUIRED. Empty-account handling remains unresolved; do not reinterpret all
schema failures as empty data. The cause of the earlier consent-page session
errors remains unconfirmed. Follow up on hiding reconnect controls behind an
additional action for healthy connections, and verify actual renewal after expiry.
