// Watch / share page.
"use strict";

let clip = JSON.parse(document.getElementById("clip-data").textContent);
const video = document.getElementById("video");
const details = document.getElementById("details");
let admin = false;

function render() {
  document.title = `${clip.title} · ${document.title.split(" · ").pop()}`;
  const meta = h("div", { class: "watch-meta" });
  if (clip.game) {
    meta.append(h("a", { class: `game-pill${clip.game.has_cover ? "" : " bare"}`, href: `/?game=${clip.game.id}`, title: "More clips from this game" },
      clip.game.has_cover ? h("img", { src: `/covers/${clip.game.id}.jpg`, alt: "" }) : null, clip.game.name));
  }
  meta.append(h("span", { class: clip.game ? "dot" : "" }, fmtDate(clip.recorded_at, true)));
  meta.append(h("span", { class: "dot" }, fmtViews(clip.views)));
  if (clip.game && clip.game.steam_appid) {
    meta.append(h("a", { class: "dot link", href: `https://steamdb.info/app/${clip.game.steam_appid}/`, target: "_blank", rel: "noopener" }, "SteamDB"));
  }

  const actions = h("div", { class: "watch-actions" });
  if (admin) {
    actions.append(
      h("button", { class: `btn${clip.favorite ? " on" : ""}`, onclick: async () => {
        try { clip = await api(`/api/clips/${clip.id}`, { method: "PATCH", body: { favorite: !clip.favorite } }); render(); }
        catch (e) { toast(e.message); }
      } }, icon("star"), clip.favorite ? "Favorited" : "Favorite"),
      h("button", { class: "btn", onclick: () => editDialog(clip, (c) => { clip = c; render(); }) }, icon("edit"), "Edit"),
    );
  }
  actions.append(
    h("a", { class: "btn", href: `/v/${clip.id}.mp4?download=true` }, icon("download"), "Download"),
    h("button", { class: "btn primary", onclick: () => admin ? shareClip(clip, render)
      : copyText(location.href).then((ok) => toast(ok ? "Link copied" : location.href)) }, icon("link"), "Copy link"),
  );

  const notes = [];
  if (admin) {
    const vis = { private: "Private: only you can watch this.", unlisted: "Unlisted: anyone with the link can watch.", public: "Public: listed on the home page." };
    notes.push(vis[clip.visibility]);
    if (!clip.web_playable) notes.push(`This clip uses the ${(clip.vcodec || "unknown").toUpperCase()} codec, which many browsers can't play. Recording in H.264 avoids that.`);
  }
  fill(details,
    h("div", { class: "watch-head" }, h("div", { class: "info" }, h("h1", null, clip.title), meta), actions),
    notes.length ? h("div", { class: "admin-note" }, notes.join(" ")) : null,
  );
}

let counted = false;
video.addEventListener("play", () => {
  if (counted) return;
  counted = true;
  api(`/api/clips/${clip.id}/view`, { method: "POST" }).catch(() => {});
});
video.play().catch(() => {});  // autoplay where the browser allows it

render();
api("/api/me").then((me) => {
  admin = me.admin;
  const bar = document.getElementById("topbar-actions");
  bar.append(admin ? h("a", { class: "btn ghost", href: "/" }, "Library")
    : h("button", { class: "btn ghost", onclick: () => loginDialog() }, "Sign in"));
  if (admin) render();
});
