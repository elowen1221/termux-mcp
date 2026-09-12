# Termux-MCP: project overview

## What it is

Termux-MCP turns an Android phone running Termux into a remotely accessible MCP
gateway for AI clients. The Python service exposes device and shell capabilities
through Streamable HTTP, can host or import other MCP servers, and lets the phone
owner choose how much control the connected AI receives.

It is not merely an Android port of an MCP server. Its product value is the
complete path from a fresh phone to a controlled AI endpoint:

1. bootstrap and diagnose the Termux environment;
2. install a versioned Python service and its dependencies;
3. start the local REST and MCP endpoints;
4. create and verify a public tunnel when requested;
5. preserve credentials and runtime state across restarts;
6. let the user paste one URL into ChatGPT, Claude, or Grok;
7. let the connected AI install and operate additional MCP servers without
   sending the user back to the terminal.

## Who it is for

- people who found an MCP URL or GitHub project but do not know how to install it;
- users who want ChatGPT, Claude, or Grok to operate an Android phone through one URL;
- developers who want an inexpensive, portable MCP host.

## Why use this fork instead of the upstream project

The upstream project supplies the original Termux control foundation. This fork
keeps attribution and the REST API while adding an official-SDK MCP layer and a
deployment-focused product surface:

| Area | This fork's focus |
| --- | --- |
| Protocol | Streamable HTTP MCP endpoint built on the official Python SDK |
| Permissions | owner-selected read-only, standard, or full control |
| Architecture | REST and MCP share the same operation functions instead of proxying through localhost |
| Reliability | managed server/tunnel state, health checks, persistent OAuth state, isolated profiles |
| Compatibility | remote HTTP/SSE import plus common Python and Node.js GitHub MCP projects |
| Onboarding | one-line bootstrap, one short friendly setup, then one copy-ready URL |

## Product promise

A new user should paste one bootstrap command into a fresh Termux installation,
choose an AI and permission level, and receive the one URL needed by the client.
After that, normal installation and management should happen through conversation.

Compatibility is the default: imperfect third-party projects should get automatic
runtime detection and a useful fallback path, not be rejected for packaging style.
Security remains quiet infrastructure rather than onboarding friction. The owner
can explicitly choose full control; standard mode retains command-risk prompts.

## Success criteria

- clean install succeeds without manual Python or JSON editing;
- repeated installation preserves configuration and secrets;
- every failed setup stage names the failed operation and a concrete next step;
- start/stop/restart behavior does not silently invalidate a retained tunnel;
- MCP and REST paths remain covered by shared-operation and security tests;
- a zero-background user can reach a healthy endpoint from the README alone;
- an attached AI can import a remote MCP or common GitHub MCP project and call it
  without changing the client-facing gateway URL.
