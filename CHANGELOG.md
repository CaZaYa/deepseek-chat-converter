# Changelog

## 1.1.3

- 修复 Chatbox 手机端 JSON 里 AI 消息的 `status` 字段类型（必须是数组），避免导入后 AI 回答显示 “Something went wrong”
- 补齐 Chatbox 手机端消息的 `wordCount` / `tokenCount` / `finishReason` 字段

## 1.1.2

- 手机网页版：会话标题勾选、搜索筛选、按批次导出
- 修复 Cherry 手机端备份恢复提示“备份已损坏或格式无效”（ZIP 中多余的目录条目）
- 修复大导出包写入手机端数据库时出现 `SQLITE_FULL`
- Windows 构建禁用 UPX，并附带 SHA-256 校验文件，减少杀毒软件误报

## 1.1.0

- 新增 `cherry-mobile` 输出：生成 Cherry Studio 手机端可恢复的备份包（需手机导出的备份作为模板）
- 新增 `--select` / 界面「只导出标题包含」：只导出指定会话，方便部分迁移
- 修复若干细节

## 1.0.0

- 支持 DeepSeek 导出包转换为 Markdown 文集、JSONL、ChatGPT JSON
- 新增 Chatbox 备份包（V3）导出，已实测可导入
- 保留思考过程（Markdown、JSONL、ChatGPT、Chatbox reasoning 均支持）
- 提供图形界面与命令行，可打包为独立 exe
- 附带虚构示例数据，便于验证导入流程
