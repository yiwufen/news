"""
统一日志配置模块。

提供项目级别的日志配置，支持：
- 控制台输出（带颜色）
- 文件输出（可选）
- 模块级别日志器
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


# 日志格式
DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DETAILED_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

# 颜色代码（ANSI）
COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m",      # Reset
}


class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器。"""

    def format(self, record: logging.LogRecord) -> str:
        # 保存原始值，避免污染其他 handler
        original_levelname = record.levelname
        if record.levelname in COLORS:
            record.levelname = f"{COLORS[record.levelname]}{record.levelname}{COLORS['RESET']}"
        result = super().format(record)
        record.levelname = original_levelname
        return result


def setup_logging(
    level: int | str = logging.INFO,
    log_file: str | Path | None = None,
    use_color: bool = True,
    log_format: str = DEFAULT_FORMAT,
) -> None:
    """
    配置项目日志。

    Args:
        level: 日志级别，默认 INFO
        log_file: 日志文件路径，可选
        use_color: 是否使用彩色输出，默认 True
        log_format: 日志格式
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = []

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    if use_color and sys.stdout.isatty():
        console_handler.setFormatter(ColoredFormatter(log_format))
    else:
        console_handler.setFormatter(logging.Formatter(log_format))
    handlers.append(console_handler)

    # 文件处理器（可选）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(DETAILED_FORMAT))
        handlers.append(file_handler)

    # 配置根日志器
    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """
    获取模块级别的日志器。

    Args:
        name: 模块名称，通常使用 __name__

    Returns:
        配置好的 Logger 实例
    """
    return logging.getLogger(name)
