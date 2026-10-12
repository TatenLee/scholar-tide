(() => {
  'use strict';
  const form = document.getElementById('llmSettings');
  const fields = document.getElementById('settingsFields');
  const connection = document.getElementById('connectionStatus');
  const run = document.getElementById('runNow');
  let csrf = '';
  let busy = false;

  async function api(path, body) {
    const response = await fetch(`/api/local/${path}`, body === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Scholar-Token': csrf }, body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || '本地服务暂时不可用');
    }
    return response.json();
  }

  function tokenStatus(config) {
    document.getElementById('tokenState').textContent = config.has_token
      ? '已配置令牌。留空保留现有令牌；如需更换，请重新填写。'
      : '尚未配置令牌。本机无需认证的模型服务可以留空。';
  }

  function showStatus(status) {
    document.getElementById('jobStatus').textContent = status.message || '等待运行';
    run.disabled = busy || status.running;
    run.textContent = status.running ? '任务运行中…' : '保存并立即运行';
    const result = status.result;
    const time = status.finished_at ? `结束时间：${new Date(status.finished_at).toLocaleString('zh-CN', { timeZone: 'Asia/Hong_Kong' })}。` : '';
    document.getElementById('jobStats').textContent = time + (result
      ? `抓取 ${result.fetched} 条，完成 ${result.completed} 篇，复用 ${result.cached} 篇，失败 ${result.failed} 篇，待处理 ${result.remaining} 篇。模型调用 ${result.api_calls} 次，已报告用量 ${result.tokens} tokens。`
      : '完成的段落和笔记会保存在本地；中断后再次运行可继续。');
  }

  async function refresh(initial = false) {
    try {
      const data = await api('config');
      csrf = data.csrf_token;
      if (initial) {
        for (const [key, value] of Object.entries(data.config)) {
          const input = form.elements.namedItem(key);
          if (!input) continue;
          if (input.type === 'checkbox') input.checked = value;
          else input.value = value;
        }
        fields.disabled = false;
        connection.textContent = '已连接本地服务。定时任务采用香港时间（UTC+8）。';
      }
      tokenStatus(data.config);
      showStatus(data.status);
    } catch (error) {
      connection.textContent = '无法连接本地服务。请在项目目录运行 python -m engine local，再打开 http://127.0.0.1:8770/local-settings.html。';
      fields.disabled = true;
    }
  }

  async function save(start) {
    if (!form.reportValidity()) return;
    busy = true;
    fields.disabled = true;
    try {
      const payload = {};
      for (const input of form.querySelectorAll('input')) {
        payload[input.name] = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value.trim();
      }
      const data = await api('config', payload);
      form.elements.access_token.value = '';
      form.elements.clear_token.checked = false;
      tokenStatus(data.config);
      if (start) await api('run', {});
      connection.textContent = start ? '任务已提交，可以返回论文列表。' : '配置已保存。';
    } catch (error) {
      connection.textContent = error.message;
    } finally {
      busy = false;
      fields.disabled = false;
      await refresh();
    }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); save(false); });
  run.addEventListener('click', () => save(true));
  refresh(true);
  setInterval(() => { if (!busy) refresh(fields.disabled); }, 5000);
})();
