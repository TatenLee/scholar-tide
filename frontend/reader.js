(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const id = params.get('id') || '';
  const date = params.get('date') || '';
  const titleEl = document.getElementById('paperTitle');
  const statusEl = document.getElementById('readerStatus');
  const contentEl = document.getElementById('translationContent');
  const parallelRowsEl = document.getElementById('parallelRows');
  const pdfFrame = document.getElementById('pdfFrame');
  const gridEl = document.getElementById('readerGrid');
  const translateButton = document.getElementById('translatePaper');
  const translateAllButton = document.getElementById('translateAll');
  const viewButtons = document.querySelectorAll('[data-view]');
  let blocks = [];
  let translating = false;
  let targets = [];
  let sourceTargets = [];
  const translatedBlocks = new Map();
  const batchSize = 4;

  function status(message) { statusEl.textContent = message; }
  function ensureTargets() {
    if (targets.length) return;
    contentEl.replaceChildren();
    parallelRowsEl.replaceChildren();
    targets = blocks.map((block, index) => {
      const tag = block.type === 'heading' ? 'h2' : 'p';
      const row = document.createElement('div');
      row.className = `parallel-row ${block.type === 'heading' ? 'parallel-heading' : ''}`;
      const english = document.createElement(tag);
      english.className = 'parallel-en';
      english.textContent = block.text || '英文原文加载中…';
      sourceTargets.push(english);
      const chinese = document.createElement(tag);
      chinese.className = 'parallel-zh';
      chinese.textContent = translatedBlocks.get(index) || '待翻译…';
      row.append(english, chinese);
      parallelRowsEl.appendChild(row);
      const pdfChinese = document.createElement(tag);
      pdfChinese.className = block.type === 'heading' ? 'translated-heading' : 'translated-paragraph';
      pdfChinese.textContent = chinese.textContent;
      contentEl.appendChild(pdfChinese);
      return { chinese, pdfChinese };
    });
  }
  function resetTargets() {
    targets = [];
    sourceTargets = [];
    ensureTargets();
  }
  function updateTranslation(index, value) {
    targets[index].chinese.textContent = value;
    targets[index].pdfChinese.textContent = value;
  }
  function setView(view) {
    gridEl.dataset.view = view;
    viewButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.view === view)));
    if (view === 'pdf' && !pdfFrame.getAttribute('src')) pdfFrame.src = pdfUrl;
  }
  viewButtons.forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));

  if (!/^\d{4}\.\d{4,5}(v\d+)?$|^[a-z-]+(\.[A-Z]{2})?\/\d{7}(v\d+)?$/.test(id)) {
    titleEl.textContent = '无效的 arXiv 论文编号';
    status('请从论文列表重新打开。');
    translateButton.disabled = true;
    return;
  }

  const absUrl = `https://arxiv.org/abs/${id}`;
  const pdfUrl = `https://arxiv.org/pdf/${id}`;
  const htmlUrl = `https://arxiv.org/html/${id}`;
  document.getElementById('arxivLink').href = absUrl;
  document.getElementById('pdfLink').href = pdfUrl;

  async function loadMetadata() {
    const path = /^\d{4}-\d{2}-\d{2}$/.test(date) ? `data/report-${date}.json` : 'data/report.json';
    try {
      const response = await fetch(path);
      if (!response.ok) return null;
      const report = await response.json();
      const paper = (report.articles || []).find((article) =>
        article.source === 'arxiv' && article.links?.some((link) => link.url === absUrl));
      if (paper) titleEl.textContent = paper.title_zh || paper.title;
      return paper;
    } catch (error) {
      console.warn('Could not load paper metadata', error);
      return null;
    }
  }

  function extractBlocks(markup) {
    const doc = new DOMParser().parseFromString(markup, 'text/html');
    const article = doc.querySelector('article.ltx_document');
    if (!article) return [];
    const abstract = article.querySelector('.ltx_abstract');
    const abstractText = abstract?.textContent.replace(/^\s*Abstract\s*/i, '').replace(/\s+/g, ' ').trim();
    const body = [...article.querySelectorAll('.ltx_title_section, .ltx_title_subsection, .ltx_title_subsubsection, .ltx_title_appendix, .ltx_caption, .ltx_para')]
      .filter((node) => !node.closest('.ltx_bibliography, .ltx_authors, .ltx_acknowledgements'))
      .filter((node) => !node.classList.contains('ltx_para') || (node.closest('.ltx_section, .ltx_appendix') && !node.closest('.ltx_caption')))
      .map((node) => ({
        type: node.matches('.ltx_para, .ltx_caption') ? 'paragraph' : 'heading',
        text: node.textContent.replace(/\s+/g, ' ').trim(),
      }))
      .filter((block) => block.text.length > 2);
    return abstractText ? [{ type: 'heading', text: 'Abstract' }, { type: 'paragraph', text: abstractText }, ...body] : body;
  }

  async function loadPaper() {
    const metadataPromise = loadMetadata();
    try {
      const response = await fetch(`data/papers/${encodeURIComponent(id)}.json`, { cache: 'no-store' });
      if (response.ok) {
        const saved = await response.json();
        if (saved.id === id && saved.status !== 'partial' && saved.status !== 'unavailable' && Array.isArray(saved.blocks) && saved.blocks.length > 2) {
          blocks = saved.blocks.map((block) => ({ type: block.type, text: block.en || '' }));
          saved.blocks.forEach((block, index) => translatedBlocks.set(index, block.zh));
          ensureTargets();
          translateButton.hidden = true;
          translateAllButton.hidden = true;
          status(`夜间预译全文已加载，共 ${blocks.length} 段。英中两列按段同步滚动，中文为机器初译。`);
          if (blocks.some((block) => !block.text)) {
            status(`中文已加载，正在补充 ${blocks.length} 段英文原文…`);
            try {
              const sourceResponse = await fetch(htmlUrl);
              if (!sourceResponse.ok) throw new Error(`HTTP ${sourceResponse.status}`);
              const sourceBlocks = extractBlocks(await sourceResponse.text());
              if (sourceBlocks.length !== blocks.length || sourceBlocks.some((block, index) => block.type !== blocks[index].type)) {
                throw new Error('原文段落数量或顺序与译文不一致');
              }
              sourceBlocks.forEach((block, index) => {
                blocks[index].text = block.text;
                sourceTargets[index].textContent = block.text;
              });
              status(`英中全文已加载，共 ${blocks.length} 段。两列按段同步滚动；中文为机器初译。`);
            } catch (error) {
              status(`中文全文已加载；英文原文补充失败：${error.message || error}。可切换 PDF 对照。`);
            }
          }
          await metadataPromise;
          return;
        }
      }
    } catch (error) {
      console.warn('Could not load nightly translation', error);
    }
    const paper = await metadataPromise;
    if (paper?.content_zh) {
      blocks = [{ type: 'heading', text: 'Abstract' }, { type: 'paragraph', text: paper.content || '' }];
      translatedBlocks.set(0, '摘要');
      translatedBlocks.set(1, paper.content_zh);
      ensureTargets();
      status('中文摘要已加载，正在读取论文正文…');
    }
    let htmlAvailable = false;
    try {
      const response = await fetch(htmlUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      blocks = extractBlocks(await response.text());
      if (!blocks.length) throw new Error('HTML 中没有可提取的正文');
      resetTargets();
      htmlAvailable = true;
      status(`尚无夜间预译，已读取 HTML 正文 ${blocks.length} 段。可先按 4 段翻译；首次使用浏览器模型需下载语言包。`);
    } catch (error) {
      if (paper?.content) {
        blocks = [{ type: 'heading', text: 'Abstract' }, { type: 'paragraph', text: paper.content }];
        resetTargets();
        status(paper.content_zh
          ? '这篇论文的 HTML 正文不可用，目前可阅读中文摘要。英文 PDF 仍可阅读。'
          : '这篇论文的 HTML 正文不可用，目前只能翻译摘要。英文 PDF 仍可阅读。');
      } else {
        status('无法获取 HTML 正文或摘要。请使用上方链接打开 arXiv 原页。');
        translateButton.disabled = true;
      }
    }
    if (paper?.content_zh && blocks[0]?.text === 'Abstract') {
      translatedBlocks.set(0, '摘要');
      translatedBlocks.set(1, paper.content_zh);
      ensureTargets();
      if (htmlAvailable) {
        status(`中文摘要已加载。正文可每次翻译 ${batchSize} 段，已译内容会保存在本机。`);
      } else {
        translateButton.hidden = true;
        translateAllButton.hidden = true;
      }
    }
    if (titleEl.textContent === '正在加载论文…') titleEl.textContent = `arXiv ${id}`;
  }

  async function translateNext(limit) {
    if (translating || !blocks.length) return;
    translating = true;
    translateButton.disabled = true;
    translateAllButton.disabled = true;
    translateButton.textContent = '翻译中…';
    ensureTargets();
    const next = blocks.map((_, index) => index)
      .filter((index) => !translatedBlocks.has(index))
      .slice(0, limit);
    try {
      for (const i of next) {
        status(`正在翻译 ${i + 1} / ${blocks.length} 段…`);
        const translated = await ScholarTranslator.translate(blocks[i].text, status);
        translatedBlocks.set(i, translated);
        updateTranslation(i, translated);
      }
      if (translatedBlocks.size === blocks.length) {
        status(`翻译完成，共 ${blocks.length} 段。请对照原文核查专业术语和公式。`);
        translateButton.textContent = '翻译完成';
        translateAllButton.textContent = '翻译完成';
      } else {
        status(`已翻译 ${translatedBlocks.size} / ${blocks.length} 段。可继续翻译后续内容。`);
        translateButton.textContent = `继续翻译 ${Math.min(batchSize, blocks.length - translatedBlocks.size)} 段`;
        translateButton.disabled = false;
        translateAllButton.disabled = false;
      }
    } catch (error) {
      status(`翻译中断：${error.message || error}。可点击按钮重试。`);
      translateButton.textContent = '重新翻译';
      translateButton.disabled = false;
      translateAllButton.disabled = false;
    } finally {
      translating = false;
    }
  }

  translateButton.addEventListener('click', () => translateNext(batchSize));
  translateAllButton.addEventListener('click', () => translateNext(Infinity));

  loadPaper();
})();
