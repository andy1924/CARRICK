/* Device-local reports and snapshots. Only submitted reports enter the outbox. */
(() => {
  const DB_NAME = "carrick-device", DB_VERSION = 1;
  let database, reachable = true, syncing = false;
  const listeners = new Set();
  const open = () => database ||= new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      for (const name of ["outbox", "drafts", "snapshots"]) {
        if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Device storage is unavailable. Keep a copy of your report before closing this page."));
  });
  async function operation(store, mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(store, mode), request = action(transaction.objectStore(store));
      let value;
      request.onsuccess = () => value = request.result;
      transaction.oncomplete = () => resolve(value);
      transaction.onerror = () => reject(transaction.error || new Error("Device storage could not be updated"));
      transaction.onabort = () => reject(transaction.error || new Error("Device storage transaction was interrupted"));
    });
  }
  const put = (store, value) => operation(store, "readwrite", object => object.put(value));
  const get = (store, id) => operation(store, "readonly", object => object.get(id));
  const list = store => operation(store, "readonly", object => object.getAll());
  const remove = (store, id) => operation(store, "readwrite", object => object.delete(id));
  const notify = () => listeners.forEach(listener => listener());
  const id = () => crypto.randomUUID();

  async function enqueue(payload, options = {}) {
    if (!payload.schedule_version) throw new Error("Connect a schedule before saving a report offline.");
    const requestId = payload.client_request_id || id();
    await put("outbox", { id: requestId, payload: { ...payload, client_request_id: requestId },
      savedAt: new Date().toISOString(), status: options.status || "pending", error: options.error || "" });
    notify();
    return requestId;
  }

  async function sync(manual = false) {
    if (syncing || !reachable) return;
    syncing = true;
    try {
      const items = (await list("outbox")).sort((a, b) => a.savedAt.localeCompare(b.savedAt));
      for (const item of items) {
        if (item.status === "conflict" || (item.status === "failed" && !manual)) continue;
        let response;
        try {
          response = await fetch("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(item.payload) });
        } catch (_) { reachable = false; break; }
        const data = await response.json();
        if (response.ok) {
          await remove("outbox", item.id);
          window.dispatchEvent(new CustomEvent("carrick-report-synced", { detail: data }));
        } else {
          item.status = response.status === 409 ? "conflict" : "failed";
          item.error = data.error || "The report could not be submitted";
          await put("outbox", item);
          if (item.status === "conflict") window.dispatchEvent(new Event("carrick-schedule-conflict"));
        }
      }
    } finally { syncing = false; notify(); }
  }

  async function health() {
    try {
      const response = await fetch("/api/health", { cache: "no-store", signal: AbortSignal.timeout(4000) });
      const previous = reachable;
      reachable = response.ok;
      if (!previous && reachable) window.dispatchEvent(new Event("carrick-reconnected"));
      notify();
      if (reachable) await sync();
    } catch (_) { reachable = false; notify(); }
  }

  window.CarrickOffline = {
    get reachable() { return reachable; }, get syncing() { return syncing; },
    id, enqueue, sync, health, get, list, put, remove,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    setReachable(value) { const changed = reachable !== value; reachable = value; if (changed) notify(); },
    async rebind(itemId, versionId) {
      const item = await get("outbox", itemId);
      if (!item || item.status !== "conflict" || !versionId) return;
      // One transaction prevents a gap between replacing and removing the old request.
      const db = await open();
      await new Promise((resolve, reject) => {
        const transaction = db.transaction("outbox", "readwrite"), store = transaction.objectStore("outbox");
        const requestId = id();
        store.put({ ...item, id: requestId, payload: { ...item.payload, schedule_version: versionId, client_request_id: requestId }, status: "pending", error: "" });
        store.delete(itemId);
        transaction.oncomplete = resolve;
        transaction.onerror = () => reject(transaction.error);
      });
      notify(); await sync(true);
    },
    async snapshot(value) { await put("snapshots", { id: "workspace", value, savedAt: new Date().toISOString() }); },
  };
  if ("serviceWorker" in navigator && window.isSecureContext) {
    navigator.serviceWorker.register("/sw.js").catch(() => window.dispatchEvent(new Event("carrick-cache-unavailable")));
  }
  window.addEventListener("online", health);
  // Internet connectivity is not a reliable indicator of localhost availability.
  setInterval(health, 20000);
  window.addEventListener("DOMContentLoaded", health);
})();
