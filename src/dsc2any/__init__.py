"""DeepSeek2Any：DeepSeek 导出包 → Markdown / JSONL / ChatGPT JSON。"""

from .core import APP_NAME, APP_VERSION, FORMATS, ConversionError, Options, Report, convert

__all__ = ["APP_NAME", "APP_VERSION", "FORMATS", "ConversionError", "Options", "Report", "convert"]
