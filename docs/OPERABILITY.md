# Operability baseline

A demo is not considered finished until it is recoverable without chat history.

## Required for each persistent component
- `status`: version/build, process/service state, bind address/port, dependency/permission state.
- `doctor`: end-to-end checks, last error, last healthy timestamp, and a concrete recovery hint.
- Health checks test the real endpoint/protocol, not only PID existence.
- Auto-start for persistent services; auto-recovery only after a failed health check.
- Recovery actions write a reason and result to a short-retention log.
- Keep a compact runbook: architecture, ports, config locations, start/stop/recover commands.

## Termux-MCP stack acceptance
- Local REST responds.
- MCP initialize succeeds.
- OAuth/resource metadata is reachable.
- Public MCP endpoint is reachable through Cloudflare.
- Android Bridge reports actual APK/server build and accessibility state.
- Health/wearable integration reports provider and permission state explicitly.

## Failure drill before calling it done
Break one safe dependency at a time (for example stop the tunnel), run doctor, verify the fault is named, recover it, and verify health returns without rediscovery.
