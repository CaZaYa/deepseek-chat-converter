"""DeepSeek 导出包 → 通用聊天记录格式（Markdown / JSONL / ChatGPT JSON）。"""

from __future__ import annotations

import datetime
import json
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "DeepSeek2Any"
APP_VERSION = "1.1.0"
PROJECT_URL = "https://github.com/CaZaYa/deepseek-chat-converter"

TEXT_FRAGMENTS = {"REQUEST", "RESPONSE", "TEMPLATE_RESPONSE"}

FORMATS = (
    ("markdown", "Markdown 文集（每个会话一个 .md，通用）"),
    ("jsonl", "JSONL（每行一条消息，方便脚本处理）"),
    ("chatgpt", "ChatGPT JSON（Cherry Studio 等支持该格式的工具）"),
    ("chatbox", "Chatbox 备份包（V3 格式）"),
    ("cherry-mobile", "Cherry 手机端备份（需模板）"),
)


class ConversionError(Exception):
    pass


@dataclass
class Message:
    id: str
    parent: str | None
    role: str
    text: str
    created: int
    reasoning: str = ""


@dataclass
class Conversation:
    id: str
    title: str
    created: int
    updated: int
    current: str | None
    messages: list[Message] = field(default_factory=list)


@dataclass
class Options:
    with_thinking: bool = False
    chunk_size: int = 200
    template: str | None = None
    select: tuple[str, ...] = ()


@dataclass
class Report:
    conversations: int = 0
    messages: int = 0
    files: int = 0
    output_dir: Path | None = None


def parse_ts(value) -> int:
    if not value:
        return 0
    try:
        return int(datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


def safe_name(text: str | None, limit: int = 60) -> str:
    text = (text or "未命名").strip()
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", text).strip(" .")
    return (text[:limit] or "未命名").rstrip(" .")


def run_directory(base: str | Path, name: str | None = None) -> Path:
    """每次转换单独一个子目录：用户指定名字，或按时间自动命名，避免覆盖上次结果。"""
    base = Path(base)
    folder = (name or "").strip() or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = base / safe_name(folder, 60)
    counter = 2
    while target.exists():
        target = base / f"{safe_name(folder, 60)}-{counter}"
        counter += 1
    target.mkdir(parents=True, exist_ok=True)
    return target


class Reader:
    """读取 DeepSeek 导出包，产出规范化的会话对象。"""

    def __init__(self, zip_path: str | Path, options: Options | None = None):
        self.zip_path = Path(zip_path)
        self.options = options or Options()
        if not self.zip_path.is_file():
            raise ConversionError(f"找不到导出包：{self.zip_path}")
        try:
            self.archive = zipfile.ZipFile(self.zip_path)
        except zipfile.BadZipFile as error:
            raise ConversionError("不是有效的 ZIP 导出包。") from error
        self.names = set(self.archive.namelist())
        if "chat_session_index.json" not in self.names:
            raise ConversionError("这不是 DeepSeek 导出的数据包（缺少 chat_session_index.json）。")
        self.index = self._load_index()

    def _load_index(self) -> list[dict]:
        entries = json.loads(self.archive.read("chat_session_index.json"))
        available = {
            name[len("chat_sessions/"):-len(".json")]
            for name in self.names
            if name.startswith("chat_sessions/") and name.endswith(".json")
        }
        entries = [entry for entry in entries if entry.get("id") in available]
        entries.sort(key=lambda entry: entry.get("updated_at") or "", reverse=True)
        return entries

    def conversations(self):
        for entry in self.index:
            session = json.loads(self.archive.read(f"chat_sessions/{entry['id']}.json"))
            messages = []
            for raw in session.get("messages") or []:
                texts, reasons = [], []
                for fragment in raw.get("fragments") or []:
                    kind, content = fragment.get("type"), fragment.get("content")
                    if kind in TEXT_FRAGMENTS and content:
                        texts.append(content.strip())
                    elif kind == "THINK" and self.options.with_thinking and content:
                        reasons.append(content.strip())
                    elif kind == "FILE":
                        for info in fragment.get("files") or []:
                            label = "图片" if info.get("is_image") else "附件"
                            texts.append(f"[{label}：{info.get('file_name') or '附件'}]")
                messages.append(
                    Message(
                        id=str(raw.get("id")),
                        parent=str(raw.get("parent_id")) if raw.get("parent_id") is not None else None,
                        role="user" if raw.get("role") == "USER" else "assistant",
                        text="\n\n".join(part for part in texts if part),
                        created=parse_ts(raw.get("inserted_at")),
                        reasoning="\n\n".join(part for part in reasons if part),
                    )
                )
            yield Conversation(
                id=session.get("id") or entry["id"],
                title=session.get("title") or entry.get("title") or "未命名对话",
                created=parse_ts(session.get("inserted_at")),
                updated=parse_ts(session.get("updated_at")),
                current=str(session.get("current_message_id")) if session.get("current_message_id") is not None else None,
                messages=messages,
            )


# ---------------- 输出 ----------------
def _with_reason(message: Message) -> str:
    """把思考过程和正文合成一段纯文本（用于只能存文本的格式）。"""
    chunks = []
    if message.reasoning:
        chunks.append("**思考过程**\n\n" + message.reasoning)
    if message.text:
        chunks.append(message.text)
    return "\n\n".join(chunks)


def to_chatgpt(conversation: Conversation) -> dict:
    mapping = {}
    for message in conversation.messages:
        mapping[message.id] = {
            "id": message.id,
            "message": {
                "id": message.id,
                "author": {"role": message.role},
                "create_time": message.created,
                "content": {"content_type": "text", "parts": ([_with_reason(message)] if _with_reason(message) else [])},
                "status": "finished_successfully",
                "recipient": "all",
            },
            "parent": message.parent,
            "children": [],
        }
    for message in conversation.messages:
        if message.parent and message.parent in mapping:
            mapping[message.parent]["children"].append(message.id)
    current = conversation.current if conversation.current in mapping else (
        conversation.messages[-1].id if conversation.messages else None
    )
    return {
        "title": conversation.title,
        "create_time": conversation.created,
        "update_time": conversation.updated,
        "mapping": mapping,
        "current_node": current,
        "conversation_id": conversation.id,
        "id": conversation.id,
        "is_archived": False,
    }


def to_markdown(conversation: Conversation, index: int) -> str:
    lines = [f"# {conversation.title}", ""]
    if conversation.updated:
        stamp = datetime.datetime.fromtimestamp(conversation.updated).strftime("%Y-%m-%d %H:%M")
        lines += [f"> 导出时间：{stamp}", ""]
    for message in conversation.messages:
        if not message.text and not message.reasoning:
            continue
        lines += ["## 用户" if message.role == "user" else "## 助手", ""]
        if message.reasoning:
            lines += ["**思考过程**", "", message.reasoning, ""]
        if message.text:
            lines += [message.text, ""]
    return "\n".join(lines)


def write_markdown(conversations, out_dir: Path, name_fn) -> int:
    folder = out_dir / "markdown"
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for index, conversation in enumerate(conversations, start=1):
        text = to_markdown(conversation, index)
        path = folder / name_fn(index, conversation.title)
        path.write_text(text, encoding="utf-8")
        count += 1
    return count


def write_jsonl(conversations, out_dir: Path) -> int:
    path = out_dir / "conversations.jsonl"
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for conversation in conversations:
            for message in conversation.messages:
                if not message.text:
                    continue
                record = {
                    "conversation_id": conversation.id,
                    "title": conversation.title,
                    "message_id": message.id,
                    "role": message.role,
                    "content": message.text,
                    "reasoning": message.reasoning,
                    "created": message.created,
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
    return count


def write_chatgpt(conversations, out_dir: Path, chunk_size: int) -> int:
    chunk, chunk_no, files = [], 1, 0

    def flush():
        nonlocal chunk, chunk_no, files
        if not chunk:
            return
        name = f"conversations-{chunk_no}.json" if chunk_size > 0 else "conversations.json"
        (out_dir / name).write_text(
            json.dumps(chunk, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        files += 1
        chunk, chunk_no = [], chunk_no + 1

    for conversation in conversations:
        if not any(message.text for message in conversation.messages):
            continue
        chunk.append(to_chatgpt(conversation))
        if chunk_size > 0 and len(chunk) >= chunk_size:
            flush()
    flush()
    return files


def _stable_uuid(*parts) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "deepseek2any:" + ":".join(str(part) for part in parts)))


def _active_path(conversation: Conversation) -> list[Message]:
    """沿当前活跃分支从根走到最新一条，丢弃被重新生成掉的分支。"""
    by_id = {message.id: message for message in conversation.messages}
    current = conversation.current if conversation.current in by_id else (
        conversation.messages[-1].id if conversation.messages else None
    )
    chain, seen = [], set()
    while current and current in by_id and current not in seen:
        seen.add(current)
        chain.append(by_id[current])
        current = by_id[current].parent
    chain.reverse()
    return [message for message in chain if message.text or message.reasoning]


def write_chatbox(conversations, out_dir: Path, stamp: str) -> tuple[int, int]:
    """生成 Chatbox V3 备份包，返回 (会话数, 消息数)。"""
    path = out_dir / f"chatbox-backup-{stamp}.zip"
    archive_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
    created = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    session_count = message_count = 0
    data_bytes = 0

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "format": "chatbox-backup",
            "formatVersion": 3,
            "layout": "rows",
            "archiveId": archive_id,
            "createdAt": created,
            "producer": "DeepSeek2Any",
            "selection": {"sessions": True, "settings": False, "copilots": False, "credentials": False},
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))

        for conversation in conversations:
            messages = _active_path(conversation)
            if not messages:
                continue

            session_id = _stable_uuid(conversation.id, "session")
            thread_id = session_id
            created_ms = (conversation.created or conversation.updated) * 1000
            updated_ms = (conversation.updated or conversation.created) * 1000
            ids = [_stable_uuid(conversation.id, message.id) for message in messages]

            rows = [
                {
                    "type": "session",
                    "session": {
                        "id": session_id,
                        "type": "chat",
                        "name": conversation.title,
                        "settings": {
                            "temperature": 0.7,
                            "provider": "deepseek",
                            "modelId": "deepseek-chat",
                            "maxContextMessageCount": 9007199254740991,
                            "topP": 1,
                        },
                        "activeThreadId": thread_id,
                    },
                    "meta": {"sortOrder": updated_ms or created_ms, "createdAt": created_ms},
                },
                {
                    "type": "thread",
                    "thread": {
                        "sessionId": session_id,
                        "threadId": thread_id,
                        "threadOrder": -1,
                        "name": "对话",
                        "createdAt": created_ms,
                        "rootMessageId": ids[0],
                        "compactionPoints": [],
                    },
                },
            ]

            for index, message in enumerate(messages):
                parts = []
                if message.reasoning:
                    parts.append({"type": "reasoning", "text": message.reasoning})
                if message.text:
                    parts.append({"type": "text", "text": message.text})
                timestamp = (message.created or conversation.updated or conversation.created) * 1000
                rows.append(
                    {
                        "type": "message",
                        "message": {
                            "sessionId": session_id,
                            "threadId": thread_id,
                            "messageId": ids[index],
                            "parentMessageId": ids[index - 1] if index else None,
                            "activeChildId": ids[index + 1] if index + 1 < len(ids) else None,
                            "siblingOrder": index,
                            "kind": "message",
                            "createdAt": timestamp,
                            "updatedAt": timestamp,
                            "branchId": None,
                            "message": {
                                "id": ids[index],
                                "role": message.role,
                                "contentParts": parts,
                                "timestamp": timestamp,
                                "wordCount": len(message.text),
                                "tokenCount": max(1, len(message.text) // 2),
                            },
                        },
                    }
                )

            payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n"
            archive.writestr(f"sessions/{session_id}.jsonl", payload)
            data_bytes += len(payload.encode("utf-8"))
            session_count += 1
            message_count += len(messages)

        archive.writestr("resources.jsonl", "")
        archive.writestr("warnings.jsonl", "")
        archive.writestr(
            "complete.json",
            json.dumps(
                {
                    "archiveId": archive_id,
                    "counts": {
                        "session": session_count,
                        "thread": session_count,
                        "message": message_count,
                        "global": 0,
                        "resource": 0,
                        "warning": 0,
                    },
                    "resourceBytes": 0,
                    "dataBytes": data_bytes,
                    "entryCount": 4 + session_count,
                    "uncompressedBytes": data_bytes,
                },
                ensure_ascii=False,
            ),
        )

    return session_count, message_count


def convert(zip_path, out_dir, fmt: str = "markdown", options: Options | None = None,
            log=None, progress=None) -> Report:
    options = options or Options()
    log = log or (lambda message: None)
    progress = progress or (lambda done, total: None)

    reader = Reader(zip_path, options)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 会话只遍历一次，但不同写出器需要重复使用，先收集到内存
    conversations = list(reader.conversations())
    if options.select:
        keywords = [item.lower() for item in options.select if item.strip()]
        conversations = [
            item for item in conversations
            if any(keyword in item.title.lower() for keyword in keywords)
        ]
    total = len(conversations)
    log(f"读取到 {total} 个会话")

    report = Report(conversations=total, output_dir=out_dir)

    if fmt == "chatgpt":
        report.files = write_chatgpt(conversations, out_dir, options.chunk_size)
        report.messages = sum(
            1 for conversation in conversations for message in conversation.messages if message.text
        )
    elif fmt == "jsonl":
        report.messages = write_jsonl(conversations, out_dir)
        report.files = 1
    elif fmt == "cherry-mobile":
        if not options.template:
            raise ConversionError("cherry-mobile 需要 --template 指定手机端导出的备份作为模板。")
        from .mobile import write_cherry_mobile

        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        session_count, message_count = write_cherry_mobile(
            conversations, out_dir, options.template, stamp
        )
        report.conversations = session_count
        report.files = 1
        report.messages = message_count
    elif fmt == "chatbox":
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
        _sessions, message_count = write_chatbox(conversations, out_dir, stamp)
        report.files = 1
        report.messages = message_count
    elif fmt == "markdown":
        def name_fn(index, title):
            return f"{index:04d}-{safe_name(title)}.md"

        report.files = write_markdown(conversations, out_dir, name_fn)
        report.messages = sum(
            1 for conversation in conversations for message in conversation.messages if message.text
        )
    else:
        raise ConversionError(f"未知的输出格式：{fmt}")

    progress(total, total)
    log(f"完成：{report.conversations} 个会话 / {report.messages} 条消息 / {report.files} 个文件")
    return report
