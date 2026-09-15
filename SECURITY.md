# Security Policy

Termux-MCP can execute commands, access files, control supported Android UI actions, and expose an MCP endpoint over the network. Treat it as a privileged remote-control surface for your own device.

## Safe defaults

- Keep the default `standard` permission mode unless you have a specific reason to change it.
- Use `read-only` when an agent only needs inspection access.
- `full` is a trusted-agent mode. It can bypass normal command-risk confirmations and should not be used with agents, prompts, or MCP clients you do not fully trust.
- Keep authentication enabled on every remotely reachable endpoint. TLS alone is not authentication.
- Never publish or screenshot the output of `termux-mcp token --show`.
- Do not commit `~/.config/termux-mcp/`, OAuth state, Cloudflare credentials, private keys, tokens, or local extension configuration.
- Prefer a private/local connection when public Internet access is unnecessary.
- If you expose Termux-MCP through a reverse proxy or tunnel, preserve the `Authorization` header and use HTTPS.

## Threat model

Termux-MCP is designed primarily for a device owner connecting a trusted AI client to their own Android/Termux environment. It is **not** a sandbox for mutually untrusted users or arbitrary agents.

The project includes permission modes, authentication, command risk classification, confirmation gates, path checks, snapshots before writes, and trash-based deletion. These controls reduce risk; they do not turn arbitrary shell access into a secure multi-tenant sandbox.

Prompt injection is also part of the threat model. An AI with shell or Android-control permissions may act on malicious instructions found in files, webpages, messages, or third-party MCP output. Grant only the capabilities needed for the task.

## If a credential is exposed

1. Rotate the affected token or credential immediately.
2. Revoke affected OAuth sessions/clients where applicable.
3. Remove the secret from the working tree and public history if it was committed.
4. Review recent logs and device activity for unexpected actions.

Do not rely on deleting a GitHub file or commit alone: secrets can remain in Git history, forks, caches, and clones.

## Reporting a vulnerability

Please do **not** open a public issue for an unpatched vulnerability or include live credentials, tokens, personal data, or exploit details in a public discussion.

Use GitHub private vulnerability reporting for this repository when it is available. If private reporting is unavailable, open a minimal public issue that contains no exploit details or secrets and asks the maintainer for a private contact channel.

A useful report includes the affected version/commit, impact, reproduction conditions, and a minimal proof of concept with all credentials and personal data removed.

## Supported versions

Security fixes currently target the latest commit on `main`. Older commits and personal forks may not receive fixes.
