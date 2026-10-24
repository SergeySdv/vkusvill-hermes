"use strict";
const message = document.getElementById("message");
const actionMessage = document.getElementById("action-message");
let submitting = false;
function showAction(text) {
  actionMessage.textContent = text;
  actionMessage.scrollIntoView({block: "nearest"});
}
async function request(path, data) {
  const options = {credentials: "same-origin", signal: AbortSignal.timeout(30000)};
  if (data !== undefined) {
    options.method = "POST";
    options.headers = {"Content-Type": "application/json"};
    options.body = JSON.stringify(data);
  }
  const response = await fetch(path, options);
  const result = await response.json();
  if (!result.ok) throw new Error(result.error?.code === "AUTH_REQUIRED" ?
    "Сессия формы истекла. Закройте окно и откройте приложение заново из бота. Сохранённое подключение не удалено." :
    "Запрос не выполнен. Проверьте состояние подключения перед повторной попыткой.");
  return result.data;
}
async function update() {
  try {
    const status = await request("/api/status");
    document.getElementById("callback").textContent = status.redirect_uri;
    message.textContent = status.auth === "configured" ?
      "Подключение сохранено. Вернитесь в бот и проверьте доступ к заказам." :
      status.auth === "reconnect_required" ? "Нужен повторный вход во ВкусВилл." : "ВкусВилл не подключён.";
    document.getElementById("connect").hidden = status.auth === "configured";
    document.getElementById("setup-help").hidden = status.auth === "configured";
    document.getElementById("disconnect").hidden = status.auth !== "configured" && status.auth !== "reconnect_required";
  } catch {
    message.textContent = "Откройте приложение заново из личного чата бота.";
  }
}
document.getElementById("connect").addEventListener("submit", async event => {
  event.preventDefault();
  if (submitting) return;
  submitting = true;
  const button = event.target.querySelector("button");
  button.disabled = true;
  showAction("Начинаем подключение… Не закрывайте окно.");
  const data = Object.fromEntries(new FormData(event.target));
  if (!data.client_secret) delete data.client_secret;
  try {
    const result = await request("/api/connect", data);
    event.target.reset();
    const target = new URL(result.authorize_url);
    if (target.origin !== "https://oauth.vkusvill.ru" || target.pathname !== "/oauth2/auth") {
      throw new Error("Неожиданный адрес авторизации");
    }
    window.location.assign(target.href);
  } catch (error) {
    showAction(error.name === "TimeoutError" || error.name === "TypeError" ?
      "Нет ответа от сервиса. Проверьте состояние подключения перед повтором; сохранённое подключение не удалено." : error.message);
    button.disabled = false;
  } finally {
    submitting = false;
    document.querySelector('[name="client_secret"]').value = "";
    delete data.client_secret;
  }
});
document.getElementById("disconnect").addEventListener("click", async () => {
  if (!window.confirm("Отключить ВкусВилл для этого бота?")) return;
  try { await request("/api/disconnect", {}); await update(); }
  catch (error) { message.textContent = error.message; }
});
update();
