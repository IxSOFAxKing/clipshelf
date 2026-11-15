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
      h("button", { class: "btn", disabled: clip.processing, onclick: openTrimmer }, icon("trim"), clip.trim_start != null ? "Edit trim" : "Trim"),
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
    if (clip.processing) note.append(clip.highlight ? " Saving this highlight… the video appears here when it's ready." : " Trimming… this can take a minute for longer clips.");
    else if (clip.highlight) note.append(` Highlight cut from ${clip.filename}.`);
    else if (clip.trim_start != null) note.append(` Trimmed to ${fmtPrecise(clip.trim_end - clip.trim_start)} of ${fmtPrecise(clip.source_duration)}; the original file is untouched.`);
    if (clip.thumb_custom) note.append(" Custom thumbnail. ", h("button", { class: "link", onclick: () => setThumb(null) }, "Reset"));
    if (!clip.web_playable) note.append(` This clip uses the ${(clip.vcodec || "unknown").toUpperCase()} codec, which many browsers can't play. Recording in H.264 avoids that.`);
  }
  fill(details, h("div", { class: "watch-head" }, h("div", { class: "info" }, h("h1", null, clip.title), meta), actions), note);
}

// ------------------------------------------------------------------ trim ----

ICONS.trim = '<circle cx="6" cy="7" r="2.5"/><circle cx="6" cy="17" r="2.5"/><path d="M8.2 8.3 20 16M8.2 15.7 20 8"/>';
const trimmer = document.getElementById("trimmer");
const fmtPrecise = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
let closeTrimmer = null;

function openTrimmer() {
  if (closeTrimmer) return;
  const full = clip.source_duration;
  const MIN = 0.5;
  let start = clip.trim_start ?? 0, end = clip.trim_end ?? full, looping = false;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const pct = (t) => `${(t / full) * 100}%`;

  video.pause();
  video.src = `/v/${clip.id}.mp4?original=true`;      // edit against the whole original
  video.addEventListener("loadedmetadata", () => { video.currentTime = start; }, { once: true });

  const sel = h("div", { class: "trim-sel" });
  const head = h("div", { class: "trim-head" });
  const handle = (which) => {
    const el = h("button", { type: "button", class: `trim-handle ${which}`, role: "slider", "aria-label": which === "start" ? "Trim start" : "Trim end",
      "aria-valuemin": 0, "aria-valuemax": full.toFixed(1) });
    const set = (t) => {
      if (which === "start") start = clamp(t, 0, end - MIN); else end = clamp(t, start + MIN, full);
      video.currentTime = which === "start" ? start : end;
      draw();
    };
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); looping = false; video.pause(); });
    el.addEventListener("pointermove", (e) => {
      if (!el.hasPointerCapture(e.pointerId)) return;
      const box = track.getBoundingClientRect();
      set(((e.clientX - box.left) / box.width) * full);
    });
    el.addEventListener("keydown", (e) => {
      const step = (e.shiftKey ? 1 : 0.1) * ({ ArrowLeft: -1, ArrowRight: 1 }[e.key] || 0);
      if (step) { e.preventDefault(); set((which === "start" ? start : end) + step); }
    });
    return el;
  };
  const hStart = handle("start"), hEnd = handle("end");
  const track = h("div", { class: "trim-track" }, sel, head, hStart, hEnd);
  track.addEventListener("click", (e) => {
    if (e.target.closest(".trim-handle")) return;
    const box = track.getBoundingClientRect();
    video.currentTime = clamp(((e.clientX - box.left) / box.width) * full, 0, full);
  });

  const readout = h("div", { class: "trim-readout" });
  const playBtn = h("button", { type: "button", class: "btn", onclick: () => {
    looping = !looping;
    if (looping) { video.currentTime = start; video.play().catch(() => {}); } else video.pause();
    draw();
  } });
  const error = h("div", { class: "error" });

  function draw() {
    sel.style.left = pct(start); sel.style.width = pct(end - start);
    hStart.style.left = pct(start); hEnd.style.left = pct(end);
    hStart.setAttribute("aria-valuenow", start.toFixed(1)); hEnd.setAttribute("aria-valuenow", end.toFixed(1));
    fill(readout,
      h("span", null, "Start ", h("strong", null, fmtPrecise(start))),
      h("span", null, "End ", h("strong", null, fmtPrecise(end))),
      h("span", null, "New length ", h("strong", null, fmtPrecise(end - start))),
      h("span", { class: "muted" }, `of ${fmtPrecise(full)}`));
    playBtn.textContent = looping ? "Stop preview" : "Preview selection";
  }
  const onTime = () => {
    head.style.left = pct(clamp(video.currentTime, 0, full));
    if (looping && video.currentTime >= end) video.currentTime = start;
  };
  video.addEventListener("timeupdate", onTime);

  closeTrimmer = (restore = true) => {
    video.removeEventListener("timeupdate", onTime);
    trimmer.hidden = true;
    trimmer.replaceChildren();
    closeTrimmer = null;
    if (restore) { video.pause(); video.src = clip.video; }
  };
  const save = async (body) => {
    error.textContent = "";
    try {
      const wanted = body.start;
      clip = await api(`/api/clips/${clip.id}/trim`, { method: "POST", body });
      closeTrimmer();
      render();
      if (clip.processing) waitForTrim(wanted);
    } catch (err) { error.textContent = err.message; }
  };

  // Save the selection as its own clip; this one stays as it is.
  function saveAsNew() {
    if (start <= 0.05 && end >= full - 0.05) { error.textContent = "Select part of the clip first."; return; }
    openDialog((dlg) => {
      const title = h("input", { type: "text", value: `${clip.title} (highlight)`, maxLength: 200, required: true });
      const err = h("div", { class: "error" });
      return h("form", { onsubmit: async (e) => {
        e.preventDefault();
        try {
          const made = await api(`/api/clips/${clip.id}/trim`, { method: "POST", body: { start, end, as_new: true, title: title.value } });
          location.href = `/w/${made.id}`;
        } catch (ex) { err.textContent = ex.message; }
      } },
        h("h2", null, "Save as new clip"),
        h("p", { class: "hint" }, `Saves the selected ${fmtPrecise(end - start)} as a separate clip with its own link. This clip stays as it is.`),
        h("label", { class: "field" }, h("span", null, "Title"), title), err,
        h("div", { class: "dialog-actions" },
          h("button", { type: "button", class: "btn ghost", onclick: () => dlg.close() }, "Cancel"),
          h("button", { class: "btn primary" }, "Save clip")));
    });
  }

  fill(trimmer,
    h("div", { class: "trim-top" }, h("strong", null, "Trim clip"),
      h("span", { class: "hint" }, "Drag the handles, or play to the spot and use the buttons. The original file is never changed.")),
    track, readout,
    h("div", { class: "trim-actions" },
      h("button", { type: "button", class: "btn", onclick: () => { start = clamp(video.currentTime, 0, end - MIN); draw(); } }, "Start here"),
      h("button", { type: "button", class: "btn", onclick: () => { end = clamp(video.currentTime, start + MIN, full); draw(); } }, "End here"),
      playBtn,
      h("div", { class: "spacer" }),
      clip.trim_start != null && !clip.highlight ? h("button", { type: "button", class: "btn ghost", onclick: () => save({ start: null }) }, "Remove trim") : null,
      h("button", { type: "button", class: "btn ghost", onclick: () => closeTrimmer() }, "Cancel"),
      h("button", { type: "button", class: "btn", title: "Keep this clip as it is and save the selection as a separate clip", onclick: saveAsNew }, "Save as new clip"),
      h("button", { type: "button", class: "btn primary", onclick: () => save({ start, end }) }, "Save trim")),
    error);
  trimmer.hidden = false;
  draw();
  trimmer.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// Poll until the background trim finishes, then swap in the new video.
async function waitForTrim(wanted) {
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    let now;
    try { now = await api(`/api/clips/${clip.id}`); }
    catch (err) {
      if (err.status !== 404) continue;
      toast("Saving this clip failed; the container log has details.");   // a failed highlight is dropped
      return setTimeout(() => { location.href = "/"; }, 2500);
    }
    if (now.processing) continue;
    clip = now;
    const applied = wanted == null ? clip.trim_start == null : clip.trim_start != null && Math.abs(clip.trim_start - wanted) < 0.01;
    toast(applied ? (wanted == null ? "Trim removed" : clip.highlight && !clip.views && document.referrer.includes("/w/") ? "New clip saved" : "Clip trimmed") : "Trimming failed. The clip is unchanged; the container log has details.");
    if (!closeTrimmer) { video.src = clip.video; video.poster = clip.thumb; }
    return render();
  }
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
  if (me.admin && clip.processing) waitForTrim(clip.trim_start);
});
