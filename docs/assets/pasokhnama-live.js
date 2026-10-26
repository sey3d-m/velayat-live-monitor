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
        (fresh && feed.status === "starting" ? "پردازش صوت" : "آخرین مطالب ثبت‌شده");
      $("live-program").textContent = String(feed.program || "شبکه ولایت فارسی").slice(0, 100);
      $("live-updated").textContent = "آخرین دریافت: " + dateLabel(feed.updated_at);
      const wrap = $("live-content");
      wrap.replaceChildren();
      const items = feed.items.filter(item => item && item.kind === "automatic_transcript" &&
        item.verification_status === "unverified" && typeof item.summary === "string").slice(-3).reverse();
      if (!items.length) {
        wrap.append(append("div", "tv-empty", "در انتظار دریافت رونوشت واقعی برنامه فارسی …"));
      }
      for (const item of items) {
        const node = append("article", "tv-card", "");
        node.append(append("h2", "", "گزیده خودکار از گفت‌وگوی در حال پخش"));
        node.append(append("p", "", item.summary.slice(0, 290)));
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
