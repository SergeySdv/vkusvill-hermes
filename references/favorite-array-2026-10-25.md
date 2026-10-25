# Nonempty favorite response

Owner diagnostic at 2026-10-25T02:19:19Z: orders parser accepts the empty history;
favorite input schema matches and provider ok=true, but data is a nonempty array
of objects. Sample fields: id/string, name/string, unit/string, price/object.
Additional fields are present. No credential values or product values were logged.
The previous empty-only fix rejected this at the envelope boundary.

Successful favorite arrays are now accepted with validation of the observed
fields. Empty retains product=null; nonempty becomes products=[...] with every
element and additional field preserved. Existing object responses are unchanged.
This is not an implementation of ordinary saved favorites or a mutation command.
No price subfield semantics or discount eligibility are inferred.

Tests cover single/multiple products, malformed fields, existing empty and
provider-error handling, plus a real local SDK/CLI protocol test. Production
acceptance requires the owner to request favorite show after coordinated rollout.
Authorization is neither reset nor re-entered for this update.
