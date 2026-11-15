// Watch / share page.
"use strict";

let clip = JSON.parse(document.getElementById("clip-data").textContent);
const video = document.getElementById("video");
const details = document.getElementById("details");
let me = { admin: false, allow_download: true };

function render() {
  document.title = `${clip.title} · ${document.title.split(" · ").pop()}`;
  const meta = h("div", { class: "watch-meta" });
  if (clip.game) {
    meta.append(h("a", { class: `game-pill${clip.game.cover ? "" : " bare"}`, href: `/?game=${clip.game.id}`, title: "More clips from this game" },
      clip.game.cover ? h("img", { src: clip.game.cover, alt: "" }) : null, clip.game.name));
  }
  meta.append(h("span", { class: clip.game ? "dot" : "" }, fmtDate(clip.recorded_at, true)));
  if (clip.views != null) meta.append(h("span", { class: "dot" }, fmtViews(clip.views)));
  if (clip.game && clip.game.steam_appid) {
    meta.append(h("a", { class: "dot link", href: `https://steamdb.info/app/${clip.game.steam_appid}/`, target: "_blank", rel: "noopener" }, "SteamDB"));
  }

  const patch = async (body) => {
    try { clip = await api(`/api/clips/${clip.id}`, { method: "PATCH", body }); render(); }
    catch (e) { toast(e.message); }
  };
  const setThumb = async (time) => {
    try {
      clip = await api(`/api/clips/${clip.id}/thumbnail`, { method: "POST", body: { time } });
      video.poster = clip.thumb;
      render();
      toast(time == null ? "Thumbnail reset" : "Thumbnail set to this frame");
    } catch (e) { toast(e.message); }
  };

  const actions = h("div", { class: "watch-actions" });
  if (me.admin) {
    actions.append(
      h("button", { class: `btn${clip.favorite ? " on" : ""}`, onclick: () => patch({ favorite: !clip.favorite }) }, icon("star"), clip.favorite ? "Favorited" : "Favorite"),
      h("button", { class: "btn", onclick: () => editDialog(clip, (c) => { clip = c; render(); }) }, icon("edit"), "Edit"),
      h("button", { class: "btn", title: "Pause on the frame you want, then click", onclick: () => setThumb(video.currentTime) }, icon("image"), "Use frame as thumbnail"),
    );
  }
  if (me.admin || me.allow_download) {
    actions.append(h("a", { class: "btn", href: `/v/${clip.id}.mp4?download=true` }, icon("download"), "Download"));
  }
  if (me.admin) {
    actions.append(h("button", { class: "btn", title: "Delete", "aria-label": "Delete", onclick: () => deleteDialog([clip.id], () => { location.href = "/"; }) }, icon("trash")));
  }
  actions.append(h("button", { class: "btn primary", onclick: () => me.admin ? shareClip(clip, render)
    : copyText(location.href).then((ok) => toast(ok ? "Link copied" : location.href)) }, icon("link"), "Copy link"));

  let note = null;
  if (me.admin) {
    const vis = { private: "Private: only you can watch this.", unlisted: "Unlisted: anyone with the link can watch.", public: "Public: listed on the home page." };
    note = h("div", { class: "admin-note" }, vis[clip.visibility]);
    if (clip.thumb_custom) note.append(" Custom thumbnail. ", h("button", { class: "link", onclick: () => setThumb(null) }, "Reset"));
    if (!clip.web_playable) note.append(` This clip uses the ${(clip.vcodec || "unknown").toUpperCase()} codec, which many browsers can't play. Recording in H.264 avoids that.`);
  }
  fill(details, h("div", { class: "watch-head" }, h("div", { class: "info" }, h("h1", null, clip.title), meta), actions), note);
}

let counted = false;
video.addEventListener("play", () => {
  if (counted) return;
  counted = true;
  api(`/api/clips/${clip.id}/view`, { method: "POST" }).catch(() => {});
});
video.play().catch(() => {});  // autoplay where the browser allows it

render();
api("/api/me").then((data) => {
  me = data;
  const bar = document.getElementById("topbar-actions");
  bar.append(me.admin ? h("a", { class: "btn ghost", href: "/" }, "Library")
    : h("button", { class: "btn ghost", onclick: () => loginDialog() }, "Sign in"));
  render();
});
