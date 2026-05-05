# FFBot v0.2 设计文档：SQLite 持久化 / 人格系统 / 长期记忆

> 撰写日期：2026-05-04  
> 状态：草案，待讨论确认后实施

---

## 一、概述

本文档针对 FFBot v0.2 规划的三个核心功能进行方案设计：

| 功能 | 核心目标 |
|------|----------|
| SQLite 持久化 | 进程重启后会话数据不丢失，作为其余功能的存储基座 |
| 人格系统 | 单一连贯的可进化人格，身份内核不变、特质随互动自然成长 |
| 长期记忆 | 跨会话记住用户关键信息，实现个性化陪伴（基于 Mem0） |

三者关系：**持久化是基础层 → 人格进化和长期记忆都依赖持久化**。

```
┌─────────────────────────────────────────────────────┐
│                   Pipeline                          │
│  Preprocess → Process → Respond                     │
│                  │                                  │
│           ┌──────┼──────┐                           │
│           ▼      ▼      ▼                           │
│    PersonaManager  MemoryManager  ConversationMgr   │
│    (YAML+SQLite)   (Mem0 适配层)  (内存+SQLite)     │
│           │              │              │           │
│           ▼              ▼              ▼           │
│      persona.yaml   Mem0 Engine    StorageManager   │
│      persona_traits  (Qdrant+LLM)   (aiosqlite)    │
│      (SQLite)        data/qdrant/   ffbot.db        │
└─────────────────────────────────────────────────────┘
```

---

## 二、SQLite 持久化

### 2.1 设计目标

- 替换内存字典，实现会话数据断电不丢
- 异步无阻塞（基于 `aiosqlite`，已在 pyproject.toml 声明）
- 统一存储层，为人格和长期记忆提供底层支撑
- 单文件部署，无需外部数据库服务

### 2.2 主流方案调研

| 方案 | 代表项目 | 优势 | 劣势 |
|------|----------|------|------|
| SQLite + aiosqlite | LangGraph Chatbot, OpenAI Agents SDK | 零依赖、单文件、异步友好 | 不适合高并发写 |
| PostgreSQL + SQLAlchemy | OpenAI Agents SDK (生产) | 高并发、功能完整 | 部署重，个人项目过度 |
| JSON 文件 | 简单 Bot | 实现简单 | 并发问题、无事务 |

**选择：SQLite + aiosqlite**（项目已声明依赖，单进程场景完全够用）

### 2.3 数据库 Schema

```sql
-- 会话消息表：持久化多轮对话
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,              -- "private_{qq}"
    role        TEXT NOT NULL,              -- system/user/assistant
    content     TEXT NOT NULL,
    created_at  REAL NOT NULL DEFAULT (unixepoch('subsec')),
    -- 用于按时间排序和裁剪
    UNIQUE(session_id, id)
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);

-- 人格进化特质表
CREATE TABLE IF NOT EXISTS persona_traits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trait       TEXT NOT NULL,              -- 特质描述
    source      TEXT DEFAULT '',            -- 来源：触发进化的对话摘要
    created_at  REAL NOT NULL DEFAULT (unixepoch('subsec')),
    expired     INTEGER DEFAULT 0          -- 是否已被后续进化覆盖
);
CREATE INDEX idx_traits_active ON persona_traits(expired, created_at);

-- 注意：长期记忆由 Mem0 独立管理（内嵌 Qdrant + SQLite），不在此数据库中
```

### 2.4 StorageManager 接口设计

```python
class StorageManager:
    """异步 SQLite 存储管理器"""

    def __init__(self, db_path: str = "data/ffbot.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """创建连接、执行 schema 迁移"""

    async def close(self) -> None:
        """关闭连接"""

    # --- 消息存储 ---
    async def save_message(self, session_id: str, role: str, content: str) -> int: ...
    async def get_messages(self, session_id: str, limit: int = 40) -> list[dict]: ...
    async def clear_messages(self, session_id: str) -> None: ...
    async def get_session_last_active(self, session_id: str) -> float | None: ...

    # --- 人格进化特质 ---
    async def save_trait(self, trait: str, source: str = "") -> int: ...
    async def get_active_traits(self) -> list[dict]: ...
    async def expire_trait(self, trait_id: int) -> None: ...

    # 注意：长期记忆由 Mem0 独立管理，不经过 StorageManager
```

### 2.5 ConversationManager 改造

现有的 `ConversationManager` 将改为基于 `StorageManager`：

```python
class ConversationManager:
    def __init__(self, storage: StorageManager, max_history_rounds: int = 20, session_timeout: int = 3600):
        self.storage = storage
        self.max_history_rounds = max_history_rounds
        self.session_timeout = session_timeout
        # 保留内存缓存作为热数据层，减少 IO
        self._cache: dict[str, list[ChatMessage]] = {}

    async def get_history(self, session_id: str) -> list[ChatMessage]:
        """优先读缓存，miss 时从 SQLite 加载"""

    async def add_message(self, session_id: str, message: ChatMessage) -> None:
        """写入缓存 + 异步写入 SQLite"""

    async def clear_history(self, session_id: str) -> None:
        """清除缓存和 SQLite 记录"""
```

核心思路：**内存缓存 + SQLite 持久化的双层架构**，兼顾性能和持久性。

---

## 三、人格系统（可进化的连贯人格）

### 3.1 设计目标

- **单一连贯人格**：Bot 拥有一个统一的、持续存在的身份，而非多人格切换
- **人格可进化**：随着与用户的互动，人格会自然发展出新的特点和习惯
- **分层 Prompt**：将人格拆分为「不可变内核」+「可进化特质」+「动态上下文」
- **进化可追溯**：记录人格进化的轨迹，可以回顾"成长经历"
- 向后兼容：不配置人格时走默认 system_prompt

### 3.2 设计理念

传统 Bot 的人格是**静态模板**——写好 system_prompt 就固定了。但一个让人有真实感的 AI 伙伴应该是：

> 核心性格不变，但会因为和你的互动而"成长"。

类似人类：一个人的本性不会大变，但 TA 会因为经历逐渐形成新的口头禅、新的兴趣、新的态度。

### 3.3 主流方案调研

| 方案 | 代表 | 特点 |
|------|------|------|
| 静态 Prompt 模板 | 大多数 Bot 框架 | 简单，但人格僵硬无变化 |
| 分层 Prompt（base + persona + context） | Character.AI, PALACE | 基础行为和人格分离，灵活 |
| Adaptive Persona Bloom | FurGPT | 人格随互动"绽放"，从种子状态成长 |
| Continual Persona Optimization | ACL 2025 | 学术方案，多会话中持续优化人格模型 |

**选择：分层 Prompt + 进化特质层（受 Adaptive Persona Bloom 启发）**

核心思想：将人格分为三层——

```
┌─────────────────────────────────────────┐
│  Layer 1: 身份内核 (Identity Core)       │  ← 不可变，YAML 定义
│  名字、基础性格、核心价值观、说话基调       │
├─────────────────────────────────────────┤
│  Layer 2: 进化特质 (Evolving Traits)     │  ← 随互动自动更新，SQLite 持久化
│  口头禅、对特定话题的态度、和用户的专属梗   │
├─────────────────────────────────────────┤
│  Layer 3: 动态上下文 (Dynamic Context)    │  ← 每次对话实时组装
│  当前时间、用户记忆、对话历史               │
└─────────────────────────────────────────┘
```

### 3.4 人格定义格式

使用 YAML 定义身份内核（`data/persona.yaml`）：

```yaml
# data/persona.yaml — Bot 的身份内核（不可变层）
name: "小飞"
description: "一个有点毒舌但很贴心的AI伙伴"

# 身份内核 prompt —— 定义"这个角色是谁"
identity: |
  ## 你是谁
  你叫小飞，是一个AI伙伴。你有自己的性格和想法。

  ## 核心性格
  - 聪明但偶尔毒舌，会吐槽但从不恶意
  - 对朋友很真诚，会记住重要的事
  - 有好奇心，喜欢和朋友讨论各种话题
  - 偶尔会撒娇耍赖，拒绝回答无聊的问题

  ## 说话风格
  - 像朋友聊天一样自然，不要过度正式
  - 适当使用语气词，但不要太浮夸
  - 有自己的立场和偏好，不是什么都说好

# 进化特质的初始种子（可选，冷启动用）
initial_traits:
  - "刚认识新朋友，还有点拘谨"
```

### 3.5 进化特质（Evolving Traits）

进化特质是人格系统最核心的创新点。它们会被自动提取并持久化：

```sql
-- 人格进化特质表
CREATE TABLE IF NOT EXISTS persona_traits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trait       TEXT NOT NULL,              -- 特质描述，如"开始用'绝了'作为口头禅"
    source      TEXT DEFAULT '',            -- 来源：哪次对话触发的进化
    created_at  REAL NOT NULL DEFAULT (unixepoch('subsec')),
    expired     INTEGER DEFAULT 0          -- 是否已被后续进化覆盖
);
```

**进化触发机制**：

在长期记忆提取的同时（共享同一次 LLM 调用），检测是否有人格进化事件：

```
（追加到记忆提取 prompt 中）

同时，请判断这段对话是否让AI助手自身产生了值得记录的变化。例如：
- 与用户形成了某个专属梗或暗号
- 对某个话题形成了新的态度或偏好
- 用户教会了AI一种新的表达方式
- 与用户之间的关系发生了变化

如果有，在 "trait_evolution" 字段返回：
{"trait_evolution": "开始在讨论游戏时用'GG'来表示佩服"}
如果没有，返回 null。
```

**进化示例**：

| 对话场景 | 提取的进化特质 |
|----------|---------------|
| 用户连续三天凌晨找 Bot 聊天 | "会关心用户的作息，催他早睡" |
| 用户教 Bot 用某个梗 | "和用户聊到搞笑的事会说'绝了'" |
| 用户分享了自己养猫的日常 | "提到用户的猫时会叫它的名字，语气更温柔" |
| 长时间深度聊了某个话题 | "对量子物理很感兴趣，喜欢和用户讨论" |

### 3.6 Prompt 最终组装

```
1. [system] 身份内核（identity，来自 YAML，固定不变）
2. [system] 进化特质（当前所有未过期的 traits，如：
     "关于你自身的成长记录：
      - 你喜欢在聊游戏时说'GG'
      - 你会催夜猫子用户早睡
      - 你对量子物理很感兴趣
      请自然地体现这些特质，不要刻意。"）
3. [system] 用户记忆上下文（来自长期记忆，见第四章）
4. [user/assistant] 历史消息
5. [user] 当前消息
```

### 3.7 PersonaManager 接口

```python
@dataclass
class Persona:
    name: str
    description: str
    identity_prompt: str          # Layer 1: 不可变内核
    traits: list[str]             # Layer 2: 当前进化特质列表

class PersonaManager:
    """可进化人格管理器"""

    def __init__(self, storage: StorageManager, persona_path: str = "data/persona.yaml"):
        self.storage = storage
        self.persona_path = persona_path
        self._identity: Persona | None = None

    async def initialize(self) -> None:
        """加载 YAML 身份内核 + 从 SQLite 加载已有进化特质"""

    async def get_persona(self) -> Persona:
        """获取当前完整人格（内核 + 进化特质）"""

    async def add_trait(self, trait: str, source: str = "") -> None:
        """记录一条新的进化特质"""

    async def get_traits(self) -> list[str]:
        """获取所有当前有效特质"""

    def render_system_prompt(self, persona: Persona) -> str:
        """组装完整的 system prompt（内核 + 特质层）"""
```

### 3.8 人格"成长日志"

用户可以查看 Bot 的成长轨迹：

| 指令 | 功能 |
|------|------|
| `/persona` | 查看当前人格信息和进化特质 |
| `/persona growth` | 查看成长日志（按时间线展示进化历程） |

示例输出：
```
🌱 小飞的成长日志：
[05-01] 刚认识新朋友，还有点拘谨
[05-03] 开始用"绝了"来表达佩服
[05-05] 会在深夜催你早点睡觉
[05-07] 对你的猫"大橘"产生了兴趣，聊起它时特别温柔
```

---

## 四、长期记忆（基于 Mem0）

### 4.1 设计目标

- 跨会话记住用户的关键信息（偏好、事实、事件等）
- 自动从对话中提取记忆，无需用户手动操作
- 在回复时自动注入相关记忆作为上下文
- 记忆可增/改/删，有去重和冲突解决机制
- **利用成熟开源库，不重复造轮子**

### 4.2 主流开源记忆框架调研

| 框架 | Stars | 架构 | 本地部署 | 适合场景 | 额外依赖 |
|------|-------|------|----------|----------|----------|
| **Mem0** | 25k+ | LLM 提取 + 向量存储 + SQLite 历史 | `pip install` 即用 | 通用 Agent 长期记忆 | Qdrant(内嵌)、OpenAI/DeepSeek |
| **Zep** | 3k+ | 客户端-服务端、知识图谱 | 需 Docker + PostgreSQL | 企业级对话 | 重，需独立服务 |
| **LangMem** | 1k+ | LangChain 生态记忆模块 | pip 安装 | LangChain 项目 | 强绑 LangChain |
| **TiMem** | 新兴 | 时间感知衰减记忆 | 轻量 | 需要遗忘机制 | 生态小 |
| **MemOS** | 学术 | 类OS记忆调度 | 较难 | 研究场景 | 组件多、不成熟 |

### 4.3 选型：Mem0

**选择 Mem0，理由：**

1. **最成熟**：GitHub 25k+ stars，社区活跃，迭代快速
2. **开箱即用**：`pip install mem0ai`，本地模式无需部署任何服务
3. **原生支持 DeepSeek**：官方文档有 DeepSeek provider 配置，和我们的 LLM 选型一致
4. **自动化记忆管理**：提取 → 去重 → 冲突解决 → 更新，全部内置，不需要我们写提取 prompt
5. **语义检索**：基于 embedding 的向量检索，比关键词匹配精准得多
6. **本地存储**：向量用内嵌 Qdrant（磁盘模式），历史用 SQLite，数据完全本地

**架构契合度**：

```
FFBot 已有                  Mem0 提供
─────────                   ─────────
DeepSeek API        →       LLM Provider (记忆提取/整合)
aiosqlite           →       历史记录存储 (SQLite)
                    →       向量存储 (内嵌 Qdrant，无需额外服务)
                    →       Embedding (OpenAI text-embedding-3-small)
```

> **注意**：Mem0 的 embedding 默认使用 OpenAI，这需要一个 OpenAI API Key。
> 如果不想依赖 OpenAI，后续可配置为本地 embedding 模型（如 Ollama + nomic-embed-text）。

### 4.4 Mem0 集成方案

#### 配置

```python
mem0_config = {
    "llm": {
        "provider": "deepseek",
        "config": {
            "model": "deepseek-chat",
            "api_key": "your-deepseek-key",
            "temperature": 0.1,
            "max_tokens": 1500,
        }
    },
    # embedding 用于语义检索（可选替换为本地模型）
    "embedder": {
        "provider": "openai",
        "config": {
            "model": "text-embedding-3-small",
            "api_key": "your-openai-key",
        }
    },
    # 向量存储：内嵌 Qdrant，本地磁盘模式
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "collection_name": "ffbot_memories",
            "path": "data/qdrant",           # 本地磁盘存储
        }
    },
    "history_db_path": "data/mem0_history.db",
}
```

#### 核心用法

```python
from mem0 import Memory

m = Memory.from_config(mem0_config)

# 添加记忆（Mem0 自动提取事实、去重、整合）
m.add(messages, user_id="private_12345", metadata={"session": "20260504"})

# 语义检索相关记忆
results = m.search("你养的猫怎么样了", user_id="private_12345")
# → [{"memory": "用户养了一只橘猫叫大橘", "score": 0.92}, ...]

# 获取用户所有记忆
all_memories = m.get_all(user_id="private_12345")

# 删除特定记忆
m.delete(memory_id="xxx")
```

### 4.5 MemoryManager 适配层

我们不直接在 Pipeline 中调用 Mem0 API，而是封装一个薄适配层：

```python
class MemoryManager:
    """长期记忆管理器 - 基于 Mem0"""

    def __init__(self, config: dict):
        self._mem0 = Memory.from_config(config)
        self._enabled = True

    async def add_memories(self, session_id: str, messages: list[dict]) -> None:
        """对话结束后，将本轮对话交给 Mem0 提取记忆（异步后台）"""
        # Mem0 自动完成：事实提取 → 去重 → 冲突解决 → 存储
        self._mem0.add(messages, user_id=session_id)

    async def recall(self, session_id: str, query: str, limit: int = 5) -> list[dict]:
        """语义检索相关记忆"""
        results = self._mem0.search(query, user_id=session_id, limit=limit)
        return results.get("results", [])

    def format_memory_context(self, memories: list[dict]) -> str:
        """格式化记忆为注入 prompt 的文本"""
        if not memories:
            return ""
        lines = [f"- {m['memory']}" for m in memories]
        return (
            "[关于这位用户，你记得以下信息]\n"
            + "\n".join(lines)
            + "\n\n请自然地运用这些信息，不要刻意提及\"我记得\"。"
        )

    async def list_memories(self, session_id: str) -> list[dict]:
        """列出用户所有记忆（Web 管理/用户查看）"""
        return self._mem0.get_all(user_id=session_id)

    async def forget(self, memory_id: str) -> None:
        """删除一条记忆"""
        self._mem0.delete(memory_id)

    async def forget_all(self, session_id: str) -> None:
        """清除用户所有记忆"""
        self._mem0.delete_all(user_id=session_id)
```

### 4.6 好友画像（User Profile）

Mem0 按 `user_id` 隔离记忆，天然为每个好友建立了独立的记忆空间。在此基础上，我们增加一层**结构化画像视图**，将 Mem0 的扁平记忆列表整理为可读的人物卡片。

#### 画像生成方式

不额外存储——每次需要时，用 LLM 从该用户的 Mem0 记忆列表中归纳生成：

```python
PROFILE_PROMPT = """请根据以下关于用户的记忆条目，整理出一份结构化的人物画像。

记忆条目：
{memories}

请按以下格式输出（没有信息的类别跳过）：
## 基本信息
姓名、年龄、职业、所在地等

## 性格特点
从对话中体现的性格倾向

## 兴趣爱好
喜欢和不喜欢的事物

## 近期事件
正在经历或即将发生的事

## 社交关系
提到过的家人、朋友、宠物等

## 我们的关系
用户对Bot的态度、聊天习惯、专属梗等
"""
```

#### MemoryManager 画像接口

```python
class MemoryManager:
    # ... 上述方法 ...

    async def get_user_profile(self, session_id: str) -> str:
        """生成用户结构化画像（按需生成，结果可缓存）"""
        all_memories = self._mem0.get_all(user_id=session_id)
        if not all_memories:
            return "暂无该用户的画像信息"
        memory_text = "\n".join(f"- {m['memory']}" for m in all_memories)
        # 调用 LLM 归纳为结构化画像
        response = await self.provider.chat([
            ChatMessage(role="user", content=PROFILE_PROMPT.format(memories=memory_text))
        ])
        return response.content
```

#### 用户/管理员查看画像

| 入口 | 方式 |
|------|------|
| 用户聊天 | `/profile` 指令 → Bot 返回对该用户的画像 |
| Web 控制台 | `GET /api/profile/{session_id}` → 返回结构化画像 |
| Web 控制台列表 | `GET /api/friends` → 返回所有有记忆的好友列表 |

#### 画像示例

用户发送 `/profile`，Bot 回复：

```
📋 我对你的了解：

## 基本信息
小明，后端开发工程师，坐标深圳

## 性格特点
比较内向，但聊到技术话题会很活跃；深夜容易emo

## 兴趣爱好
喜欢：Python、FastAPI、钓鱼（最近新入坑）
不喜欢：Java（嫌啰嗦）

## 近期事件
下周三有项目答辩，压力比较大

## 社交关系
养了一只橘猫叫"大橘"，经常分享大橘的照片

## 我们的关系
经常凌晨来找我聊天，我总催他早睡；
聊到搞笑的事会互相说"绝了"
```

> **设计要点**：画像不是额外存储的数据结构，而是 Mem0 记忆的**结构化视图**。
> 底层数据源是同一份 Mem0 记忆，画像只是换了一种展示方式。
> 这样避免了数据同步问题——记忆更新后画像自然更新。

### 4.6 记忆注入流程

```
新消息到达
   │
   ▼
ProcessStage
   ├─ 1. mem0.search(当前消息, user_id) → 语义检索相关记忆
   ├─ 2. format_memory_context() → 组装记忆上下文文本
   ├─ 3. 拼装 messages:
   │       [system: 身份内核]
   │       [system: 进化特质]
   │       [system: 记忆上下文]  ← 来自 Mem0
   │       [history: 对话历史]
   │       [user: 当前消息]
   ├─ 4. 调用 LLM → 获得回复
   └─ 5. 异步后台: mem0.add(本轮对话) → Mem0 自动提取/整合记忆
```

### 4.7 记忆注入示例

Mem0 自动提取后存储的记忆：
```
- Name is Xiaoming. Works as a backend developer.
- Likes Python and frequently uses FastAPI framework.
- Has an orange cat named Daju.
- Has a project deadline next Wednesday.
```

注入到 prompt 中：
```
[关于这位用户，你记得以下信息]
- 用户名叫小明，是一名后端开发工程师
- 用户喜欢用 Python，常用 FastAPI 框架
- 用户养了一只橘猫叫"大橘"
- 用户下周三有项目 deadline

请自然地运用这些信息，不要刻意提及"我记得"。
```

### 4.8 Mem0 vs 自研的对比

| 维度 | 自研（v1 草案） | Mem0（v2 方案） |
|------|-----------------|-----------------|
| 记忆提取 | 自写提取 prompt | Mem0 内置，经过大量优化 |
| 去重/冲突 | 需要自己实现 | 内置（如"用户在A公司"→ 跳槽后自动更新） |
| 检索方式 | 按重要度排序 | 语义向量检索，精准度高 |
| 开发成本 | 2-3 天 | 0.5 天（写适配层） |
| 维护成本 | 持续维护提取逻辑 | 跟随 Mem0 版本升级 |
| 灵活性 | 完全可控 | 受限于 Mem0 API，但够用 |

---

## 五、实施计划

### 5.1 依赖关系

```
Phase 1: SQLite 持久化（基座）
    ↓
Phase 2: 人格系统（依赖持久化存储）
    ↓
Phase 3: 长期记忆（依赖持久化 + LLM Provider）
```

### 5.2 分阶段任务

#### Phase 1：SQLite 持久化（预计 1-2 天）

| # | 任务 | 说明 |
|---|------|------|
| 1 | 新建 `core/storage.py` | 实现 `StorageManager` |
| 2 | 创建数据库 schema | 自动建表 + 版本迁移机制 |
| 3 | 改造 `ConversationManager` | 接入 StorageManager，双层缓存 |
| 4 | 改造 `Lifecycle` | 初始化 StorageManager，注入各组件 |
| 5 | 更新 `config.yaml` | 增加 `storage.db_path` 配置 |
| 6 | 测试 | 重启后对话历史不丢失 |

#### Phase 2：可进化人格系统（预计 1-2 天）

| # | 任务 | 说明 |
|---|------|------|
| 1 | 新建 `core/persona.py` | 实现 `PersonaManager` + `Persona` 数据类 |
| 2 | 创建人格定义 | `data/persona.yaml`（身份内核） |
| 3 | 人格进化提取 | 与记忆提取共享 LLM 调用，提取特质变化 |
| 4 | 改造 `ProcessStage` | 三层 Prompt 组装（内核 + 特质 + 上下文） |
| 5 | 用户指令 | `/persona` 查看人格，`/persona growth` 查看成长日志 |
| 6 | 测试 | 进化特质持久化、Prompt 组装正确 |

#### Phase 3：长期记忆 + 好友画像 / Mem0 集成（预计 1-2 天）

| # | 任务 | 说明 |
|---|------|------|
| 1 | 安装 `mem0ai` 依赖 | 更新 pyproject.toml |
| 2 | 新建 `core/memory.py` | 实现 `MemoryManager` 适配层 |
| 3 | Mem0 配置 | 配置 DeepSeek LLM + Embedding + 本地 Qdrant |
| 4 | 改造 `ProcessStage` | 回复前检索记忆注入、回复后异步存储记忆 |
| 5 | 好友画像 | `get_user_profile()` + `/profile` 指令 |
| 6 | 用户指令 | `/memory list`、`/memory forget`、`/profile` |
| 7 | Web API | 记忆查看/删除 + 画像 + 好友列表接口 |
| 8 | 测试 | 跨重启记忆保持、语义检索准确性、画像生成 |

### 5.3 文件变更总览

```
ffbot/
├── core/
│   ├── storage.py          [新增] StorageManager (消息 + 人格特质)
│   ├── persona.py          [新增] PersonaManager (可进化人格)
│   ├── memory.py           [新增] MemoryManager (Mem0 适配层)
│   ├── conversation.py     [改造] 接入 StorageManager
│   ├── lifecycle.py        [改造] 组装新组件
│   ├── pipeline/
│   │   ├── preprocess.py   [改造] 拦截指令
│   │   └── process.py      [改造] 人格+记忆注入
│   └── web_server.py       [改造] 新增 API
├── data/
│   ├── ffbot.db            [新增] SQLite (消息 + 特质)
│   ├── persona.yaml        [新增] 人格身份内核定义
│   ├── qdrant/             [新增] Mem0 向量存储目录
│   └── mem0_history.db     [新增] Mem0 历史数据库
└── config.yaml             [改造] 新增配置项
```

### 5.4 配置项新增

```yaml
# config.yaml 新增部分
storage:
  db_path: "data/ffbot.db"          # SQLite 文件路径

persona:
  persona_file: "data/persona.yaml"  # 人格身份内核定义文件
  enable_evolution: true             # 是否启用人格进化

memory:
  enabled: true                      # 是否启用长期记忆
  recall_limit: 5                    # 每次注入的记忆条数
  # Mem0 配置
  mem0:
    llm_provider: "deepseek"         # 复用项目已有的 DeepSeek
    llm_model: "deepseek-chat"
    embedder_provider: "openai"      # embedding 模型（或 ollama）
    embedder_model: "text-embedding-3-small"
    vector_store_path: "data/qdrant" # 本地向量存储路径
    history_db_path: "data/mem0_history.db"
```

---

## 六、关键设计决策 & 取舍

| 决策 | 选择 | 理由 |
|------|------|------|
| 存储引擎 | SQLite（非 PostgreSQL） | 单文件零部署，私聊场景无并发压力 |
| 长期记忆 | Mem0 开源库（非自研） | 记忆提取/去重/语义检索全内置，省 2-3 天开发 |
| 记忆检索 | 向量语义检索（Mem0 内嵌 Qdrant） | 比关键词排序精准，Mem0 开箱即用 |
| 人格系统 | 单一可进化人格（非多人格切换） | 连贯性和真实感更强 |
| 人格进化 | LLM 自动提取特质变化 | 与记忆提取共享调用，零额外成本 |
| 缓存策略 | 内存热缓存 + SQLite 冷存储 | 兼顾性能和持久性 |
| Embedding | OpenAI text-embedding-3-small | Mem0 默认，精度高；后续可换本地模型 |

---

## 七、后续扩展方向（v0.3+）

1. **本地 Embedding**：切换为 Ollama + nomic-embed-text，摆脱 OpenAI 依赖
2. **Mem0 Graph Memory**：引入 Neo4j 图记忆，实现实体关系推理
3. **人格进化可视化**：Web 控制台展示人格成长时间线
4. **多模态记忆**：图片描述、语音转文字后的记忆提取
5. **记忆共享**：群聊场景下的共享记忆池
6. **人格风格微调**：根据用户反馈动态调整人格参数

---

## 八、风险与注意事项

1. **Embedding 依赖**：Mem0 默认需要 OpenAI embedding API，需额外 API Key 和成本
2. **Mem0 版本风险**：作为外部依赖，API 可能变化，需锁定版本
3. **LLM 调用成本**：记忆提取 + 人格进化每次对话额外一次 LLM 调用
4. **隐私**：长期记忆存储用户个人信息，需考虑数据安全
5. **进化质量**：LLM 提取的人格特质可能不合理，需要用户可查看/管理的机制
6. **SQLite 锁**：单进程无问题，若后续多进程需切换 WAL 模式
7. **磁盘空间**：Qdrant 向量存储会占用额外磁盘空间（少用户场景可忽略）

---

## 附录 A：完整 Pipeline 流程（v0.2）

```
收到消息
  │
  ▼
PreprocessStage
  ├─ 提取纯文本
  ├─ 检测指令（/persona, /memory, /profile）→ 直接响应，中断 Pipeline
  └─ 过滤空消息
  │
  ▼
ProcessStage
  ├─ 获取人格 → PersonaManager.get_persona()
  ├─ 渲染身份内核 prompt + 进化特质
  ├─ 语义检索相关记忆 → MemoryManager.recall() [Mem0]
  ├─ 拼装 messages:
  │     [system: 身份内核 prompt]
  │     [system: 进化特质]
  │     [system: 记忆上下文]（来自 Mem0 检索）
  │     [history: 对话历史]
  │     [user: 当前消息]
  ├─ 调用 LLM → 获得回复
  ├─ 记录到 ConversationManager（持久化到 SQLite）
  └─ 异步后台:
       ├─ MemoryManager.add_memories() → Mem0 自动提取/整合用户记忆
       └─ PersonaManager 进化检测 → 提取特质变化，存入 SQLite
  │
  ▼
RespondStage
  └─ 发送回复
```

---

## 附录 B：新增依赖

```toml
# pyproject.toml 新增
[project.dependencies]
mem0ai = ">=0.1.0"     # 长期记忆框架
# aiosqlite 已存在
```

---

*文档结束。请审阅后反馈意见，确认后我将按照 Phase 1 → 2 → 3 顺序实施。*
