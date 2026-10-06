# OAuth implementation gate

Status: discovery verified on 2026-10-05; OAuth is NOT implemented in vv.
Do not interpret the test fixture's AUTH_REQUIRED response as an OAuth login test.

## Verified public metadata

Sources (no credentials were used):

- https://mcp.vkusvill.ru/.well-known/oauth-protected-resource/mcp
- https://oauth.vkusvill.ru/.well-known/oauth-authorization-server

The protected resource is `https://mcp.vkusvill.ru/mcp` and its authorization
server is `https://oauth.vkusvill.ru/`.
Advertised resource scopes: `catalog.search`, `purchase_history.read`,
`discounts.view`, `recommendations.personalized`.
Authorization endpoint: `https://oauth.vkusvill.ru/oauth2/auth`.
Token endpoint: `https://oauth.vkusvill.ru/oauth2/token`.
PKCE S256 and the authorization-code and refresh-token grants are advertised.
The server advertises multiple client authentication methods; this does NOT
identify the method allowed for a particular registered client.
Authorization-server scopes differ from resource scopes. Confirm the client's
grants, including refresh permission, rather than blindly requesting all scopes.

## Required before enabling login

1. Register the client through https://vkusvill.ru/oauth/registration/.
2. Confirm its exact redirect URI and allowed token endpoint authentication method.
3. Choose the callback arrangement for the user's remote Hermes deployment.
4. Store credentials outside the repository and agent/model context; never paste
   a client secret, token, authorization code, or credential email into chat.

Metadata does not confirm these client-specific settings. Therefore no speculative
`auth login` command or guessed callback is shipped in this change.

## Next implementation checkpoints

- Use the official MCP SDK OAuth provider, with explicit login separate from shopping.
- Owner-only, atomic per-profile token/client/metadata storage; no token output.
- Absolute expiry persisted across restarts, discovery metadata persistence,
  refresh rotation and interprocess locking; revoked refresh requires login.
- Verify PKCE and state, callback cancellation/timeout, wrong-state rejection,
  concurrent 401 recovery, secret redaction and profile isolation against a local
  OAuth server before attempting a real account.
- Bind basket checks to the authenticated context and invalidate checks when it changes.
- Rediscover and review authenticated tool schemas; authorization alone does not
  prove availability, address selection, or permission to purchase.
- Real read-only acceptance requires the user to complete browser consent.
  Cart-share mutation remains explicitly opt-in; checkout/payment stay unsupported.

Do not import private Hermes modules into vv or share its mutable token files.
Hermes' OAuth regressions are design references, not proof of vv compatibility.
