/* Scholar Tide — static renderer.
 * Fetches data/report.json (latest build) or archived days
 * (data/report-YYYY-MM-DD.json) and renders a grid of cards with
 * subject, text and date-scope filters.
 */
(() => {
  "use strict";

  const state = {
    articles: [],
    subjects: [],
    activeSubject: "all",
    query: "",
    days: [],
    mode: "today",
    rangeStart: "",
    rangeEnd: "",
  };

  const feedEl = document.getElementById("feed");
  const pillsEl = document.getElementById("subjectPills");
  const searchEl = document.getElementById("search");
  const generatedEl = document.getElementById("generatedAt");
  const countEl = document.getElementById("itemCount");
  const dateSelect = document.getElementById("dateSelect");
  const startEl = document.getElementById("startDate");
  const endEl = document.getElementById("endDate");
  const applyEl = document.getElementById("applyRange");

  const fmtSec = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hourCycle: "h23",
  });
  const fmtMin = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  });

  function formatBeijing(value, withSeconds = false) {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return (withSeconds ? fmtSec : fmtMin).format(d);
  }

  async function getJSON(url) {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) throw new Error(`${url} -> ${res.status}`);
    return res.json();
  }

  async function loadIndex() {
    try {
      const index = await getJSON("data/index.json");
      state.days = index.days || [];
      populateDateSelect();
    } catch (err) {
      state.days = [];
      console.warn("no history index found", err);
    }
  }

  function populateDateSelect() {
    const opts = [
      { value: "today", label: "Today" },
      ...state.days
        .slice()
        .reverse()
        .map((d) => ({ value: `day:${d.date}`, label: d.date })),
      { value: "all", label: "All history" },
    ];
    dateSelect.replaceChildren(
      ...opts.map((o) => {
        const opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.label;
        return opt;
      })
    );
    if (state.days.length) {
      startEl.min = state.days[0].date;
      endEl.max = state.days[state.days.length - 1].date;
    }
    dateSelect.value = "today";
  }

  function fetchDayFile(date) {
    return getJSON(`data/report-${date}.json`);
  }

  function datesInRange(start, end) {
    return state.days
      .map((d) => d.date)
      .filter((d) => (!start || d >= start) && (!end || d <= end));
  }

  async function fetchMany(dates) {
    const out = [];
    const queue = dates.slice();
    async function worker() {
      while (queue.length) {
        out.push(await fetchDayFile(queue.shift()));
      }
    }
    await Promise.all(Array.from({ length: Math.min(6, queue.length) }, worker));
    return out;
  }

  function applyPayloads(payloads) {
    const articles = [];
    const subjects = [];
    payloads.forEach((p) => {
      (p.articles || []).forEach((a) => {
        articles.push(a);
        if (a.subject && !subjects.includes(a.subject)) subjects.push(a.subject);
      });
    });
    state.articles = articles;
    state.subjects = subjects;
    state.activeSubject = "all";
    const gen = payloads.find((p) => p.generated_at);
    const g = formatBeijing(gen && gen.generated_at, true);
    generatedEl.textContent = g ? `${g} CST` : "—";
    countEl.textContent = `${articles.length} items`;
    renderPills();
    render();
  }

  async function loadData() {
    feedEl.innerHTML = '<div class="empty">Loading…</div>';
    let payloads;
    try {
      if (state.mode === "today") {
        payloads = [await getJSON("data/report.json")];
      } else if (state.mode === "all") {
        payloads = await fetchMany(state.days.map((d) => d.date));
      } else if (state.mode === "range") {
        const dates = datesInRange(state.rangeStart, state.rangeEnd);
        payloads = dates.length ? await fetchMany(dates) : [];
      } else if (state.mode.startsWith("day:")) {
        payloads = [await fetchDayFile(state.mode.slice(4))];
      } else {
        payloads = [await getJSON("data/report.json")];
      }
    } catch (err) {
      feedEl.innerHTML =
        '<div class="empty">Could not load the selected range — check that ' +
        "data/index.json and data/report-YYYY-MM-DD.json exist.</div>";
      console.error(err);
      return;
    }
    if (!payloads.length) {
      feedEl.innerHTML = '<div class="empty">No archived reports in this range.</div>';
      return;
    }
    applyPayloads(payloads);
  }

  function renderPills() {
    const counts = {};
    state.articles.forEach((a) => {
      counts[a.subject] = (counts[a.subject] || 0) + 1;
    });
    const pill = (name) => {
      const btn = document.createElement("button");
      btn.className = "pill" + (state.activeSubject === name ? " active" : "");
      btn.textContent =
        name === "all" ? "All" : `${name} · ${counts[name] || 0}`;
      btn.addEventListener("click", () => {
        state.activeSubject = name;
        pillsEl.querySelectorAll(".pill").forEach((p) =>
          p.classList.toggle("active", p === btn)
        );
        render();
      });
      return btn;
    };
    pillsEl.replaceChildren(
      pill("all"),
      ...state.subjects.map((s) => pill(s))
    );
  }

  function visibleArticles() {
    const q = state.query.trim().toLowerCase();
    return state.articles.filter((a) => {
      const okSubject =
        state.activeSubject === "all" || a.subject === state.activeSubject;
      const okQuery =
        !q ||
        a.title.toLowerCase().includes(q) ||
        a.content.toLowerCase().includes(q);
      return okSubject && okQuery;
    });
  }

  function render() {
    const list = visibleArticles();
    if (!list.length) {
      feedEl.innerHTML =
        '<div class="empty">Nothing matches your filter.</div>';
      return;
    }
    feedEl.replaceChildren(...list.map(articleEl));
  }

  function articleEl(a) {
    const el = document.createElement("article");
    el.className = "article" + (a.score > 0 ? " top" : "");

    const time = document.createElement("time");
    time.textContent = formatBeijing(a.published_at) || "";
    time.title = "Beijing time (CST, UTC+8)";

    const subject = document.createElement("span");
    subject.className = "badge-subject";
    subject.textContent = a.subject;

    const source = document.createElement("span");
    source.className = "badge-source";
    source.textContent = a.source || "source";

    const rowTop = document.createElement("div");
    rowTop.className = "row-top";
    rowTop.append(subject, source, time);

    const title = document.createElement("h2");
    const anchor = document.createElement("a");
    const firstLink = a.links?.[0];
    anchor.textContent = a.title;
    if (firstLink) {
      anchor.href = firstLink.url;
      anchor.target = "_blank";
      anchor.rel = "noopener";
    }
    title.appendChild(anchor);

    const links = document.createElement("div");
    links.className = "links";
    (a.links || []).forEach((l) => {
      const chip = document.createElement("a");
      chip.className = "link-chip";
      chip.textContent = l.label;
      chip.href = l.url;
      chip.target = "_blank";
      chip.rel = "noopener";
      links.appendChild(chip);
    });

    const abstract = document.createElement("p");
    abstract.className = "abstract collapsed";
    abstract.textContent = a.content || "";

    const toggle = document.createElement("button");
    toggle.className = "expand-btn";
    toggle.textContent = "Read more";
    toggle.addEventListener("click", () => {
      const collapsed = abstract.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "Read more" : "Show less";
    });

    el.append(rowTop, title, links, abstract, toggle);

    if (typeof a.score === "number" && a.score !== 0) {
      const score = document.createElement("div");
      score.className = "score";
      const bar = document.createElement("div");
      bar.className = "bar";
      const scores = state.articles.map((x) => x.score || 0);
      const max = Math.max(...scores, 1e-9);
      bar.style.width = `${Math.min(100, Math.max(6, (a.score / max) * 100))}%`;
      score.appendChild(bar);
      el.appendChild(score);
    }

    return el;
  }

  dateSelect.addEventListener("change", () => {
    state.mode = dateSelect.value;
    loadData();
  });

  applyEl.addEventListener("click", () => {
    const s = startEl.value;
    const e = endEl.value;
    if (!s || !e || s > e) return;
    state.mode = "range";
    state.rangeStart = s;
    state.rangeEnd = e;
    let opt = dateSelect.querySelector('option[value="range"]');
    if (!opt) {
      opt = document.createElement("option");
      opt.value = "range";
      dateSelect.add(opt);
    }
    opt.textContent = `${s} ~ ${e}`;
    dateSelect.value = "range";
    loadData();
  });

  searchEl.addEventListener("input", (e) => {
    state.query = e.target.value;
    render();
  });

  (async () => {
    await loadIndex();
    loadData();
  })();
})();