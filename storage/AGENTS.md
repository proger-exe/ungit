# storage

## Роль папки

`storage` отвечает только за физическое хранение данных.

Storage не знает бизнес-логику:

- deploy
- croc
- agent stages
- API
- WebUI
- license
- auth

Storage просто безопасно читает и пишет данные.

## Локальное хранилище проекта

```text
.ungit/
  config.json
  index.json
  HEAD
  refs/
    heads/
      master
  objects/
    blobs/
    trees/
    commits/
  deploy/
    preship.sh
    ship.sh
    postship.sh
    health.sh
```

## Agent runtime storage

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

## Главный принцип

Правильно:

```text
core решает, что хранить
storage решает, как безопасно записать
```

Неправильно:

```text
storage сам решает, как делать deploy
```

## Object storage

Объекты хранятся по типам:

```text
.ungit/objects/blobs/<hash>.json
.ungit/objects/trees/<hash>.json
.ungit/objects/commits/<hash>.json
```

Для MVP использовать JSON-файлы. Не тащить SQLite/PostgreSQL в MVP, потому что продукт ещё не деплоит, а люди уже хотят миграции. Классика дурдома.

## Atomic writes

Все важные записи должны быть атомарными.

Алгоритм:

```text
1. write temp file
2. flush
3. rename temp -> final
```

Применять к:

```text
index.json
HEAD
refs
state.json
config.json
```

## Refs

Branch ref:

```text
.ungit/refs/heads/master
```

Содержимое:

```text
sha256:...
```

## HEAD

Для MVP:

```text
ref: refs/heads/master
```

## Index

Path:

```text
.ungit/index.json
```

Storage должен уметь:

```text
read_index()
write_index()
clear_index()
```

## Runtime state

```json
{
  "project": "test-app",
  "current_commit": "sha256:abc",
  "previous_commit": "sha256:def",
  "current_release": "/opt/ungitted/projects/test-app/releases/sha256-abc",
  "previous_release": "/opt/ungitted/projects/test-app/releases/sha256-def",
  "last_deploy_status": "success"
}
```

## Release directories

Storage/runtime создаёт:

```text
/opt/ungitted/projects/<project>/releases/<commit>/
```

И поддерживает:

```text
current -> releases/<commit>
previous -> releases/<old_commit>
```

## Symlink switch

Переключение current:

```text
1. определить old current
2. создать current.tmp -> releases/<new_commit>
3. atomic rename current.tmp -> current
4. обновить previous
5. обновить state.json
```

## Logs

Deploy logs:

```text
/opt/ungitted/projects/<project>/logs/deploy-<deploy_id>.log
```

Логи append-only.

## Public API MVP

Storage должен предоставить функции уровня:

```text
ensure_repository(path)
read_json(path)
write_json_atomic(path, data)

write_object(object_type, object_id, data)
read_object(object_type, object_id)
has_object(object_type, object_id)

read_ref(branch)
write_ref(branch, commit_id)

ensure_agent_project(root, project)
create_release(root, project, commit_id)
switch_current(root, project, commit_id)
rollback_current(root, project)
write_state(root, project, state)
read_state(root, project)

append_log(root, project, deploy_id, line)
```

## Запрещено в storage

Не добавлять сюда:

- croc
- HTTP
- auth
- deploy stages
- subprocess hooks
- CLI parsing
- WebUI
- business rules

Storage должен быть скучным. Весёлый storage обычно заканчивается потерей данных и ночным матом.
