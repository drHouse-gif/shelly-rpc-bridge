const PAGES = [
  ["overview", "Overview"],
  ["devices", "Devices"],
  ["remote", "Remote Pair"],
  ["doctor", "Doctor"],
  ["backups", "Backup / Restore"],
  ["clone", "Clone"],
  ["rpc", "RPC Explorer"],
  ["scripts", "Scripts"],
  ["events", "Events"],
  ["settings", "Settings"],
];

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const pretty = (value) => escapeHtml(JSON.stringify(value, null, 2));

class ShellyToolkitPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = undefined;
    this.page = "overview";
    this.devices = [];
    this.backups = [];
    this.credentials = [];
    this.output = undefined;
    this.overview = {};
    this.error = "";
    this.busy = false;
  }

  set hass(value) {
    const firstLoad = !this._hass;
    this._hass = value;
    if (firstLoad) this.loadBase();
  }

  set panel(value) {
    this._panel = value;
  }

  connectedCallback() {
    this.render();
  }

  disconnectedCallback() {
    if (this.eventSubscription) this.eventSubscription();
    this.eventSubscription = undefined;
  }

  async call(type, data = {}) {
    if (!this._hass) throw new Error("Home Assistant is not ready");
    return this._hass.callWS({ type: `shelly_toolkit/${type}`, ...data });
  }

  async loadBase() {
    await this.run(async () => {
      [this.devices, this.backups, this.credentials, this.overview] = await Promise.all([
        this.call("devices"),
        this.call("backups"),
        this.call("credentials"),
        this.call("overview"),
      ]);
    }, false);
  }

  async run(action, showOutput = true) {
    this.busy = true;
    this.error = "";
    this.render();
    try {
      const result = await action();
      if (showOutput) this.output = result;
      return result;
    } catch (error) {
      this.error = error?.message || String(error);
      throw error;
    } finally {
      this.busy = false;
      this.render();
    }
  }

  render() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <style>${this.styles()}</style>
      <div class="shell">
        <header>
          <div><h1>Shelly Toolkit</h1><p>Independent community project. Not affiliated with or endorsed by Shelly Group.</p></div>
          <button id="refresh" class="secondary" ${this.busy ? "disabled" : ""}>Refresh</button>
        </header>
        <nav>${PAGES.map(([key, label]) => `<button data-page="${key}" class="${this.page === key ? "active" : ""}">${label}</button>`).join("")}</nav>
        ${this.error ? `<div class="alert error">${escapeHtml(this.error)}</div>` : ""}
        ${this.busy ? '<div class="progress">Working…</div>' : ""}
        <main>${this.pageContent()}</main>
      </div>`;
    this.bindCommon();
    this.bindPage();
  }

  pageContent() {
    const renderer = this[`render_${this.page}`];
    return renderer ? renderer.call(this) : "";
  }

  bindCommon() {
    this.shadowRoot.querySelectorAll("nav button").forEach((button) => {
      button.addEventListener("click", () => {
        this.page = button.dataset.page;
        this.output = undefined;
        this.error = "";
        this.render();
      });
    });
    this.shadowRoot.getElementById("refresh")?.addEventListener("click", () => {
      this.run(async () => {
        await this.call("refresh");
        await this.loadBase();
        return { refreshed: true };
      }).catch(() => {});
    });
  }

  bindPage() {
    const binder = this[`bind_${this.page}`];
    if (binder) binder.call(this);
  }

  deviceOptions(selected = "") {
    if (!this.devices.length) return '<option value="">No devices available</option>';
    return this.devices.map((device) => `<option value="${escapeHtml(device.id)}" ${device.id === selected ? "selected" : ""}>${escapeHtml(device.name)} · ${escapeHtml(device.connection)}${device.online ? "" : " · offline"}</option>`).join("");
  }

  outputCard(title = "Result") {
    return this.output === undefined ? "" : `<section class="card"><h2>${escapeHtml(title)}</h2><pre>${pretty(this.output)}</pre></section>`;
  }

  render_overview() {
    const online = this.devices.filter((item) => item.online).length;
    const remote = this.devices.filter((item) => item.connection === "remote").length;
    return `
      <div class="stats">
        ${[["Devices", this.devices.length], ["Online", online], ["Remote", remote], ["Warnings", this.overview.warnings || 0], ["Backups", this.backups.length]].map(([label, value]) => `<section class="stat"><span>${label}</span><strong>${value}</strong></section>`).join("")}
      </div>
      <section class="card"><h2>Purpose</h2><p>Shelly Toolkit is an administrator-only maintenance and developer layer for Shelly Gen2+ RPC devices. It is not a cloud fleet manager and does not replace normal Home Assistant entities.</p></section>
      ${this.overview.latest_problems?.length ? `<section class="card"><h2>Latest diagnostic problems</h2><ul class="list">${this.overview.latest_problems.map((item) => `<li><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.severity)} · ${escapeHtml(item.title)}</small></div></li>`).join("")}</ul></section>` : ""}
      ${this.outputCard()}`;
  }

  render_devices() {
    const rows = this.devices.map((device) => `<tr>
      <td><strong>${escapeHtml(device.name)}</strong><small>${escapeHtml(device.id)}</small></td>
      <td>${escapeHtml(device.model || "Unknown")}</td><td>${escapeHtml(device.connection)}</td>
      <td><span class="badge ${device.online ? "ok" : "bad"}">${device.online ? "Online" : "Offline"}</span></td>
      <td>${escapeHtml(device.firmware || "—")}</td><td>${escapeHtml(device.rssi ?? "—")}</td>
      <td>${escapeHtml(device.last_seen ? new Date(device.last_seen * 1000).toLocaleString() : "—")}</td>
      <td><button class="secondary" data-capabilities="${escapeHtml(device.id)}">Capabilities</button>${device.connection === "local" ? ` <button class="danger" data-remove-local="${escapeHtml(device.id)}">Remove</button>` : ""}</td>
    </tr>`).join("");
    return `
      <section class="card"><h2>Known targets</h2><div class="table"><table><thead><tr><th>Device</th><th>Model</th><th>Connection</th><th>Status</th><th>Firmware</th><th>RSSI</th><th>Last seen</th><th>Tools</th></tr></thead><tbody>${rows || '<tr><td colspan="8">No targets yet.</td></tr>'}</tbody></table></div></section>
      <section class="card"><h2>Add local RPC target</h2><p class="hint">If the official Shelly integration already owns the same MAC, Toolkit reuses it instead of creating duplicate entities.</p>
        <form id="local-form" class="form-grid">
          <label>Host<input name="host" required placeholder="192.168.1.25"></label>
          <label>Port<input name="port" type="number" min="1" max="65535" value="80"></label>
          <label>Transport<select name="transport"><option value="websocket">WebSocket</option><option value="http">HTTP</option></select></label>
          <label>Username<input name="username" value="admin" autocomplete="username"></label>
          <label>Password<input name="password" type="password" autocomplete="current-password"></label>
          <label class="check"><input name="use_ssl" type="checkbox"> TLS</label>
          <button type="submit">Add and verify</button>
        </form>
      </section>${this.outputCard()}`;
  }

  bind_devices() {
    this.shadowRoot.querySelectorAll("[data-capabilities]").forEach((button) => button.addEventListener("click", () => {
      const device = this.devices.find((item) => item.id === button.dataset.capabilities);
      this.output = device ? device.capabilities : { error: "Device not found" };
      this.render();
    }));
    this.shadowRoot.querySelectorAll("[data-remove-local]").forEach((button) => button.addEventListener("click", () => {
      if (!confirm("Remove this Toolkit-managed local target?")) return;
      this.run(async () => { await this.call("local/remove", { device_id: button.dataset.removeLocal }); await this.loadBase(); return { removed: button.dataset.removeLocal }; }).catch(() => {});
    }));
    this.shadowRoot.getElementById("local-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(event.currentTarget));
      this.run(async () => {
        const result = await this.call("local/add", {
          host: data.host, port: Number(data.port), transport: data.transport,
          username: data.username, password: data.password || undefined,
          use_ssl: data.use_ssl === "on", verify_ssl: data.use_ssl === "on",
        });
        await this.loadBase();
        return result;
      }).catch(() => {});
    });
  }

  render_remote() {
    const credentials = this.credentials.map((item) => `<li><div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.id)} · ${item.bound_device_id ? `Bound to ${escapeHtml(item.bound_device_id)}` : "Not yet paired"}</small></div><div class="actions"><button data-regenerate="${escapeHtml(item.id)}" class="secondary">Regenerate</button><button data-revoke="${escapeHtml(item.id)}" class="danger">Revoke</button></div></li>`).join("");
    return `<section class="card"><h2>Remote Pair</h2><p>A remote Shelly opens an outbound WebSocket to Home Assistant. The generated token is shown once; Toolkit stores only its SHA-256 verifier. Use HTTPS/WSS externally.</p>
      <form id="credential-form" class="inline"><input name="name" required maxlength="80" placeholder="Remote office relay"><button type="submit">Generate pairing URL</button></form>
      <ul class="list">${credentials || "<li>No remote credentials.</li>"}</ul></section>
      ${this.output ? `<section class="card"><h2>Pairing result</h2>${this.output.url ? `<div class="alert warning"><strong>Copy now — shown once</strong><code>${escapeHtml(this.output.url)}</code></div>` : `<pre>${pretty(this.output)}</pre>`}</section>` : ""}`;
  }

  bind_remote() {
    this.shadowRoot.getElementById("credential-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const name = new FormData(event.currentTarget).get("name");
      this.run(async () => {
        const result = await this.call("credential/create", { name });
        this.credentials = await this.call("credentials");
        return result;
      }).catch(() => {});
    });
    this.shadowRoot.querySelectorAll("[data-revoke]").forEach((button) => button.addEventListener("click", () => {
      if (!confirm("Revoke this credential and disconnect its device?")) return;
      this.run(async () => {
        this.credentials = await this.call("credential/revoke", { credential_id: button.dataset.revoke, confirm: true });
        return { revoked: button.dataset.revoke };
      }).catch(() => {});
    }));
    this.shadowRoot.querySelectorAll("[data-regenerate]").forEach((button) => button.addEventListener("click", () => {
      if (!confirm("Regenerate this token? The previous URL stops working immediately.")) return;
      this.run(async () => {
        const result = await this.call("credential/regenerate", { credential_id: button.dataset.regenerate, confirm: true });
        this.credentials = await this.call("credentials");
        return result;
      }).catch(() => {});
    }));
  }

  toolForm(title, id, submit, body, note = "") {
    return `<section class="card"><h2>${title}</h2>${note ? `<p class="hint">${note}</p>` : ""}<form id="${id}" class="form-grid">${body}<button type="submit">${submit}</button></form></section>`;
  }

  render_doctor() {
    return this.toolForm("Shelly Doctor", "doctor-form", "Run diagnostics", `<label>Device<select name="device_id">${this.deviceOptions()}</select></label>`, "Findings are reported only when the device exposes supporting evidence.") + this.outputCard("Diagnostic report");
  }

  bind_doctor() {
    this.bindSimpleForm("doctor-form", "doctor", (data) => ({ device_id: data.get("device_id") }));
  }

  render_backups() {
    const rows = this.backups.map((item) => `<tr><td>${escapeHtml(item.id)}</td><td>${escapeHtml(item.device?.name || item.device?.model || "Unknown")}</td><td>${escapeHtml(item.created_at || "")}</td><td><button class="secondary" data-download="${escapeHtml(item.id)}">Download</button> <button class="danger" data-delete="${escapeHtml(item.id)}">Delete</button></td></tr>`).join("");
    return `
      ${this.toolForm("Create backup", "backup-form", "Back up device", `<label>Device<select name="device_id">${this.deviceOptions()}</select></label>`, "Structured secret fields are redacted. Script source is preserved and can contain hard-coded sensitive values.")}
      <section class="card"><h2>Stored backups</h2><div class="table"><table><thead><tr><th>ID</th><th>Source</th><th>Created</th><th>Actions</th></tr></thead><tbody>${rows || '<tr><td colspan="4">No backups.</td></tr>'}</tbody></table></div></section>
      <section class="card"><h2>Restore with preview</h2><form id="restore-form" class="form-grid"><label>Backup<select name="backup_id">${this.backups.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.id)} · ${escapeHtml(item.device?.name || "device")}</option>`).join("")}</select></label><label>Target<select name="target_id">${this.deviceOptions()}</select></label><label>Mode<select name="mode"><option value="smart">Smart migration</option><option value="exact">Exact clone</option></select></label><button type="submit">Preview restore</button><button type="button" id="restore-apply" class="danger">Apply last preview</button></form></section>${this.outputCard("Backup / restore report")}`;
  }

  bind_backups() {
    this.shadowRoot.getElementById("backup-form")?.addEventListener("submit", (event) => {
      event.preventDefault(); const data = new FormData(event.currentTarget);
      this.run(async () => { const result = await this.call("backup/create", { device_id: data.get("device_id") }); this.backups = await this.call("backups"); return result; }).catch(() => {});
    });
    this.shadowRoot.getElementById("restore-form")?.addEventListener("submit", (event) => {
      event.preventDefault(); const data = new FormData(event.currentTarget);
      const request = { backup_id: data.get("backup_id"), target_id: data.get("target_id"), mode: data.get("mode") };
      this.lastRestore = request; this.run(() => this.call("restore/preview", request)).catch(() => {});
    });
    this.shadowRoot.getElementById("restore-apply")?.addEventListener("click", () => {
      if (!this.lastRestore || !confirm("Apply every READY operation from the last preview?")) return;
      this.run(() => this.call("restore/apply", { ...this.lastRestore, confirm: true })).catch(() => {});
    });
    this.shadowRoot.querySelectorAll("[data-download]").forEach((button) => button.addEventListener("click", () => this.run(async () => {
      const backup = await this.call("backup/get", { backup_id: button.dataset.download });
      const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" })); link.download = `${button.dataset.download}.json`; link.click(); URL.revokeObjectURL(link.href); return { downloaded: button.dataset.download };
    }).catch(() => {})));
    this.shadowRoot.querySelectorAll("[data-delete]").forEach((button) => button.addEventListener("click", () => {
      if (!confirm("Delete this stored backup?")) return;
      this.run(async () => { await this.call("backup/delete", { backup_id: button.dataset.delete, confirm: true }); this.backups = await this.call("backups"); return { deleted: button.dataset.delete }; }).catch(() => {});
    }));
  }

  render_clone() {
    return this.toolForm("Clone / Smart Migration", "clone-form", "Preview", `<label>Source<select name="source_id">${this.deviceOptions()}</select></label><label>Target<select name="target_id">${this.deviceOptions()}</select></label><label>Mode<select name="mode"><option value="smart">Smart migration</option><option value="exact">Exact clone</option></select></label><button type="button" id="clone-apply" class="danger">Apply last preview</button>`, "A fresh source backup and compatibility report are created before any target mutation.") + this.outputCard("Migration report");
  }

  bind_clone() {
    this.shadowRoot.getElementById("clone-form")?.addEventListener("submit", (event) => {
      event.preventDefault(); const data = new FormData(event.currentTarget); this.lastClone = { source_id: data.get("source_id"), target_id: data.get("target_id"), mode: data.get("mode") }; this.run(() => this.call("migration/preview", this.lastClone)).catch(() => {});
    });
    this.shadowRoot.getElementById("clone-apply")?.addEventListener("click", () => {
      if (!this.lastClone || !confirm("Apply the compatible operations from the last migration preview?")) return;
      this.run(() => this.call("migration/apply", { ...this.lastClone, confirm: true })).catch(() => {});
    });
  }

  render_rpc() {
    const history = JSON.parse(localStorage.getItem("shelly_toolkit_rpc_history") || "[]");
    return this.toolForm("RPC Explorer", "rpc-form", "Execute RPC", `<label>Device<select name="device_id">${this.deviceOptions()}</select></label><label>Method<input name="method" required list="rpc-history" value="Shelly.GetStatus"><datalist id="rpc-history">${history.map((item) => `<option value="${escapeHtml(item)}">`).join("")}</datalist></label><label class="wide">JSON parameters<textarea name="params" rows="7">{}</textarea></label><label class="check"><input name="confirm" type="checkbox"> Confirm destructive method</label>`, "Only Home Assistant administrators can use this console. Credentials are never added to local history.") + this.outputCard("RPC response");
  }

  bind_rpc() {
    this.shadowRoot.getElementById("rpc-form")?.addEventListener("submit", (event) => {
      event.preventDefault(); const data = new FormData(event.currentTarget); let params;
      try { params = JSON.parse(data.get("params")); } catch { this.error = "Parameters must be valid JSON"; this.render(); return; }
      const method = data.get("method").trim(); const history = JSON.parse(localStorage.getItem("shelly_toolkit_rpc_history") || "[]"); localStorage.setItem("shelly_toolkit_rpc_history", JSON.stringify([method, ...history.filter((item) => item !== method)].slice(0, 20)));
      this.run(() => this.call("rpc", { device_id: data.get("device_id"), method, params, confirm: data.get("confirm") === "on" })).catch(() => {});
    });
  }

  render_scripts() {
    return `<section class="card"><h2>Script Studio</h2><form id="script-list" class="inline"><select name="device_id">${this.deviceOptions()}</select><button>List scripts</button></form><form id="script-editor" class="form-grid"><label>Device<select name="device_id">${this.deviceOptions()}</select></label><label>Script ID<input name="script_id" type="number" min="1" required></label><label>Name<input name="name" value="Shelly Script"></label><label class="wide">Code<textarea name="code" rows="14" spellcheck="false"></textarea></label><div class="actions wide"><button type="button" id="script-load" class="secondary">Load code</button><button type="submit" class="danger">Back up and upload</button><button type="button" data-control="start">Start</button><button type="button" data-control="stop" class="secondary">Stop</button><button type="button" data-control="restart" class="secondary">Restart</button></div></form></section>${this.outputCard("Script result")}`;
  }

  bind_scripts() {
    this.shadowRoot.getElementById("script-list")?.addEventListener("submit", (event) => { event.preventDefault(); const data = new FormData(event.currentTarget); this.run(() => this.call("scripts", { device_id: data.get("device_id") })).catch(() => {}); });
    const editor = this.shadowRoot.getElementById("script-editor");
    const request = () => { const data = new FormData(editor); return { device_id: data.get("device_id"), script_id: Number(data.get("script_id")) }; };
    this.shadowRoot.getElementById("script-load")?.addEventListener("click", () => this.run(async () => { const result = await this.call("script/code", request()); editor.elements.code.value = result.code; return result; }).catch(() => {}));
    editor?.addEventListener("submit", (event) => { event.preventDefault(); if (!confirm("Overwrite this script after saving its current code as a Toolkit backup?")) return; const data = new FormData(editor); this.run(() => this.call("script/upload", { ...request(), name: data.get("name"), code: data.get("code"), confirm: true })).catch(() => {}); });
    this.shadowRoot.querySelectorAll("[data-control]").forEach((button) => button.addEventListener("click", () => this.run(() => this.call("script/control", { ...request(), action: button.dataset.control })).catch(() => {})));
  }

  render_events() {
    return `<section class="card"><h2>Event Viewer</h2><form id="events-form" class="form-grid"><label>Device<select name="device_id"><option value="">All devices</option>${this.deviceOptions()}</select></label><label>Filter<input name="filter" placeholder="switch:0"></label><label>Limit<input name="limit" type="number" min="1" max="500" value="200"></label><button>Load events</button><button type="button" id="events-live" class="secondary">${this.eventSubscription ? "Stop live events" : "Start live events"}</button></form></section>${this.outputCard("Bounded event history")}`;
  }

  bind_events() {
    this.shadowRoot.getElementById("events-form")?.addEventListener("submit", (event) => { event.preventDefault(); const data = new FormData(event.currentTarget); const request = { filter: data.get("filter") || undefined, limit: Number(data.get("limit")) }; if (data.get("device_id")) request.device_id = data.get("device_id"); this.run(() => this.call("events", request)).catch(() => {}); });
    this.shadowRoot.getElementById("events-live")?.addEventListener("click", async () => {
      if (this.eventSubscription) {
        this.eventSubscription(); this.eventSubscription = undefined; this.render(); return;
      }
      try {
        this.eventSubscription = await this._hass.connection.subscribeMessage((event) => {
          const current = Array.isArray(this.output) ? this.output : [];
          this.output = [event, ...current].slice(0, 200);
          if (this.page === "events") this.render();
        }, { type: "shelly_toolkit/events/subscribe" });
        this.render();
      } catch (error) { this.error = error?.message || String(error); this.render(); }
    });
  }

  render_settings() {
    return `<section class="card"><h2>Settings and security boundaries</h2><ul><li>The panel and every backend command require a Home Assistant administrator.</li><li>Remote credentials are revocable, one-device-bound verifiers; secrets are never logged or stored in clear text.</li><li>RPC Explorer is intentionally powerful. Destructive methods need explicit confirmation.</li><li>Backups redact structured password, token, secret, credential, and private-key fields. Script source is preserved and may itself contain sensitive values.</li><li>Factory reset and automatic network/auth restoration are not implemented.</li></ul><p>Version 0.4.1 · Shelly Gen2+ capability-based support.</p></section>`;
  }

  bindSimpleForm(id, command, build) {
    this.shadowRoot.getElementById(id)?.addEventListener("submit", (event) => { event.preventDefault(); this.run(() => this.call(command, build(new FormData(event.currentTarget)))).catch(() => {}); });
  }

  styles() {
    return `:host{display:block;background:var(--primary-background-color);color:var(--primary-text-color);min-height:100vh;font-family:var(--paper-font-body1_-_font-family,Roboto,sans-serif)}*{box-sizing:border-box}.shell{max-width:1400px;margin:auto;padding:20px}header{display:flex;justify-content:space-between;gap:16px;align-items:center}h1{font-size:28px;margin:0}h2{font-size:19px;margin:0 0 14px}p{line-height:1.5}header p,.hint,small{display:block;color:var(--secondary-text-color);font-size:13px}nav{display:flex;gap:5px;overflow:auto;padding:16px 0;position:sticky;top:0;background:var(--primary-background-color);z-index:2}button,input,select,textarea{font:inherit}button{border:0;border-radius:8px;background:var(--primary-color);color:var(--text-primary-color);padding:10px 14px;cursor:pointer;white-space:nowrap}button:disabled{opacity:.5}button.secondary,nav button{background:var(--secondary-background-color);color:var(--primary-text-color)}nav button.active{background:var(--primary-color);color:var(--text-primary-color)}button.danger{background:var(--error-color,#db4437);color:white}.card,.stat{background:var(--card-background-color);border-radius:12px;box-shadow:var(--ha-card-box-shadow,0 2px 5px #0002);padding:18px;margin-bottom:16px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}.stat span{color:var(--secondary-text-color)}.stat strong{display:block;font-size:30px;margin-top:7px}.form-grid{display:grid;grid-template-columns:repeat(3,minmax(150px,1fr));gap:14px;align-items:end}.form-grid label{display:grid;gap:6px}.form-grid .wide{grid-column:1/-1}.inline,.actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.inline input,.inline select{flex:1}.check{display:flex!important;grid-auto-flow:column;justify-content:start;align-items:center}input,select,textarea{width:100%;border:1px solid var(--divider-color);border-radius:7px;padding:10px;background:var(--card-background-color);color:var(--primary-text-color)}textarea,pre,code{font-family:var(--code-font-family,monospace)}pre{overflow:auto;white-space:pre-wrap;max-height:480px;background:var(--secondary-background-color);padding:14px;border-radius:8px}.table{overflow:auto}table{border-collapse:collapse;width:100%;min-width:720px}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--divider-color);vertical-align:top}.badge{border-radius:20px;padding:4px 8px;font-size:12px}.ok{background:color-mix(in srgb,var(--success-color,#43a047) 18%,transparent);color:var(--success-color,#43a047)}.bad{background:color-mix(in srgb,var(--error-color,#db4437) 18%,transparent);color:var(--error-color,#db4437)}.alert{padding:12px;border-radius:8px;margin:10px 0}.error{background:color-mix(in srgb,var(--error-color,#db4437) 18%,transparent);color:var(--error-color,#db4437)}.warning{background:color-mix(in srgb,var(--warning-color,#ffa600) 16%,transparent)}.alert code{display:block;overflow-wrap:anywhere;margin-top:8px;user-select:all}.progress{height:3px;background:var(--primary-color);animation:pulse 1s infinite}.list{padding:0;list-style:none}.list li{display:flex;justify-content:space-between;gap:10px;padding:12px 0;border-bottom:1px solid var(--divider-color)}@keyframes pulse{50%{opacity:.35}}@media(max-width:800px){.shell{padding:12px}.stats{grid-template-columns:repeat(2,1fr)}.form-grid{grid-template-columns:1fr}header{align-items:flex-start}.list li{display:block}.list .actions{margin-top:8px}}`;
  }
}

if (!customElements.get("shelly-toolkit-panel")) {
  customElements.define("shelly-toolkit-panel", ShellyToolkitPanel);
}
