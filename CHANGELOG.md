# Changelog

## v0.1 (2026-05-05)

初始版本。

### 核心功能
- OneBot v11 正向 WebSocket 连接（NapCat）
- OpenAI 兼容 LLM 调用（DeepSeek）
- Pipeline 架构：预处理 → LLM → 响应
- SQLite 持久化：消息记录（message_id 主键，含 reply 字段）
- 用户管理：自动记录、白名单鉴权
- Web 控制台：配置管理 / 连通性测试 / 用户白名单 / 对话查询与多选删除

### 消息支持
- 文本 / 图片 / 文件 / 表情 / 引用回复 / JSON 卡片

### 架构
- Event（pipeline/event.py）：Pipeline 处理单元
- Message（platform/message.py）：消息收发载体
- StorageManager：SQLite 异步存储
- ConversationManager：预留，后续负责 LLM 输入拼装
