/* Isolated Pasokhnama live overlay: no Didban API calls, no secrets. */
(function () {
  "use strict";
  // Some studio networks load github.io but cannot reach raw.githubusercontent.com.
  // Only PUBLIC, read-only mirrors of the isolated Pasokhnama data are used.
  // No Didban endpoint, private token, or unrelated feed is accessed.
  const sources = [
    {name: "GitHub Raw", url: "https://raw.githubusercontent.com/sey3d-m/velayat-live-monitor/pasokhnama-live-data/state/live.json", format: "json"},
    {name: "GitHub API", url: "https://api.github.com/repos/sey3d-m/velayat-live-monitor/contents/state/live.json?ref=pasokhnama-live-data", format: "github"},
    {name: "jsDelivr", url: "https://cdn.jsdelivr.net/gh/sey3d-m/velayat-live-monitor@pasokhnama-live-data/state/live.json", format: "json"},
    {name: "پشتیبان سایت (غیرزنده)", url: "data/pasokhnama-snapshot.json", format: "json"}
  ];
  let apiUnreachableUntil = 0;
  const loadFeed = async () => {
    const diagnostics = [];
    for (const source of sources) {
      // Rate-limit fallback API requests when source 1 is inaccessible.
      if (source.format === "github" && Date.now() < apiUnreachableUntil) continue;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 6500);
      try {
        const separator = source.url.includes("?") ? "&" : "?";
        const response = await fetch(source.url + separator + "_=" + Date.now(), {
          cache: "no-store", signal: controller.signal
        });
        if (!response.ok) throw new Error("HTTP " + response.status);
        let feed;
        if (source.format === "github") {
          const envelope = await response.json();
          if (envelope.encoding !== "base64" || typeof envelope.content !== "string")
            throw new Error("GitHub content response malformed");
          const decoded = atob(envelope.content.replace(/\s/g, ""));
          const bytes = Uint8Array.from(decoded, ch => ch.charCodeAt(0));
          feed = JSON.parse(new TextDecoder("utf-8").decode(bytes));
        } else {
          feed = await response.json();
        }
        if (!feed || feed.network !== "velayat_farsi" || !Array.isArray(feed.items))
          throw new Error("Feed data incomplete");
        return {feed, source: source.name};
      } catch (err) {
        diagnostics.push(source.name + ": " + (err && err.message || "unavailable"));
        if (source.format === "github") apiUnreachableUntil = Date.now() + 600000;
      } finally {
        clearTimeout(timeout);
      }
    }
    throw new Error("All isolated public feed sources unavailable: " + diagnostics.join("; "));
  };
  const $ = id => document.getElementById(id);
  const append = (tag, cls, content) => {
    const node = document.createElement(tag);
    node.className = cls;
    node.textContent = content;
    return node;
  };
  const dateLabel = value => {
    const n = Date.parse(value || "");
    if (!Number.isFinite(n)) return "زمان نامشخص";
    return new Intl.DateTimeFormat("fa-IR", {
      timeZone: "Asia/Tehran", dateStyle: "short", timeStyle: "medium"
    }).format(new Date(n));
  };
  function programWindowOpen(feed) {
    // Didban's job dispatch happens ~15 minutes early. Never show captions
    // under the new program name before that program's Tehran start time.
    const match = String(feed.program || "").match(/\|\s*(\d{2}):(\d{2})/);
    if (!match || !/^\d{4}-\d{2}-\d{2}$/.test(String(feed.program_date || ""))) return false;
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Tehran", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23"
    }).formatToParts(new Date()).filter(p => p.type !== "literal")
      .map(p => [p.type, p.value]));
    const today = parts.year + "-" + parts.month + "-" + parts.day;
    if (feed.program_date > today) return false;
    if (feed.program_date < today) return true;
    const nowMinute = Number(parts.hour) * 60 + Number(parts.minute);
    const slotMinute = Number(match[1]) * 60 + Number(match[2]);
    return nowMinute >= slotMinute;
  }
  async function refresh() {
    try {
      const {feed, source} = await loadFeed();
      const age = Date.now() - Date.parse(feed.updated_at || "");
      const fresh = Number.isFinite(age) && age > -120000 && age < 240000;
      const live = feed.status === "live" && fresh;
      $("live-status").textContent = live ? "دریافت زنده" :
        (fresh && feed.status === "reviewing" ? "صوت دریافت شد؛ بررسی متن" :
        (fresh && feed.status === "starting" ? "تبدیل گفتار و ویراستاری" : "آخرین مطالب ثبت‌شده"));
      $("live-program").textContent = String(feed.program || "شبکه ولایت فارسی").slice(0, 100);
      $("live-updated").textContent = "آخرین داده: " + dateLabel(feed.updated_at) + " | " + source;
      const wrap = $("live-content");
      wrap.replaceChildren();
      if (!programWindowOpen(feed)) {
        $("live-status").textContent = "در انتظار آغاز رسمی برنامه";
        wrap.append(append("div", "tv-empty", "مطالب این برنامه از ساعت رسمی پخش نمایش داده می‌شوند."));
        return;
      }
      // OBS must NOT turn blank merely because the upstream published
      // fewer than four minutes ago. Previously accepted headlines stay
      // visible as ARCHIVE with an explicit stale status, never as "live".
      if (!fresh) {
        $("live-status").textContent = "آخرین مطالب ثبت‌شده (غیرزنده)";
      }
      const items = feed.items.filter(item => item && item.kind === "edited_transcript" &&
        item.verification_status === "machine_edited_unverified" &&
        item.scope === "topic_only" &&
        typeof item.title === "string" && item.title.length >= 12 &&
        typeof item.summary === "string" && item.summary.trim().length >= 35).slice(-3).reverse();
      if (!items.length) {
        const progress = feed.progress || {};
        const audioChunks = Number(progress.segments_captured) || 0;
        const edits = Number(progress.editor_attempts) || 0;
        wrap.append(append("div", "tv-empty", audioChunks > 0
          ? "صوت برنامه دریافت شده (" + audioChunks + " قطعه)؛ " +
            edits + " بخش بررسی شده و هنوز موضوع قابل انتشار ثبت نشده است."
          : "هنوز تیتر ثبت نشده؛ وضعیت اتصال و دریافت صوت در حال بررسی است."));
      }
      for (const item of items) {
        const node = append("article", "tv-card", "");
        node.append(append("h2", "", item.title.slice(0, 90)));
        node.append(append("p", "", item.summary.slice(0, 390)));
        wrap.append(node);
      }
    } catch (err) {
      $("live-status").textContent = "اتصال داده برقرار نیست (۳ مسیر بررسی شد)";
      $("live-updated").textContent = "دریافت داده ناموفق؛ بررسی اتصال GitHub";
      const wrap = $("live-content");
      // If a browser occasionally fails to reach raw.githubusercontent.com,
      // preserve on-screen previously accepted material instead of erasing it.
      if (!wrap.children.length) {
        wrap.append(append("div", "tv-empty", "اتصال مرورگر به منابع داده GitHub برقرار نیست. این پیام مربوط به نمایش است، نه لزوماً توقف ضبط شبکه."));
      }
      console.warn("Pasokhnama isolated feed fetch failed:", err && err.message);
    }
  }
  refresh();
  setInterval(refresh, 25000);
})();
