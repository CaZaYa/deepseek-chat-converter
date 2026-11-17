/* DeepSeek 导出包 → 手机端可用格式（纯浏览器端处理，不上传任何数据） */

const encoder = new TextEncoder();

export function stableId(...parts) {
  let h1 = 1779033703, h2 = 3144134277, h3 = 1013904242, h4 = 2773480762;
  const str = 'deepseek2any-mobile:' + parts.join(':');
  for (let i = 0; i < str.length; i++) {
    const k = str.charCodeAt(i);
    h1 = h2 ^ Math.imul(h1 ^ k, 597399067);
    h2 = h3 ^ Math.imul(h2 ^ k, 2869860233);
    h3 = h4 ^ Math.imul(h3 ^ k, 951274213);
    h4 = h1 ^ Math.imul(h4 ^ k, 2716044179);
  }
  h1 = Math.imul(h3 ^ (h1 >>> 18), 597399067);
  h2 = Math.imul(h4 ^ (h2 >>> 22), 2869860233);
  h3 = Math.imul(h1 ^ (h3 >>> 17), 951274213);
  h4 = Math.imul(h2 ^ (h4 >>> 19), 2716044179);
  const hex = [(h1 ^ h2 ^ h3 ^ h4) >>> 0, (h2 ^ h1) >>> 0, (h3 ^ h1) >>> 0, (h4 ^ h1) >>> 0]
    .map((n) => n.toString(16).padStart(8, '0'))
    .join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}

export function stamp(date = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}`;
}

function ts(value) {
  const n = Date.parse(value || '');
  return Number.isFinite(n) ? n : 0;
}

export async function parseDeepSeek(buffer, includeThinking, JSZipLib) {
  const zip = await JSZipLib.loadAsync(buffer);
  const indexFile = zip.file('chat_session_index.json');
  if (!indexFile) throw new Error('这不是 DeepSeek 导出的数据包（缺少 chat_session_index.json）');
  const index = JSON.parse(await indexFile.async('string'));
  const conversations = [];

  for (const entry of index) {
    const file = zip.file(`chat_sessions/${entry.id}.json`);
    if (!file) continue;
    const data = JSON.parse(await file.async('string'));
    const messages = (data.messages || []).map((raw) => {
      const texts = [];
      const reasons = [];
      for (const fragment of raw.fragments || []) {
        if (['REQUEST', 'RESPONSE', 'TEMPLATE_RESPONSE'].includes(fragment.type) && fragment.content) {
          texts.push(fragment.content.trim());
        } else if (fragment.type === 'THINK' && includeThinking && fragment.content) {
          reasons.push(fragment.content.trim());
        } else if (fragment.type === 'FILE') {
          for (const info of fragment.files || []) {
            texts.push(`[${info.is_image ? '图片' : '附件'}：${info.file_name || '附件'}]`);
          }
        }
      }
      return {
        id: String(raw.id),
        parent: raw.parent_id == null ? null : String(raw.parent_id),
        role: raw.role === 'USER' ? 'user' : 'assistant',
        text: texts.join('\n\n'),
        reasoning: reasons.join('\n\n'),
        created: ts(raw.inserted_at),
      };
    });
    conversations.push({
      id: data.id || entry.id,
      title: data.title || entry.title || '未命名对话',
      created: ts(data.inserted_at),
      updated: ts(data.updated_at),
      current: data.current_message_id == null ? null : String(data.current_message_id),
      messages,
    });
  }
  return conversations;
}

export function filterConversations(conversations, keywords) {
  const list = String(keywords || '')
    .split(/[,，]/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
  if (!list.length) return conversations;
  return conversations.filter((c) => list.some((k) => c.title.toLowerCase().includes(k)));
}

export function activePath(conversation) {
  const byId = new Map(conversation.messages.map((m) => [m.id, m]));
  let current = conversation.current;
  if (!byId.has(current)) current = conversation.messages.at(-1)?.id;
  const chain = [];
  const seen = new Set();
  while (current && byId.has(current) && !seen.has(current)) {
    seen.add(current);
    const message = byId.get(current);
    chain.push(message);
    current = message.parent;
  }
  chain.reverse();
  return chain.filter((m) => m.text || m.reasoning);
}

function zipBlob(JSZipLib, files, compression = 'DEFLATE') {
  const zip = new JSZipLib();
  for (const file of files) zip.file(file.name, file.data);
  return zip.generateAsync({ type: 'uint8array', compression });
}

export async function writeChatbox(conversations, includeThinking, JSZipLib) {
  const archiveId = crypto.randomUUID();
  const createdAt = new Date().toISOString();
  const zip = new JSZipLib();
  let sessions = 0;
  let messages = 0;

  for (const conversation of conversations) {
    const path = activePath(conversation);
    if (!path.length) continue;
    const sessionId = stableId(conversation.id, 'session');
    const threadId = sessionId;
    const ids = path.map((m) => stableId(conversation.id, m.id));
    const createdAt = (conversation.created || conversation.updated) * 1000;
    const updatedAt = (conversation.updated || conversation.created) * 1000;
    const rows = [
      {
        type: 'session',
        session: {
          id: sessionId, type: 'chat', name: conversation.title,
          settings: { temperature: 0.7, provider: 'deepseek', modelId: 'deepseek-chat', maxContextMessageCount: 9007199254740991, topP: 1 },
          activeThreadId: threadId,
        },
        meta: { sortOrder: updatedAt || createdAt, createdAt },
      },
      {
        type: 'thread',
        thread: { sessionId, threadId, threadOrder: -1, name: '对话', createdAt, rootMessageId: ids[0], compactionPoints: [] },
      },
    ];
    path.forEach((message, index) => {
      const parts = [];
      if (message.reasoning) parts.push({ type: 'reasoning', text: message.reasoning });
      if (message.text) parts.push({ type: 'text', text: message.text });
      const time = (message.created || conversation.updated || conversation.created) * 1000;
      rows.push({
        type: 'message',
        message: {
          sessionId, threadId, messageId: ids[index],
          parentMessageId: index ? ids[index - 1] : null,
          activeChildId: index + 1 < ids.length ? ids[index + 1] : null,
          siblingOrder: index, kind: 'message', createdAt: time, updatedAt: time, branchId: null,
          message: {
            id: ids[index], role: message.role, contentParts: parts, timestamp: time,
            wordCount: message.text.length, tokenCount: Math.max(1, Math.floor(message.text.length / 2)),
          },
        },
      });
    });
    zip.file(`sessions/${sessionId}.jsonl`, rows.map((row) => JSON.stringify(row)).join('\n') + '\n');
    sessions += 1;
    messages += path.length;
  }

  const manifest = {
    format: 'chatbox-backup', formatVersion: 3, layout: 'rows', archiveId, createdAt,
    producer: 'DeepSeek2Any Web', selection: { sessions: true, settings: false, copilots: false, credentials: false },
  };
  zip.file('manifest.json', JSON.stringify(manifest));
  zip.file('resources.jsonl', '');
  zip.file('warnings.jsonl', '');
  zip.file('complete.json', JSON.stringify({
    archiveId,
    counts: { session: sessions, thread: sessions, message: messages, global: 0, resource: 0, warning: 0 },
    resourceBytes: 0, dataBytes: 0, entryCount: 4 + sessions, uncompressedBytes: 0,
  }));

  const bytes = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' });
  return { filename: `chatbox-backup-${stamp()}.zip`, bytes, sessions, messages };
}

export async function writeChatboxMobile(conversations, includeThinking) {
  const sessions = [];
  const payload = {
    configVersion: 13,
    __exported_items: ['conversations'],
    __exported_at: new Date().toISOString(),
    myCopilots: [],
    'chat-sessions-list': sessions,
  };
  for (const conversation of conversations) {
    const path = activePath(conversation);
    if (!path.length) continue;
    const sessionId = stableId(conversation.id, 'session');
    sessions.push({ id: sessionId, name: conversation.title, starred: false, type: 'chat' });
    const messages = [];
    for (const message of path) {
      const parts = [];
      if (message.reasoning) parts.push({ type: 'reasoning', text: message.reasoning });
      if (message.text) parts.push({ type: 'text', text: message.text });
      if (!parts.length) continue;
      const item = {
        id: stableId(conversation.id, message.id),
        role: message.role,
        contentParts: parts,
        content: message.text,
        timestamp: (message.created || conversation.updated || conversation.created) * 1000,
      };
      if (message.role === 'assistant') {
        Object.assign(item, { model: 'deepseek-chat', aiProvider: 'deepseek', status: 'finished', generating: false });
      }
      messages.push(item);
    }
    payload[`session:${sessionId}`] = {
      id: sessionId, name: conversation.title, type: 'chat', starred: false,
      settings: { provider: 'deepseek', modelId: 'deepseek-chat', temperature: 0.7 },
      messages,
    };
  }
  const bytes = encoder.encode(JSON.stringify(payload));
  return { filename: `chatbox-exported-data-${stamp().slice(0, 8)}.json`, bytes, sessions: sessions.length };
}

export async function writeChatgpt(conversations, includeThinking, JSZipLib) {
  const output = [];
  for (const conversation of conversations) {
    const mapping = {};
    const order = [];
    for (const message of conversation.messages) {
      const parts = [];
      if (message.reasoning) parts.push('**思考过程**\n\n' + message.reasoning);
      if (message.text) parts.push(message.text);
      const text = parts.join('\n\n');
      mapping[message.id] = {
        id: message.id,
        message: {
          id: message.id,
          author: { role: message.role },
          create_time: message.created,
          content: { content_type: 'text', parts: text ? [text] : [] },
          status: 'finished_successfully', recipient: 'all',
        },
        parent: message.parent,
        children: [],
      };
      if (text) order.push(message.id);
    }
    for (const message of conversation.messages) {
      if (message.parent && mapping[message.parent]) mapping[message.parent].children.push(message.id);
    }
    let current = conversation.current;
    if (!mapping[current]) current = conversation.messages.at(-1)?.id ?? null;
    output.push({
      title: conversation.title, create_time: conversation.created, update_time: conversation.updated,
      mapping, current_node: current, conversation_id: conversation.id, id: conversation.id, is_archived: false,
    });
  }
  const json = JSON.stringify(output);
  return { filename: 'conversations.json', bytes: encoder.encode(json), conversations: output.length };
}

export async function writeJsonl(conversations, includeThinking) {
  const lines = [];
  for (const conversation of conversations) {
    for (const message of conversation.messages) {
      if (!message.text && !message.reasoning) continue;
      lines.push(JSON.stringify({
        conversation_id: conversation.id, title: conversation.title, message_id: message.id,
        role: message.role, content: message.text, reasoning: message.reasoning, created: message.created,
      }));
    }
  }
  return { filename: 'conversations.jsonl', bytes: encoder.encode(lines.join('\n') + '\n'), messages: lines.length };
}

function safeName(text) {
  return String(text || '未命名').replace(/[\\/:*?"<>|\r\n\t]+/g, '_').slice(0, 60).trim() || '未命名';
}

export async function writeMarkdown(conversations, includeThinking, JSZipLib) {
  const zip = new JSZipLib();
  let count = 0;
  conversations.forEach((conversation, index) => {
    const lines = [`# ${conversation.title}`, ''];
    for (const message of conversation.messages) {
      if (!message.text && !message.reasoning) continue;
      lines.push(message.role === 'user' ? '## 用户' : '## 助手', '');
      if (message.reasoning) lines.push('**思考过程**', '', message.reasoning, '');
      if (message.text) lines.push(message.text, '');
    }
    if (lines.length > 2) {
      zip.file(`${String(index + 1).padStart(4, '0')}-${safeName(conversation.title)}.md`, lines.join('\n'));
      count += 1;
    }
  });
  const bytes = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' });
  return { filename: `deepseek-markdown-${stamp()}.zip`, bytes, files: count };
}

async function sha256(bytes) {
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function writeCherryMobile(conversations, templateBuffer, JSZipLib, sqlite3) {
  const template = await JSZipLib.loadAsync(templateBuffer);
  const manifestFile = template.file('manifest.json');
  const dbFile = template.file('database/cherry.db');
  if (!manifestFile || !dbFile) throw new Error('模板不是 Cherry 手机端备份（缺少 manifest.json 或 database/cherry.db）');
  const manifest = JSON.parse(await manifestFile.async('string'));
  if (manifest.product !== 'cherry-mobile') throw new Error('模板不是 Cherry 手机端备份（product 不是 cherry-mobile）');

  const dbBytes = await dbFile.async('uint8array');
  const ptr = sqlite3.wasm.allocFromTypedArray(dbBytes);
  const db = new sqlite3.oo1.DB();
  let rc = sqlite3.capi.sqlite3_deserialize(db.pointer, 'main', ptr, dbBytes.length, dbBytes.length, 0);
  if (rc) throw new Error('无法打开模板数据库：' + rc);

  try {
    const agentId = db.selectValue('SELECT id FROM agent WHERE deleted_at IS NULL LIMIT 1');
    if (!agentId) throw new Error('模板里没有可用的智能体，请先在手机上创建智能体并重新备份');
    const modelId = db.selectValue("SELECT id FROM user_model WHERE id LIKE 'deepseek::%' LIMIT 1")
      || db.selectValue('SELECT id FROM user_model LIMIT 1') || null;

    let imported = 0;
    db.exec('BEGIN');
    for (const conversation of conversations) {
      const path = activePath(conversation);
      if (!path.length) continue;
      const sessionId = stableId(conversation.id, 'session');
      db.exec({ sql: 'DELETE FROM agent_session_message WHERE session_id = ?', bind: [sessionId] });
      db.exec({ sql: 'DELETE FROM agent_session WHERE id = ?', bind: [sessionId] });
      const created = (conversation.created || conversation.updated) * 1000;
      const updated = (conversation.updated || conversation.created) * 1000;
      db.exec({
        sql: 'INSERT INTO agent_session (id, agent_id, name, is_name_manually_edited, last_activity_at, created_at, updated_at, runtime_revision) VALUES (?, ?, ?, 0, ?, ?, ?, 0)',
        bind: [sessionId, agentId, conversation.title, updated, created, updated],
      });
      for (const message of path) {
        const parts = [];
        if (message.reasoning) parts.push({ type: 'reasoning', text: message.reasoning });
        if (message.text) parts.push({ type: 'text', text: message.text });
        if (!parts.length) continue;
        const time = (message.created || conversation.updated || conversation.created) * 1000;
        db.exec({
          sql: 'INSERT INTO agent_session_message (id, session_id, role, data, status, model_id, searchable_text, created_at, updated_at) VALUES (?, ?, ?, ?, \'success\', ?, ?, ?, ?)',
          bind: [
            stableId(conversation.id, message.id), sessionId, message.role,
            JSON.stringify({ parts }), message.role === 'assistant' ? modelId : null,
            parts.map((p) => p.text).join('\n'), time, time,
          ],
        });
      }
      imported += 1;
    }
    db.exec('COMMIT');

    const totalSessions = db.selectValue('SELECT COUNT(*) FROM agent_session');
    const totalMessages = db.selectValue('SELECT COUNT(*) FROM agent_session_message');
    const result = sqlite3.capi.sqlite3_js_db_export(db.pointer);

    manifest.counts = { sessions: totalSessions, messages: totalMessages, files: 0, pluginConnections: 0 };
    for (const entry of manifest.entries || []) {
      if (entry.path === 'database/cherry.db') {
        entry.size = result.length;
        entry.sha256 = await sha256(result);
      }
    }

    const zip = new JSZipLib();
    zip.file('manifest.json', JSON.stringify(manifest));
    zip.file('database/cherry.db', result);
    for (const name of Object.keys(template.files)) {
      if (name.startsWith('avatars/') && !template.files[name].dir) {
        zip.file(name, await template.files[name].async('uint8array'));
      }
    }
    const bytes = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' });
    return { filename: `cherry-mobile-${stamp()}.zip`, bytes, sessions: imported, messages: totalMessages };
  } finally {
    db.close();
  }
}
