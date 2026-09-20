# Release policy

Termux-MCP uses an explicit promotion pipeline. A Git commit is not a release.

## Repository roles

- `walnut-playground` (private): ideas, demos, disposable prototypes.
- `walnut-private` (private): device-specific operations, private integrations, snapshots.
- `work/upstream-integration`: public-product development and release candidates.
- `origin/main`: stable installable product state only.
- `upstream/main`: external upstream reference. Its tags and version numbers are not releases of this fork.

## Version source of truth

`pyproject.toml` `[project].version` is canonical. `termux_mcp.__version__` must equal it. A product release tag must be exactly `v<canonical-version>` and point at the release commit on `origin/main`.

Tags fetched from `upstream` are external history and MUST NOT be interpreted as releases of `origin`.

## Promotion flow

`playground -> work/upstream-integration -> release gate -> origin/main -> origin tag/release -> updater`

Private/device-specific work goes to `walnut-private`, not through the public promotion flow.

## Release gate

Before a public release:

1. version consistency check passes;
2. full test suite and static checks pass;
3. clean-checkout/install test passes;
4. release notes / CHANGELOG entry exists;
5. configuration migrations required by the release are defined and tested;
6. build artifacts are reproducible enough to identify by checksum;
7. post-upgrade `termux-mcp doctor` succeeds on the supported path;
8. rollback target and recovery instructions are known.

## Update contract

The future updater is transactional: inspect installed version -> check target release -> snapshot mutable configuration -> install/migrate -> run doctor -> commit the update. If validation fails, restore the previous known-good application/config state when safe and report the failed stage.

Do not implement update as an unqualified `git pull` of a development branch.

## Version numbering

Do not choose a new public version merely by looking at local `git tag`: the worktree also fetches external upstream tags. Select the next fork version deliberately from the `origin` release history and document it in the release candidate.
