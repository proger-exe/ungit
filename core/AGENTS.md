# core

## Роль

`core` = remote repo service Ungit.

Отвечает за:

- users + bearer tokens
- local object model: files -> index -> tree -> commit -> ref
- core service: repos, refs, payloads, agents, jobs
- remote между CLI и agent
- payload manifest/hash helpers
- optional croc subprocess boundary

Core хранит удалённые репозитории, payload push и pipeline jobs.

## HTTP MVP

```text
GET  /whoami
POST /repos
POST /agents
POST /agents/<agent_id>/tokens
POST /repos/<repo_id>/link-agent
POST /repos/<repo_id>/pipeline
POST /repos/<repo_id>/push
POST /agents/<agent_id>/jobs/claim
GET  /jobs/<job_id>/payload
POST /jobs/<job_id>/events
```

Default:

```text
http://127.0.0.1:8765
~/.local/share/ungit/core
```

Auth:

```text
Authorization: Bearer <token>
```

`/health` public. Остальное protected.

## CLI

```bash
ungit-core serve --host 127.0.0.1 --port 8765
ungit-core user create <login> --admin
```

## Delivery

Термины:

```text
delivery
delivery payload
delivery manifest
payload hash
pipeline job
```

Не использовать `pack`.

## Запрещено

- WebUI
- auth/cloud billing
- Kubernetes/SSH deploy
- agent release runtime
- storage symlink switching
