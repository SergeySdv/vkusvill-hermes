# Первичные источники

Проверены 5 октября 2026 года. Это документация; живой MCP из данной среды не протестирован.

1. Официальная текущая страница ВкусВилла: `https://mcp.vkusvill.ru/mcp` — инструменты, лимиты, авторизация и адресный контекст.
2. Официальный manifest/changelog: `https://github.com/vkustech/vkusvill-mcp-server-manifest` — история возможностей.
3. Статья команды ВкусВилла: `https://habr.com/ru/companies/vkusvill/articles/981866/` — ранний пример и особенности текстового JSON; не подмена актуальной схемы.
4. Hermes MCP: `https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp` — подключение HTTP, OAuth, фильтрация инструментов.
5. Hermes skills: `https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/` — SKILL.md и подключение каталогов.
6. Hermes skills guide: `https://hermes-agent.nousresearch.com/docs/guides/work-with-skills/` — загрузка инструкций и reference-файлов.
7. MCP SDK client: `https://py.sdk.modelcontextprotocol.io/client/` — discovery, tool calls, structured content, is_error.
8. MCP SDK OAuth: `https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/oauth-clients.md` — библиотечный клиент авторизации.
9. MCPorter: `https://github.com/openclaw/mcporter` — CLI для discovery и вызовов MCP.
10. MCPorter generator: `https://github.com/openclaw/mcporter/blob/main/docs/cli-generator.md` — генерация низкоуровневой CLI и границы policy.
11. MCPorter CLI: `https://github.com/openclaw/mcporter/blob/main/docs/cli-reference.md` — проверка флагов list/call/generate-cli.

Все команды `vv`, локальные схемы и правила жизненного цикла корзины — наши проектные предложения, не существующие возможности MCP-провайдера.
