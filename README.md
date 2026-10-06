# VkusVill × Hermes

Рабочий Hermes skill и отдельная CLI `vv` для публичного MCP ВкусВилла.
Версия **0.3.0**: десять MCP-адаптеров, проверка корзины и
создание ссылки. Без второго LLM, оформления заказа и оплаты.

## Отправить Hermes

> Установи или обнови себе этот скилл вместе с CLI по INSTALL.md:
> https://github.com/SergeySdv/vkusvill-hermes
> После установки найди молоко и хлеб, покажи варианты и создай тестовую ссылку.

[INSTALL.md](INSTALL.md) описывает установку через штатный skills hub и отдельное
Python-окружение. Нужны Python 3.11+ с venv/pip, Git и доступ к сети.
Глобальный vv в PATH не нужен: со скиллом поставляется launcher.
Bootstrap закреплён на Git commit; проверяет реальное соединение через doctor --live.

## Что работает

Реализованы адаптеры **10/10** объявленных MCP tools. Bootstrap закреплён
на CLI 0.3.0, commit `02bee28cd9f5a7fc563da9635ee4d5519873c936`.
Для существующей установки обновите скилл и повторите setup по INSTALL.md.

`make release-check` проверяет чистую установку неизменённого скилла, фактический
commit и файлы установленного CLI, обновление прежнего runtime, сохранность
корзин и восстановление после ошибок. Подробности: [release gate](e2e/README.md#release-gate).

- `product search` — реальные товары, до 10 на страницу, `--page`.
- `product get` и `product analogs` — карточка и кандидаты на замену.
- `product barcode` — карточка по строке из 13 цифр, включая ведущие нули.
- `discount search` — акции по типу и сортировке; текстового поиска в живой схеме нет.
- `recipe search` и `shop search` — рецепты/магазины, фильтры и страницы.
- `orders list` и `favorite show` — адаптеры персональных tools, без OAuth — AUTH_REQUIRED.
- `basket import/show` — локальное намерение и сохранённое состояние.
- `basket check --refresh` — свежие карточки, xml_id, количества и оценка товаров.
- `basket link --checked-hash HASH` — повторное чтение карточек, сравнение,
  проверка ограничений и настоящая share-ссылка.

Публичный каталог работает **без входа**. Наличие по адресу, региональная цена,
доставка и персональные скидки не проверены. Это явно возвращается как unknown.
OAuth пока не реализован; успешные персональные ответы не проверены на аккаунте.
Наличие адаптеров не означает доступ к личным данным. Ссылка ничего не оформляет и не оплачивает.
Подтверждённый discovery и условия следующего этапа: [OAuth onboarding](references/oauth-onboarding.md).

## Быстрый запуск для разработчика

```sh
uv sync --locked
uv run vv doctor --live --json
uv run vv product search "молоко" --limit 3 --json
uv run vv product get 36296 --json
```

Используйте product_id из свежего поиска. Запишите собственный request по
examples/request.json, затем:

```sh
uv run vv basket import dinner --file request.json --json
uv run vv basket check dinner --refresh --json
uv run vv basket link dinner --checked-hash HASH_FROM_CHECK --json
```

Без --refresh проверка остаётся локальной и не разрешает создание ссылки.
Примеры JSON содержат условные ID, не имитируют ответы магазина.
Каждая рабочая команда возвращает один JSON с schema_version/ok/data/error/warnings/meta.
Ошибки — exit 1, успех — exit 0. --json допустим до группы или после подкоманды.

## Ограничения

product_id и xml_id разрешаются отдельно по реальной карточке. Импорт не принимает
цены или xml_id от агента. Поддерживаются целые piece/package для продажи «шт»,
kg/g для продажи «кг» с точностью 0.01 кг. Другие преобразования блокируются.
Ограничения ссылки: 1–20 SKU после объединения, q от 0.01 до 40.
Реальная inputSchema сейчас указывает maxItems=30, но описание провайдера и
наш контракт ограничены 20; более строгий предел сохранён.

Бюджет — оценка товаров в RUB, не окончательная стоимость с доставкой.
Неизвестная цена не равна нулю. Строгие исключения по составу не считаются
выполненными по отсутствию слова: unknown блокирует ссылку.
Наличие — advisory unknown; если пользователь требует подтверждённое наличие,
задайте constraints.require_availability=true: без авторизации ссылка блокируется.

Состояния draft → checked → link_created. Повторный импорт сбрасывает проверку.
Хеш связывает профиль, ревизию, товары, ограничения и снимки; TTL 15 минут.
Материальное изменение перед ссылкой → REVIEW_REQUIRED. Повтор успешной команды
с тем же свежим хешем возвращает сохранённую ссылку. Обрыв результата →
OUTCOME_UNKNOWN и запрет автоматического повтора/изменения этой корзины.
pending после сбоя процесса также требует разбора; это не идемпотентность сервера.
Хеш не является согласием пользователя или защитой от владельца БД.

## Hermes и хранение

```sh
hermes skills install SergeySdv/vkusvill-hermes/skills/vkusvill
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
python3 "$HERMES_HOME/skills/vkusvill/scripts/setup.py"
python3 "$HERMES_HOME/skills/vkusvill/scripts/vv.py" doctor --live --json
```

Для существующей установки следуйте разделу обновления INSTALL.md.
Runtime и корзины launcher находятся в HERMES_HOME/integrations/vkusvill.
Для прямого vv по умолчанию используется ~/.local/state/vv.
VV_STATE_DIR и VV_PROFILE переопределяют хранилище/namespace; профиль не является
аутентификацией. Устанавливайте runtime в реальном terminal backend, в том числе
в контейнере. Установка на хост не распространяется на контейнер автоматически.

## Проверка и архитектура

`make check` — offline-тесты и Ruff; `make build` — wheel/sdist.
CI: Python 3.11–3.14. Скилл распространяется из репозитория/sdist, отдельно от wheel.
`make test-protocol` — CLI + настоящий локальный MCP; `make e2e-smoke` —
изолированный Hermes Docker smoke без модели. Прогоны с реальной моделью:
[E2E-стенд и границы проверки](e2e/README.md).
Исходный проектный пакет сохранён без изменений в references/design.

[Контракт CLI](skills/vkusvill/references/cli.md) ·
[Сценарии](skills/vkusvill/references/workflows.md) ·
[MCP и границы доверия](references/mcp.md) ·
[План](IMPLEMENTATION_BRIEF.md) · [Безопасность](SECURITY.md)

Инструменты и схемы проверены на [официальном сервере](https://mcp.vkusvill.ru/mcp)
2026-10-05. Проект использует [официальный Python SDK](https://github.com/modelcontextprotocol/python-sdk).
MIT. Неофициальная интеграция, не продукт ВкусВилла или Nous Research.
