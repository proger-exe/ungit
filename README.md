# ungit

A tiny version-control-and-deploy tool that is not git. Snapshot a directory, push the snapshot to a server, and let an agent there release it with health checks and automatic rollback. Pure Python standard library, no daemons on the client, no git.

```
ungit init        # create .ungit/ in the project
ungit add .       # hash files into the index
ungit push        # build a commit, send the payload to the remote agent
ungit log / status / remote
```

## Why

For small self-hosted projects the real question is not "how do I version this" but "how do I get this exact tree onto the box and roll back if it breaks". ungit keeps the object model of a VCS (files → index → tree → commit → ref) and makes `push` the deploy.

## Parts

| Package | Role |
|---|---|
| `core/` | object model, users and bearer tokens, repos / refs / payloads / jobs, remote protocol between CLI and agent |
| `storage/` | local `.ungit/` layout: objects, refs, index |
| `cli/` | `ungit` command |
| `agent/` | server side: receive → verify → release → run deploy stages → health check → rollback on failure. Releases live under `/opt/ungitted`. |

Payloads are transferred with [croc](https://github.com/schollz/croc) as an optional subprocess boundary.

## Deploy stages

The agent runs scripts from the pushed tree, in order:

```
.ungit/deploy/preship.sh
.ungit/deploy/ship.sh
.ungit/deploy/postship.sh
.ungit/deploy/health.sh    # non-zero exit → rollback to the previous release
```

## Install

```bash
./install.sh            # venv + editable install of all four packages, adds ungit to PATH
ungit --help
```

## Tests

```bash
.venv/bin/pytest -q
```

Each package has its own `AGENTS.md` with the design contract for that part.

## License

MIT
