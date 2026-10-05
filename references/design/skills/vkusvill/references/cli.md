# Проект интерфейса vv, версия 1

Все команды ниже — **предлагаемый контракт**, пока не реализация. После реализации сверить с `vv --help` и `vv --json doctor`.

## Формат

Глобальный `--json` включает один JSON envelope в stdout. Диагностика — stderr, без секретов. Операции неинтерактивные, кроме отдельного `auth login`. Exit codes: 0 success; 2 invalid input; 3 auth required; 4 constraint/review required; 5 upstream/network; 6 incompatible schema; 7 unknown remote outcome.

```json
{
  "schema_version": 1,
  "ok": true,
  "data": {},
  "warnings": [],
  "meta": {"request_id": "opaque-id", "catalog_scope": "public", "retrieved_at": null}
}
```

Ошибка: ok=false, data=null, error={code,message,retryable}; никаких токенов или произвольных dump внутренних исключений. Неизвестные значения — null плюс причина, не 0.

## Команды и инструменты

| CLI | Официальное имя MCP |
|---|---|
| product search TEXT --page N --limit N --sort VALUE | vkusvill_products_search |
| product get ID [ID...] | vkusvill_product_details |
| product analogs ID | vkusvill_product_analogs |
| product barcode CODE | vkusvill_product_barcode |
| discount search TEXT --page N | vkusvill_products_discount |
| recipe search TEXT --page N | vkusvill_recipes |
| shop search TEXT --page N | vkusvill_shops |
| orders list --page N | vkusvill_orders_history |
| favorite show | vkusvill_product_lp |
| basket link NAME --checked-hash HASH | vkusvill_cart_link_create |

CLI-аргументы НЕ являются документацией параметров MCP. Точное преобразование реализуется после tools/list. Недоступный инструмент возвращает UNSUPPORTED_CAPABILITY.

## Локальные и служебные операции

`doctor` — версия CLI, поддерживаемый контракт, доступность MCP, auth status, состояние адресного контекста без адреса и токенов. Не запускает login.

`auth login | status | logout` — авторизация человека и управление локальными credentials; logout не обещает удалённую ревокацию, если она не подтверждена.

`profile show` — возвращает только разрешённые пользовательские предпочтения. Запись предпочтений не входит в первый MVP.

`basket import NAME --file REQUEST.json` — атомарное создание или новая ревизия локальной корзины; overwrite существующей ревизии должен быть явно запрошен. Request содержит выбранные id, а источник истины о товарах — provider snapshot.

`basket show NAME` — содержимое, ревизия, происхождение и последняя проверка.

`basket check NAME --refresh` — обновление фактов, проверки и estimate; возвращает check_hash. Никаких удалённых корзин/заказов не создаёт.

`basket link NAME --checked-hash HASH` — сверка снимка, проверка свежести и ограничений, затем запрос ссылки. Сама команда не означает оплату или подтверждённое согласие: авторизация действия обеспечивается доверенным слоем запуска.

`basket clone SOURCE TARGET` — позднее; копирует намерение покупки, но не переносит checked status и актуальность цен.

## Последовательность MVP

```sh
vv --json doctor
vv --json product search 'творог' --limit 5
# Заполняем request.json только id из ответа; при необходимости читаем details.
vv --json basket import breakfast --file request.json
vv --json basket check breakfast --refresh
# Только по запросу пользователя на ссылку и с реальным check_hash:
vv --json basket link breakfast --checked-hash '<hash-from-check>'
```

## Подтверждённые особенности поставщика

В ссылке 1–20 строк; q в пределах 0.01–40. Эти числовые пределы не определяют смысл единицы для каждого SKU. Наличие адресное и требует авторизации. История — сводки за 30 дней, не гарантированный состав заказа. Пагинация и фильтры неодинаковы у разных инструментов. Точные схемы необходимо получить при реализации.
