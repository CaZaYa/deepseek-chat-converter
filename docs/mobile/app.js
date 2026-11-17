import {
  filterConversations, parseDeepSeek, writeChatbox, writeChatgpt,
  writeCherryMobile, writeChatboxMobile, writeJsonl, writeMarkdown,
} from './converter.js';

const $ = (id) => document.getElementById(id);
const sourceInput = $('source');
const templateInput = $('template');
const formatSelect = $('format');
const filterInput = $('filter');
const thinkingInput = $('thinking');
const runButton = $('run');
const statusEl = $('status');
const downloadEl = $('download');
const templateField = $('template-field');

let sqlitePromise = null;

function setStatus(text) {
  statusEl.textContent = text;
}

function loadSqlite() {
  if (!sqlitePromise) {
    sqlitePromise = import('./vendor/sqlite3.mjs').then(async (mod) => {
      const init = mod.default || mod;
      return init({ locateFile: (file) => `vendor/${file}` });
    });
  }
  return sqlitePromise;
}

formatSelect.addEventListener('change', () => {
  templateField.hidden = formatSelect.value !== 'cherry-mobile';
});
templateField.hidden = formatSelect.value !== 'cherry-mobile';

runButton.addEventListener('click', async () => {
  const file = sourceInput.files?.[0];
  if (!file) {
    setStatus('请先选择 DeepSeek 导出的 zip');
    return;
  }

  runButton.disabled = true;
  downloadEl.hidden = true;
  setStatus('正在读取导出包…');

  try {
    const buffer = await file.arrayBuffer();
    const thinking = thinkingInput.checked;
    const conversations = await parseDeepSeek(buffer, thinking, window.JSZip);
    const selected = filterConversations(conversations, filterInput.value);
    if (!selected.length) throw new Error('没有匹配的会话，请检查筛选关键词');
    setStatus(`已读取 ${selected.length} 个会话，正在转换…`);

    const format = formatSelect.value;
    let result;
    if (format === 'cherry-mobile') {
      const templateFile = templateInput.files?.[0];
      if (!templateFile) throw new Error('Cherry 手机端格式需要先选择手机导出的备份作为模板');
      const templateBuffer = await templateFile.arrayBuffer();
      setStatus('正在加载 SQLite 引擎…');
      const sqlite3 = await loadSqlite();
      result = await writeCherryMobile(selected, templateBuffer, window.JSZip, sqlite3);
    } else if (format === 'chatbox') {
      result = await writeChatbox(selected, thinking, window.JSZip);
    } else if (format === 'chatbox-mobile') {
      result = await writeChatboxMobile(selected, thinking);
    } else if (format === 'markdown') {
      result = await writeMarkdown(selected, thinking, window.JSZip);
    } else if (format === 'chatgpt') {
      result = await writeChatgpt(selected, thinking, window.JSZip);
    } else if (format === 'jsonl') {
      result = await writeJsonl(selected, thinking);
    } else {
      throw new Error('未知格式');
    }

    const type = result.filename.endsWith('.json') ? 'application/json'
      : result.filename.endsWith('.jsonl') ? 'application/jsonl'
      : 'application/zip';
    const blob = new Blob([result.bytes], { type });
    const url = URL.createObjectURL(blob);
    downloadEl.href = url;
    downloadEl.download = result.filename;
    downloadEl.hidden = false;

    // 尝试直接触发下载（部分手机浏览器会拦截，改成手动点链接）
    try {
      downloadEl.click();
    } catch (_) { /* ignore */ }

    setStatus(`完成：${result.filename}（${(blob.size / 1024).toFixed(0)} KB）。若没有自动下载，点下面的链接。`);
  } catch (error) {
    setStatus('失败：' + (error?.message || error));
  } finally {
    runButton.disabled = false;
  }
});
