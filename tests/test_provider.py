"""测试 OpenAI Provider - 验证 LLM 连通性

运行方式:
    cd /data/workspace/ffbot
    python3 -m tests.test_provider
"""

import asyncio
import sys
from pathlib import Path

import yaml
import aiohttp

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.provider.openai_provider import OpenAIProvider
from core.provider.base import ChatMessage


def load_config() -> dict:
    """从 config.yaml 加载 provider 配置"""
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, encoding="utf-8") as f:
        full_config = yaml.safe_load(f)
    return full_config.get("provider", {}).get("openai", {})


async def test_list_models():
    config = load_config()
    models_url = config.get("models_url", "")
    api_key = config.get("api_key", "")

    if not models_url:
        print("[跳过] 未配置 models_url")
        return

    print(f"[测试] 请求模型列表: {models_url}")

    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {api_key}"}
        async with session.get(models_url, headers=headers) as resp:
            print(f"[结果] HTTP 状态码: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                models = data.get("data", [])
                print(f"[结果] 可用模型 ({len(models)} 个):")
                for m in models:
                    print(f"         - {m.get('id', '未知')}")
            else:
                text = await resp.text()
                print(f"[错误] {text[:200]}")
                return

    print("✅ 模型列表获取成功")


async def test_basic_chat():
    config = load_config()
    provider = OpenAIProvider(config)

    messages = [
        ChatMessage(role="user", content="你好，请回复'连接正常'这四个字"),
    ]

    print(f"\n[测试] 基本对话")
    print(f"[测试] 模型: {provider.model}")
    print(f"[测试] API: {provider.api_base}")
    print("[测试] 等待响应...")

    response = await provider.chat(messages)

    print(f"[结果] 回复: {response.content}")
    print(f"[结果] Token: {response.usage}")
    assert response.content, "回复内容为空!"
    print("✅ 基本对话测试通过")


async def test_multi_turn():
    config = load_config()
    provider = OpenAIProvider(config)

    messages = [
        ChatMessage(role="system", content="你是一个助手，回答尽量简短。"),
        ChatMessage(role="user", content="我叫小明"),
        ChatMessage(role="assistant", content="你好小明！"),
        ChatMessage(role="user", content="我叫什么名字？"),
    ]

    print("\n[测试] 多轮对话 - 验证上下文记忆")
    response = await provider.chat(messages)

    print(f"[结果] 回复: {response.content}")
    assert "小明" in response.content, f"回复中没有'小明': {response.content}"
    print("✅ 多轮对话测试通过")


async def main():
    print("=" * 50)
    print("  Provider 测试 - 验证 LLM 连通性")
    print("=" * 50)

    try:
        await test_list_models()
        await test_basic_chat()
        await test_multi_turn()
    except Exception as e:
        print(f"\n❌ 测试失败: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("  全部测试通过 ✅")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
