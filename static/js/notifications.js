async function fetchJson(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return await res.json();
}

function setUnreadCount(count) {
  const badge = document.getElementById("notifUnreadBadge");
  if (!badge) return;
  if (count > 0) {
    badge.textContent = String(count);
    badge.classList.remove("d-none");
  } else {
    badge.textContent = "";
    badge.classList.add("d-none");
  }
}

function renderNotifications(items) {
  const list = document.getElementById("notifList");
  if (!list) return;
  list.innerHTML = "";

  if (!items || items.length === 0) {
    const div = document.createElement("div");
    div.className = "dropdown-item text-muted py-3";
    div.textContent = "No notifications yet.";
    list.appendChild(div);
    return;
  }

  for (const n of items) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "dropdown-item notif-item";
    btn.innerHTML = `<div class="fw-semibold">${escapeHtml(n.title)}</div>
      <div class="small text-muted">${escapeHtml(n.message)}</div>`;
    btn.addEventListener("click", async () => {
      try {
        await fetchJson(`/api/notifications/${n.id}/read`, { method: "POST" });
        await refreshNotifications();
      } catch (e) {
        // ignore
      }
    });
    list.appendChild(btn);
    const divider = document.createElement("hr");
    divider.className = "dropdown-divider my-0";
    list.appendChild(divider);
  }

  // remove trailing divider
  const last = list.lastElementChild;
  if (last && last.tagName === "HR") last.remove();
}

function escapeHtml(str) {
  return String(str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function refreshNotifications() {
  const [count, items] = await Promise.all([
    fetchJson("/api/notifications/unread_count"),
    fetchJson("/api/notifications?limit=10"),
  ]);
  setUnreadCount(count.unread || 0);
  renderNotifications(items);
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  try {
    return await navigator.serviceWorker.register("/sw.js");
  } catch (e) {
    return null;
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

async function enablePush() {
  const pk = await fetchJson("/api/push/public_key");
  if (!pk.publicKey) {
    alert("Push notifications are not configured on the server (missing VAPID keys).");
    return;
  }
  const reg = await registerServiceWorker();
  if (!reg) {
    alert("Service worker registration failed.");
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return;

  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(pk.publicKey),
  });
  await fetchJson("/api/push/subscribe", {
    method: "POST",
    body: JSON.stringify(sub),
  });
  alert("Push notifications enabled.");
}

function setupPushButton() {
  const btn = document.getElementById("enablePushBtn");
  if (!btn) return;
  btn.addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      await enablePush();
    } catch (err) {
      alert("Failed to enable push notifications.");
    }
  });
}

function setupSocket() {
  if (typeof io === "undefined") return;
  const socket = io();
  socket.on("connect", () => {
    // connected
  });
  socket.on("notification", async () => {
    // refresh list + count
    try {
      await refreshNotifications();
    } catch (e) {
      // ignore
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await refreshNotifications();
  } catch (e) {
    // ignore
  }
  setupPushButton();
  setupSocket();
});


