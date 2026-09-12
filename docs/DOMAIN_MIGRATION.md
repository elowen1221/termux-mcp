# Domain migration

The public domain is an replaceable edge layer, not permanent application state.
Keep service names stable (`termux`, `weather`, `alpaca`) and move the base domain
when renewal pricing makes that worthwhile.

## Safe workflow

1. Preview Cloudflare ingress changes. This does not write anything:

   `termux-mcp domain plan NEW_DOMAIN --from-domain OLD_DOMAIN`

2. Preview known local URL/config changes. Secret values are never printed:

   `python scripts/domain-migrate.py OLD_DOMAIN NEW_DOMAIN`

3. Apply and validate Cloudflare ingress. Add `--no-dns` for a staged migration:

   `termux-mcp domain migrate NEW_DOMAIN --from-domain OLD_DOMAIN --tunnel TUNNEL_NAME`

4. Apply local URL rewrites:

   `python scripts/domain-migrate.py OLD_DOMAIN NEW_DOMAIN --apply`

   Every changed file receives a sibling `.before-domain-TIMESTAMP` backup.

5. Restart affected services / the named tunnel, then run:

   `python scripts/domain-health.py NEW_DOMAIN`

6. Only after all routes are healthy, reconnect clients/OAuth integrations to the
   new URLs. Keep the old domain/routes available during the cutover when possible.

## Current known rewrite targets

The local migration helper checks the core Termux-MCP env, weather env, Alpaca env,
stack launcher, weather server/launcher, and Alpaca wrapper. Missing optional private
env files are skipped; missing required project files abort the plan.

The helper deliberately does not scan the whole home directory or rewrite arbitrary
files. New public services should be added to the explicit target list and health
check list when they become part of the stack.
