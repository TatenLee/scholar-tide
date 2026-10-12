(() => {
  'use strict';
  window.ScholarStudy = {
    render(study) {
      if (!study?.overview) return null;
      const details = document.createElement('details');
      details.className = 'study-note';
      const summary = document.createElement('summary');
      summary.textContent = `AI 学习笔记 · ${study.basis === 'full_text' ? '基于全文文本' : '仅基于摘要'}`;
      const overview = document.createElement('p');
      overview.textContent = study.overview;
      details.append(summary, overview);
      const labels = { problem: '研究问题', method: '核心方法', evidence: '实验与结论', limitations: '局限与待核查', learning: '接下来学什么' };
      for (const [key, label] of Object.entries(labels)) {
        const heading = document.createElement('h3');
        heading.textContent = label;
        const paragraph = document.createElement('p');
        paragraph.textContent = Array.isArray(study[key]) ? study[key].join('\n') : study[key] || '材料未提供';
        details.append(heading, paragraph);
      }
      const meta = document.createElement('small');
      meta.textContent = `${study.model || '大模型'} 生成 · 请结合原文核查，全文文本不包含图片内容。`;
      details.append(meta);
      return details;
    },
  };
})();
