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

Object.assign(ICONS, {
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v.1a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  image: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4.5 17 5-4.5 3.5 3 2.5-2 4 3.5"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  film: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="m10 9.5 5 2.5-5 2.5z"/>',
});

// Game name + Steam search, shared by the clip editor's bulk variant.
// Resolves with {game, steam_appid?, steam_name?} or null if cancelled.
function gamePickerDialog(heading) {
  return new Promise((resolve) => {
    let result = null;
    const dlg = openDialog((dlg) => {
      let picked;
      const game = h("input", { type: "text", maxLength: 120, placeholder: "Game name (empty for no game)", list: "picker-games" });
      const names = h("datalist", { id: "picker-games" });
      api("/api/games").then((d) => names.append(...d.games.map((g) => h("option", { value: g.name })))).catch(() => {});
      const results = h("div", { class: "steam-results" });
      game.addEventListener("input", () => { picked = undefined; });
      async function find() {
        if (!game.value.trim()) return game.focus();
        results.replaceChildren(h("div", { class: "hint" }, "Searching Steam…"));
        try {
          const data = await api(`/api/steam/search?q=${encodeURIComponent(game.value.trim())}`);
          fill(results, data.results.length ? data.results.map((r) =>
            h("button", { type: "button", onclick: () => { game.value = r.name; picked = r; results.replaceChildren(); } },
              h("img", { src: r.image, alt: "", loading: "lazy" }), h("span", null, r.name), h("small", null, r.appid)))
            : h("div", { class: "hint" }, "Nothing found on Steam for that name."));
        } catch (err) { fill(results, h("div", { class: "error" }, err.message)); }
      }
      return h("form", { onsubmit: (e) => {
        e.preventDefault();
        result = { game: game.value.trim() };
        if (picked) Object.assign(result, { steam_appid: picked.appid, steam_name: picked.name });
        dlg.close();
      } },
        h("h2", null, heading),
        h("div", { class: "field" }, h("div", { class: "row" }, game,
          h("button", { type: "button", class: "btn", onclick: find }, "Find on Steam")), names, results),
        h("div", { class: "dialog-actions" },
          h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Cancel"),
          h("button", { class: "btn primary" }, "Apply")));
    });
    dlg.addEventListener("close", () => resolve(result));
  });
}

// Edit a game: name, Steam match, details and artwork. `onChange(game)` fires after every saved change.
function gameDialog(game, onChange) {
  openDialog((dlg) => {
    dlg.classList.add("wide");
    let tab = "details";
    const body = h("div", { class: "tab-body" });
    const error = h("div", { class: "error" });
    const changed = (g) => { game = Object.assign({}, game, g); onChange?.(game); };
    const run = async (fn) => {
      error.textContent = "";
      try { await fn(); } catch (err) { error.textContent = err.message; }
    };

    // ---- details tab
    function details() {
      const name = h("input", { type: "text", value: game.name, maxLength: 120, required: true });
      const desc = h("textarea", { value: game.description || "", rows: 4, maxLength: 2000 });
      const dev = h("input", { type: "text", value: game.developer || "" });
      const rel = h("input", { type: "text", value: game.release_date || "" });
      const genres = h("input", { type: "text", value: game.genres || "", placeholder: "Action, Shooter" });
      const search = h("input", { type: "text", value: game.name, placeholder: "Game name or Steam app ID" });
      const results = h("div", { class: "steam-results" });

      async function find() {
        if (!search.value.trim()) return search.focus();
        fill(results, h("div", { class: "hint" }, "Searching Steam…"));
        try {
          const data = await api(`/api/steam/search?q=${encodeURIComponent(search.value.trim())}`);
          fill(results, data.results.length ? data.results.map((r) =>
            h("button", { type: "button", onclick: () => run(async () => {
              fill(results, h("div", { class: "hint" }, `Loading ${r.name} from Steam…`));
              changed(await api(`/api/games/${game.id}`, { method: "PATCH", body: { name: r.name, steam_appid: r.appid, steam_name: r.name, wait: true } }));
              render();
              toast(`Matched to ${r.name}`);
            }) }, h("img", { src: r.image, alt: "", loading: "lazy" }), h("span", null, r.name), h("small", null, r.appid)))
            : h("div", { class: "hint" }, "Nothing found. Try a shorter name, or paste the app ID from the game's Steam or SteamDB address."));
        } catch (err) { fill(results, h("div", { class: "error" }, err.message)); }
      }
      search.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); find(); } });

      const match = h("div", { class: "match" });
      if (game.steam_appid) {
        match.append(
          h("div", null, h("strong", null, game.steam_name || "Steam app"), ` · app ${game.steam_appid} · `,
            h("a", { href: `https://steamdb.info/app/${game.steam_appid}/`, target: "_blank", rel: "noopener" }, "SteamDB"), " · ",
            h("a", { href: `https://store.steampowered.com/app/${game.steam_appid}/`, target: "_blank", rel: "noopener" }, "Steam")),
          h("div", { class: "row" },
            h("button", { type: "button", class: "btn small", onclick: () => run(async () => {
              changed(await api(`/api/games/${game.id}/refresh`, { method: "POST", body: {} })); render(); toast("Details refreshed from Steam");
            }) }, "Refresh details"),
            h("button", { type: "button", class: "btn small", onclick: () => run(async () => {
              changed(await api(`/api/games/${game.id}`, { method: "PATCH", body: { steam_appid: null } })); render();
            }) }, "Remove match")));
      } else {
        match.append(h("div", { class: "hint" }, "Not matched to a Steam game. Search below to add artwork and details, or fill them in by hand."));
      }

      return h("form", { onsubmit: (e) => { e.preventDefault(); run(async () => {
        const g = await api(`/api/games/${game.id}`, { method: "PATCH", body: {
          name: name.value, description: desc.value, developer: dev.value, release_date: rel.value, genres: genres.value } });
        changed(g); dlg.close(); toast("Game saved");
      }); } },
        h("label", { class: "field" }, h("span", null, "Name"), name),
        h("div", { class: "field" }, h("span", null, "Steam match"), match,
          h("div", { class: "row" }, search, h("button", { type: "button", class: "btn", onclick: find }, "Search Steam")), results),
        h("label", { class: "field" }, h("span", null, "Description"), desc),
        h("div", { class: "field-row" },
          h("label", { class: "field" }, h("span", null, "Developer"), dev),
          h("label", { class: "field" }, h("span", null, "Released"), rel)),
        h("label", { class: "field" }, h("span", null, "Genres"), genres),
        h("div", { class: "dialog-actions" },
          h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Close"),
          h("button", { class: "btn primary" }, "Save")));
    }

    // ---- artwork tab
    let slot = "cover";
    let source = game.steam_appid ? "steam" : "sgdb";
    let sgdbQuery = "";
    function artwork() {
      const SLOTS = { cover: ["Cover", "Shown in the sidebar, the games grid and on share pages."],
        hero: ["Background", "The wide banner behind the game's page."] };
      const current = game[slot];
      const choices = h("div", { class: "art-grid" });
      const use = (payload) => run(async () => {
        choices.classList.add("busy");
        try {
          changed(payload instanceof Blob
            ? await uploadArt(game.id, slot, payload)
            : await api(`/api/games/${game.id}/art/${slot}`, { method: "POST", body: { url: payload } }));
          toast(`${SLOTS[slot][0]} updated`);
        } finally { choices.classList.remove("busy"); render(); }
      });
      const show = (art, empty) => fill(choices, art.length ? art.map((a) =>
        h("button", { type: "button", class: "art-choice", title: `Use this image (${a.label})`, onclick: () => use(a.url) },
          h("img", { src: a.thumb, alt: a.label, loading: "lazy", onerror: (e) => e.target.closest("button").remove() }),
          h("span", null, a.label)))
        : h("div", { class: "hint" }, empty));
      const loading = (text) => fill(choices, h("div", { class: "hint" }, text));
      const failed = (err) => fill(choices, h("div", { class: "error" }, err.message));

      let sgdbSearch = null;
      if (source === "steam") {
        if (game.steam_appid) {
          loading("Loading artwork from Steam…");
          api(`/api/games/${game.id}/art`).then((d) => show(d.art, "Steam has no artwork for this game.")).catch(failed);
        } else {
          loading("This game isn't matched to Steam. Match it on the Details tab, or try SteamGridDB.");
        }
      } else {
        const q = h("input", { type: "text", value: sgdbQuery, placeholder: `Search SteamGridDB (default: ${game.name})`, "aria-label": "Search SteamGridDB" });
        const go = () => { sgdbQuery = q.value.trim(); render(); };
        q.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); go(); } });
        sgdbSearch = h("div", { class: "row" }, q, h("button", { type: "button", class: "btn", onclick: go }, "Search"));
        loading("Loading artwork from SteamGridDB…");
        api("/api/me").then((me) => {
          if (!me.sgdb) {
            sgdbSearch.hidden = true;
            return fill(choices, h("div", { class: "hint" }, "SteamGridDB has community artwork for almost every game, including ones that aren't on Steam. ",
              h("a", { href: "/settings#artwork" }, "Add a free API key in Settings"), " to use it."));
          }
          return api(`/api/games/${game.id}/art?source=sgdb&slot=${slot}&q=${encodeURIComponent(sgdbQuery)}`).then((d) =>
            show(d.art, d.matched ? `SteamGridDB has no ${slot === "cover" ? "wide covers" : "backgrounds"} for ${d.matched}.`
              : "SteamGridDB didn't find this game. Try searching for it by another name."));
        }).catch(failed);
      }

      const url = h("input", { type: "text", placeholder: "https://…/image.jpg", "aria-label": "Image address" });
      const file = h("input", { type: "file", accept: "image/*", hidden: true, onchange: () => file.files[0] && use(file.files[0]) });
      const chip = (key, label) => h("button", { type: "button", class: `chip${source === key ? " active" : ""}`, onclick: () => { source = key; render(); } }, label);
      return h("div", { class: "art-tab" },
        h("div", { class: "seg two" }, Object.entries(SLOTS).map(([key, [label, help]]) =>
          h("label", null, h("input", { type: "radio", name: "slot", checked: slot === key, onchange: () => { slot = key; render(); } }),
            label, h("small", null, help)))),
        h("div", { class: `art-current ${slot}` }, current ? h("img", { src: current, alt: "" }) : h("span", null, "No image yet")),
        h("div", { class: "field" },
          h("div", { class: "row" }, h("span", null, "Choose from"), chip("steam", "Steam"), chip("sgdb", "SteamGridDB")),
          sgdbSearch, choices),
        h("div", { class: "field" }, h("span", null, "Or use your own image"),
          h("div", { class: "row" }, url,
            h("button", { type: "button", class: "btn", onclick: () => url.value.trim() ? use(url.value.trim()) : url.focus() }, "Use address"),
            h("button", { type: "button", class: "btn", onclick: () => file.click() }, "Upload…"), file)),
        h("div", { class: "dialog-actions" },
          game.art_locked ? h("button", { type: "button", class: "btn ghost", onclick: () => run(async () => {
            changed(await api(`/api/games/${game.id}/art`, { method: "DELETE" })); render(); toast("Artwork reset");
          }) }, "Reset to automatic artwork") : null,
          h("div", { class: "spacer" }),
          h("button", { type: "button", class: "btn primary", onclick: () => dlg.close() }, "Done")));
    }

    const tabs = h("div", { class: "tabs", role: "tablist" });
    function render() {
      fill(tabs, [["details", "Details"], ["artwork", "Artwork"]].map(([key, label]) =>
        h("button", { type: "button", role: "tab", class: tab === key ? "active" : "", onclick: () => { tab = key; error.textContent = ""; render(); } }, label)));
      fill(body, tab === "details" ? details() : artwork());
    }
    render();
    return h("div", { class: "dialog-pad" }, h("h2", null, `Edit ${game.name}`), tabs, body, error);
  });
}

async function uploadArt(gameId, slot, blob) {
  const res = await fetch(`/api/games/${gameId}/art/${slot}`, { method: "PUT", body: blob, credentials: "same-origin",
    headers: { "Content-Type": "application/octet-stream" } });
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error((data && data.detail) || "Upload failed");
  return data;
}

ICONS.trash = '<path d="M4 7h16"/><path d="M9 7V4.5h6V7"/><path d="M6.5 7l1 12.5h9l1-12.5"/><path d="M10 11v5M14 11v5"/>';

// Ask how to delete clips, then do it. `onDone()` runs after a successful delete.
function deleteDialog(ids, onDone) {
  const many = ids.length !== 1;
  const what = many ? `${ids.length} clips` : "this clip";
  openDialog((dlg) => {
    const error = h("div", { class: "error" });
    const note = h("div", { class: "hint" });
    const fileBtn = h("button", { type: "button", class: "btn danger", hidden: true }, many ? "Delete files" : "Delete file");
    const go = async (file) => {
      error.textContent = "";
      try {
        await api("/api/clips/delete", { method: "POST", body: { ids, file } });
        dlg.close();
        toast(file ? `Deleted ${what}` : `Removed ${what} from the library`);
        onDone?.();
      } catch (err) { error.textContent = err.message; }
    };
    fileBtn.addEventListener("click", () => go(true));
    api("/api/me").then((me) => {
      if (me.can_delete_files) {
        fileBtn.hidden = false;
        note.textContent = `“Delete ${many ? "files" : "file"}” erases the video from the clips folder for good. If that folder syncs with your PC, it may be deleted there too.`;
      } else {
        note.textContent = "The clips folder is mounted read-only, so the video files can't be deleted from here. To allow it, remove “:ro” from the clips volume in your compose file.";
      }
    }).catch(() => {});
    return h("form", { onsubmit: (e) => e.preventDefault() },
      h("h2", null, `Delete ${what}?`),
      h("p", null, `“Remove from library” hides ${many ? "them" : "it"} here and turns off ${many ? "their links" : "its link"}, but keeps the video ${many ? "files" : "file"} on disk. You can bring removed clips back from Settings.`),
      note, error,
      h("div", { class: "dialog-actions" },
        h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Cancel"),
        fileBtn,
        h("button", { type: "button", class: "btn primary", onclick: () => go(false) }, "Remove from library")));
  });
}
