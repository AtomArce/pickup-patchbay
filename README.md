# Pickup Patchbay

**A one-person VFX shop's local AI patchbay: a router agent and local models, plugged into production software, aiming to learn from their own mistakes.**

Pickup Patchbay is an independent, local-first project. It connects language models running on hardware I own to the software a VFX pipeline runs on, through one typed, logged interface. It is built on a small budget on purpose, with no studio behind it. Pickup rules: show up with what you have, make it work.

## What it does
- **Router agent** (in progress): describe what a shot needs, such as "I need smoke for this scene". The agent returns ranked options, then a verified how-to guide or a dispatched job. A small decision layer does the ranking and gates risky actions, and every call is logged.
- **Integrations** (in progress): scripts and MCP servers that let a local model operate DCC and production-tracking software through the same interface.
- **Local compute** (working): models run on modest, local hardware. Rented GPUs are used only for short, approved bursts.
- **Self-improving agents** (planned): agents that review their own runs and patch their own skills and prompts, checked against held-out tasks.

## How it is built
In the open where possible, with every tool, machine and budget choice written down along with the evidence for it. Claims are marked verified (it was run) or unverified.

Project page: https://atomarce.github.io/pickup-patchbay/
