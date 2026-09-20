# Changelog

All notable changes to this fork are recorded here from the point the release lifecycle was introduced.

The format follows Keep a Changelog conventions and the public product uses Semantic Versioning. Historical upstream tags are not releases of this fork.

## [Unreleased]

### Added
- Nothing yet.

### Changed
- Nothing yet.

### Fixed
- Nothing yet.

## [0.12.0] - 2026-09-20

### Added
- Read-only `termux-mcp update check` and `--json` output for stable release discovery.
- Release lifecycle policy, canonical version checks, CI release metadata gate, and configuration schema tracking.
- Component governance and operability model for explicit owners, desired state, topology, and recovery policy.
- Transactional update foundation: persistent-state snapshots, application snapshots, known-good state, managed-install guard, manifests, and coordinator rollback tests.

### Migration
- Configuration schema remains at `1`; no migration is required for this release candidate.

### Rollback
- Automatic update apply/rollback is not exposed to users in 0.12.0. This release only exposes update detection; existing installation/recovery procedures remain unchanged.

## Historical note

Before 0.12.0, the public fork reported package version `0.10.2`, while its `origin` product tags visible at lifecycle adoption ended at `v0.8.4`. The 0.12.0 release is intended to establish a deliberate new public baseline without rewriting that history.
