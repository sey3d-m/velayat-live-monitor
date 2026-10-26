/* Isolated Pasokhnama live overlay: no Didban API calls, no secrets. */
(function () {
  "use strict";
  const origin = "https://raw.githubusercontent.com/sey3d-m/velayat-live-monitor/pasokhnama-live-data/state/live.json";
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
      const response = await fetch(origin + "?_=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("Source unavailable");
      const feed = await response.json();
      if (!feed || feed.network !== "velayat_farsi" || !Array.isArray(feed.items)) throw new Error("Bad feed");
      const age = Date.now() - Date.parse(feed.updated_at || "");
      const fresh = Number.isFinite(age) && age > -120000 && age < 240000;
      const live = feed.status === "live" && fresh;
      $("live-status").textContent = live ? "دریافت زنده" :
        (fresh && feed.status === "starting" ? "تبدیل گفتار و ویراستاری" : "آخرین مطالب ثبت‌شده");
      $("live-program").textContent = String(feed.program || "شبکه ولایت فارسی").slice(0, 100);
      $("live-updated").textContent = "آخرین دریافت: " + dateLabel(feed.updated_at);
      const wrap = $("live-content");
      wrap.replaceChildren();
      if (!programWindowOpen(feed)) {
        $("live-status").textContent = "در انتظار آغاز رسمی برنامه";
        wrap.append(append("div", "tv-empty", "مطالب این برنامه از ساعت رسمی پخش نمایش داده می‌شوند."));
        return;
      }
      const items = feed.items.filter(item => item && item.kind === "edited_transcript" &&
        item.verification_status === "machine_edited_unverified" &&
        item.scope === "topic_only" &&
        typeof item.title === "string" && item.title.length >= 12 &&
        typeof item.summary === "string" && item.summary.length >= 85).slice(-3).reverse();
      if (!items.length) {
        wrap.append(append("div", "tv-empty", "در انتظار استخراج و بازنویسی دقیق مطالب برنامه فارسی …"));
      }
      for (const item of items) {
        const node = append("article", "tv-card", "");
        node.append(append("h2", "", item.title.slice(0, 90)));
        node.append(append("p", "", item.summary.slice(0, 390)));
        wrap.append(node);
      }
    } catch (_) {
      $("live-status").textContent = "اتصال داده موقتاً قطع است";
      $("live-updated").textContent = "در انتظار تازه‌سازی";
    }
  }
  refresh();
  setInterval(refresh, 25000);
})();
