// subtool 웹 화면. 서버 API만 호출하며 처리 작업은 모두 서버 백그라운드에서 돈다.
"use strict";

const $ = (id) => document.getElementById(id);
const LANG = "en";
const MAX_CHARS = 42;
const STATUS_LABEL = {
  new: "새 영상", queued: "대기", running: "생성 중", generated: "생성됨",
  synced: "싱크 완료", exported: "텍스트 추출됨", missing: "파일 없음",
};

const S = {
  info: null,
  videos: [],
  current: null,      // 선택한 영상 경로
  doc: null,          // 자막 문서
  dirty: false,
  undo: [],
  redo: [],
  selected: -1,       // 오른쪽에서 선택한 자막
  nowIdx: -1,         // 재생 위치의 자막
  offset: 0,          // 이번 세션에서 전체 이동한 양 (표시용)
  ranges: [],         // I/O 키로 지정한 구간 [[s, e]]
  pendingIn: null,
  extraGlossary: [],
  jobState: {},       // 작업 id → 상태 (완료 감지용)
  autosave: null,
};

// ---------------------------------------------------------------- 유틸

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const res = await fetch(url, opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`);
  return data;
}
const enc = encodeURIComponent;

let toastTimer = null;
function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isError ? 6000 : 2500);
}

function fmt(sec, withMs = true) {
  sec = Math.max(0, sec || 0);
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  const ss = withMs ? s.toFixed(3).padStart(6, "0") : String(Math.floor(s)).padStart(2, "0");
  return `${String(m).padStart(2, "0")}:${ss}`;
}

function parseTime(text) {
  const parts = String(text).trim().replace(",", ".").split(":");
  if (!parts.length || parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null;
  return parts.reduce((acc, p) => acc * 60 + parseFloat(p), 0);
}

function flat(text) { return String(text || "").replace(/\s+/g, " ").trim(); }

function wrap(text) {
  text = flat(text);
  if (text.length <= MAX_CHARS) return text;
  const mid = text.length / 2;
  let best = -1;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === " " && (best < 0 || Math.abs(i - mid) < Math.abs(best - mid))) best = i;
  }
  return best < 0 ? text : text.slice(0, best) + "\n" + text.slice(best + 1);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ---------------------------------------------------------------- 테마

function initTheme() {
  let theme = "dark";
  try { theme = localStorage.getItem("subtool-theme") || "dark"; } catch (e) { /* 저장소 사용 불가 */ }
  document.documentElement.dataset.theme = theme;
  $("themeBtn").onclick = () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("subtool-theme", next); } catch (e) { /* 무시 */ }
  };
}

// ---------------------------------------------------------------- 영상 목록·작업

async function refreshVideos() {
  try { S.videos = await api("GET", "/api/videos"); } catch (e) { return; }
  const ul = $("videoList");
  ul.innerHTML = "";
  for (const v of S.videos) {
    const li = document.createElement("li");
    li.className = "video-item" + (v.path === S.current ? " active" : "");
    const pct = v.status === "running" ? ` ${Math.round((v.progress || 0) * 100)}%` : "";
    li.innerHTML = `<div class="name">${escapeHtml(v.name)}</div>
      <div class="meta"><span class="badge ${v.status}">${STATUS_LABEL[v.status] || v.status}${pct}</span>
      <button class="remove" title="목록에서 빼기 (파일은 그대로)">✕</button></div>
      ${v.status === "running" ? `<div class="bar"><i style="width:${Math.round((v.progress || 0) * 100)}%"></i></div>` : ""}`;
    li.title = v.path;
    li.onclick = () => selectVideo(v.path);
    li.querySelector(".remove").onclick = async (ev) => {
      ev.stopPropagation();
      await api("DELETE", `/api/videos?path=${enc(v.path)}`);
      if (S.current === v.path) clearWorkspace();
      refreshVideos();
    };
    ul.appendChild(li);
  }
  updateStats();
}

async function refreshJobs() {
  let jobs;
  try { jobs = await api("GET", "/api/jobs"); } catch (e) { return; }
  const ul = $("jobList");
  ul.innerHTML = "";
  for (const j of jobs.slice().reverse().slice(0, 12)) {
    const li = document.createElement("li");
    li.className = "job-item";
    const name = j.video.split(/[\\/]/).pop();
    const pct = j.status === "running" ? ` ${Math.round(j.progress * 100)}%` : "";
    const label = { queued: "대기", running: "진행", done: "완료", failed: "실패" }[j.status];
    const cls = { queued: "queued", running: "running", done: "synced", failed: "failed" }[j.status];
    li.innerHTML = `<div class="top"><span class="badge ${cls}">${label}${pct}</span><span class="name">${escapeHtml(j.kind)} · ${escapeHtml(name)}</span></div>
      <div class="msg">${escapeHtml(j.message || "")}</div>`;
    li.title = j.command + (j.log.length ? "\n\n" + j.log.slice(-8).join("\n") : "");
    ul.appendChild(li);

    const prev = S.jobState[j.id];
    if (prev && prev !== j.status && (j.status === "done" || j.status === "failed")) onJobFinished(j);
    S.jobState[j.id] = j.status;
  }
}

function onJobFinished(job) {
  const name = job.video.split(/[\\/]/).pop();
  if (job.status === "failed") {
    toast(`${name}: ${job.kind} 실패 — ${job.message}`, true);
    return;
  }
  toast(`${name}: ${job.kind} 완료`);
  if (job.video === S.current) {
    if (S.dirty) toast("작업이 끝났지만 저장하지 않은 변경이 있어 다시 불러오지 않았습니다.", true);
    else loadDoc();
  }
}

async function addVideo(path) {
  if (!path) return;
  try {
    const r = await api("POST", "/api/videos", { path });
    await refreshVideos();
    selectVideo(r.path);
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- 영상 선택·문서

function clearWorkspace() {
  S.current = null;
  S.doc = null;
  setDirty(false);
  $("workspace").hidden = true;
  $("empty").hidden = false;
  $("video").removeAttribute("src");
  renderCues();
}

async function selectVideo(path) {
  if (path === S.current) return;
  if (S.dirty && !confirm("저장하지 않은 변경이 있습니다. 버리고 다른 영상으로 이동할까요?")) return;
  S.current = path;
  S.undo = []; S.redo = []; S.selected = -1; S.offset = 0; S.ranges = []; S.pendingIn = null;
  setDirty(false);
  $("empty").hidden = true;
  $("workspace").hidden = false;
  $("videoName").textContent = path.split(/[\\/]/).pop();
  $("video").src = `/api/media?path=${enc(path)}`;
  $("optRanges").value = "";
  $("optForce").checked = false;
  $("optReplace").checked = false;
  updateOffsetLabel();
  renderRanges();
  refreshVideos();
  await loadDoc();
  loadGlossaryInfo();
  updateCommand();
}

async function loadDoc() {
  if (!S.current) return;
  try {
    const r = await api("GET", `/api/doc?path=${enc(S.current)}`);
    S.doc = r.doc;
    S.autosave = r.autosave;
  } catch (e) { toast(e.message, true); return; }
  $("noDoc").hidden = !!S.doc;
  $("restoreBanner").hidden = !S.autosave;
  $("syncedChk").checked = S.doc && S.doc.status === "synced";
  S.undo = []; S.redo = [];
  setDirty(false);
  renderCues();
  updateOverlay(true);
}

function setDirty(d) {
  S.dirty = d;
  const pill = $("saveState");
  if (!S.current || !S.doc) { pill.textContent = ""; pill.className = "pill"; return; }
  pill.textContent = d ? "저장 안 됨" : "저장됨";
  pill.className = "pill " + (d ? "dirty" : "saved");
}

async function save() {
  if (!S.doc || !S.current) return false;
  S.doc.status = $("syncedChk").checked ? "synced" : "generated";
  try {
    await api("PUT", `/api/doc?path=${enc(S.current)}`, S.doc);
    setDirty(false);
    toast("저장했습니다.");
    refreshVideos();
    return true;
  } catch (e) { toast(e.message, true); return false; }
}

async function autosave() {
  if (!S.dirty || !S.doc || !S.current) return;
  try { await api("PUT", `/api/autosave?path=${enc(S.current)}`, S.doc); } catch (e) { /* 다음에 다시 */ }
}

// ---------------------------------------------------------------- 편집 (되돌리기 포함)

function cues() { return S.doc ? S.doc.cues : []; }

function edit(fn) {
  if (!S.doc) return;
  S.undo.push(JSON.stringify(S.doc.cues));
  if (S.undo.length > 200) S.undo.shift();
  S.redo = [];
  fn();
  S.doc.cues.sort((a, b) => a.start - b.start);
  for (const c of S.doc.cues) { c.start = Math.round(c.start * 1000) / 1000; c.end = Math.round(c.end * 1000) / 1000; }
  setDirty(true);
  renderCues();
  updateOverlay(true);
}

function undo() {
  if (!S.undo.length) return;
  S.redo.push(JSON.stringify(S.doc.cues));
  S.doc.cues = JSON.parse(S.undo.pop());
  setDirty(true); renderCues(); updateOverlay(true);
}

function redo() {
  if (!S.redo.length) return;
  S.undo.push(JSON.stringify(S.doc.cues));
  S.doc.cues = JSON.parse(S.redo.pop());
  setDirty(true); renderCues(); updateOverlay(true);
}

function cueAt(t) {
  const list = cues();
  for (let i = 0; i < list.length; i++) if (list[i].start <= t && t < list[i].end) return i;
  return -1;
}

function targetIdx() {
  const i = cueAt(video().currentTime);
  return i >= 0 ? i : S.selected;
}

function overlapsSet() {
  const list = cues();
  const s = new Set();
  for (let i = 0; i < list.length - 1; i++) {
    if (list[i].end > list[i + 1].start + 0.001) { s.add(i); s.add(i + 1); }
  }
  return s;
}

function setStart(i, t) {
  const c = cues()[i];
  if (!c) return;
  if (t >= c.end) return toast("시작이 끝보다 늦을 수 없습니다.", true);
  edit(() => { c.start = t; });
}

function setEnd(i, t) {
  const c = cues()[i];
  if (!c) return;
  if (t <= c.start) return toast("끝이 시작보다 빠를 수 없습니다.", true);
  edit(() => { c.end = t; });
}

function nudge(i, d) {
  const c = cues()[i];
  if (!c) return;
  edit(() => { c.start = Math.max(0, c.start + d); c.end = Math.max(c.start + 0.05, c.end + d); });
}

function shiftAll(d) {
  if (!cues().length) return;
  edit(() => { for (const c of cues()) { c.start = Math.max(0, c.start + d); c.end = Math.max(c.start + 0.05, c.end + d); } });
  S.offset += d;
  updateOffsetLabel();
}

function splitAt(i, t) {
  const c = cues()[i];
  if (!c || t <= c.start + 0.1 || t >= c.end - 0.1) return toast("자막 안쪽 위치에서 나눌 수 있습니다.", true);
  const text = flat(c.text[LANG]);
  const words = c.words || [];
  let left, right, lw = [], rw = [];
  if (words.length && flat(words.map((w) => w.w).join("")) === text) {
    lw = words.filter((w) => (w.s + w.e) / 2 < t);
    rw = words.filter((w) => (w.s + w.e) / 2 >= t);
    left = flat(lw.map((w) => w.w).join(""));
    right = flat(rw.map((w) => w.w).join(""));
  } else {
    // 텍스트를 고친 뒤라 단어 시각을 쓸 수 없으면 시간 비율로 가까운 공백에서 나눔
    const target = Math.round(text.length * (t - c.start) / (c.end - c.start));
    let cut = -1;
    for (let k = 0; k < text.length; k++) if (text[k] === " " && (cut < 0 || Math.abs(k - target) < Math.abs(cut - target))) cut = k;
    if (cut < 0) return toast("나눌 공백이 없습니다.", true);
    left = text.slice(0, cut); right = text.slice(cut + 1);
  }
  if (!left || !right) return toast("한쪽이 비어서 나눌 수 없습니다.", true);
  edit(() => {
    const a = { start: c.start, end: t, text: { ...c.text, [LANG]: wrap(left) }, words: lw };
    const b = { start: t, end: c.end, text: { ...c.text, [LANG]: wrap(right) }, words: rw };
    for (const k of Object.keys(c.text)) if (k !== LANG) { a.text[k] = c.text[k]; b.text[k] = ""; }
    cues().splice(i, 1, a, b);
  });
  S.selected = i;
}

function mergeNext(i) {
  const list = cues();
  if (i < 0 || i >= list.length - 1) return toast("합칠 다음 자막이 없습니다.", true);
  const a = list[i], b = list[i + 1];
  edit(() => {
    const text = {};
    for (const k of new Set([...Object.keys(a.text), ...Object.keys(b.text)])) {
      text[k] = wrap(flat(a.text[k]) + " " + flat(b.text[k]));
    }
    list.splice(i, 2, { start: Math.min(a.start, b.start), end: Math.max(a.end, b.end), text, words: [...(a.words || []), ...(b.words || [])] });
  });
  S.selected = i;
}

function deleteCue(i) {
  if (!cues()[i]) return;
  edit(() => cues().splice(i, 1));
  S.selected = Math.min(i, cues().length - 1);
  renderCues();
}

// ---------------------------------------------------------------- 그리기

function renderCues() {
  const list = cues();
  const ov = overlapsSet();
  const ul = $("cueList");
  ul.innerHTML = "";
  list.forEach((c, i) => {
    const li = document.createElement("li");
    li.className = "cue" + (i === S.selected ? " sel" : "") + (i === S.nowIdx ? " now" : "") + (ov.has(i) ? " overlap" : "");
    li.dataset.i = i;
    li.innerHTML = `<span class="num">${i + 1}</span><span class="time mono">${fmt(c.start)} → ${fmt(c.end)}</span><span class="txt">${escapeHtml(c.text[LANG] || "")}</span>`;
    li.onclick = () => { S.selected = i; video().currentTime = c.start + 0.001; renderCues(); };
    ul.appendChild(li);
  });
  $("cueCount").textContent = list.length ? `${list.length}개` : "";
  renderEditor();
  updateStats();
}

function renderEditor() {
  const c = cues()[S.selected];
  $("cueEditor").hidden = !c;
  if (!c) return;
  if (document.activeElement !== $("edStart")) $("edStart").value = fmt(c.start);
  if (document.activeElement !== $("edEnd")) $("edEnd").value = fmt(c.end);
  if (document.activeElement !== $("edText")) $("edText").value = c.text[LANG] || "";
}

function updateStats() {
  const v = S.videos.find((x) => x.path === S.current);
  const dur = (S.doc && S.doc.duration) || video().duration || 0;
  $("statCues").textContent = S.doc ? cues().length : "-";
  $("statDur").textContent = dur ? fmt(dur, false) : "-";
  const n = S.doc ? overlapsSet().size : 0;
  $("statOverlap").textContent = S.doc ? n : "-";
  $("statOverlap").className = "card-value" + (n ? " warn" : "");
  const st = v ? v.status : "-";
  $("statStatus").textContent = STATUS_LABEL[st] || st;
  $("statStatus").className = "card-value" + (st === "synced" || st === "exported" ? " ok" : "");
}

function updateOverlay(force = false) {
  const v = video();
  const t = v.currentTime;
  const i = cueAt(t);
  const ov = $("overlay");
  if (i !== S.nowIdx || force) {
    S.nowIdx = i;
    if (!ov.classList.contains("editing")) ov.textContent = i >= 0 ? cues()[i].text[LANG] || "" : "";
    document.querySelectorAll(".cue.now").forEach((el) => el.classList.remove("now"));
    if (i >= 0) {
      const el = document.querySelector(`.cue[data-i="${i}"]`);
      if (el) {
        el.classList.add("now");
        if (!v.paused) el.scrollIntoView({ block: "nearest" });
      }
    }
  }
  const dur = v.duration || 0;
  $("timeLabel").textContent = `${fmt(t).slice(0, -2)} / ${fmt(dur, false)}`;
  if (document.activeElement !== $("seek") && dur) $("seek").value = Math.round((t / dur) * 1000);
}

function updateOffsetLabel() {
  $("offsetLabel").textContent = `${S.offset >= 0 ? "+" : ""}${S.offset.toFixed(1)}s`;
}

function renderRanges() {
  const parts = S.ranges.map(([s, e]) => `${fmt(s, false)}-${fmt(e, false)}`);
  if (S.pendingIn !== null) parts.push(`${fmt(S.pendingIn, false)}-?`);
  $("rangeLabel").textContent = parts.length ? parts.join(", ") : "I / O 키로 지정";
}

// ---------------------------------------------------------------- 플레이어

function video() { return $("video"); }

function tick() {
  if (S.current) updateOverlay();
  requestAnimationFrame(tick);
}

function togglePlay() {
  const v = video();
  if (v.paused) v.play(); else v.pause();
}

function jumpCue(dir) {
  const list = cues();
  const t = video().currentTime;
  let idx;
  if (dir > 0) idx = list.findIndex((c) => c.start > t + 0.05);
  else { idx = -1; for (let i = list.length - 1; i >= 0; i--) if (list[i].start < t - 0.3) { idx = i; break; } }
  if (idx >= 0) { S.selected = idx; video().currentTime = list[idx].start + 0.001; renderCues(); }
}

function startOverlayEdit() {
  const i = cueAt(video().currentTime);
  if (i < 0) return;
  video().pause();
  const ov = $("overlay");
  ov.dataset.i = i;
  ov.classList.add("editing");
  ov.contentEditable = "true";
  ov.focus();
  const sel = window.getSelection();
  sel.selectAllChildren(ov);
  sel.collapseToEnd();
}

function endOverlayEdit(commit) {
  const ov = $("overlay");
  if (!ov.classList.contains("editing")) return;
  const i = Number(ov.dataset.i);
  const text = ov.innerText.replace(/\n{2,}/g, "\n").trim();
  ov.classList.remove("editing");
  ov.contentEditable = "false";
  const c = cues()[i];
  if (commit && c && text !== (c.text[LANG] || "")) edit(() => { c.text[LANG] = text; });
  else updateOverlay(true);
}

// ---------------------------------------------------------------- 단축키

function isTyping(el) {
  return el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
}

function onKey(e) {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.code === "KeyS") { e.preventDefault(); save(); return; }
  if (isTyping(document.activeElement)) return;
  if (!S.current || $("tab-edit").hidden) return;
  if (mod && e.code === "KeyZ") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
  if (mod && e.code === "KeyY") { e.preventDefault(); redo(); return; }
  if (mod || e.altKey) return;

  const v = video();
  const t = v.currentTime;
  const handled = {
    Space: () => togglePlay(),
    ArrowLeft: () => { v.currentTime = Math.max(0, t - 1); },
    ArrowRight: () => { v.currentTime = t + 1; },
    ArrowUp: () => jumpCue(-1),
    ArrowDown: () => jumpCue(1),
    BracketLeft: () => setStart(targetIdx(), t),
    BracketRight: () => setEnd(targetIdx(), t),
    Comma: () => (e.shiftKey ? shiftAll(-0.1) : nudge(targetIdx(), -0.1)),
    Period: () => (e.shiftKey ? shiftAll(0.1) : nudge(targetIdx(), 0.1)),
    KeyS: () => splitAt(cueAt(t), t),
    KeyM: () => mergeNext(targetIdx()),
    KeyI: () => { S.pendingIn = t; renderRanges(); toast(`구간 시작 ${fmt(t, false)}`); },
    KeyO: () => {
      if (S.pendingIn === null || t <= S.pendingIn) return toast("먼저 I로 구간 시작을 지정하세요.", true);
      S.ranges.push([S.pendingIn, t]);
      S.ranges.sort((a, b) => a[0] - b[0]);
      S.pendingIn = null;
      renderRanges();
    },
  }[e.code];
  if (handled) {
    e.preventDefault();
    if (S.doc || ["Space", "ArrowLeft", "ArrowRight", "KeyI", "KeyO"].includes(e.code)) handled();
  }
}

// ---------------------------------------------------------------- 받아쓰기 탭 (명령어 생성기)

function options() {
  return {
    video: S.current,
    ranges: $("optRanges").value.trim(),
    glossary: S.extraGlossary,
    no_default_glossary: $("optNoDefault").checked,
    engine: $("optEngine").value,
    model: $("optModel").value.trim(),
    max_chars: Number($("optMaxChars").value) || 42,
    force: $("optForce").checked,
    replace: $("optReplace").checked,
  };
}

let cmdTimer = null;
function updateCommand() {
  clearTimeout(cmdTimer);
  cmdTimer = setTimeout(async () => {
    if (!S.current) return;
    try {
      const r = await api("POST", "/api/command", options());
      $("cmdPreview").textContent = r.display;
    } catch (e) { $("cmdPreview").textContent = e.message; }
  }, 150);
}

function renderExtraGlossary() {
  const ul = $("extraGlossary");
  ul.innerHTML = "";
  S.extraGlossary.forEach((g, i) => {
    const li = document.createElement("li");
    li.innerHTML = `<span class="mono">${escapeHtml(g)}</span><button class="ghost sm">빼기</button>`;
    li.querySelector("button").onclick = () => { S.extraGlossary.splice(i, 1); renderExtraGlossary(); updateCommand(); };
    ul.appendChild(li);
  });
}

async function loadGlossaryInfo() {
  try {
    const r = await api("GET", `/api/series-glossary?path=${enc(S.current)}`);
    const ul = $("autoGlossary");
    ul.innerHTML = "";
    r.files.forEach((f, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="tag">${i === 0 ? "기본" : "시리즈"}</span><span class="mono">${escapeHtml(f.path)}</span>
        <span class="tag">${f.exists ? "있음" : "없음"}</span>`;
      ul.appendChild(li);
    });
  } catch (e) { /* 표시만 생략 */ }
}

async function runTranscribe() {
  if (!S.current) return;
  const o = options();
  if (o.force && !confirm("처음부터 다시 받아쓰면 지금까지 편집한 내용이 사라집니다. 계속할까요?")) return;
  try {
    await api("POST", "/api/run", o);
    toast("받아쓰기를 시작했습니다. 진행 상황은 왼쪽에서 볼 수 있습니다.");
    refreshVideos(); refreshJobs();
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- 연결

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $("tab-edit").hidden = name !== "edit";
  $("tab-cmd").hidden = name !== "cmd";
  if (name === "cmd") updateCommand();
}

async function exportFormat(fmtName) {
  if (!S.doc) return toast("자막이 없습니다.", true);
  if (S.dirty && !(await save())) return;
  const body = { path: S.current, formats: [fmtName] };
  try {
    const r = await api("POST", "/api/export", body);
    toast(`저장: ${r.files.join(", ")}`);
  } catch (e) {
    if (/이미 있습니다/.test(e.message) && confirm(`${e.message}\n덮어쓸까요?`)) {
      try { const r = await api("POST", "/api/export", { ...body, force: true }); toast(`저장: ${r.files.join(", ")}`); }
      catch (e2) { toast(e2.message, true); }
    } else toast(e.message, true);
  }
  refreshVideos();
}

function bind() {
  $("addBtn").onclick = async () => {
    const r = await api("POST", "/api/pick", { prompt: "영상 선택" }).catch((e) => toast(e.message, true));
    if (r && r.path) addVideo(r.path);
  };
  $("pathInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { addVideo(e.target.value.trim().replace(/^"|"$/g, "")); e.target.value = ""; }
  });
  document.querySelectorAll(".tab").forEach((b) => (b.onclick = () => switchTab(b.dataset.tab)));
  $("goCmd").onclick = () => switchTab("cmd");

  const v = video();
  $("playBtn").onclick = togglePlay;
  v.addEventListener("play", () => ($("playBtn").textContent = "❚❚"));
  v.addEventListener("pause", () => ($("playBtn").textContent = "▶"));
  v.addEventListener("loadedmetadata", () => updateStats());
  v.addEventListener("error", () => toast("이 영상은 브라우저에서 재생할 수 없는 형식입니다. (자막 생성은 가능)", true));
  $("seek").addEventListener("input", (e) => { if (v.duration) v.currentTime = (e.target.value / 1000) * v.duration; });
  $("rateBtn").onclick = () => { v.playbackRate = v.playbackRate === 1 ? 0.5 : 1; $("rateBtn").textContent = v.playbackRate + "x"; };

  $("overlay").addEventListener("click", () => { if (!$("overlay").classList.contains("editing")) startOverlayEdit(); });
  $("overlay").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); endOverlayEdit(true); }
    else if (e.key === "Escape") { e.preventDefault(); endOverlayEdit(false); }
    e.stopPropagation();
  });
  $("overlay").addEventListener("blur", () => endOverlayEdit(true));

  document.querySelectorAll("[data-shift]").forEach((b) => (b.onclick = () => shiftAll(parseFloat(b.dataset.shift))));
  $("autoSyncBtn").onclick = async () => {
    if (!S.doc) return toast("자막이 없습니다.", true);
    if (S.dirty && !(await save())) return;
    try { await api("POST", "/api/sync-auto", { path: S.current }); toast("자동 맞춤을 시작했습니다."); refreshJobs(); }
    catch (e) { toast(e.message, true); }
  };
  $("rangeToCmd").onclick = () => {
    if (!S.ranges.length) return toast("I / O 키로 구간을 먼저 지정하세요.", true);
    $("optRanges").value = S.ranges.map(([s, e]) => `${fmt(s, false)}-${fmt(e, false)}`).join(", ");
    $("optReplace").checked = !!S.doc;
    switchTab("cmd");
  };
  $("rangeClear").onclick = () => { S.ranges = []; S.pendingIn = null; renderRanges(); };

  $("undoBtn").onclick = undo;
  $("redoBtn").onclick = redo;
  $("saveBtn").onclick = save;
  $("syncedChk").onchange = () => setDirty(true);
  document.querySelectorAll("[data-export]").forEach((b) => (b.onclick = () => exportFormat(b.dataset.export)));

  $("restoreYes").onclick = () => {
    S.undo.push(JSON.stringify(S.doc ? S.doc.cues : []));
    S.doc = S.autosave;
    S.autosave = null;
    $("restoreBanner").hidden = true;
    $("noDoc").hidden = true;
    setDirty(true); renderCues(); updateOverlay(true);
  };
  $("restoreNo").onclick = async () => {
    await api("DELETE", `/api/autosave?path=${enc(S.current)}`).catch(() => {});
    S.autosave = null;
    $("restoreBanner").hidden = true;
  };

  $("edStart").addEventListener("change", (e) => { const t = parseTime(e.target.value); if (t === null) return toast("시각 형식: 분:초.밀리초", true); setStart(S.selected, t); });
  $("edEnd").addEventListener("change", (e) => { const t = parseTime(e.target.value); if (t === null) return toast("시각 형식: 분:초.밀리초", true); setEnd(S.selected, t); });
  $("edText").addEventListener("change", (e) => {
    const c = cues()[S.selected];
    if (c && e.target.value.trim() !== (c.text[LANG] || "")) edit(() => { c.text[LANG] = e.target.value.trim(); });
  });
  $("edSplit").onclick = () => splitAt(S.selected, video().currentTime);
  $("edMerge").onclick = () => mergeNext(S.selected);
  $("edDelete").onclick = () => deleteCue(S.selected);

  ["optRanges", "optNoDefault", "optEngine", "optModel", "optMaxChars", "optForce", "optReplace"].forEach((id) => {
    $(id).addEventListener("input", updateCommand);
    $(id).addEventListener("change", updateCommand);
  });
  $("addGlossary").onclick = async () => {
    const r = await api("POST", "/api/pick", { prompt: "용어집 CSV 선택" }).catch((e) => toast(e.message, true));
    if (r && r.path && !S.extraGlossary.includes(r.path)) { S.extraGlossary.push(r.path); renderExtraGlossary(); updateCommand(); }
  };
  $("copyCmd").onclick = async () => {
    try { await navigator.clipboard.writeText($("cmdPreview").textContent); toast("복사했습니다."); }
    catch (e) { toast("복사하지 못했습니다. 직접 선택해서 복사하세요.", true); }
  };
  $("runCmd").onclick = runTranscribe;

  document.addEventListener("keydown", onKey);
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
}

async function init() {
  initTheme();
  bind();
  try {
    S.info = await api("GET", "/api/info");
    $("autoSyncBtn").disabled = !S.info.ffsubsync;
    if (!S.info.ffsubsync) $("autoSyncBtn").title = "ffsubsync 설치 시 사용 가능 (pip install ffsubsync)";
    $("optModel").placeholder = S.info.default_models[S.info.engine];
  } catch (e) { toast("서버에 연결할 수 없습니다.", true); }
  await refreshVideos();
  await refreshJobs();
  setInterval(() => { refreshVideos(); refreshJobs(); }, 1500);
  setInterval(autosave, 30000);
  requestAnimationFrame(tick);
}

init();
