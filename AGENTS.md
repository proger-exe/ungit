# Agent Sector

## Назначение

`agent` отвечает за серверную сторону Ungit.

Агент принимает croc delivery, проверяет payload, разворачивает релиз в `/opt/ungitted`, выполняет deploy-стадии и делает rollback при ошибке.

Агент не должен быть Git-клиентом, WebUI, API-сервером или системой сборки. Его задача тупая и святая:

```text
receive → verify → release → scripts → health → rollback