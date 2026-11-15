// Settings page. Every control saves as soon as it changes.
"use strict";

const main = document.getElementById("settings-main");
const nav = document.getElementById("settings-nav");
const ACCENTS = ["#ff7a45", "#f2b84b", "#4cc38a", "#3ec5d6", "#5b8def", "#9b7bff", "#ee5c9a", "#e5484d"];
let values = {}, defaults = {};

async function save(key, value, control) {
  try {
    values = (await api("/api/settings", { method: "PATCH", body: { [key]: value } })).values;
    toast("Saved");
    if (key === "accent") applyAccent(values.accent);
    if (key === "site_name") document.querySelector(".brand-name").textContent = values.site_name;
    return true;
  } catch (err) {
    toast(err.message);
    control?.classList.add("invalid");
    return false;
  }
}

function applyAccent(color) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
  const root = document.documentElement.style;
  root.setProperty("--accent", color);
  root.setProperty("--accent-ink", 0.299 * r + 0.587 * g + 0.114 * b > 140 ? "#14100e" : "#ffffff");
}

// ---- controls ---------------------------------------------------------------

function row(label, help, control) {
  return h("div", { class: "set-row" },
    h("div", { class: "set-label" }, h("strong", null, label), help ? h("span", null, help) : null), h("div", { class: "set-control" }, control));
}

function toggle(key) {
  const input = h("input", { type: "checkbox", checked: values[key], "aria-label": key.replaceAll("_", " "),
    onchange: async () => { if (!(await save(key, input.checked))) input.checked = !input.checked; } });
  return h("label", { class: "switch" }, input, h("span"));
}

function text(key, attrs = {}) {
  const input = h("input", { type: "text", value: values[key], ...attrs });
  input.addEventListener("change", async () => {
    input.classList.remove("invalid");
    if (await save(key, input.value, input)) input.value = values[key];
  });
  return input;
}

function select(key, options) {
  const el = h("select", { onchange: () => save(key, el.value) }, options.map(([value, label]) => h("option", { value }, label)));
  el.value = values[key];
  return el;
}

function number(key, min, max, unit) {
  const input = h("input", { type: "number", value: values[key], min, max, style: "width:110px" });
  input.addEventListener("change", async () => {
    input.classList.remove("invalid");
    if (await save(key, Number(input.value), input)) input.value = values[key];
  });
  return h("div", { class: "row" }, input, h("span", { class: "hint" }, unit));
}

function accentPicker() {
  const custom = h("input", { type: "color", value: values.accent, title: "Custom colour", "aria-label": "Custom colour",
    onchange: () => save("accent", custom.value).then(draw) });
  const box = h("div", { class: "swatches" });
  function draw() {
    fill(box, ACCENTS.map((c) => h("button", { type: "button", class: `swatch${values.accent === c ? " active" : ""}`, style: `background:${c}`,
      title: c, "aria-label": `Accent ${c}`, onclick: () => save("accent", c).then(draw) })), custom);
    custom.value = values.accent;
  }
  draw();
  return box;
}

// ---- sections ---------------------------------------------------------------

function section(id, title, intro, ...rows) {
  return h("section", { class: "set-card", id }, h("h2", null, title), intro ? h("p", { class: "set-intro" }, intro) : null, rows);
}

function appearance() {
  return section("appearance", "Appearance", null,
    row("Site name", "Shown in the header, browser tab and link previews.", text("site_name", { maxLength: 60 })),
    row("Accent colour", "Buttons, highlights and the colour of link previews.", accentPicker()),
    row("Default sort", "How clips are ordered when you open the library.",
      select("default_sort", [["newest", "Newest first"], ["oldest", "Oldest first"], ["views", "Most viewed"], ["longest", "Longest"], ["title", "Title A–Z"]])),
    row("Group clips by month", "Adds month headings when sorting by date.", toggle("group_by_month")),
    row("Preview on hover", "Plays a muted preview when the mouse rests on a clip.", toggle("hover_preview")),
    installRow());
}

function installRow() {
  const control = h("div", { class: "install" });
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  function draw() {
    if (standalone) return fill(control, h("span", { class: "ok-text" }, "Installed"));
    if (installPrompt) {
      return fill(control, h("button", { class: "btn primary", onclick: async () => {
        installPrompt.prompt();
        const choice = await installPrompt.userChoice.catch(() => null);
        installPrompt = null;
        if (choice && choice.outcome === "accepted") toast("Installed");
        draw();
      } }, "Install"));
    }
    const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    fill(control, h("span", { class: "hint" }, ios ? "In Safari, tap Share, then “Add to Home Screen”."
      : location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname) ? "Use your browser's menu: “Install app” or “Add to Home screen”."
      : "Browsers only offer installing over HTTPS. Open the site through its https:// address, then come back here."));
  }
  window.addEventListener("installable", draw);
  draw();
  return row("Install as an app", "Puts the library on your home screen or desktop with its own icon and window.", control);
}

function library(clipsDir) {
  return section("library", "Library", `Clips are read from ${clipsDir} inside the container. The folder itself is set by the volume in your compose file.`,
    row("Check for new clips every", "Lower is quicker to notice new files; higher is gentler on network shares.", number("scan_interval", 5, 86400, "seconds")),
    row("Match games to Steam", "Looks up new games for artwork, descriptions and SteamDB links.", toggle("steam_lookup")),
    row("Mix separate audio tracks", "Keeps a browser-friendly copy of clips recorded with game and microphone on separate tracks.", toggle("merge_audio_tracks")),
    row("Trimming", "Exact cuts on the frame you pick and re-encodes the trimmed part, which takes longer. Fast keeps the original quality but the start can shift by a second or two.",
      select("trim_mode", [["exact", "Exact"], ["fast", "Fast"]])),
    row("New clips start as", "Who can see a clip right after it is imported.",
      select("default_visibility", [["private", "Private"], ["unlisted", "Unlisted"], ["public", "Public"]])));
}

function filenames() {
  const sample = h("input", { type: "text", value: "ARC-Raiders__2026-09-12__00-31-35.mp4", "aria-label": "Example file name" });
  const out = h("div", { class: "tester-out" });
  const pattern = text("filename_pattern", { placeholder: "Built-in patterns only", spellcheck: false, class: "mono" });
  let timer;
  const run = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const r = await api("/api/settings/test-filename", { method: "POST", body: { filename: sample.value, pattern: pattern.value } });
        fill(out,
          h("div", null, h("span", null, "Game"), h("strong", null, r.game || "No game")),
          h("div", null, h("span", null, "Recorded"), h("strong", null, r.recorded_at ? fmtDate(r.recorded_at, true) : "From the file's date")),
          h("div", null, h("span", null, "Title"), h("strong", null, r.title || "")));
      } catch (err) { fill(out, h("div", { class: "error" }, err.message)); }
    }, 200);
  };
  sample.addEventListener("input", run);
  pattern.addEventListener("input", run);
  run();
  const sec = section("filenames", "File names", "How a clip's game and date are read from its file name. SteelSeries Moments, ShadowPlay, Medal and OBS-style names work without any setup.",
    row("Use the folder as the game", "When a file name has no game in it, file the clip under its folder's name.", toggle("folder_as_game")),
    row("Names that aren't games", "Comma-separated. Clips with these names go under “No game”.", text("ignored_names", { maxLength: 1000 })),
    row("Custom pattern", h("span", null, "Optional regular expression tried first. Name the parts ", h("code", null, "(?P<game>…)"), ", ", h("code", null, "(?P<date>…)"), " and ", h("code", null, "(?P<time>…)"), "."), pattern),
    h("div", { class: "tester" }, h("strong", null, "Try a file name"), sample, out,
      h("span", { class: "hint" }, "Changes apply to clips imported from now on. Clips already in the library keep their game.")));
  sec.addEventListener("change", run);
  return sec;
}

function artworkSources(keySet) {
  const box = h("div", { class: "set-control wide" });
  function draw() {
    if (keySet) {
      return fill(box, h("span", { class: "ok-text" }, "Key saved"),
        h("button", { class: "btn", onclick: async () => {
          try { keySet = (await api("/api/settings/steamgriddb-key", { method: "PUT", body: { key: "" } })).steamgriddb_key_set; toast("Key removed"); draw(); }
          catch (err) { toast(err.message); }
        } }, "Remove"));
    }
    const input = h("input", { type: "password", placeholder: "Paste your API key", autocomplete: "off", "aria-label": "SteamGridDB API key" });
    const saveKey = async () => {
      if (!input.value.trim()) return input.focus();
      try {
        keySet = (await api("/api/settings/steamgriddb-key", { method: "PUT", body: { key: input.value } })).steamgriddb_key_set;
        toast("Key saved. Looking for artwork for unmatched games…");
        draw();
      } catch (err) { toast(err.message); input.classList.add("invalid"); }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") saveKey(); });
    fill(box, input, h("button", { class: "btn", onclick: saveKey }, "Save"));
  }
  draw();
  return section("artwork", "Artwork sources", "Steam is used automatically for games it knows. SteamGridDB adds community artwork for almost every game, including ones that aren't on Steam.",
    h("div", { class: "set-row" },
      h("div", { class: "set-label" }, h("strong", null, "SteamGridDB API key"),
        h("span", null, "Free. Sign in at steamgriddb.com, open ",
          h("a", { href: "https://www.steamgriddb.com/profile/preferences/api", target: "_blank", rel: "noopener" }, "Preferences › API"),
          " and copy the key. With a key saved, games without a Steam match get artwork on their own, and the artwork picker gains a SteamGridDB tab.")),
      box));
}

function sharing() {
  return section("sharing", "Sharing", null,
    row("Public address", "Used in copied links and Discord previews, e.g. https://clips.example.com. Leave empty to use the address in your browser.", text("base_url", { placeholder: "https://clips.example.com", spellcheck: false })),
    row("Public library", "Off: the library needs your sign-in, and visitors can only open clips you've shared a link to. On: visitors can also browse every clip marked Public.", toggle("public_library")),
    row("Let visitors download", "Shows a Download button on share pages.", toggle("allow_download")),
    row("Show view counts to visitors", "You always see them.", toggle("show_views")));
}

function account(username) {
  const name = h("input", { type: "text", value: username, autocomplete: "username", autocapitalize: "none", spellcheck: false, required: true, maxLength: 40 });
  const current = h("input", { type: "password", autocomplete: "current-password", required: true });
  const next = h("input", { type: "password", autocomplete: "new-password", minLength: 6, placeholder: "Leave empty to keep it" });
  const error = h("div", { class: "error" });
  return section("account", "Account", "Your sign-in for this library. Changing the password signs out every other browser. If you get locked out, change ADMIN_PASSWORD in your compose file and restart: that resets both to the values in the compose file.",
    h("form", { class: "pw-form account", onsubmit: async (e) => {
      e.preventDefault();
      error.textContent = "";
      try {
        const r = await api("/api/account", { method: "POST", body: { username: name.value, current: current.value, new: next.value } });
        name.value = r.username;
        current.value = next.value = "";
        toast("Account updated");
      } catch (err) { error.textContent = err.message; }
    } },
      h("label", { class: "field" }, h("span", null, "Username"), name),
      h("label", { class: "field" }, h("span", null, "New password"), next),
      h("label", { class: "field" }, h("span", null, "Current password (to confirm)"), current),
      h("button", { class: "btn primary" }, "Save account")), error);
}

function fmtBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

function maintenance() {
  const stats = h("div", { class: "stats" });
  const problems = h("div");
  async function load() {
    try {
      const s = await api("/api/stats");
      const hours = s.seconds / 3600;
      const stat = (value, label) => h("div", { class: "stat" }, h("strong", null, value), h("span", null, label));
      fill(stats,
        stat(s.clips, s.clips === 1 ? "clip" : "clips"), stat(s.games, s.games === 1 ? "game" : "games"),
        stat(hours >= 1 ? `${hours.toFixed(1)} h` : `${Math.round(s.seconds / 60)} min`, "of footage"),
        stat(fmtBytes(s.bytes), "of clips"), stat(fmtBytes(s.data_bytes), "thumbnails and data"), stat(s.views, "views"),
        stat(`${s.public} / ${s.unlisted} / ${s.private}`, "public / unlisted / private"),
        stat(s.scanner.last_scan ? fmtDate(s.scanner.last_scan, true) : "Not yet", "last scan"));
      fill(problems,
        !s.scanner.clips_dir_ok ? h("div", { class: "notice" }, `The clips folder (${s.clips_dir}) isn't available. Check the volume mount.`) : null,
        s.unmatched_games ? h("div", { class: "hint" }, `${s.unmatched_games} ${s.unmatched_games === 1 ? "game has" : "games have"} no Steam match. Open the game and choose Edit game to fix it.`) : null,
        s.removed ? h("div", { class: "hint removed-row" }, `${s.removed} ${s.removed === 1 ? "clip was" : "clips were"} removed from the library (the files are still on disk). `,
          h("button", { class: "link", onclick: async () => {
            try { await api("/api/maintenance/restore-removed", { method: "POST" }); toast("Restoring removed clips…"); setTimeout(load, 2500); }
            catch (err) { toast(err.message); }
          } }, "Bring them back")) : null,
        s.unreadable.length ? h("details", { class: "unreadable" }, h("summary", null, `${s.unreadable.length} ${s.unreadable.length === 1 ? "file" : "files"} couldn't be read as video`),
          h("ul", null, s.unreadable.map((p) => h("li", null, p)))) : null);
    } catch (err) { fill(stats, h("div", { class: "error" }, err.message)); }
  }
  load();
  const task = (name, label, help, done) => row(label, help,
    h("button", { class: "btn", onclick: async (e) => {
      e.currentTarget.disabled = true;
      try { await api(`/api/maintenance/${name}`, { method: "POST" }); toast(done); setTimeout(load, 4000); }
      catch (err) { toast(err.message); }
      e.target.disabled = false;
    } }, "Run"));
  return section("maintenance", "Library status", null, stats, problems,
    task("rescan", "Scan for new clips", "Checks the clips folder right now.", "Scanning…"),
    task("refresh-metadata", "Refresh game details", "Re-downloads descriptions and artwork from Steam and retries unmatched games. Artwork you picked by hand is kept.", "Refreshing in the background…"),
    task("regenerate-thumbnails", "Regenerate thumbnails", "Rebuilds clip thumbnails. Frames you picked by hand are kept.", "Regenerating in the background…"));
}

(async () => {
  let data;
  try { data = await api("/api/settings"); }
  catch (err) {
    if (err.status === 401) return loginDialog();
    return fill(main, h("div", { class: "error" }, err.message));
  }
  values = data.values; defaults = data.defaults;
  const me = await api("/api/me");
  const sections = [appearance(), library(data.clips_dir), filenames(), artworkSources(data.steamgriddb_key_set), sharing(), account(me.username), maintenance()];
  fill(main, sections);
  fill(nav, sections.map((s) => h("a", { href: `#${s.id}` }, s.querySelector("h2").textContent)));
})();
