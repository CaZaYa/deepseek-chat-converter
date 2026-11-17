"""生成 Cherry Studio 手机端（Android/iOS 0.3.x）可恢复的备份包。

手机端备份是一个 ZIP：manifest.json + database/cherry.db + avatars/...
本模块以用户手机上导出的备份作为模板，保留其智能体、模型配置与头像，
只替换其中的会话和消息。恢复会覆盖手机本地数据，使用前请先在手机上备份。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from pathlib import Path

from .core import ConversionError, _active_path


def _stable_uuid(*parts) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "deepseek2any-mobile:" + ":".join(str(p) for p in parts)))


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    for info in archive.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts or (len(name) > 1 and name[1] == ":"):
            raise ConversionError(f"模板包含不安全的路径：{name}")
        archive.extract(info, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_cherry_mobile(conversations, out_dir: Path, template_path: str, stamp: str) -> tuple[int, int]:
    template = Path(template_path)
    if not template.is_file():
        raise ConversionError("请先选择手机端导出的 cherry-mobile 备份作为模板。")

    try:
        archive = zipfile.ZipFile(template)
    except zipfile.BadZipFile as error:
        raise ConversionError("模板不是有效的 ZIP 备份。") from error

    with archive:
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except KeyError as error:
            raise ConversionError("模板缺少 manifest.json，不是 Cherry 手机端备份。") from error
        if manifest.get("product") != "cherry-mobile":
            raise ConversionError("模板不是 Cherry Studio 手机端备份（product 不是 cherry-mobile）。")

        work = Path(tempfile.mkdtemp(prefix="dsc2any-mobile-"))
        try:
            _safe_extract(archive, work)
            db_path = work / "database" / "cherry.db"
            if not db_path.is_file():
                raise ConversionError("模板缺少 database/cherry.db。")

            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys = ON")
            cur = conn.cursor()

            agent = cur.execute("SELECT id FROM agent WHERE deleted_at IS NULL LIMIT 1").fetchone()
            if not agent:
                raise ConversionError("模板里没有可用的智能体，请先在手机上创建一个智能体并重新备份。")
            agent_id = agent[0]

            model_row = cur.execute("SELECT id FROM user_model WHERE id LIKE 'deepseek::%' LIMIT 1").fetchone()
            if not model_row:
                model_row = cur.execute("SELECT id FROM user_model LIMIT 1").fetchone()
            model_id = model_row[0] if model_row else None

            imported_sessions = imported_messages = 0
            for conversation in conversations:
                messages = _active_path(conversation)
                if not messages:
                    continue

                session_id = _stable_uuid(conversation.id, "session")
                cur.execute("DELETE FROM agent_session_message WHERE session_id = ?", (session_id,))
                cur.execute("DELETE FROM agent_session WHERE id = ?", (session_id,))
                created = (conversation.created or conversation.updated) * 1000
                updated = (conversation.updated or conversation.created) * 1000

                cur.execute(
                    "INSERT INTO agent_session (id, agent_id, name, is_name_manually_edited, "
                    "last_activity_at, created_at, updated_at, runtime_revision) "
                    "VALUES (?, ?, ?, 0, ?, ?, ?, 0)",
                    (session_id, agent_id, conversation.title, updated, created, updated),
                )

                for message in messages:
                    message_row_id = _stable_uuid(conversation.id, message.id)
                    parts = []
                    if message.reasoning:
                        parts.append({
                            "id": f"{message_row_id}:part-{len(parts)}",
                            "type": "reasoning",
                            "text": message.reasoning,
                            "state": "done",
                        })
                    if message.text:
                        parts.append({
                            "id": f"{message_row_id}:part-{len(parts)}",
                            "type": "text",
                            "text": message.text,
                            "state": "done",
                        })
                    if not parts:
                        continue
                    timestamp = (message.created or conversation.updated or conversation.created) * 1000
                    searchable = "\n".join(
                        part["text"] for part in parts if part.get("text")
                    )
                    cur.execute(
                        "INSERT INTO agent_session_message "
                        "(id, session_id, role, data, status, model_id, searchable_text, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, 'success', ?, ?, ?, ?)",
                        (
                            message_row_id,
                            session_id,
                            message.role,
                            json.dumps({"parts": parts}, ensure_ascii=False),
                            model_id if message.role == "assistant" else None,
                            searchable,
                            timestamp,
                            timestamp,
                        ),
                    )
                    imported_messages += 1
                imported_sessions += 1

            conn.commit()
            integrity = cur.execute("PRAGMA integrity_check").fetchone()
            if integrity and integrity[0] != "ok":
                raise ConversionError(f"生成的数据库校验失败：{integrity[0]}")
            total_sessions = cur.execute("SELECT COUNT(*) FROM agent_session").fetchone()[0]
            total_messages = cur.execute("SELECT COUNT(*) FROM agent_session_message").fetchone()[0]
            conn.execute("VACUUM")
            conn.close()

            for entry in manifest.get("entries", []):
                path = work / entry["path"]
                if path.is_file():
                    entry["size"] = path.stat().st_size
                    entry["sha256"] = _sha256(path)

            counts = manifest.setdefault("counts", {})
            counts["sessions"] = total_sessions
            counts["messages"] = total_messages
            counts["files"] = 0
            counts["pluginConnections"] = 0

            (work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

            out_dir.mkdir(parents=True, exist_ok=True)
            output = out_dir / f"cherry-mobile-{stamp}.zip"
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
                for path in work.rglob("*"):
                    if path.is_file():
                        target.write(path, path.relative_to(work).as_posix())

            return imported_sessions, imported_messages
        finally:
            shutil.rmtree(work, ignore_errors=True)
