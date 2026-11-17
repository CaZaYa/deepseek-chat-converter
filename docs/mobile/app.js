import {
  filterConversations, filterEntries, openDeepSeek, parseDeepSeek, writeChatbox,
  writeChatgpt, writeCherryMobileFromZip, writeChatboxMobile, writeJsonl, writeMarkdown,
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
    const format = formatSelect.value;
    let result;

    if (format === 'cherry-mobile') {
      // 手机端格式逐条读取、逐条写入数据库，避免整包聊天记录同时占满手机内存。
      const templateFile = templateInput.files?.[0];
      if (!templateFile) throw new Error('Cherry 手机端格式需要先选择手机导出的备份作为模板');
      const { zip, index } = await openDeepSeek(buffer, window.JSZip);
      const entries = filterEntries(index, filterInput.value);
      if (!entries.length) {
        throw new Error(index.length
          ? `筛选后没有会话：导出包共 ${index.length} 个，但没有标题包含“${filterInput.value.trim()}”的。请清空筛选或换个标题关键词。`
          : '这个导出包里没有会话');
      }
      setStatus(`已匹配 ${entries.length} 个会话，正在准备转换…`);
      const templateBuffer = await templateFile.arrayBuffer();
      setStatus('正在加载 SQLite 引擎…');
      const sqlite3 = await loadSqlite();
      result = await writeCherryMobileFromZip(
        zip, entries, thinking, templateBuffer, window.JSZip, sqlite3,
        (done, total) => setStatus(`正在写入数据库… ${done}/${total} 个会话`),
      );
    } else {
      const conversations = await parseDeepSeek(buffer, thinking, window.JSZip);
      const selected = filterConversations(conversations, filterInput.value);
      if (!selected.length) {
        throw new Error(conversations.length
          ? `筛选后没有会话：导出包共 ${conversations.length} 个，但没有标题包含“${filterInput.value.trim()}”的。请清空筛选或换个标题关键词。`
          : '这个导出包里没有会话');
      }
      setStatus(`已读取 ${selected.length} 个会话，正在转换…`);
      if (format === 'chatbox') {
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
