// Shared helpers, sign-in and the clip editor (used by the library and watch pages).
"use strict";

const ICONS = {
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  star: '<path d="m12 3 2.7 5.6 6.1.8-4.5 4.3 1.1 6.1L12 16.9l-5.4 2.9 1.1-6.1-4.5-4.3 6.1-.8z"/>',
  download: '<path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-4M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  out: '<path d="M14 5h5v5"/><path d="M19 5 10 14"/><path d="M19 14v5H5V5h5"/>',
};
function icon(name) {
  const span = document.createElement("span");
  span.style.display = "contents";
  span.innerHTML = `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
  return span.firstChild;
}

// h("div", {class: "x", onclick: fn}, child, "text") -> element. Text is never parsed as HTML.
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k in el && k !== "list" && k !== "form") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : String(c));
  }
  return el;
}

// replaceChildren that skips null/false entries.
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {}, credentials: "same-origin" };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error((data && data.detail) || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const m = Math.floor(s / 60), hh = Math.floor(m / 60);
  const pad = (n) => String(n).padStart(2, "0");
  return hh ? `${hh}:${pad(m % 60)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

function fmtDate(iso, long) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  if (long) return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const days = Math.floor((Date.now() - d) / 864e5);
  if (days < 1) return "Today";
  if (days < 2) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}

const fmtViews = (n) => `${n} ${n === 1 ? "view" : "views"}`;

let toastTimer;
function toast(message) {
  document.querySelector(".toast")?.remove();
  const el = h("div", { class: "toast", role: "status" }, message);
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), 3200);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = h("textarea", { value: text, style: "position:fixed;opacity:0" });
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

const clipUrl = (clip) => `${location.origin}/w/${clip.id}`;

// Copy a clip's link. Private clips become unlisted first, so the link works.
async function shareClip(clip, onChange) {
  try {
    let made = false;
    if (clip.visibility === "private") {
      Object.assign(clip, await api(`/api/clips/${clip.id}`, { method: "PATCH", body: { visibility: "unlisted" } }));
      made = true;
      onChange?.(clip);
    }
    const ok = await copyText(clipUrl(clip));
    toast(ok ? (made ? "Link copied. Clip is now unlisted." : "Link copied") : clipUrl(clip));
  } catch (e) { toast(e.message); }
}

function openDialog(build) {
  const dlg = h("dialog");
  dlg.addEventListener("close", () => dlg.remove());
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
  dlg.append(build(dlg));
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

function loginDialog(onDone) {
  openDialog((dlg) => {
    const pw = h("input", { type: "password", autocomplete: "current-password", required: true });
    const error = h("div", { class: "error" });
    return h("form", {
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        try {
          await api("/api/login", { method: "POST", body: { password: pw.value } });
          dlg.close();
          onDone ? onDone() : location.reload();
        } catch (err) { error.textContent = err.message; pw.select(); }
      },
    },
      h("h2", null, "Sign in"),
      h("label", { class: "field" }, h("span", null, "Admin password"), pw),
      error,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Cancel"),
        h("button", { class: "btn primary" }, "Sign in")),
    );
  });
}

const VISIBILITY = [
  ["private", "Private", "Only you"],
  ["unlisted", "Unlisted", "Anyone with the link"],
  ["public", "Public", "Listed on the home page"],
];

// Edit title, game and visibility. `onSaved(clip)` is called with the updated clip.
function editDialog(clip, onSaved) {
  openDialog((dlg) => {
    const original = clip.game ? clip.game.name : "";
    let picked;  // undefined = untouched, {appid, name} = chosen Steam app, {appid: null} = match removed

    const title = h("input", { type: "text", value: clip.title, maxLength: 200, required: true });
    const game = h("input", { type: "text", value: original, maxLength: 120, placeholder: "No game", list: "game-names" });
    const results = h("div", { class: "steam-results" });
    const steamHint = h("div", { class: "hint" });
    const applyAll = h("input", { type: "checkbox" });
    const applyRow = h("label", { class: "check", hidden: true }, applyAll,
      h("span", null, `Apply to every clip filed under “${original}”`));
    const error = h("div", { class: "error" });

    const names = h("datalist", { id: "game-names" });
    api("/api/games").then((d) => names.append(...d.games.map((g) => h("option", { value: g.name })))).catch(() => {});

    function showSteam() {
      steamHint.replaceChildren();
      const cur = picked !== undefined ? picked : (clip.game && game.value.trim() === original
        ? { appid: clip.game.steam_appid, name: clip.game.steam_name } : null);
      if (cur && cur.appid) {
        steamHint.append(`Steam: ${cur.name || "app"} (${cur.appid}) · `,
          h("a", { href: `https://steamdb.info/app/${cur.appid}/`, target: "_blank", rel: "noopener" }, "SteamDB"), " · ",
          h("button", { type: "button", class: "link", onclick: () => { picked = { appid: null }; refresh(); } }, "remove match"));
      } else if (game.value.trim()) {
        steamHint.append(picked ? "Steam match will be removed." : "No Steam match yet.");
      }
    }
    function refresh() {
      const changed = game.value.trim() !== original || picked !== undefined;
      applyRow.hidden = !(original && changed && game.value.trim());
      showSteam();
    }
    game.addEventListener("input", () => { picked = undefined; refresh(); });

    async function findOnSteam() {
      const term = game.value.trim();
      if (!term) return game.focus();
      results.replaceChildren(h("div", { class: "hint" }, "Searching Steam…"));
      try {
        const data = await api(`/api/steam/search?q=${encodeURIComponent(term)}`);
        results.replaceChildren(...(data.results.length ? data.results.map((r) =>
          h("button", { type: "button", onclick: () => {
            game.value = r.name; picked = { appid: r.appid, name: r.name };
            results.replaceChildren(); refresh();
          } }, h("img", { src: r.image, alt: "", loading: "lazy" }), h("span", null, r.name), h("small", null, r.appid)),
        ) : [h("div", { class: "hint" }, "Nothing found on Steam for that name.")]));
      } catch (err) { results.replaceChildren(h("div", { class: "error" }, err.message)); }
    }

    const seg = h("div", { class: "seg" }, VISIBILITY.map(([value, label, help]) =>
      h("label", null, h("input", { type: "radio", name: "visibility", value, checked: clip.visibility === value }),
        label, h("small", null, help))));

    async function save(e) {
      e.preventDefault();
      error.textContent = "";
      const body = { title: title.value, visibility: dlg.querySelector("input[name=visibility]:checked").value };
      const name = game.value.trim();
      const gameChanged = name !== original || picked !== undefined;
      try {
        if (gameChanged && original && name && applyAll.checked) {
          const gbody = {};
          if (name !== original) gbody.name = name;
          if (picked !== undefined) { gbody.steam_appid = picked.appid; gbody.steam_name = picked.name; }
          await api(`/api/games/${clip.game.id}`, { method: "PATCH", body: gbody });
        } else if (gameChanged) {
          body.game = name;
          if (picked !== undefined) { body.steam_appid = picked.appid; body.steam_name = picked.name; }
        }
        const updated = await api(`/api/clips/${clip.id}`, { method: "PATCH", body });
        dlg.close();
        onSaved?.(updated, gameChanged);
      } catch (err) { error.textContent = err.message; }
    }

    refresh();
    return h("form", { onsubmit: save },
      h("h2", null, "Edit clip"),
      h("label", { class: "field" }, h("span", null, "Title"), title),
      h("div", { class: "field" }, h("label", { for: "edit-game" }, "Game"),
        h("div", { class: "row" }, Object.assign(game, { id: "edit-game" }),
          h("button", { type: "button", class: "btn", onclick: findOnSteam }, "Find on Steam")),
        names, results, steamHint, applyRow),
      h("div", { class: "field" }, h("span", null, "Who can watch"), seg),
      clip.filename ? h("div", { class: "hint" }, `File: ${clip.filename}`) : null,
      error,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Cancel"),
        h("button", { class: "btn primary" }, "Save")),
    );
  });
}
