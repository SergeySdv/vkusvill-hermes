# vv 0.2.0: контракт

Запуск: `python3 <путь-скилла>/scripts/vv.py ...`; далее vv — это сокращение.
HERMES_HOME должен соответствовать активному профилю и установке.

| Команда | Поведение |
| --- | --- |
| vv --version | Текст; vv --json --version возвращает envelope |
| vv doctor --json | Локальное хранилище и возможности |
| vv doctor --live --json | Дополнительно discovery и один реальный публичный поиск |
| vv product search TEXT --limit 5 --page 1 --json | Реальные товары; limit 1–10, page 1–99999 |
| vv product get PRODUCT_ID --json | Карточка по id, не xml_id |
| vv product analogs PRODUCT_ID --json | Кандидаты-аналоги |
| vv basket import NAME --file request.json --json | Новая ревизия draft, прежняя проверка сбрасывается |
| vv basket show NAME --json | Корзина, отчёт и сохранённая ссылка |
| vv basket check NAME --json | Только локальная проверка |
| vv basket check NAME --refresh --json | Свежие карточки, суммы, ограничения, hash |
| vv basket link NAME --checked-hash HASH --json | Перепроверка фактов и реальная ссылка |

Один JSON в stdout; ok=true → exit 0, ошибка → exit 1.
Оболочка: schema_version=1, ok, data, error, warnings, meta.
error содержит code/message/retryable. Ветвление — по code, не тексту.
Метаданные: cli_version, request_id. Флаг --json поддерживается перед группой
или после подкоманды. Help и обычный --version выводятся текстом.

## Запрос корзины

```json
{
  "schema_version": 1,
  "items": [
    {"product_id": 36296, "quantity": "1", "unit": "piece"}
  ],
  "constraints": {
    "currency": "RUB",
    "max_goods_total": "500.00",
    "hard_exclusions": [],
    "preferences": [],
    "require_availability": false
  }
}
```

ID здесь — пример реальной карточки на момент разработки. Для новой покупки
возьми свежий результат поиска. quantity — положительная decimal-строка.
unit: piece/package/kg/g/l/ml; l/ml пока не преобразуются автоматически.
Другие поля, цены и xml_id в запросе запрещены. Файл ≤1 MiB; до 1000 исходных
строк, после нормализации 1–20 product_id. Имена: 1–64 ASCII буквы/цифры/_/-.
Одинаковые id с разными человеческими единицами отклоняются.
Перед отправкой объединяются xml_id; 1–20 SKU, q ∈ [0.01,40].
Для шт требуются целые piece/package; для кг — kg/g с точностью 0.01 кг.
Шаг и окончательная фасовка дополнительно проверяются самим магазином.

## Отчёт

scope=local_only или public_live. products — подтверждённые карточки со временем,
источником и отдельными product_id/xml_id. payload — вычисленный вход cart tool.
goods_total — decimal-строка или null; это оценка товаров без доставки.
checks: status=pass/fail/unknown, evidence, blocking.

Строгие исключения, количество, id и заданный бюджет — blocking.
При hard_exclusions любое отсутствие доказательства даёт unknown; совпадение
исключения с составом/аллергенами блокирует как fail.
Наличие в публичном режиме unknown; blocking только при require_availability=true.
Неизвестная цена блокирует заданный бюджет, иначе показывается как неизвестная оценка.

## Состояния и ошибки

draft → checked → link_created. TTL проверки 15 минут. Хеш охватывает профиль,
имя, ревизию, запрос, факты и проверки. Перед отправкой карточки читаются заново.
Изменения требуют нового check/review. Повтор с тем же свежим хешем после успеха
возвращает сохранённую ссылку, не создаёт ещё одну.
link_attempt=pending/unknown запрещает повторы, check и перезапись корзины.
После неоднозначного результата нужен ручной разбор, не новая отправка.
Хеш — защита от случайного устаревания, не согласие пользователя/контроль доступа.

| code | Действие |
| --- | --- |
| SETUP_REQUIRED | Только launcher: установить runtime по явному запросу |
| INVALID_INPUT | Исправить аргументы/JSON |
| CONSTRAINT_FAILED | Исправить нарушенные ограничения |
| REVIEW_REQUIRED | Обновить проверку/разобрать unknown или изменившиеся факты |
| OUTCOME_UNKNOWN | Не повторять создание ссылки и не обходить блокировку |
| AUTH_REQUIRED | Публичный вызов недоступен без входа; OAuth ещё не реализован |
| SCHEMA_CHANGED | Разработчик должен проверить контракт; ничего не угадывать |
| NETWORK_ERROR | Ошибка безопасного чтения; возможен ограниченный повтор |
| PROVIDER_ERROR | Инструмент/провайдер сообщил ошибку |
| NOT_FOUND / STORAGE_ERROR / INTERNAL_ERROR | Проверить имя/профиль/локальную среду |

CLI не открывает браузер, не принимает токены, не оформляет и не оплачивает заказ.
