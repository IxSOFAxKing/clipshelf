// Library page: sidebar, game pages, the clip grid and bulk editing.
"use strict";

const PAGE = 60;
const SORT_LABELS = { newest: "Newest", oldest: "Oldest", views: "Most viewed", longest: "Longest", title: "Title A–Z" };
const params = new URLSearchParams(location.search);
const state = {
  me: { admin: false },
  games: { games: [], uncategorized: 0, total: 0 },
  view: params.get("view") === "games" ? "games" : "clips",
  game: params.get("game") || "",
  q: params.get("q") || "",
  sort: params.get("sort") || "",       // "" = the default from Settings
  visibility: "",
  favorite: false,
  clips: [],
  total: 0,
  selecting: false,
  selected: new Set(),
};
const $ = (id) => document.getElementById(id);
const sortNow = () => state.sort || state.me.default_sort || "newest";
let loadToken = 0;

function syncUrl() {
  const p = new URLSearchParams();
  if (state.view === "games") p.set("view", "games");
  if (state.game) p.set("game", state.game);
  if (state.q) p.set("q", state.q);
  if (state.sort) p.set("sort", state.sort);
  history.replaceState(null, "", p.size ? `?${p}` : location.pathname);
}

function go(view, game = "") {
  state.view = view;
  state.game = String(game || "");
  if (view === "games") { state.q = ""; $("search").value = ""; }
  document.body.classList.remove("nav-open");
  setSelecting(false);
  renderSidebar();
  show();
  window.scrollTo({ top: 0 });
}

// ---------------------------------------------------------------- top bar ----

function renderTopbar() {
  if (state.me.admin) {
    fill($("topbar-actions"),
      h("button", { class: "icon-btn", title: "Check the clips folder for new files now", "aria-label": "Scan for new clips", onclick: async () => {
        await api("/api/rescan", { method: "POST" }).catch((err) => toast(err.message));
        toast("Scanning the clips folder…");
        setTimeout(refreshAll, 2500);
        setTimeout(refreshAll, 9000);
      } }, icon("refresh")),
      h("a", { class: "icon-btn", href: "/settings", title: "Settings", "aria-label": "Settings" }, icon("settings")),
      h("button", { class: "btn ghost", onclick: async () => { await api("/api/logout", { method: "POST" }); location.href = "/"; } }, "Sign out"));
  } else {
    fill($("topbar-actions"), h("button", { class: "btn", onclick: () => loginDialog() }, "Sign in"));
  }
}

// ---------------------------------------------------------------- sidebar ----

function gameArt(g) {
  if (g && g.cover) return h("img", { class: "game-art", src: g.cover, alt: "", loading: "lazy" });
  return h("span", { class: "game-art" }, g ? g.name.slice(0, 2).toUpperCase() : "");
}

function renderSidebar() {
  const { games, uncategorized, total } = state.games;
  const link = (active, label, n, art, onclick) =>
    h("button", { class: `game-link${active ? " active" : ""}`, onclick }, art, h("span", { class: "name" }, label),
      n == null ? null : h("span", { class: "n" }, n));
  const clipsView = state.view === "clips";
  fill($("sidebar"),
    link(clipsView && !state.game, "All clips", total, h("span", { class: "nav-icon" }, icon("film")), () => go("clips")),
    games.length ? link(!clipsView, "Games", games.length, h("span", { class: "nav-icon" }, icon("grid")), () => go("games")) : null,
    games.length ? h("div", { class: "side-label" }, "Games") : null,
    ...games.map((g) => link(clipsView && state.game === String(g.id), g.name, g.clips, gameArt(g), () => go("clips", g.id))),
    uncategorized && games.length ? link(clipsView && state.game === "none", "No game", uncategorized, gameArt(null), () => go("clips", "none")) : null,
  );
}

// ------------------------------------------------------------ game banner ----

const currentGame = () => state.games.games.find((g) => String(g.id) === state.game);

function renderHero() {
  const g = state.view === "clips" && !state.q ? currentGame() : null;
  const hero = $("hero");
  if (!g) return hero.replaceChildren();
  const facts = [g.release_date, g.developer, g.genres].filter(Boolean);
  const banner = h("section", { class: `game-hero${g.hero ? " has-art" : ""}` },
    g.hero ? h("img", { class: "game-hero-bg", src: g.hero, alt: "" }) : null,
    h("div", { class: "game-hero-body" },
      g.cover ? h("img", { class: "game-hero-cover", src: g.cover, alt: "" }) : null,
      h("div", { class: "game-hero-text" },
        h("h1", null, g.name),
        facts.length ? h("div", { class: "facts" }, facts.join("  ·  ")) : null,
        g.description ? h("p", null, g.description) : null,
        h("div", { class: "game-hero-actions" },
          state.me.admin ? h("button", { class: "btn", onclick: () => gameDialog(g, onGameChanged) }, icon("edit"), "Edit game") : null,
          state.me.admin && !g.steam_appid ? h("span", { class: "hint" }, "No Steam match yet. Edit the game to add artwork and details.") : null,
          g.steam_appid ? h("a", { class: "btn ghost", href: `https://steamdb.info/app/${g.steam_appid}/`, target: "_blank", rel: "noopener" }, "SteamDB ↗") : null,
          g.steam_appid ? h("a", { class: "btn ghost", href: `https://store.steampowered.com/app/${g.steam_appid}/`, target: "_blank", rel: "noopener" }, "Steam ↗") : null))));
  fill(hero, banner);
}

async function onGameChanged(g) {
  if (String(g.id) !== state.game) state.game = String(g.id);   // renamed into another game
  await refreshAll();
}

// ---------------------------------------------------------------- toolbar ----

function renderToolbar() {
  const g = currentGame();
  const games = state.view === "games";
  $("heading").textContent = games ? "Games" : state.q ? `Results for “${state.q}”` : g ? "Clips" : state.game === "none" ? "No game" : "All clips";
  const n = games ? state.games.games.length : state.total;
  $("count").textContent = n ? `${n} ${games ? (n === 1 ? "game" : "games") : (n === 1 ? "clip" : "clips")}` : "";
  const sort = $("sort");
  sort.hidden = games;
  if (!sort.options.length) sort.append(...Object.entries(SORT_LABELS).map(([value, label]) => h("option", { value }, label)));
  sort.value = sortNow();

  const filters = $("filters");
  filters.replaceChildren();
  if (state.me.admin && !games) {
    const chip = (label, active, onclick) => h("button", { class: `chip${active ? " active" : ""}`, onclick }, label);
    filters.append(
      chip("★ Favorites", state.favorite, () => { state.favorite = !state.favorite; loadClips(); }),
      ...["private", "unlisted", "public"].filter((v) => v !== "public" || state.me.public_library).map((v) =>
        chip(v[0].toUpperCase() + v.slice(1), state.visibility === v, () => { state.visibility = state.visibility === v ? "" : v; loadClips(); })),
      h("button", { class: `chip select-chip${state.selecting ? " active" : ""}`, onclick: () => setSelecting(!state.selecting) }, state.selecting ? "Done selecting" : "Select"));
  }
}

// ------------------------------------------------------------ bulk select ----

function setSelecting(on) {
  state.selecting = on;
  state.selected.clear();
  document.body.classList.toggle("selecting", on);
  document.querySelectorAll(".card.selected").forEach((c) => c.classList.remove("selected"));
  renderBulkbar();
  if ($("heading").textContent) renderToolbar();
}

function renderBulkbar() {
  const bar = $("bulkbar");
  bar.hidden = !state.selecting;
  if (!state.selecting) return;
  const n = state.selected.size;
  const apply = async (body, done) => {
    if (!n) return toast("Pick some clips first");
    try {
      await api("/api/clips/bulk", { method: "POST", body: { ids: [...state.selected], ...body } });
      toast(`${done} ${n} ${n === 1 ? "clip" : "clips"}`);
      setSelecting(false);
      await refreshAll();
    } catch (e) { toast(e.message); }
  };
  fill(bar,
    h("strong", null, n ? `${n} selected` : "Select clips"),
    h("button", { class: "btn small", onclick: () => {
      document.querySelectorAll(".card[data-id]").forEach((c) => { state.selected.add(c.dataset.id); c.classList.add("selected"); });
      renderBulkbar();
    } }, "Select all shown"),
    h("span", { class: "bulk-sep" }),
    h("button", { class: "btn small", onclick: () => apply({ visibility: "private" }, "Made private:") }, "Private"),
    h("button", { class: "btn small", onclick: () => apply({ visibility: "unlisted" }, "Made unlisted:") }, "Unlisted"),
    state.me.public_library ? h("button", { class: "btn small", onclick: () => apply({ visibility: "public" }, "Made public:") }, "Public") : null,
    h("span", { class: "bulk-sep" }),
    h("button", { class: "btn small", onclick: () => apply({ favorite: true }, "Favorited") }, "★ Favorite"),
    h("button", { class: "btn small", onclick: async () => {
      if (!n) return toast("Pick some clips first");
      const pick = await gamePickerDialog(`Move ${n} ${n === 1 ? "clip" : "clips"} to a game`);
      if (pick) apply(pick, "Moved");
    } }, "Set game…"),
    h("button", { class: "btn small danger", onclick: () => {
      if (!n) return toast("Pick some clips first");
      deleteDialog([...state.selected], () => { setSelecting(false); refreshAll(); });
    } }, "Delete…"),
    h("div", { class: "spacer" }),
    h("button", { class: "btn small primary", onclick: () => setSelecting(false) }, "Done"));
}

// ------------------------------------------------------------------- grid ----

function clipCard(clip) {
  const href = `/w/${clip.id}`;
  const thumb = h("a", { class: "thumb", href, "aria-label": clip.title },
    h("img", { src: clip.thumb, alt: "", loading: "lazy", onerror: (e) => e.target.remove() }),
    h("span", { class: "badge dur" }, fmtDuration(clip.duration)),
    state.me.admin ? h("span", { class: `badge vis ${clip.visibility}` }, clip.visibility[0].toUpperCase() + clip.visibility.slice(1)) : null,
    h("span", { class: "tick" }, icon("check")),
  );
  const card = h("article", { class: `card${state.selected.has(clip.id) ? " selected" : ""}`, "data-id": clip.id });
  card.addEventListener("click", (e) => {
    if (!state.selecting) return;
    e.preventDefault();
    state.selected.has(clip.id) ? state.selected.delete(clip.id) : state.selected.add(clip.id);
    card.classList.toggle("selected", state.selected.has(clip.id));
    renderBulkbar();
  }, true);

  // Muted preview while hovering (desktop only).
  let timer, preview;
  if (state.me.hover_preview && matchMedia("(hover: hover)").matches && clip.web_playable) {
    thumb.addEventListener("mouseenter", () => {
      if (state.selecting) return;
      timer = setTimeout(() => {
        preview = h("video", { src: clip.video, muted: true, loop: true, playsInline: true, preload: "auto" });
        thumb.append(preview);
        preview.play().catch(() => {});
      }, 350);
    });
    thumb.addEventListener("mouseleave", () => {
      clearTimeout(timer);
      if (preview) { preview.pause(); preview.removeAttribute("src"); preview.load(); preview.remove(); preview = null; }
    });
  }

  const replace = (updated, gameChanged) => {
    Object.assign(clip, updated);
    card.replaceWith(clipCard(clip));
    if (gameChanged) refreshAll();
  };
  let actions = null;
  if (state.me.admin) {
    const fav = h("button", { class: clip.favorite ? "on" : "", title: clip.favorite ? "Remove from favorites" : "Add to favorites", "aria-label": "Favorite",
      onclick: async () => {
        try { replace(await api(`/api/clips/${clip.id}`, { method: "PATCH", body: { favorite: !clip.favorite } })); }
        catch (e) { toast(e.message); }
      } }, icon("star"));
    actions = h("div", { class: "card-actions" },
      fav,
      h("button", { title: "Copy share link", "aria-label": "Copy share link", onclick: () => shareClip(clip, replace) }, icon("link")),
      h("button", { title: "Edit", "aria-label": "Edit", onclick: () => editDialog(clip, replace) }, icon("edit")),
      h("button", { title: "Delete", "aria-label": "Delete", onclick: () => deleteDialog([clip.id], refreshAll) }, icon("trash")),
    );
  }
  const meta = h("div", { class: "meta" });
  if (clip.game && !state.game) meta.append(h("button", { onclick: () => go("clips", clip.game.id) }, clip.game.name), " · ");
  meta.append(fmtDate(clip.recorded_at));
  if (clip.views) meta.append(` · ${fmtViews(clip.views)}`);
  card.append(h("div", { class: "thumb-wrap" }, thumb, actions),
    h("div", { class: "card-body" }, h("a", { class: "card-title", href }, clip.title), meta));
  return card;
}

const monthOf = (iso) => new Date(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });

function appendClips(clips) {
  const grid = $("grid");
  const grouped = state.me.group_by_month && ["newest", "oldest"].includes(sortNow());
  for (const clip of clips) {
    const month = grouped ? monthOf(clip.recorded_at) : null;
    if (month && month !== grid.dataset.month) {
      grid.dataset.month = month;
      grid.append(h("h2", { class: "month" }, month));
    }
    grid.append(clipCard(clip));
  }
}

function gameCard(g) {
  return h("button", { class: "game-card", onclick: () => go("clips", g.id) },
    h("span", { class: "game-card-art" }, g.cover ? h("img", { src: g.cover, alt: "", loading: "lazy" }) : h("span", null, g.name)),
    h("span", { class: "game-card-name" }, g.name),
    h("span", { class: "meta" }, `${g.clips} ${g.clips === 1 ? "clip" : "clips"} · ${fmtDate(g.latest)}`));
}

function renderNotice() {
  const s = state.me.scanner;
  const box = $("notice");
  box.replaceChildren();
  if (!s) return;
  if (!s.clips_dir_ok) box.append(h("div", { class: "notice" }, "The clips folder isn't available inside the container. Check the volume mount."));
  else if (s.pending) box.append(h("div", { class: "notice" }, `Importing ${s.pending} new ${s.pending === 1 ? "clip" : "clips"}…`));
}

function renderEmpty() {
  const filtered = state.q || state.game || state.visibility || state.favorite;
  if (filtered) return h("div", { class: "empty" }, h("h2", null, "No clips match"), h("p", null, "Try a different search or filter."));
  if (state.me.admin) {
    return h("div", { class: "empty" }, h("h2", null, "No clips yet"),
      h("p", null, "Save a clip into the folder mounted at ", h("code", null, "/clips"), " and it will show up here on its own."));
  }
  return h("div", { class: "empty" }, h("h2", null, "Nothing public yet"),
    h("p", null, "Clips shared publicly will be listed here. If this is your library, sign in to see everything."));
}

async function loadClips(append = false) {
  const token = ++loadToken;
  syncUrl();
  const p = new URLSearchParams({ sort: sortNow(), limit: PAGE, offset: append ? state.clips.length : 0 });
  if (state.game) p.set("game", state.game);
  if (state.q) p.set("q", state.q);
  if (state.visibility) p.set("visibility", state.visibility);
  if (state.favorite) p.set("favorite", "true");
  let data;
  try { data = await api(`/api/clips?${p}`); } catch (e) { return toast(e.message); }
  if (token !== loadToken) return;
  state.total = data.total;
  state.clips = append ? state.clips.concat(data.clips) : data.clips;
  const grid = $("grid");
  grid.className = "grid";
  if (!append) { grid.replaceChildren(); delete grid.dataset.month; }
  appendClips(data.clips);
  fill($("more"),
    !state.clips.length ? renderEmpty()
      : state.clips.length < state.total ? h("button", { class: "btn", onclick: () => loadClips(true) }, "Show more") : null);
  renderHero();
  renderToolbar();
}

// Show whichever view is current.
function show() {
  if (state.view !== "games") return loadClips();
  ++loadToken;
  syncUrl();
  const grid = $("grid");
  grid.className = "grid games-grid";
  delete grid.dataset.month;
  const games = [...state.games.games].sort((a, b) => (b.latest || "").localeCompare(a.latest || ""));
  fill(grid, games.map(gameCard));
  fill($("more"), games.length ? null : renderEmpty());
  renderHero();
  renderToolbar();
}

async function refreshAll() {
  try {
    [state.me, state.games] = await Promise.all([api("/api/me"), api("/api/games")]);
  } catch (err) {
    if (err.status === 401) loginDialog();     // signed out (or the session ended)
    return;
  }
  window.publicLibrary = state.me.public_library;
  if (state.game && state.game !== "none" && !currentGame()) state.game = "";
  renderSidebar();
  renderNotice();
  await show();
}

// ------------------------------------------------------------------- init ----

$("menu-btn").append(icon("menu"));
$("menu-btn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
document.querySelector(".search-icon").append(icon("search"));
document.querySelector(".content").addEventListener("click", () => document.body.classList.remove("nav-open"));
$("search").value = state.q;
let searchTimer;
$("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); if (state.q) state.view = "clips"; renderSidebar(); show(); }, 220);
});
$("sort").addEventListener("change", (e) => { state.sort = e.target.value; loadClips(); });

(async () => {
  await refreshAll();
  renderTopbar();
  // Pick up newly imported clips without a manual reload.
  setInterval(async () => {
    if (document.hidden || document.querySelector("dialog[open]") || state.selecting) return;
    try {
      const [me, games] = await Promise.all([api("/api/me"), api("/api/games")]);
      const changed = JSON.stringify(games) !== JSON.stringify(state.games);
      state.me = me; state.games = games;
      renderNotice();
      if (changed) { renderSidebar(); if (state.clips.length <= PAGE && window.scrollY < 200) show(); }
    } catch { /* offline; try again next tick */ }
  }, 15000);
})();
