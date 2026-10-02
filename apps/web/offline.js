/* Device-local reports and snapshots. Only submitted reports enter the outbox. */
(() => {
  const DB_VERSION = 1;
  let database, databaseScope, reachable = true, syncing = false;
  const listeners = new Set();
  // Only the initial project owner inherits data saved before accounts existed.
  // Keep the original database intact so migration is recoverable.
  async function migrateLegacy(db, project) {
    if(project.id!=="prj_default" || project.role!=="owner") return;
    const read=(target,store)=>new Promise((resolve,reject)=>{
      const tx=target.transaction(store,"readonly"),request=tx.objectStore(store).getAll();
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
    if((await read(db,"snapshots")).some(item=>item.id==="legacy-imported"))return;
    const legacy=await new Promise((resolve,reject)=>{
      const request=indexedDB.open("carrick-device");let missing=false;
      request.onupgradeneeded=()=>{missing=true;request.transaction.abort();};
      request.onsuccess=()=>resolve(request.result);
      request.onerror=()=>missing?resolve(null):reject(request.error);
    });
    let rows={outbox:[],drafts:[],snapshots:[]};
    if(legacy){
      try {for(const name of Object.keys(rows))if(legacy.objectStoreNames.contains(name))rows[name]=await read(legacy,name);}
      finally {legacy.close();}
    }
    await new Promise((resolve,reject)=>{
      const tx=db.transaction(Object.keys(rows),"readwrite");
      for(const [name,values] of Object.entries(rows))for(const value of values){
        const store=tx.objectStore(name),request=store.get(value.id);
        request.onsuccess=()=>{if(request.result===undefined)store.put(value);};
      }
      tx.objectStore("snapshots").put({id:"legacy-imported",savedAt:new Date().toISOString()});
      tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);
    });
  }
  const open = () => {
    const account=window.CarrickAuth?.current,project=window.CarrickAuth?.project;
    if(!account || !project) return Promise.reject(new Error("Sign in and select a project before using device storage."));
    const scope=`carrick-device:${account.user.id}:${project.id}`;
    if(scope!==databaseScope){database=undefined;databaseScope=scope;}
    return database ||= new Promise((resolve, reject) => {
    const request = indexedDB.open(scope, DB_VERSION);
    request.onupgradeneeded = () => {
      for (const name of ["outbox", "drafts", "snapshots"]) {
        if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name, { keyPath: "id" });
      }
    };
    request.onsuccess = () => migrateLegacy(request.result,project).then(()=>resolve(request.result)).catch(reject);
    request.onerror = () => reject(new Error("Device storage is unavailable. Keep a copy of your report before closing this page."));
    });
  };
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
    if (syncing || !reachable || !window.CarrickAuth?.current) return;
    syncing = true;
    try {
      const items = (await list("outbox")).sort((a, b) => a.savedAt.localeCompare(b.savedAt));
      for (const item of items) {
        if (item.status === "conflict" || (item.status === "failed" && !manual)) continue;
        if(!manual && item.retryAt && Date.now()<item.retryAt) continue;
        let response;
        try {
          response = await fetch("/api/reports", { method: "POST", headers: { "Content-Type": "application/json",...window.CarrickAuth.headers() }, body: JSON.stringify(item.payload) });
        } catch (_) { reachable = false; break; }
        const data = await response.json();
        if (response.ok) {
          await remove("outbox", item.id);
          window.dispatchEvent(new CustomEvent("carrick-report-synced", { detail: data }));
        } else {
          item.attempts=(item.attempts||0)+1;
          item.status = response.status === 409 ? "conflict" : response.status>=500 && item.attempts<3 ? "pending" : "failed";
          item.retryAt=Date.now()+Math.min(300000,10000*2**item.attempts);
          item.error = data.error || "The report could not be submitted";
          await put("outbox", item);
          if (item.status === "conflict") window.dispatchEvent(new Event("carrick-schedule-conflict"));
          if(response.status===401){window.CarrickAuth.showLogin("Sign in to recover your saved reports.");break;}
        }
      }
    } finally { syncing = false; notify(); }
  }

  async function send(payload) {
    await enqueue(payload);
    if(!reachable) return undefined;
    let response;
    try {response=await fetch("/api/reports",{method:"POST",headers:{"Content-Type":"application/json",...window.CarrickAuth.headers()},body:JSON.stringify(payload)});}
    catch(error){reachable=false;notify();return undefined;}
    const data=await response.json();
    if(response.ok){await remove("outbox",payload.client_request_id);notify();return data;}
    const item=await get("outbox",payload.client_request_id);
    item.attempts=1;item.error=data.error||"Submission needs attention";item.status=response.status===409?"conflict":response.status>=500?"pending":"failed";item.retryAt=Date.now()+30000;
    await put("outbox",item);notify();
    const error=Object.assign(new Error(item.error+" Your report is saved; retry or use standard matching."),{status:response.status,code:data.code,data});
    if(response.status===401) window.CarrickAuth.showLogin("Sign in to retry saved reports.");
    throw error;
  }

  async function fallbackRules(itemId){
    const item=await get("outbox",itemId);if(!item)return;
    const requestId=id();
    const db=await open();
    await new Promise((resolve,reject)=>{const tx=db.transaction("outbox","readwrite"),store=tx.objectStore("outbox");store.put({...item,id:requestId,payload:{...item.payload,analysis_mode:"rules",client_request_id:requestId,fallback_for:itemId},status:"pending",error:"",attempts:0,retryAt:0});store.delete(itemId);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});
    notify();await sync(true);
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
    id, enqueue, send, fallbackRules, sync, health, get, list, put, remove,
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
        store.put({ ...item, id: requestId, payload: { ...item.payload, schedule_version: versionId, client_request_id: requestId, supersedes_submission:itemId }, status: "pending", error: "",attempts:0,retryAt:0 });
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
