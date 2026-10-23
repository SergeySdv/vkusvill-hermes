# План внедрения авторизации ВкусВилла для Jarvis

Дата решений: 2026-10-17. Статус: локальная реализация кандидата 0.5.0.dev0;
внедрение на сервер не выполнено.
Пилот: только Jarvis на `hermes-research-01`. Cloudflare не используется.
После сохранения плана пользователь разрешил локальную реализацию.
Изменение работающих стеков, DNS, регистрации OAuth или настроек Telegram
требует отдельного согласования и не разрешается самим наличием этого плана.

## Текущий результат локальной реализации

- CP1: 2026-10-17 перепроверены публичные discovery и все 11 input schemas через SDK:
  отличий от snapshot нет. Scopes/method/HTTPS callback конкретного клиента пока
  не подтверждены; метаданные провайдера не заменяют регистрацию.
- CP2/CP3: ограничение нагрузки/Host/body, безопасная страница ошибок callback,
  браузерный стенд Chromium с loopback HTTPS, все 11 вызовов через broker/SDK,
  отказ без browser cookie и отсутствие доступа CLI к OAuth-файлам.
- CP4: ограниченный lock, сериализация refresh между процессами, durable marker
  неопределённого refresh, consistency backup через SQLite API и age,
  restore в новый каталог и offline rotate-copy без изменения старого поколения.
- CP5: идемпотентный offline prepare, sidecar без собственных 80/443,
  публичный allowlist и стенд двух владельцев с Caddy/TLS/restart/recreate/log canaries.
  [Артефакты Jarvis](../deploy/jarvis/README.md) не заменяют review текущего Compose.
- CP6: код release gate переведён на upgrade с 0.4.0 и проверку HTML/JS/CSS assets.
  Pin по-прежнему указывает на опубликованный 0.4.0. До commit/push и нового pin
  настоящий release gate обязан отклонять этот кандидат; обхода нет.
- CP0 и CP7 не выполнены: SSH/DNS/Caddy/Telegram и работающие стеки не менялись.
  Server-specific apply/verify/rollback подготовлен 2026-10-18 в operations-репозитории;
  его запуск под sudo, реальный WebView,
  live consent, VM reboot и реальный restore/revoke остаются отдельными gates.

Исходные чекбоксы ниже не закрываются количеством тестов: перечисленные в них
live-условия и проверка опубликованного runtime всё ещё обязательны.

Дополнение 2026-10-18: создан отдельный путь неопубликованного пилота — проверенный
wheel + зафиксированные hash-зависимости + штатный сканер Hermes. Он не меняет release
pin и не превращает красный release gate в зелёный. `jarvis-vkusvill` выполняет
inspect/stage/apply/verify/rollback, проверяет неизменность baseline и посторонних
контейнеров, требует проверенную копию Hermes/Buzz и согласие на recreate Caddy.
Доступ по SSH проверен только read-only; sudo требует интерактивного пароля владельца.
Работающие Compose, DNS и меню Telegram не менялись.

[Отчёт проверок кандидата](jarvis-auth-verification.md): фактические результаты,
происхождение образов и незакрытые gates; не отчёт о live-развёртывании.

## Цель и границы

Пользователь открывает защищённую страницу из своего Telegram-бота, самостоятельно
вводит данные OAuth-клиента из письма и подтверждает доступ на сайте ВкусВилла.
Отдельный сервис принимает callback, получает и обновляет токены, затем выполняет
разрешённые MCP-запросы Jarvis. Ни терминал, ни SSH-доступ пользователю не нужны.

Первый результат — работающий read-only сценарий `orders list` / `favorite show`
через установленный skill без передачи OAuth-секретов в контейнер Hermes.
Повторная установка, обновление и перезапуск сохраняют подключение и корзины.
Отзыв доступа или непригодный refresh token требуют нового входа пользователя.

В пилот не входят:

- personal-assistant, Eisenhorn, их боты, память, секреты и авторизации;
- общий многопользовательский vault или один OAuth-клиент для разных карт;
- автоматическая регистрация клиента ВкусВилла и выдача прав Docker агенту;
- универсальный провижионер новых Hermes-стеков, Cloudflare, отдельный кластер БД;
- оформление/оплата заказа, генерация персональных скидок или share-ссылок
  ради проверки входа; реальные изменяющие операции требуют отдельного запроса.

## Исходное состояние и разрыв до внедрения

Локальная ветка `feat/telegram-oauth-onboarding` содержит неопубликованный прототип.
Его наличие и существующие тесты не закрывают критерии этого плана автоматически.
Runtime pin опубликованного CLI 0.4.0 не содержит broker-режим.

| Уже есть в рабочей ветке | Что ещё необходимо доказать или реализовать |
| --- | --- |
| `src/vv/broker/`: Mini App, OAuth callback, encrypted SQLite, refresh, bridge | Реальный браузерный цикл, ограничения нагрузки, аудит секретов и восстановление |
| `src/vv/bridge.py`, выбор провайдера в CLI, переменные launcher | Чистая установка и upgrade опубликованного broker-совместимого runtime |
| `tests/test_broker.py`, `e2e/broker_smoke.py` | Полная контейнерная сеть через ingress, изоляция двух экземпляров, отказные сценарии |
| `deploy/broker/compose.yaml`, `Caddyfile` | Профиль для существующего Caddy, без второго слушателя 80/443 |
| `.github/workflows/broker.yml` | Зелёные проверки конкретного кандидата и последующего merge, не только наличие workflow |

По локальному operations-проекту целевой стек — `/srv/hermes/compose.yaml`,
service `hermes`, контейнер `hermes-agent`, постоянные данные `/srv/hermes/data/`.
Caddy обслуживает существующий Buzz; его конфигурация указана как
`/srv/buzz/runtime/Caddyfile`. Это ориентиры для будущей read-only сверки,
не утверждение о текущем live-состоянии сервера.

Новый план хранится здесь; серверные изменения будут отдельным review в
`hermes-server-operations`. Его `AGENTS.md` и runbook обязательны при внедрении.

## Целевая архитектура

Рабочее имя пилота: `vv-jarvis.buzzersteam.net`.
Перед регистрацией подтвердить владение DNS и отсутствие конфликта имени.

```text
Телефон или компьютер пользователя
  Telegram Mini App -> HTTPS vv-jarvis.buzzersteam.net
                                |
                         существующий Caddy
                                | отдельная ingress-сеть
                         Jarvis auth-сервис
                           |             |
                 отдельный vault        | HTTPS + OAuth
                                         v
                                OAuth / MCP ВкусВилла

Jarvis: skill -> vv -> отдельная bridge-сеть -> Jarvis auth-сервис
                     только разрешённые операции; ответы без токенов
```

- Один образ и один репозиторий для CLI, skill и optional-пакета `[broker]`.
  Это разные процессы и контейнеры. Второй LLM и второй MCP-сервер не нужны:
  внутренний HTTP bridge вызывает официальный MCP через SDK.
- Предлагаемый корень sidecar-стека: `/srv/vkusvill-auth/jarvis/`, вне всех
  монтируемых в Hermes каталогов. Окончательные пути и UID фиксируются после сверки.
- Отдельные сети: `Jarvis ↔ auth`, `Caddy ↔ auth`; исходящий доступ auth к провайдеру.
  Hermes не присоединяется к ingress-сети, auth — к сетям OpenViking/БД/Buzz.
  У auth нет опубликованного host-порта, Docker socket или host PID namespace.
- Общий Caddy остаётся доверенным: он завершает HTTPS и видит данные формы.
  Его компрометация, root на хосте и компрометация самого broker вне обещания
  «OAuth-секреты недоступны агенту». Контейнеры используют общее ядро хоста.
- Hermes получает только отдельный instance bridge key с доступом к своему API.
  Это доступная агенту capability, а не OAuth-токен. Агент может читать разрешённые
  пользовательские данные; сервис не предотвращает их дальнейшую передачу моделью.
- Операции изменения ограничены allowlist и явным флагом подтверждения. Этот флаг
  и checked hash не являются криптографическим доказательством согласия человека
  при скомпрометированном агенте. Дополнительное browser approval — отдельная задача.

## Внешние настройки и владельцы действий

| Настройка | Решение для пилота | Кто выполняет |
| --- | --- | --- |
| Домен | Использовать `buzzersteam.net`, не покупать новый | Владелец домена |
| DNS | A на подтверждённый IP; AAAA только при проверенной IPv6-маршрутизации; без Cloudflare proxy/tunnel | Администратор после согласования |
| HTTPS | Дополнить существующий Caddy; автоматическое продление сертификата, persistent TLS storage | Администратор |
| Порты | Только существующий публичный ingress 80/443; bridge, vault и admin API не публикуются | Администратор |
| Callback | `https://vv-jarvis.buzzersteam.net/oauth/callback`, точное совпадение в регистрации | Пользователь и ВкусВилл |
| OAuth-клиент | Персональные ID/secret, подтверждённые scopes и token endpoint auth method | Пользователь вводит через форму |
| Telegram | Существующий бот Jarvis, проверенный числовой owner ID, private-chat menu | Администратор; пользователь проходит вход |
| Сеть и время | DNS, исходящий HTTPS к OAuth/MCP ВкусВилла, корректные часы; Telegram/ACME по необходимости | Администратор |
| Хранилище и backup | Отдельные постоянные данные/ключи, зашифрованная копия вне сервера и проверка restore | Администратор |

Выданный пользователю callback `http://localhost:3000/callback` не подходит для
выбранного серверного web-flow. Сначала получить подтверждение изменения URI
или зарегистрировать новый клиент; не подменять его только в конфиге.
Метод `client_secret_basic`/`client_secret_post` и scopes нельзя угадывать по письму
с ID/secret или по общим discovery metadata. Рабочий аккаунт должен иметь адрес
доставки, но OAuth сам по себе не подтверждает наличие товаров и итоговую цену.

Не нужны новый VPS, платный TLS-сертификат, Redis/PostgreSQL, Vault или новый бот.
Защиту от объёмного DDoS со стороны хостинга необходимо учитывать отдельно:
локальный rate limit и Caddy не дают такой гарантии.

## Контракты и безопасность

### Пользовательский вход

1. Кнопка существующего бота открывает HTTPS Mini App; сервис проверяет Telegram
   Ed25519 signature, bot ID, owner ID, свежесть и отсутствие повтора initData.
   Сохранить проверки HMAC прототипа, но не допускать HMAC-only fallback:
   Hermes может знать bot token и самостоятельно вычислить HMAC.
2. Выдаётся короткая host-only browser session, не доступная bridge-клиенту.
   Credential-форма отдельная, без Telegram SDK, сторонних скриптов и аналитики.
   Секреты не идут в `sendData`, чат, URL, localStorage или модель.
3. Callback задаётся серверной конфигурацией. Пользователь не выбирает issuer,
   token endpoint, адрес проксирования или произвольный redirect.
4. Для каждой попытки — свежие `state` и PKCE S256. Одноразовый callback привязан
   к исходной browser session; только затем сервер обменивает code на токены.
5. После успеха форма показывает только безопасный статус. Новая авторизация
   заменяет старую атомарно; отмена и ошибка не стирают действующее подключение.
6. Повторный вход и отключение доступны только владельцу через browser session.
   Удаление локальных токенов не выдаётся за отзыв доступа у ВкусВилла.

Начальные параметры прототипа: initData не старше 120 секунд, browser session
600 секунд, OAuth attempt 300 секунд, JSON body до 32 KiB. Зафиксировать и проверить
границы; изменение TTL не должно превращать истёкшую попытку в действующую.
Cookies: Secure, HttpOnly, SameSite=Lax, без Domain; browser POST — exact Origin.
Ответы: no-store, no-referrer, CSP; callback после обработки очищается редиректом
на страницу без code/state. Дубли параметров, подмена Host и open redirect запрещены.

**Блокер UX:** нынешний прототип требует возврата в тот же браузер/WebView.
Проверить Telegram на целевых мобильных и desktop-клиентах. Если OAuth открывает
другой браузер, нельзя отключать cookie-binding или просить прислать callback.
До пилота нужен отдельно проверенный одноразовый handoff без OAuth-секретов
либо явное ограничение поддерживаемого клиента, приемлемое владельцу.

### Bridge и CLI

- Внутри: `GET /bridge/status`, `POST /bridge/call`; bearer capability привязана
  к одному экземпляру. Она не открывает `/api/connect`, `/api/disconnect` или vault.
- Публично: только список разрешённых page/assets/browser API/callback routes.
  Unknown routes и все варианты пути `/bridge` закрыты на ingress независимо
  от наличия валидного bridge key. Нельзя просто проксировать весь сайт catch-all.
- Разрешены только проверенные tool names/аргументы на фиксированном MCP endpoint.
  Нет произвольных URL/headers, shell interpolation, credential export и обхода
  проверки схем. Токен не уходит на чужой host при redirect/SSRF.
- Сохраняется envelope `schema_version/ok/data/error/warnings/meta` и стабильные
  коды `AUTH_REQUIRED`, `SCHEMA_CHANGED`, `REVIEW_REQUIRED`, `OUTCOME_UNKNOWN`.
  При выборе broker CLI не читает локальный AuthStore и не запускает consent.
- При сломанной авторизации нет скрытого перехода на публичный каталог.
  При недоступности broker нет автоматического возврата к legacy-токенам.
- Refresh сериализован между запросами/процессами, новая пара токенов сохраняется
  до MCP-вызова. При неоднозначном сбое ротации — безопасная ошибка и при
  необходимости новый вход, не обещание восстановления уже отозванного refresh.
- Login/logout/смена аккаунта инвалидируют старый basket auth context;
  обычный refresh его сохраняет. Проверки бюджета, наличия и checked hash остаются
  в CLI. Прокси независимо проверяет schema, тип операции и лимиты корзины.
- Сохраняются текущие `id` для cart, отличие от legacy `xml_id`, 1–20 SKU,
  q 0.01–40 и статус unknown. Старые корзины не переписываются фоново.
  Изменяющие вызовы не повторяются после сетевой неопределённости.

### Хранение и эксплуатация

- Vault, encryption key и OAuth-конфигурация не входят в образ/Git, env Hermes,
  его volumes, контекст модели и логи. У broker отдельные UID и права 0700/0600;
  config read-only, root filesystem read-only, cap_drop ALL, no-new-privileges.
- Encryption key сохраняется отдельно от БД и стабилен после recreate/reboot.
  Нельзя генерировать новый ключ при каждом старте, install или upgrade.
  Для unattended boot ключ доступен broker на хосте: это не защита от host root.
- Backup должен согласованно сохранять БД с учётом SQLite journal/WAL и версию
  ключа; копировать только основной файл работающей БД недостаточно.
  Ключи включаются в защищённый recovery-процесс, но не в открытый backup рядом
  с зашифрованной БД. Копии шифруются off-host recovery key; агент их не читает.
- Restore не гарантирует пригодность старого refresh token после его ротации
  у провайдера. Проверка restore требует целостности/изоляции и безопасного
  reconnect при `invalid_grant`, без отката чужих данных и автоматических мутаций.
- При старых локальных OAuth-файлах в Hermes нужен отдельный согласованный отзыв
  прежнего доступа и защищённое удаление/карантин. Включение broker само по себе
  не удаляет исторические копии, переписку или backups.
- Ограничить частоту login/session/callback и bridge-запросов, очередь, количество
  соединений, CPU/RAM/PIDs, размер ответов и таймауты. Проверять давление на SQLite
  lock. Конкретные лимиты фиксируются по стенду до публичного запуска.
- Healthcheck отражает живость процесса, readiness — пригодность конфигурации и
  локального хранилища. Отсутствие OAuth до первого входа не означает crash-loop.
  Падение ВкусВилла не должно бесконечно перезапускать исправный broker.
- Логи/метрики содержат безопасные коды, длительности и request ID, но не headers,
  тела, query callback, initData или данные заказов. Аудит охватывает Caddy runtime
  errors, container logs, CI artifacts, tracing и crash dumps, не только access log.

## Чекпоинты внедрения

Каждый checkpoint закрывается результатами проверок конкретного commit/image,
а не отметкой «код написан». Последующие live-действия требуют отдельного разрешения.

### CP0 Сверка и внешние зависимости

- [ ] Зафиксировать sanitized baseline Jarvis, mounts/UID/privileges, фактический
  Caddy/сети/порты и runtime/skill pin. SSH-сверка read-only; не выводить secret files,
  полный `docker inspect` Env или развёрнутый Compose с секретами.
- [ ] Подтвердить hostname, DNS-доступ, регистрацию точного HTTPS callback,
  scopes/method, bot ID и owner ID. Сами секреты не входят в отчёт.
- [ ] Зафиксировать объекты, разрешённые для будущего изменения, лимит простоя,
  backup/rollback и сохранность остальных контейнеров/маршрутов.

**Приёмка:** нет нерешённого конфликта домена/портов/владельца; внешние параметры
подтверждены. Невыполненная регистрация блокирует live OAuth, но не offline-разработку.

### CP1 Проверенный контракт и модель угроз

- [ ] Перепроверить официальные discovery и актуальные tool schemas без секретов;
  зафиксировать дату, ресурс/issuer, допустимые client methods и scopes клиента.
- [ ] Описать browser/bridge API и состояния `not_configured`, подключение,
  действующее подключение, необходимость повторного входа; отделить сохранённую
  конфигурацию от live-валидности токена.
- [ ] Провести read-only security review endpoint allowlist, сетей, error redaction,
  модели подтверждений, Telegram-подписи и границ доверия.

**Приёмка:** нет произвольного proxy URL и export-secret API; protocol drift закрыт
явной ошибкой. У каждого выявленного разрыва есть тест и следующий checkpoint.

### CP2 Завершение browser OAuth

- [ ] Доработать CP1-разрывы, rate limits и безопасные страницы ошибок/повторного входа.
- [ ] Проверить весь цикл в браузерном стенде с синтетическим OAuth issuer:
  initData → форма → consent → callback → безопасный статус.
- [ ] Проверить перенос browser context; подготовить решение UX-блокера без
  ослабления session binding и без передачи секретов через Telegram.

**Приёмка:** T01–T05 и T15 проходят; чужой пользователь/бот/браузер не может привязать
аккаунт. Сбой нового входа сохраняет прежнее подключение. Реальный WebView — CP7.

### CP3 Интеграция bridge и сохранение CLI-контракта

- [ ] Проверить все адаптеры на синтетическом MCP через настоящий SDK и CLI launcher.
- [ ] Проверить refresh/concurrency, schema drift, timeout/502, account context,
  режим без OAuth и отсутствие legacy/public fallback при ошибке авторизации.
- [ ] Сохранить локальные корзины и контракт ошибок, запрет replay мутаций;
  обновить skill-инструкции «подключить/статус/повторить вход» без секретов в чате.

**Приёмка:** T06–T08 и T12 проходят; успешный read-only запрос возвращает данные,
не credential. Нет регрессии basket lifecycle или shell interpolation.

### CP4 Постоянное хранение и восстановление

- [ ] Проверить файл/каталог/UID/symlink guards, сохранность ключей и owner binding.
- [ ] Реализовать и описать consistency backup, восстановление в чистый volume,
  ротацию bridge/encryption keys с защищённым recovery и отменой при сбое.
- [ ] Проверить restart/recreate, аварийное завершение и disk-full/lock contention.

**Приёмка:** T09–T11 проходят. Повторная установка не меняет ключи и не стирает vault.
При утрате/несовпадении ключа нет автоматического создания пустой «успешной» БД.

### CP5 Артефакты развёртывания и контейнерный стенд

- [ ] Подготовить в этом репозитории пример sidecar без собственного Caddy,
  совместимый с уже работающим ingress, и тестовую схему с disposable ingress.
- [ ] Подготовить отдельный review в `hermes-server-operations`: dry-run/prepare,
  точечный apply, verify и rollback для Jarvis, конфиг без секретов, runbook.
  Скрипт валидирует target/owner/mounts; repeat run идемпотентен, mismatch — отказ.
- [ ] Не применять универсальный `create-agent-template` к существующему Jarvis.
  Его текущий контракт рассчитан на Hermes/OpenViking; обобщение отложено.
- [ ] Согласовать TLS/logging policy с существующим Caddy. Не копировать глобальный
  `admin off` или глобальные logging-настройки из примера без анализа reload и
  других сайтов. Учесть file bind-mount inode при apply и rollback.
- [ ] Поднять только disposable Compose с двумя синтетическими владельцами и
  Caddy, проверить ingress/bridge/egress и недоступность чужого vault.

**Приёмка:** T10, T13–T16 проходят; Compose config, `caddy validate` и `bash -n`
успешны. Standalone-пример с собственными 80/443 не запускается на рабочем сервере.
Если безопасный route-scoped logging невозможен, публичный rollout блокируется.

### CP6 Поставка и release gate

- [ ] Выпустить новую версию CLI/skill с broker-режимом; не переиспользовать 0.4.0
  для отличающегося поведения. Собрать wheel/sdist/image из проверенной ревизии.
- [ ] После отдельно разрешённых commit/push закрепить installer на доступном
  неизменяемом runtime commit; image — на digest. Pin update отдельный, payload
  CLI после закрепления не менять без нового pin и повторного gate.
- [ ] Проверить установку по обычной GitHub-ссылке в чистом Hermes и upgrade
  с 0.4.0, штатный scanner, происхождение установленного пакета, rollback.
- [ ] Прогнать текущий `release-installation` и новый broker deployment gate.
  Назначить нужные required checks после их появления. Самостоятельно проверить
  PR checks/logs/artifacts и проверки main после merge через GitHub tools/CLI.

**Приёмка:** T17–T18 проходят на опубликованном кандидате; pin, версия и образ
согласованы. Локально переписанный pin не считается проверкой release.
Merge/release не означает разрешение изменять Jarvis на сервере.

### CP7 Контролируемый пилот Jarvis

- [ ] Получить отдельное разрешение на точный diff, окно и ожидаемый эффект.
  Сделать свежий проверенный encrypted backup затрагиваемых данных/настроек,
  включая существующий ingress, и сохранить rollback metadata вне чата.
- [ ] Через доверенный operations-скрипт развернуть только Jarvis sidecar,
  добавить DNS/маршрут, сеть и bridge key Jarvis; при необходимости пересоздать
  только целевой Hermes. OpenViking и другие Hermes не перезапускать.
- [ ] Поменять только согласованное private-chat menu Jarvis, сохранив старое для
  отката. Не менять webhook и не запускать дополнительный Telegram poller.
- [ ] Пользователь лично вводит client credentials и подтверждает доступ;
  выполнить только `auth status`, `doctor --live --json`, orders/favorite.
- [ ] Выполнить T19–T20, безопасно проверить целевые restart/recreate. Host reboot
  сначала доказывается на VM; на общем сервере — только в отдельное окно, поскольку
  он затрагивает остальные сервисы. Не обещать live-reboot проверку без неё.
- [ ] Зафиксировать UTC, target, commit/pin/digest, результаты, backup/rollback,
  остаточные риски; новые данные — в `changes/` operations-проекта.

**Приёмка:** пользователь входит без SSH/администратора, получает реальные
персональные данные или корректный пустой ответ своего аккаунта. Другие стеки,
память, cron и публичный Buzz работают как до пилота. Секретов в agent-visible
данных нет. Неудача любого security gate означает остановку и откат.

## Матрица тестов

В автоматических тестах только синтетические credentials, подписи, заказы и MCP.
CI не содержит реальные OAuth/Telegram secret values, публичный consent и личные
заказы. Browser traces/HAR/screenshots с секретами не публикуются даже при падении.

| ID | Уровень и сценарий | Наблюдаемый критерий |
| --- | --- | --- |
| T01 | Unit: Telegram signature/HMAC, owner/bot, future/stale/replayed initData | Подделка, чужая identity и повтор отклонены; знания bot token недостаточно |
| T02 | HTTP/browser: Origin, CSRF, cookie flags, host header, body/content type | Нет доступа к форме/настройкам без owner session; опасный ввод не отражён |
| T03 | OAuth: PKCE S256, exact URI, state, дубли параметров, отсутствующий cookie | Code exchange только у правильной одноразовой попытки; verifier не покидает сервис, кроме token exchange |
| T04 | OAuth: cancel/timeout/expiry/replay/параллельные callbacks/exchange failure | Максимум один обмен; предыдущий аккаунт сохранён при неуспехе |
| T05 | Browser: очищенный callback URL, CSP, no-store/no-referrer, внешние скрипты | Нет code/secret в DOM результата, URL после callback, browser storage и сторонних запросах |
| T06 | Protocol: реальный SDK → локальный MCP, все текущие адаптеры | Правильные tools/args и bearer только на ожидаемом upstream; unknown и envelope сохранены |
| T07 | Refresh: конкурентные потоки/процессы, ротация, invalid_grant, crash | Один refresh для конкурирующих запросов; сохранение до MCP; нет анонимного fallback и replay мутаций |
| T08 | Negative: неизвестный tool/extra args/SSRF/redirect/schema drift/502/timeout | Стабильная безопасная ошибка, нет произвольного egress/секрета; счётчик мутаций ≤ 1 |
| T09 | Storage: encryption, права/UID/symlink, плохой ключ, перепутанный vault | Канарейки отсутствуют в plaintext БД; fail closed; owner/bot binding нельзя переопределить |
| T10 | Docker isolation: два владельца, чужой key/session/network, agent root | Чужой экземпляр недоступен; Hermes не читает config/vault/ключ, не управляет Docker |
| T11 | Recovery: restart/recreate/VM reboot, backup→clean restore, disk full | Сохраняются account/context/expiry и ключи; stale refresh требует reconnect; integrity failure не скрыт |
| T12 | CLI: legacy AuthStore запрещён; basket check/context/hash/limits | Broker-команды не читают OAuth-файлы; login/logout требует recheck, refresh — нет; старые корзины сохранены |
| T13 | Ingress: HTTP→HTTPS, TLS, unknown host, bridge paths/encoding/methods | Снаружи доступны только разрешённые routes; bridge закрыт даже с валидным key |
| T14 | Security logs: синтетические секреты в success/ошибках/reflected upstream | Нет canary-токенов, кодов, initData и секретных headers в логах/JSON/артефактах; проверяется и Caddy upstream error |
| T15 | Browser E2E: истечение/отключение/два окна/другой browser context | Сессии не смешиваются; неподдерживаемый handoff отклоняется с понятным безопасным действием |
| T16 | Operations: dry-run/repeat/mismatch/failure injection/rollback/load | Нет дублей/перегенерации ключей; unrelated config сохранён; очередь и ресурсы ограничены, 429/timeout безопасны |
| T17 | Release: fresh install/0.4.0 upgrade/offline doctor/live fixture | Scanner не обходится; immutable revision подтверждена; настройки bridge и корзины сохраняются |
| T18 | Regression: Ruff, unit, protocol, Hermes smoke, packaging, release-installation | Все обязательные jobs зелёные на точном кандидате; нет реальных секретов/мутаций |
| T19 | Manual: реальный Telegram mobile/desktop → ВкусВилл → Jarvis | Владелец сам вводит данные; read-only orders/favorite подтверждены; токены в ответе/контейнере агента отсутствуют |
| T20 | Manual operations: targeted restart, health/memory/cron/Buzz/backup | Подключение работает после рестарта; остальные стеки и маршруты не изменены; rollback проверяем |

Наличие T01–T12 в существующих тестах оценивается по конкретным assertions,
не по количеству тестов. Группы дополняются, если перечисленная граница не покрыта.
Real-model Hermes E2E может быть дополнительным opt-in прогоном с лимитом затрат;
он не заменяет детерминированные проверки безопасности и human consent.

### Команды проверки кандидата

Существующие команды из корня репозитория, не команды для рабочего сервера:

```sh
uv sync --locked --extra broker
make check
make test-broker test-protocol
make build
make broker-build broker-smoke
make e2e-smoke
make release-check
```

`broker-smoke` проверяет пакет в read-only контейнере без сети, а не публичный OAuth.
`release-check` требует доступный согласованный pin и может закономерно не пройти
до CP6. Browser и two-instance ingress теперь запускаются через `make broker-browser`
и `make broker-containers`; добавлены CI jobs. Fault injection локального storage,
refresh и upstream покрыт тестами. Server-specific ops apply/rollback и VM reboot
ещё не выполнялись и не объявляются завершёнными.

## Откат и условия остановки

При утечке/смешении аккаунтов, открытом bridge, несовпадающем pin, проблемах
callback binding, невалидном backup или воздействии на чужой стек — остановить
rollout. Не обходить scanner, TLS, CSRF, schema checks или ограничения sudo.

Порядок rollback после согласования:

1. Прекратить новые обращения к sidecar и убрать только его публичный маршрут/menu.
2. Восстановить предыдущую конфигурацию Jarvis/CLI и сети из проверенного baseline;
   не возвращать отозванные/скомпрометированные legacy OAuth-токены.
3. Остановить только новый auth-контейнер; vault и ключи сохранить защищённо,
   не выполнять общий `compose down -v`. Не откатывать корзины поверх новых данных.
4. При утечке отозвать соответствующий grant/client у ВкусВилла; простого
   отключения контейнера недостаточно. Ротацию ключей провести отдельной процедурой.
5. Проверить Caddy и Buzz, Jarvis Telegram/память/cron/backups, идентичность и
   состояние всех нетронутых сервисов. Зафиксировать результат в operations runbook.

Общий Caddy и хост остаются точками совместного отказа. Если reload не видит
новый bind-mounted файл, нельзя молча пересоздавать общий ingress: отдельно
согласовать влияние и выполнить тот же проверенный механизм в rollback.

## Итоговая приёмка пилота

- [ ] Владелец подключает ВкусВилл из Telegram без SSH, передачи ключей в чат и
  действий администратора за него на сайте провайдера.
- [ ] HTTPS callback зарегистрирован, real mobile/desktop flow проверен;
  подтверждённые ограничения клиентов явно документированы.
- [ ] Jarvis получает свои заказы/любимый продукт через broker, но не OAuth-секреты.
- [ ] Сохранность проверена после recreate/upgrade и restore; стратегия перезагрузки
  подтверждена на стенде, live-проверки обозначены отдельно.
- [ ] Другие владельцы, bot tokens и bridge keys не открывают Jarvis auth-session/vault.
- [ ] Нет секретов в репозитории, образе, артефактах, agent mounts и диагностике.
- [ ] Fresh install, upgrade, scanner, CI и immutable pin/image подтверждены.
- [ ] Есть проверенный backup/rollback, пределы нагрузки, health/alerts и инструкция
  повторного входа/отзыва/удаления подключения с учётом retention backups.
- [ ] Рабочие personal/Eisenhorn/OpenViking/Buzz не изменены вне явно согласованного
  маршрута общего Caddy; корзины и ссылки не создавались для проверки OAuth.

## Связанные материалы

- [Текущий прототип Telegram onboarding](telegram-onboarding.md).
- [Терминальный OAuth и подтверждённый ранее контракт](oauth-onboarding.md).
- [Контракт CLI](../skills/vkusvill/references/cli.md), [безопасность](../SECURITY.md),
  [установка и обновление](../INSTALL.md), [E2E и release gate](../e2e/README.md).
- [Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https): сертификаты,
  DNS, доступность портов и постоянное хранилище TLS.
- [OAuth Security BCP](https://www.rfc-editor.org/rfc/rfc9700.html): exact redirect,
  PKCE, защита redirect-based flow и refresh tokens.
- [Telegram third-party validation](https://core.telegram.org/bots/webapps#validating-data-for-third-party-use):
  независимая проверка Ed25519 signature и свежести initData.

Для будущего серверного этапа: `AGENTS.md`, `config/server.yaml`,
`docs/HERMES-SERVER-RUNBOOK.md`, `scripts/remote/` и
`scripts/templates/agent-stack.sh.in` в `hermes-server-operations`.
Этот план не изменяет указанные файлы и не является отчётом о live-развёртывании.
