# cli

## Роль папки

`cli` — главный пользовательский интерфейс Ungit.

CLI должен быть простым:

```text
init
add
push
log
status
remote
pipeline
```

Главный UX:

```bash
ungit init
ungit add .
ungit push master -c "initial deploy"
```

Cloud UX:

```bash
ungit login --core-url <core-url> --token <token>
ungit remote add origin <core-url>/<repo-name>
ungit pipeline add <agent-name>
ungit add .
ungit push master -c "initial deploy"
```

## Философия CLI

В Ungit `push` — главная команда.

В MVP:

```text
push = create commit + build delivery payload + upload to remote core
```

Не заставлять пользователя делать:

```text
add -> commit -> push -> deploy
```

Это как раз та обрядовая хрень, от которой Ungit должен избавлять.

## MVP commands

Обязательные:

```bash
ungit init
ungit add .
ungit status
ungit log
ungit push <branch> -c "<comment>"
ungit login --core-url <core-url> --token <token>
ungit whoami
ungit agent register <agent-name>
```

Для remote/pipeline MVP:

```bash
ungit remote add origin <core-url>/<repo-name>
ungit pipeline add <agent-name>
ungit push <branch> -c "<comment>"
```

Для cloud/API MVP:

```bash
ungit remote add origin <core-url>/<repo-name>
ungit pipeline add <agent-name>
ungit pipeline list
```

## `ungit init`

Создаёт:

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

Deploy-файлы можно создать пустыми или с минимальным шаблоном.

## `ungit add`

Добавляет файлы в index.

Игнорировать:

```text
.ungit/
.git/
node_modules/
.venv/
__pycache__/
*.pyc
```

Позже добавить поддержку:

```text
.ungitignore
.gitignore
```

## `ungit push`

Основная команда.

Локально делает:

```text
1. читает index
2. создаёт tree
3. создаёт commit
4. обновляет branch ref
5. создаёт delivery payload
6. считает payload hash
7. uploads payload to remote core
8. core creates pipeline jobs
```

## Delivery

CLI не должен сам деплоить.

Граница:

```text
cli -> core remote push -> agent jobs
```

CLI не деплоит сам. Он пушит в remote core.

## Output style

Вывод должен быть линейным:

```text
[commit] created sha256:abc
[delivery] payload prepared
[remote] pushed master -> push_123
[pipeline] queued 2 jobs
```

Не рисовать pipeline-графы. Не делать YAML-театр.

## Auth

`ungit login --core-url <url> --token <token>` сохраняет user token не в `.ungit`.

Использовать:

```text
~/.config/ungit/credentials.json
```

В `.ungit/config.json` хранить только repo metadata:

```json
{
  "repo_id": "repo_123",
  "project": "minejust-panel",
  "default_branch": "master",
  "remotes": {
    "origin": {
      "core_url": "http://127.0.0.1:8765",
      "repo_id": "repo_123",
      "project": "minejust-panel",
      "pipeline": ["agent_123"]
    }
  }
}
```

Agent token печатать один раз:

```bash
ungit agent register prod-1
```

Не сохранять agent token в repo config.

## Pipeline

Команда:

```bash
ungit pipeline add <agent-name>
```

Делает:

```text
1. ищет agent через API
2. проверяет доступ
3. добавляет agent в repo pipeline
4. сохраняет local pipeline cache в .ungit/config.json
```

agent = deploy destination.

## Запрещено в cli

Не добавлять сюда:

- release runtime
- symlink switching
- прямую работу с `/opt/ungitted`
- WebUI
- сложные branch workflows
- merge/rebase
- YAML pipeline parser

CLI должен быть интерфейсом, а не комбайном. Комбайны уже есть, они и бесят.
