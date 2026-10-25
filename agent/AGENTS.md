# agent

## Роль папки

`agent` — серверный исполнитель Ungit.

Агент забирает job/payload из core, проверяет payload, разворачивает релиз и выполняет deploy stages.

Главная цепочка:

```text
receive -> verify -> release -> preship -> ship -> switch -> postship -> health -> rollback if failed
```

## Главный принцип

Агент управляет только:

```text
/opt/ungitted/
```

Он не должен свободно писать куда угодно по файловой системе.

Если проект должен быть доступен по внешнему пути, используется symlink.

Пример:

```text
/var/www/app -> /opt/ungitted/projects/app/current
```

## Runtime структура

```text
/opt/ungitted/
  projects/
    <project>/
      releases/
        <commit>/
      shared/
      current -> releases/<commit>
      previous -> releases/<old_commit>
      logs/
        deploy-<deploy_id>.log
      state.json
```

Каталог релиза — commit id с `-` вместо `:` (`sha256-<hex>`): двоеточие ломает Docker `-v`, `PATH` и `scp`.

## MVP commands

```bash
ungit-agent run --name <agent-name> --core-url <url> --token <agent-token>
ungit-agent rollback <project>
```

Позже:

```bash
ungit-agent register --token <agent-token> --name <agent-name>
```

## Job receive

Агент получает job из core:

```bash
ungit-agent run --name prod --token <agent-token>
```

Поведение:

```text
1. authenticate agent token в core
2. claim queued job
3. download payload archive
4. проверяет payload hash
5. читает manifest
6. создаёт release
7. выполняет deploy stages
```

## Delivery payload

Агент принимает delivery payload из core.

Не использовать термин `pack`.

Payload может быть архивом:

```text
delivery.tar.gz
  manifest.json
  files/
  commit.json
  tree.json
```

## Verify

Агент обязан проверить:

```text
payload_hash
project
branch
commit
manifest format
```

Если есть service-api:

```text
job_id
agent_id
expected payload_hash
```

## Deploy stages

Deploy scripts находятся в проекте:

```text
.ungit/deploy/
  preship.sh
  ship.sh
  postship.sh
  health.sh
```

Порядок выполнения строго фиксирован:

```text
1. preship.sh
2. ship.sh
3. switch current -> new release
4. postship.sh
5. health.sh
```

## Exit code contract

```text
0    success
!=0  failure
```

Поведение при ошибках:

```text
preship failed  -> stop deploy, current не трогать
ship failed     -> stop deploy, current не трогать
postship failed -> rollback
health failed   -> rollback
```

## Environment variables

Каждый stage получает:

```bash
UNGIT_PROJECT="<project>"
UNGIT_BRANCH="<branch>"
UNGIT_COMMIT="<commit>"
UNGIT_PREVIOUS_COMMIT="<previous_commit>"

UNGIT_ROOT="/opt/ungitted/projects/<project>"
UNGIT_RELEASE="/opt/ungitted/projects/<project>/releases/<commit>"
UNGIT_CURRENT="/opt/ungitted/projects/<project>/current"
UNGIT_PREVIOUS="/opt/ungitted/projects/<project>/previous"
UNGIT_SHARED="/opt/ungitted/projects/<project>/shared"

UNGIT_STAGE="preship|ship|postship|health"
```

## Release process

Агент делает:

```text
1. create release dir
2. copy/extract files into release dir
3. copy deploy scripts
4. run preship
5. run ship
6. switch current symlink
7. run postship
8. run health
9. update state
```

## Rollback

Rollback:

```text
current -> previous
write status
write log
```

В MVP достаточно откатить symlink и записать лог.

## Logging

Лог должен быть линейным:

```text
[job] claimed
[payload] downloaded
[verify] ok
[release] created
[preship] started
[preship] ok
[ship] started
[ship] ok
[switch] current -> releases/<commit>
[postship] ok
[health] ok
[deploy] success
```

При ошибке:

```text
[health] failed exit=1
[rollback] started
[rollback] success
```

## Запрещено в agent

Не добавлять сюда:

- core object model
- CLI parsing
- WebUI
- YAML pipeline parser
- сложные environments
- Kubernetes
- SSH deploy
- multi-agent orchestration

Агент должен быть тупым исполнителем. Тупой исполнитель лучше умного комбайна, потому что умные комбайны потом требуют DevOps-а для самого DevOps-а.
