"""FFBot 入口"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from core.lifecycle import Lifecycle


def main() -> None:
    # 加载配置
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("错误: config.yaml 不存在")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 配置日志
    level = config.get("logging", {}).get("level", "INFO")
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # 启动
    lifecycle = Lifecycle(config)
    asyncio.run(lifecycle.start())


if __name__ == "__main__":
    main()
