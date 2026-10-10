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
    visibleLimit: 60,
    maxScore: 1e-9,
  };
  const dayCache = new Map();

  const feedEl = document.getElementById("feed");
  const pillsEl = document.getElementById("subjectPills");
  const searchEl = document.getElementById("search");
  const generatedEl = document.getElementById("generatedAt");
  const countEl = document.getElementById("itemCount");
  const dateSelect = document.getElementById("dateSelect");
  const startEl = document.getElementById("startDate");
  const endEl = document.getElementById("endDate");
  const applyEl = document.getElementById("applyRange");
  const translateTitlesEl = document.getElementById('translateTitles');
  const titleTranslations = new Map();

  function articleKey(article) {
    return article.links?.[0]?.url || article.url || article.title;
  }

  function showTranslatedTitle(article) {
    const translated = titleTranslations.get(articleKey(article));
    if (!translated) return;
    const card = [...feedEl.querySelectorAll('.article')].find((el) => el.dataset.articleKey === articleKey(article));
    const heading = card?.querySelector('h2');
    if (heading) {
      heading.querySelector('a').textContent = translated;
    }
    if (heading && !heading.querySelector('.title-en')) {
      const line = document.createElement('span');
      line.className = 'title-en';
      line.textContent = article.title;
      heading.appendChild(line);
    }
  }

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
      { value: "today", label: "最新" },
      ...state.days
        .slice()
        .reverse()
        .map((d) => ({ value: `day:${d.date}`, label: d.date })),
      { value: "all", label: "全部历史" },
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

  async function hydrateArticle(article) {
    if (!article.catalogue) return article;
    if (!dayCache.has(article.archiveDate)) {
      dayCache.set(article.archiveDate, fetchDayFile(article.archiveDate).catch((error) => {
        dayCache.delete(article.archiveDate);
        throw error;
      }));
    }
    const report = await dayCache.get(article.archiveDate);
    const full = (report.articles || []).find((item) => item.links?.[0]?.url === article.url);
    if (!full) throw new Error('未找到原始日报中的论文');
    Object.assign(article, full, { catalogue: false });
    return article;
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
      const archiveDate = p.generated_at ? new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
      }).format(new Date(p.generated_at)) : '';
      (p.articles || []).forEach((a) => {
        if (a.title_zh) titleTranslations.set(a.links?.[0]?.url || a.url || a.title, a.title_zh);
        articles.push({
          ...a,
          content: a.content || '',
          links: a.links || (a.url ? [{ label: a.source || '原文', url: a.url }] : []),
          archiveDate: a.date || archiveDate,
          catalogue: Boolean(a.date),
        });
        if (a.subject && !subjects.includes(a.subject)) subjects.push(a.subject);
      });
    });
    state.articles = articles;
    state.maxScore = articles.reduce((max, article) => Math.max(max, article.score || 0), 1e-9);
    state.visibleLimit = 60;
    state.subjects = subjects;
    state.activeSubject = "all";
    const gen = payloads.find((p) => p.generated_at);
    const g = formatBeijing(gen && gen.generated_at, true);
    generatedEl.textContent = g ? `${g} CST` : "—";
    countEl.textContent = `${articles.length} 篇`;
    searchEl.placeholder = state.mode === 'all' ? '搜索历史标题或分类标签…' : '搜索标题或摘要…';
    renderPills();
    render();
  }

  async function loadData() {
    feedEl.innerHTML = '<div class="empty">正在加载…</div>';
    let payloads;
    try {
      if (state.mode === "today") {
        payloads = [await getJSON("data/report.json")];
      } else if (state.mode === "all") {
        payloads = [await getJSON('data/search-index.json')];
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
        '<div class="empty">无法加载所选日期的数据，请稍后重试。</div>';
      console.error(err);
      return;
    }
    if (!payloads.length) {
      feedEl.innerHTML = '<div class="empty">这个日期范围没有存档。</div>';
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
        name === "all" ? "全部" : `${name} · ${counts[name] || 0}`;
      btn.addEventListener("click", () => {
        state.activeSubject = name;
        state.visibleLimit = 60;
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
        (a.title_zh || '').toLowerCase().includes(q) ||
        a.content.toLowerCase().includes(q) ||
        (a.content_zh || '').toLowerCase().includes(q) ||
        (a.tags || []).some((tag) => tag.toLowerCase().includes(q));
      return okSubject && okQuery;
    });
  }

  function render() {
    const list = visibleArticles();
    if (!list.length) {
      feedEl.innerHTML = '<div class="empty">没有符合条件的内容。</div>';
      return;
    }
    const shown = list.slice(0, state.visibleLimit);
    feedEl.replaceChildren(...shown.map(articleEl));
    if (shown.length < list.length) {
      const more = document.createElement('button');
      more.type = 'button';
      more.className = 'load-more';
      more.textContent = `显示更多（已显示 ${shown.length} / ${list.length}）`;
      more.addEventListener('click', () => {
        state.visibleLimit += 60;
        render();
      });
      feedEl.appendChild(more);
    }
  }

  function articleEl(a) {
    const el = document.createElement("article");
    el.className = "article" + (a.score > 0 ? " top" : "");
    el.dataset.articleKey = articleKey(a);

    const time = document.createElement("time");
    time.textContent = formatBeijing(a.published_at) || "";
    time.title = "北京时间（UTC+8）";

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
    const arxivId = a.source === 'arxiv' && firstLink?.url.match(/^https:\/\/arxiv\.org\/abs\/([\w.\-]+)$/)?.[1];
    const cachedTitle = titleTranslations.get(articleKey(a)) || a.title_zh;
    anchor.textContent = cachedTitle || a.title;
    if (arxivId) {
      anchor.href = `reader.html?id=${encodeURIComponent(arxivId)}&date=${encodeURIComponent(a.archiveDate)}`;
    } else if (firstLink) {
      anchor.href = firstLink.url;
      anchor.target = '_blank';
      anchor.rel = 'noopener';
    }
    title.appendChild(anchor);
    if (cachedTitle) {
      const enLine = document.createElement('span');
      enLine.className = 'title-en';
      enLine.textContent = a.title;
      title.appendChild(enLine);
    }

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
    if (arxivId) {
      const reader = document.createElement('a');
      reader.className = 'link-chip reader-link';
      reader.href = anchor.href;
      reader.textContent = '双语阅读';
      links.prepend(reader);
    }

    const abstract = document.createElement("p");
    abstract.className = "abstract collapsed";
    abstract.textContent = a.content_zh || a.content || (a.catalogue ? '点击“展开摘要”时加载当日摘要。' : '');

    const toggle = document.createElement("button");
    toggle.className = "expand-btn";
    toggle.textContent = "展开摘要";
    toggle.addEventListener("click", async () => {
      if (a.catalogue) {
        toggle.disabled = true;
        toggle.textContent = '正在加载摘要…';
        try {
          await hydrateArticle(a);
          abstract.textContent = a.content_zh || a.content || '';
          const translationButton = el.querySelector('.translate-btn');
          if (a.content_zh && translationButton) translationButton.textContent = '显示英文摘要';
        } catch (error) {
          abstract.textContent = '摘要加载失败，请打开原文链接。';
          toggle.textContent = '重试';
          toggle.disabled = false;
          return;
        }
        toggle.disabled = false;
      }
      const collapsed = abstract.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "展开摘要" : "收起摘要";
    });

    el.append(rowTop, title, links, abstract, toggle);

    if (a.source === 'arxiv') {
      const translateButton = document.createElement('button');
      translateButton.className = 'translate-btn';
      translateButton.type = 'button';
      translateButton.textContent = a.content_zh ? '显示英文摘要' : '翻译标题与摘要';
      let original;
      let errorEl;
      translateButton.addEventListener('click', async () => {
        if (a.content_zh) {
          if (!original) {
            await hydrateArticle(a);
            original = document.createElement('div');
            original.className = 'translation original-abstract';
            const label = document.createElement('strong');
            label.textContent = '英文原文摘要';
            const paragraph = document.createElement('p');
            paragraph.textContent = a.content || '';
            original.append(label, paragraph);
            el.insertBefore(original, toggle);
            original.hidden = true;
          }
          original.hidden = !original.hidden;
          translateButton.textContent = original.hidden ? '显示英文摘要' : '隐藏英文摘要';
          return;
        }
        translateButton.disabled = true;
        translateButton.textContent = '正在翻译…';
        errorEl?.remove();
        try {
          // Pretranslated daily reports are instant; older reports use Chrome locally.
          await hydrateArticle(a);
          const titleZh = a.title_zh || await ScholarTranslator.translate(a.title, (message) => { translateButton.textContent = message; });
          titleTranslations.set(articleKey(a), titleZh);
          showTranslatedTitle(a);
          const abstractZh = a.content_zh || await ScholarTranslator.translate(a.content || '');
          a.title_zh = titleZh;
          a.content_zh = abstractZh;
          abstract.textContent = abstractZh;
          translateButton.textContent = '显示英文摘要';
        } catch (error) {
          translateButton.textContent = '无法翻译，点击重试';
          errorEl = document.createElement('p');
          errorEl.className = 'translation-error';
          errorEl.setAttribute('role', 'status');
          errorEl.textContent = error.message || '翻译失败，请稍后重试。';
          el.insertBefore(errorEl, toggle);
        } finally {
          translateButton.disabled = false;
        }
      });
      el.insertBefore(translateButton, toggle);
    }

    if (typeof a.score === "number" && a.score !== 0) {
      const score = document.createElement("div");
      score.className = "score";
      const bar = document.createElement("div");
      bar.className = "bar";
      bar.style.width = `${Math.min(100, Math.max(6, (a.score / state.maxScore) * 100))}%`;
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
    state.visibleLimit = 60;
    render();
  });

  translateTitlesEl.addEventListener('click', async () => {
    const articles = visibleArticles().slice(0, state.visibleLimit).filter((article) => article.source === 'arxiv');
    translateTitlesEl.disabled = true;
    try {
      for (let i = 0; i < articles.length; i++) {
        const article = articles[i];
        translateTitlesEl.textContent = `翻译标题 ${i + 1} / ${articles.length}…`;
        if (!titleTranslations.has(articleKey(article))) {
          const translated = await ScholarTranslator.translate(article.title, (message) => { translateTitlesEl.textContent = message; });
          titleTranslations.set(articleKey(article), translated);
        }
        showTranslatedTitle(article);
      }
    } catch (error) {
      translateTitlesEl.title = error.message;
      translateTitlesEl.textContent = error.message || '翻译不可用，点击重试';
      translateTitlesEl.disabled = false;
      return;
    }
    translateTitlesEl.textContent = '当前标题已翻译';
    translateTitlesEl.disabled = false;
  });

  (async () => {
    await loadIndex();
    loadData();
  })();
})();
