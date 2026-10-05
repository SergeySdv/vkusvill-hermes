# vv 0.1.0: действующий контракт

## Команды

| Команда | Поведение |
| --- | --- |
| vv --version | Версия текстом; --json --version возвращает envelope |
| vv doctor --json | Проверяет доступность локального SQLite; сеть/auth unknown |
| vv product search TEXT --limit 5 --json | Заглушка NOT_IMPLEMENTED |
| vv product get PRODUCT_ID --json | Заглушка; принимает product id, не xml_id |
| vv product analogs PRODUCT_ID --json | Заглушка NOT_IMPLEMENTED |
| vv basket import NAME --file request.json --json | Атомарный импорт/замена, новая ревизия draft |
| vv basket show NAME --json | Сохранённое состояние текущего профиля |
| vv basket check NAME --json | Локальная проверка, checked/hash, live-факты unknown |
| vv basket check NAME --refresh --json | NOT_IMPLEMENTED; состояние не меняется |
| vv basket link NAME --checked-hash HASH --json | Проверка хеша/свежести/unknown; реальная ссылка выключена |

JSON является форматом по умолчанию. Флаг --json также допустим перед группой.
Успех: exit 0, ошибка: exit 1. Help/version — отдельные информационные режимы.
Команд auth/profile/recipe/discount/shop/orders/favorite пока нет.

## Входной JSON

schema_version: 1; items: непустой массив; constraints: объект.
Item: product_id (положительное целое), quantity (положительная decimal-строка),
unit (piece/package/kg/g/l/ml). Constraints: currency=RUB,
max_goods_total (неотрицательная decimal-строка с максимум двумя знаками или null),
hard_exclusions (уникальные строки), preferences (строки).
Необязательные поля constraints получают безопасные пустые значения.
Дополнительные поля запрещены, в том числе цены и xml_id.
Максимальный файл — 1 MiB; максимум 1000 исходных строк,
после объединения одинаковых id/units — 1–20 позиций.
Имена корзин/профилей: 1–64 ASCII буквы/цифры/_/-, первый символ буква/цифра.

Человеческая quantity не является provider q. Объединение разных единиц одного
товара отклоняется. CartPayload — отдельная внутренняя модель:
1–20 уникальных xml_id > 0; q ∈ [0.01, 40]. Импорт не принимает CartPayload.

## Envelope

```json
{
  "schema_version": 1,
  "ok": false,
  "data": null,
  "error": {
    "code": "REVIEW_REQUIRED",
    "message": "Missing, changed or expired basket check.",
    "retryable": false
  },
  "warnings": [],
  "meta": {"cli_version": "0.1.0", "request_id": "generated UUID"}
}
```

Один JSON в stdout; нет сырых tracebacks, ответов провайдера или токенов в
диагностике. error=null при ok=true. message не является стабильным API;
ветвление делай по code. report.scope=local_only, goods_total=null.
checks содержат status=pass/fail/unknown и evidence. Только local_shape сейчас pass.

## Ошибки

| code | Действие |
| --- | --- |
| INVALID_INPUT | Исправить аргументы/JSON, не повторять неизменный ввод |
| CONSTRAINT_FAILED | Исправить лимиты/несовместимые единицы без ослабления требований |
| NOT_FOUND | Проверить имя и профиль |
| STORAGE_ERROR | Проверить локальные права/диск |
| NOT_IMPLEMENTED | Нужен следующий этап реализации; не выдумывать ответ |
| REVIEW_REQUIRED | Проверить изменения/свежесть/unknown, не обходить запрет |
| AUTH_REQUIRED | Доверенный OAuth onboarding; сейчас только контракт адаптера |
| SCHEMA_CHANGED | Разработчик должен проверить новую схему/нормализатор |
| PROVIDER_ERROR | Ошибка инструмента/провайдера; не считать результат успехом |
| NETWORK_ERROR | Только для безопасных чтений допускается ограниченный retry |
| OUTCOME_UNKNOWN | Не повторять создание ссылки вслепую |
| INTERNAL_ERROR | Сообщить об ошибке без публикации секретов |

AUTH_REQUIRED/SCHEMA_CHANGED/OUTCOME_UNKNOWN протестированы на изолированных
ошибках/ответах, но live-интеграция не подключена.

## Состояния

draft → checked → link_created. Последний переход зарезервирован и выключен.
Любой повторный импорт → новая ревизия draft, hash/report/link очищаются.
check_hash включает профиль/имя/ревизию/request/report, включая сроки и scope.
TTL 15 минут. Unknown блокирует ссылку. Хеш не является согласием пользователя
или защитой от прямого редактирования БД доверенным владельцем.

VV_STATE_DIR выбирает приватный каталог SQLite; VV_PROFILE — namespace.
Профиль не является границей безопасности между пользователями ОС.
