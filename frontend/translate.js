/* Browser-local translation. No text or secret is sent to this site. */
window.ScholarTranslator = (() => {
  let sessionPromise;
  let databasePromise;
  const memory = new Map();

  function withTimeout(promise, milliseconds, message) {
    let timer;
    return Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(message)), milliseconds);
      }),
    ]).finally(() => clearTimeout(timer));
  }

  function database() {
    if (!('indexedDB' in self)) return Promise.resolve(null);
    if (!databasePromise) {
      databasePromise = new Promise((resolve) => {
        try {
          const request = indexedDB.open('scholar-tide-translations', 1);
          request.onupgradeneeded = () => request.result.createObjectStore('en-zh');
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => resolve(null);
          request.onblocked = () => resolve(null);
        } catch (error) {
          resolve(null);
        }
      });
    }
    return databasePromise;
  }

  async function cached(text) {
    if (memory.has(text)) return memory.get(text);
    const db = await database();
    if (!db) return null;
    return new Promise((resolve) => {
      try {
        const request = db.transaction('en-zh', 'readonly').objectStore('en-zh').get(text);
        request.onsuccess = () => {
          if (typeof request.result === 'string') memory.set(text, request.result);
          resolve(request.result || null);
        };
        request.onerror = () => resolve(null);
      } catch (error) {
        resolve(null);
      }
    });
  }

  async function remember(text, translated) {
    memory.set(text, translated);
    const db = await database();
    if (!db) return;
    try {
      db.transaction('en-zh', 'readwrite').objectStore('en-zh').put(translated, text);
    } catch (error) {
      console.warn('Translation cache is unavailable', error);
    }
  }

  function session(onProgress = () => {}) {
    if (!sessionPromise) {
      sessionPromise = (async () => {
        if (!('Translator' in self)) {
          throw new Error('当前浏览器不支持本地翻译。请使用桌面版 Chrome 138 或更新版本。');
        }
        const options = { sourceLanguage: 'en', targetLanguage: 'zh' };
        onProgress('正在检查浏览器翻译模型…');
        const availability = await withTimeout(
          Translator.availability(options), 15000, '检查浏览器翻译模型超时。请稍后重试，或等待夜间预译。'
        );
        if (availability === 'unavailable') {
          throw new Error('当前设备暂不支持英译中语言包。');
        }
        onProgress('正在准备浏览器翻译模型，首次使用可能需要下载语言包…');
        return withTimeout(Translator.create({
          ...options,
          monitor(monitor) {
            monitor.addEventListener('downloadprogress', (event) => {
              onProgress(`正在下载浏览器语言包 ${Math.round(event.loaded * 100)}%…`);
            });
          },
        }), 60000, '浏览器语言包准备超过 60 秒。请稍后重试，或等待夜间预译。');
      })().catch((error) => {
        sessionPromise = undefined;
        throw error;
      });
    }
    return sessionPromise;
  }

  async function translate(text, onProgress) {
    if (!text) return '';
    const previous = await cached(text);
    if (previous) return previous;
    const translator = await session(onProgress);
    // Most abstracts fit in one request; larger passages are split for stability.
    const chunks = text.match(/[\s\S]{1,3000}/g) || [];
    const output = [];
    for (const chunk of chunks) {
      output.push(await withTimeout(
        translator.translate(chunk), 30000, '单段翻译超过 30 秒。可重试，或等待夜间预译。'
      ));
    }
    const translated = output.join('');
    await remember(text, translated);
    return translated;
  }

  return { translate };
})();
