# Відтворення ПР3

Команди виконуються в Bash у корені проєкту з доступним Docker Linux engine.
Під час запуску тег `python:3.15.2-alpine` у Docker Hub уже вказував на інший
digest, ніж у наданому `tests/images.lock.json`. Для відтворення перевіреного
оточення спочатку завантажте саме образи з lock-файла та прив'яжіть до них
очікувані локальні теги. Тести й lock-файл не змінювалися.

```sh
docker pull python@sha256:20a82dbc2783112ddb91d1534603f802d222a3e63e593cd002eb2ac534e70211
docker tag python@sha256:20a82dbc2783112ddb91d1534603f802d222a3e63e593cd002eb2ac534e70211 python:3.15.2-alpine
docker pull docker@sha256:5e6baf67325a79f64ed3bed6863954d5e05d0f3d4e57cbdb14809346814bbfdb
docker tag docker@sha256:5e6baf67325a79f64ed3bed6863954d5e05d0f3d4e57cbdb14809346814bbfdb docker:29.9.2-cli
cp .env.example .env
sh tests/compose.sh pr03 up -d --build
sh tests/check.sh pr03
sh tests/compose.sh pr03 down
sh tests/compose.sh pr03 up -d
sh tests/check.sh pr03
```

Не виконуйте `docker pull python:3.15.2-alpine` між підготовкою та перевіркою:
це знову оновить локальний тег до поточного upstream-образу. Автоматичний
протокол створює тільки `tests/check.sh`; цей файл є інструкцією запуску.
