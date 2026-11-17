# Changelog

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
