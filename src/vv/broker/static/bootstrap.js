"use strict";
(async () => {
  try {
    const initData = window.Telegram?.WebApp?.initData;
    if (!initData) throw new Error();
    const response = await fetch("/api/session", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({init_data: initData}), credentials: "same-origin"
    });
    const result = await response.json();
    if (!result.ok) throw new Error();
    window.location.replace("/connect");
  } catch {
    document.getElementById("message").textContent =
      "Не удалось подтвердить владельца. Закройте окно и откройте заново из личного чата бота.";
  }
})();
