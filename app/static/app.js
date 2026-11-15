// Library page: game sidebar, filters and the clip grid.
"use strict";

const PAGE = 60;
const params = new URLSearchParams(location.search);
const state = {
  me: { admin: false },
  games: { games: [], uncategorized: 0, total: 0 },
  game: params.get("game") || "",
  q: params.get("q") || "",
  sort: params.get("sort") || "newest",
  visibility: "",
  favorite: false,
  clips: [],
  total: 0,
};
const $ = (id) => document.getElementById(id);
let loadToken = 0;

function syncUrl() {
  const p = new URLSearchParams();
  if (state.game) p.set("game", state.game);
  if (state.q) p.set("q", state.q);
  if (state.sort !== "newest") p.set("sort", state.sort);
  history.replaceState(null, "", p.size ? `?${p}` : location.pathname);
}

function setGame(id) {
  state.game = String(id || "");
  document.body.classList.remove("nav-open");
  renderSidebar();
  loadClips();
  window.scrollTo({ top: 0 });
}

// ---------------------------------------------------------------- top bar ----

function renderTopbar() {
  const bar = $("topbar-actions");
  bar.replaceChildren();
  if (state.me.admin) {
    bar.append(
      h("button", { class: "btn", title: "Check the clips folder for new files now", onclick: async (e) => {
        e.currentTarget.disabled = true;
        await api("/api/rescan", { method: "POST" }).catch((err) => toast(err.message));
        toast("Scanning the clips folder…");
        setTimeout(refreshAll, 2500);
        setTimeout(() => { refreshAll(); renderTopbar(); }, 9000);
      } }, icon("refresh"), h("span", { class: "label-wide" }, "Rescan")),
      h("button", { class: "btn ghost", onclick: async () => { await api("/api/logout", { method: "POST" }); location.reload(); } }, "Sign out"),
    );
  } else {
    bar.append(h("button", { class: "btn", onclick: () => loginDialog() }, "Sign in"));
  }
}

// ---------------------------------------------------------------- sidebar ----

function gameArt(g) {
  if (g && g.has_cover) return h("img", { class: "game-art", src: `/covers/${g.id}.jpg`, alt: "", loading: "lazy" });
  return h("span", { class: "game-art" }, g ? g.name.slice(0, 2).toUpperCase() : "");
}

function renderSidebar() {
  const { games, uncategorized, total } = state.games;
  const link = (id, label, n, art) =>
    h("button", { class: `game-link${state.game === String(id) ? " active" : ""}`, onclick: () => setGame(id) },
      art, h("span", { class: "name" }, label), h("span", { class: "n" }, n));
  fill($("sidebar"),
    link("", "All clips", total),
    games.length ? h("div", { class: "side-label" }, "Games") : null,
    ...games.map((g) => link(g.id, g.name, g.clips, gameArt(g))),
    uncategorized && games.length ? link("none", "No game", uncategorized, gameArt(null)) : null,
  );
}

// ------------------------------------------------------------------- grid ----

function currentGame() {
  return state.games.games.find((g) => String(g.id) === state.game);
}

function renderToolbar() {
  const g = currentGame();
  const heading = $("heading");
  heading.replaceChildren(state.q ? `Results for “${state.q}”` : g ? g.name : state.game === "none" ? "No game" : "All clips");
  $("count").textContent = state.total ? `${state.total} ${state.total === 1 ? "clip" : "clips"}` : "";
  $("sort").value = state.sort;

  const filters = $("filters");
  filters.replaceChildren();
  if (g && g.steam_appid) {
    filters.append(h("a", { class: "chip", href: `https://steamdb.info/app/${g.steam_appid}/`, target: "_blank", rel: "noopener", title: g.steam_name || "" }, "SteamDB ↗"));
  }
  if (state.me.admin) {
    const chip = (label, active, onclick) => h("button", { class: `chip${active ? " active" : ""}`, onclick }, label);
    filters.append(
      chip("★ Favorites", state.favorite, () => { state.favorite = !state.favorite; loadClips(); }),
      ...["private", "unlisted", "public"].map((v) =>
        chip(v[0].toUpperCase() + v.slice(1), state.visibility === v, () => { state.visibility = state.visibility === v ? "" : v; loadClips(); })),
    );
  }
}

function clipCard(clip) {
  const href = `/w/${clip.id}`;
  const thumb = h("a", { class: "thumb", href, "aria-label": clip.title },
    h("img", { src: `/t/${clip.id}.jpg`, alt: "", loading: "lazy", onerror: (e) => e.target.remove() }),
    h("span", { class: "badge dur" }, fmtDuration(clip.duration)),
    state.me.admin ? h("span", { class: `badge vis ${clip.visibility}` }, clip.visibility[0].toUpperCase() + clip.visibility.slice(1)) : null,
  );

  // Muted preview while hovering (desktop only).
  let timer, preview;
  if (matchMedia("(hover: hover)").matches && clip.web_playable) {
    thumb.addEventListener("mouseenter", () => {
      timer = setTimeout(() => {
        preview = h("video", { src: `/v/${clip.id}.mp4`, muted: true, loop: true, playsInline: true, preload: "auto" });
        thumb.append(preview);
        preview.play().catch(() => {});
      }, 350);
    });
    thumb.addEventListener("mouseleave", () => {
      clearTimeout(timer);
      if (preview) { preview.pause(); preview.removeAttribute("src"); preview.load(); preview.remove(); preview = null; }
    });
  }

  const card = h("article", { class: "card" });
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
    );
  }
  const wrap = h("div", { style: "position:relative" }, thumb, actions);
  const meta = h("div", { class: "meta" });
  if (clip.game && !state.game) meta.append(h("button", { onclick: () => setGame(clip.game.id) }, clip.game.name), " · ");
  meta.append(fmtDate(clip.recorded_at));
  if (clip.views) meta.append(` · ${fmtViews(clip.views)}`);
  card.append(wrap, h("div", { class: "card-body" }, h("a", { class: "card-title", href }, clip.title), meta));
  return card;
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
  const p = new URLSearchParams({ sort: state.sort, limit: PAGE, offset: append ? state.clips.length : 0 });
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
  if (!append) grid.replaceChildren();
  grid.append(...data.clips.map(clipCard));
  if (!state.clips.length) grid.replaceChildren();
  $("more").replaceChildren(
    !state.clips.length ? renderEmpty()
      : state.clips.length < state.total ? h("button", { class: "btn", onclick: () => loadClips(true) }, "Show more") : "");
  renderToolbar();
}

async function refreshAll() {
  try {
    [state.me, state.games] = await Promise.all([api("/api/me"), api("/api/games")]);
  } catch { return; }
  if (state.game && state.game !== "none" && !currentGame()) state.game = "";
  renderSidebar();
  renderNotice();
  await loadClips();
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
  searchTimer = setTimeout(() => { state.q = e.target.value.trim(); loadClips(); }, 220);
});
$("sort").addEventListener("change", (e) => { state.sort = e.target.value; loadClips(); });

(async () => {
  await refreshAll();
  renderTopbar();
  if (params.has("login") && !state.me.admin) loginDialog();
  // Pick up newly imported clips without a manual reload.
  setInterval(async () => {
    if (document.hidden || document.querySelector("dialog[open]")) return;
    try {
      const [me, games] = await Promise.all([api("/api/me"), api("/api/games")]);
      const changed = JSON.stringify(games) !== JSON.stringify(state.games);
      state.me = me; state.games = games;
      renderNotice();
      if (changed) { renderSidebar(); if (state.clips.length <= PAGE && window.scrollY < 200) loadClips(); }
    } catch { /* offline; try again next tick */ }
  }, 15000);
})();
