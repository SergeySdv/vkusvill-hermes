# VkusVill × Hermes

Локальная CLI `vv` на Python + Typer + Pydantic и отдельный Hermes skill.
Hermes выбирает и объясняет, CLI проверяет структурированные данные.
Второго LLM, оформления заказа и оплаты здесь нет.

**Версия 0.1.0 — рабочий offline-каркас, не готовая интеграция с каталогом.**
Работают import/show/check, SQLite, ревизии, хеши и JSON-контракт.
product search/get/analogs и refresh возвращают `NOT_IMPLEMENTED`.
Создание ссылки блокируется при unknown; реальный переход в link_created
зарезервирован до реализации и проверки MCP. Поддельных товаров, цен и ссылок нет.

## Передать ссылку Hermes

Отправьте агенту:

> Установи себе этот скилл вместе с CLI по инструкции INSTALL.md:
> https://github.com/SergeySdv/vkusvill-hermes

[INSTALL.md](INSTALL.md) содержит полный порядок: штатная установка скилла,
изолированная установка CLI и проверка в terminal backend. Bootstrap не требует
uv и не меняет Python-зависимости Hermes. Нужны Python 3.11+ с venv/pip и Git.
Установка включает все reference-файлы и launcher, поэтому глобальный vv в PATH
не обязателен. После установки используется `/vkusvill`.

## Установка и быстрый запуск

Нужны Python 3.11+ и uv. Зависимости закреплены в `uv.lock`;
официальный MCP SDK ограничен major-версией 1.

```sh
uv sync --locked
uv run vv --version
uv run vv doctor --json
uv run vv basket import demo --file examples/request.json --json
uv run vv basket show demo --json
uv run vv basket check demo --json
uv run vv product search "творог" --json
```

Последняя команда закономерно завершается с кодом 1 и `NOT_IMPLEMENTED`.
Все рабочие команды по умолчанию возвращают один JSON, флаг `--json`
поддерживается и перед группой, и после подкоманды. Help и обычный
`--version` выводятся текстом; `vv --json --version` выводит JSON.

`examples/request.json` и `examples/basket.json` — импортируемые намерения
с явно условными ID, **не результаты ВкусВилла**. Второй файл показывает
несколько позиций. Импорт не проверяет существование товара.

Хранилище: `~/.local/state/vv/baskets.sqlite3`. Для отдельного окружения:
`VV_STATE_DIR=/absolute/private/directory`, `VV_PROFILE=personal`.
Профиль разделяет данные, но не аутентифицирует пользователя.
Каталог должен принадлежать одному доверенному пользователю ОС.

## Проверка и состояния

`draft → checked → link_created`; повторный импорт всегда создаёт новую
ревизию draft и удаляет прежнюю проверку. В этом каркасе достижимы только
draft и checked. checked означает завершённую локальную проверку,
а не разрешение отправить корзину провайдеру.

Хеш включает профиль, имя, ревизию, товары, ограничения и отчёт с временем
проверки и каталогом unverified. Срок проверки — 15 минут.
`basket link NAME --checked-hash HASH` отвергает устаревший/изменённый хеш
и unknown. Хеш не заменяет согласие пользователя и не защищает от владельца
файла БД. Ошибки не меняют сохранённую корзину.

Человеческие quantity/unit отделены от MCP q: 500 g нельзя отклонять как q > 40.
Локально объединяются одинаковые product_id с одинаковой единицей, максимум
20 разных товаров; смешанные единицы отклоняются. Отдельная модель
CartPayload проверяет xml_id, 1–20 уникальных SKU и q от 0.01 до 40.
Связывать product_id с xml_id и переводить единицы должен будущий
провайдерский нормализатор, только по подтверждённым данным.

Цена, наличие, состав, provider q и бюджет сейчас unknown, товарная сумма null.
Поля price, xml_id и другие лишние поля в импортируемом намерении запрещены.
Оценка товаров в будущем не будет означать стоимость доставки или резерв.

## Hermes

Установка по ссылке подробно описана в [INSTALL.md](INSTALL.md).
Для стандартного профиля и общего окружения skills/terminal:

```sh
hermes skills install SergeySdv/vkusvill-hermes/skills/vkusvill
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
python3 "$HERMES_HOME/skills/vkusvill/scripts/setup.py"
python3 "$HERMES_HOME/skills/vkusvill/scripts/vv.py" doctor --json
hermes skills list
```

Для нестандартного профиля задайте его фактический HERMES_HOME; для категории
используйте путь скилла, возвращённый установщиком. Runtime и состояние находятся
в HERMES_HOME/integrations/vkusvill, отдельно от зависимостей Hermes.
Bootstrap закрепляет CLI на полном Git commit SHA; повторный запуск переиспользует
успешно установленный runtime. Зависимости pip разрешаются в рамках pyproject;
для разработки с точными версиями используйте uv.lock.
В контейнере setup и launcher должны работать внутри terminal backend.
Установка на хост не делает CLI доступной в контейнере.
Штатные проверки безопасности Hermes сохраняются.
Реальный профиль Hermes при разработке не изменяется.

## Разработка

```sh
make check
make build
uv run pre-commit install
```

GitHub Actions проверяет Python 3.11–3.14. Тесты offline, без учётных данных.
Скилл находится вне Python wheel и распространяется из репозитория/sdist.

- [Контракт CLI](skills/vkusvill/references/cli.md)
- [Сценарии Hermes](skills/vkusvill/references/workflows.md)
- [План реализации и границы каркаса](IMPLEMENTATION_BRIEF.md)
- [Исходный пакет без изменений](references/design/README.md)
- [Разработка](CONTRIBUTING.md), [безопасность](SECURITY.md)

## Источники

Ограничения и разделение id/xml_id сверены с
[официальной страницей ВкусВилла](https://mcp.vkusvill.ru/mcp).
Транспорт основан на [официальном MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk);
структура скилла — на [документации Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/).
Проверено 2026-10-05; live tools/list и создание корзины не выполнялись.
MIT. Проект не является официальным продуктом ВкусВилла или Nous Research.
