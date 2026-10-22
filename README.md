# ungit

<!-- portfolio-card:start -->
[![ungit — Версии и доставка кода без Git-сервера.](docs/portfolio/card.png)](docs/portfolio/card.svg)
<!-- portfolio-card:end -->

Отправить конкретную версию проекта на свой сервер и вернуть предыдущую, если проверка после установки завершилась ошибкой. В ungit команда `push` запускает этот путь целиком: от снимка файлов до выпуска релиза.

Инструмент рассчитан на небольшие self-hosted проекты. Он хранит объекты, индекс, деревья и коммиты локально; серверный агент принимает пакет, проверяет его и выполняет сценарии развёртывания. Git-сервер для этого не нужен.

```
ungit init        # create .ungit/ in the project
ungit add .       # hash files into the index
ungit push        # build a commit, send the payload to the remote agent
ungit log / status / remote
```

## Что здесь можно оценить

Модель версий связана с жизненным циклом релиза: после deploy-скриптов агент запускает `health.sh` и при ненулевом коде завершения откатывается к предыдущему релизу. Это пример собственной CLI-утилиты с серверной частью и явным протоколом доставки.

Python-код использует стандартную библиотеку. Для передачи пакетов предусмотрен внешний процесс croc; постоянно работающий клиентский демон не требуется.

Обсудить похожий проект: [sh3l.beer](https://sh3l.beer).

## Компоненты

| Пакет | Назначение |
|---|---|
| `core/` | модель объектов, пользователи и bearer-токены, репозитории, ссылки, пакеты, задания и протокол CLI ↔ агент |
| `storage/` | локальное хранилище `.ungit/`: объекты, ссылки и индекс |
| `cli/` | команда `ungit` |
| `agent/` | приём, проверка и выпуск релиза, deploy-скрипты, health-check и откат при ошибке; релизы хранятся в `/opt/ungitted` |

Для передачи пакетов предусмотрена интеграция с [croc](https://github.com/schollz/croc) через отдельный процесс.

## Этапы развёртывания

Агент последовательно выполняет скрипты из отправленного дерева файлов:

```
.ungit/deploy/preship.sh
.ungit/deploy/ship.sh
.ungit/deploy/postship.sh
.ungit/deploy/health.sh    # non-zero exit → rollback to the previous release
```

## Установка

```bash
./install.sh            # venv + editable install of all four packages, adds ungit to PATH
ungit --help
```

## Проверки

```bash
.venv/bin/pytest -q
```

Контракт каждого пакета описан в его `AGENTS.md`.

## Лицензия

MIT
