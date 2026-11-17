import {
  openDeepSeek, parseDeepSeekEntries, writeChatbox, writeChatgpt,
  writeCherryMobileFromZip, writeChatboxMobile, writeJsonl, writeMarkdown,
} from './converter.js?v=20261117e';

const $ = (id) => document.getElementById(id);
const sourceInput = $('source');
const templateInput = $('template');
const formatSelect = $('format');
const filterInput = $('filter');
const thinkingInput = $('thinking');
const batchInput = $('batch');
const batchNote = $('batch-note');
const runButton = $('run');
const statusEl = $('status');
const downloadsEl = $('downloads');
const templateField = $('template-field');
const templateModeField = $('template-mode-field');
const templateModeSelect = $('template-mode');
const picker = $('picker');
const pickerCount = $('picker-count');
const sessionList = $('session-list');

let sqlitePromise = null;
let source = null;          // { zip, index }
let selected = new Set();   // 勾选的会话 id
let loadToken = 0;
let downloadUrls = [];
let filterTimer = 0;

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

function entryTitle(entry) {
  return String(entry.title || '未命名对话');
}

function visibleEntries() {
  const keyword = filterInput.value.trim().toLowerCase();
  if (!keyword) return source.index;
  return source.index.filter((entry) => entryTitle(entry).toLowerCase().includes(keyword));
}

function updatePickerCount() {
  if (!source) {
    pickerCount.textContent = '会话列表';
    return;
  }
  const visible = visibleEntries().length;
  const suffix = visible === source.index.length ? '' : `，当前显示 ${visible} 个`;
  pickerCount.textContent = `已选 ${selected.size} / 共 ${source.index.length} 个${suffix}`;
}

function renderSessions() {
  if (!source) return;
  const entries = visibleEntries();
  const fragment = document.createDocumentFragment();
  for (const entry of entries) {
    const label = document.createElement('label');
    label.className = 'session-row';
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.dataset.id = String(entry.id);
    box.checked = selected.has(String(entry.id));
    const text = document.createElement('span');
    text.textContent = entryTitle(entry);
    label.append(box, text);
    fragment.append(label);
  }
  if (!entries.length) {
    const empty = document.createElement('p');
    empty.className = 'status';
    empty.textContent = '没有标题匹配的会话，换个关键词试试。';
    fragment.append(empty);
  }
  sessionList.replaceChildren(fragment);
  updatePickerCount();
}

async function loadSource() {
  const token = ++loadToken;
  const file = sourceInput.files?.[0];
  source = null;
  selected = new Set();
  picker.hidden = true;
  clearDownloads();
  if (!file) {
    setStatus('等待选择文件');
    return;
  }
  setStatus('正在读取导出包和会话标题…');
  try {
    const buffer = await file.arrayBuffer();
    const opened = await openDeepSeek(buffer, window.JSZip);
    if (token !== loadToken) return;
    source = opened;
    selected = new Set(opened.index.map((entry) => String(entry.id)));
    picker.hidden = false;
    renderSessions();
    setStatus(`已读取 ${opened.index.length} 个会话，默认全选。可搜索标题后点“只选当前”。`);
  } catch (error) {
    setStatus('失败：' + (error?.message || error));
  }
}

function updateBatchNote() {
  const size = Math.floor(Number(batchInput.value) || 0);
  if (size <= 0) {
    batchNote.hidden = true;
    return;
  }
  batchNote.hidden = false;
  batchNote.textContent = formatSelect.value === 'cherry-mobile'
    ? '注意：Cherry 手机端每次恢复都会替换手机里的全部数据，分批生成的是互不叠加的独立备份。要迁移全部勾选会话，请把分批设为 0。'
    : '每批会生成一个独立文件，可以在目标客户端分别导入。';
}

function clearDownloads() {
  for (const url of downloadUrls) URL.revokeObjectURL(url);
  downloadUrls = [];
  downloadsEl.replaceChildren();
}

function partName(filename, index, total) {
  if (total <= 1) return filename;
  const dot = filename.lastIndexOf('.');
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  const ext = dot > 0 ? filename.slice(dot) : '';
  return `${stem}-part${index + 1}${ext}`;
}

function chunk(items, size) {
  const chunks = [];
  for (let i = 0; i < items.length; i += size) chunks.push(items.slice(i, i + size));
  return chunks;
}

function renderDownloads(results) {
  downloadsEl.replaceChildren();
  for (const result of results) {
    const link = document.createElement('a');
    link.className = 'download';
    link.href = result.url;
    link.download = result.filename;
    link.textContent = `下载 ${result.filename}（${(result.size / 1024).toFixed(0)} KB）`;
    downloadsEl.append(link);
    result.link = link;
  }
}

function addDownload(result, results) {
  const type = result.filename.endsWith('.json') ? 'application/json'
    : result.filename.endsWith('.jsonl') ? 'application/jsonl'
    : 'application/zip';
  const blob = new Blob([result.bytes], { type });
  result.bytes = null;
  const url = URL.createObjectURL(blob);
  downloadUrls.push(url);
  const item = { filename: result.filename, size: blob.size, url };
  if (result.imported !== undefined) {
    item.imported = result.imported;
    item.sessions = result.sessions;
  }
  results.push(item);
  renderDownloads(results);
  return item;
}

async function convertEntries(entries, thinking, format, batchLabel) {
  if (format === 'cherry-mobile') {
    const templateFile = templateInput.files?.[0];
    if (!templateFile) throw new Error('Cherry 手机端格式需要先选择手机导出的备份作为模板');
    const templateBuffer = await templateFile.arrayBuffer();
    setStatus(`${batchLabel}正在加载 SQLite 引擎…`);
    const sqlite3 = await loadSqlite();
    return writeCherryMobileFromZip(
      source.zip, entries, thinking, templateBuffer, window.JSZip, sqlite3,
      {
        keepTemplate: templateModeSelect.value === 'keep',
        onProgress: (done, total) => setStatus(`${batchLabel}正在写入数据库… ${done}/${total} 个会话`),
      },
    );
  }

  setStatus(`${batchLabel}正在读取聊天记录…`);
  const conversations = await parseDeepSeekEntries(source.zip, entries, thinking);
  if (!conversations.length) throw new Error('勾选的会话里没有可导出的内容');
  setStatus(`${batchLabel}正在转换 ${conversations.length} 个会话…`);
  if (format === 'chatbox') return writeChatbox(conversations, thinking, window.JSZip);
  if (format === 'chatbox-mobile') return writeChatboxMobile(conversations, thinking);
  if (format === 'markdown') return writeMarkdown(conversations, thinking, window.JSZip);
  if (format === 'chatgpt') return writeChatgpt(conversations, thinking, window.JSZip);
  if (format === 'jsonl') return writeJsonl(conversations, thinking);
  throw new Error('未知格式');
}

function updateTemplateVisibility() {
  const isCherryMobile = formatSelect.value === 'cherry-mobile';
  templateField.hidden = !isCherryMobile;
  templateModeField.hidden = !isCherryMobile;
}

formatSelect.addEventListener('change', () => {
  updateTemplateVisibility();
  updateBatchNote();
});
updateTemplateVisibility();
batchInput.addEventListener('input', updateBatchNote);
updateBatchNote();

sourceInput.addEventListener('change', loadSource);

filterInput.addEventListener('input', () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(renderSessions, 150);
});

sessionList.addEventListener('change', (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== 'checkbox') return;
  const id = input.dataset.id;
  if (!id) return;
  if (input.checked) selected.add(id);
  else selected.delete(id);
  updatePickerCount();
});

$('select-all').addEventListener('click', () => {
  if (!source) return;
  selected = new Set(source.index.map((entry) => String(entry.id)));
  renderSessions();
});

$('select-visible').addEventListener('click', () => {
  if (!source) return;
  selected = new Set(visibleEntries().map((entry) => String(entry.id)));
  renderSessions();
});

$('select-none').addEventListener('click', () => {
  selected = new Set();
  renderSessions();
});

runButton.addEventListener('click', async () => {
  if (!source) {
    if (!sourceInput.files?.[0]) {
      setStatus('请先选择 DeepSeek 导出的 zip');
      return;
    }
    await loadSource();
    if (!source) return;
  }

  if (!selected.size) {
    setStatus('请至少勾选一个会话，或点“全选”。');
    return;
  }

  const entries = source.index.filter((entry) => selected.has(String(entry.id)));
  const batchSize = Math.max(0, Math.floor(Number(batchInput.value) || 0));
  const batches = batchSize > 0 ? chunk(entries, batchSize) : [entries];
  const thinking = thinkingInput.checked;
  const format = formatSelect.value;
  const formatName = formatSelect.options[formatSelect.selectedIndex]?.textContent || format;

  runButton.disabled = true;
  clearDownloads();
  const results = [];

  try {
    for (let index = 0; index < batches.length; index += 1) {
      const batchLabel = batches.length > 1 ? `第 ${index + 1}/${batches.length} 批：` : '';
      setStatus(`${batchLabel}共 ${batches[index].length} 个会话，正在转换…`);
      const result = await convertEntries(batches[index], thinking, format, batchLabel);
      result.filename = partName(result.filename, index, batches.length);
      addDownload(result, results);
      const countText = result.imported !== undefined
        ? (result.imported === result.sessions
          ? `${result.imported} 个会话`
          : `本批 ${result.imported} 个，模板已有 ${result.sessions - result.imported} 个，总计 ${result.sessions} 个会话`)
        : '';
      setStatus(`${batchLabel}已生成 ${result.filename}（${(results[index].size / 1024).toFixed(0)} KB${countText ? `，${countText}` : ''}）`);
    }

    if (results.length === 1) {
      const item = results[0];
      const countText = item.imported !== undefined
        ? (item.imported === item.sessions
          ? `，${item.imported} 个会话`
          : `，本批 ${item.imported} 个 + 模板已有 ${item.sessions - item.imported} 个 = ${item.sessions} 个会话`)
        : '';
      setStatus(`完成：${item.filename}（${(item.size / 1024).toFixed(0)} KB${countText}）。若没有自动下载，点下面的链接。`);
      try { item.link.click(); } catch (_) { /* ignore */ }
    } else {
      setStatus(`完成：共 ${results.length} 个文件（${formatName}）。手机浏览器通常不允许一次自动下载多个，请点下面的链接逐个保存。`);
    }
  } catch (error) {
    setStatus('失败：' + (error?.message || error));
  } finally {
    runButton.disabled = false;
  }
});
