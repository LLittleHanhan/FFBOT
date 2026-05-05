# FFBot

最小化 AI Agent 框架。OneBot v11（NapCat）+ OpenAI 兼容 API。

## 特性

- OneBot v11 正向 WebSocket，连接 NapCat 收发私聊消息
- OpenAI 兼容 API（DeepSeek、OpenAI 等）
- 消息类型：文本 / 图片 / 文件 / 表情 / 引用回复 / JSON 卡片
- SQLite 持久化：聊天记录 + 用户管理 + 白名单鉴权
- Web 控制台：配置 / 测试 / 用户白名单 / 对话查询与删除
- 单文件配置 config.yaml，支持热重载

## 快速开始

```bash
pip install aiohttp openai pyyaml aiosqlite
```

编辑 `config.yaml`，然后：

```bash
python3 main.py
```

Web 控制台：`http://localhost:8888`

## 项目结构

```
ffbot/
├── main.py
├── config.yaml
├── core/
│   ├── lifecycle.py        # 生命周期
│   ├── storage.py          # SQLite 存储
│   ├── conversation.py     # 预留：LLM 输入拼装
│   ├── web_server.py       # Web API
│   ├── platform/
│   │   ├── base.py         # 平台基类
│   │   ├── message.py      # 消息定义
│   │   └── onebot.py       # OneBot v11 适配器
│   ├── provider/
│   │   ├── base.py         # Provider 基类
│   │   └── openai_provider.py
│   └── pipeline/
│       ├── event.py        # 事件定义
│       ├── base.py         # Stage 基类
│       ├── pipeline.py     # 编排器
│       ├── preprocess.py   # 持久化 + 鉴权 + 文本提取
│       ├── process.py      # LLM 调用
│       └── respond.py      # 发送 + 持久化回复
└── static/
    └── index.html
```

## 后续规划

- [ ] 人格系统
- [ ] 长期记忆（Mem0）
- [ ] 多轮上下文
- [ ] Agent 工具循环

## License

MIT
