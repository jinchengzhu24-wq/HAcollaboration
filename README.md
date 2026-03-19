# HAcollabration Backend Scaffold

这是一个面向“行动研究流程引导型 AI”系统的后端基础骨架。

系统目标不是提供通用闲聊，而是在每次会话中：

- 读取当前研究状态与教师的最新修订
- 识别最需要推进的研究部分
- 提出少量高针对性问题
- 基于回答生成对应部分草稿
- 将结果写回会话状态，支撑下一轮计划-行动-观察-反思循环

## 当前项目结构

```text
.
|-- app
|   |-- api
|   |   |-- router.py
|   |   `-- routes
|   |       |-- health.py
|   |       `-- sessions.py
|   |-- application
|   |   |-- schemas
|   |   `-- services
|   |-- core
|   |-- domain
|   |   |-- models
|   |   `-- services
|   `-- infrastructure
|       |-- llm
|       |-- persistence
|       `-- repositories
|-- data
|-- docs
|-- prompts
|   |-- system
|   `-- workflows
`-- tests
```

## 建议启动方式

1. 创建虚拟环境并安装依赖：`pip install -e .[dev]`
2. 启动服务：`uvicorn app.main:app --reload`
3. 打开文档：`http://127.0.0.1:8000/docs`

## 当前已预留的核心能力

- 会话状态模型
- 优先推进模块枚举
- 行动研究循环阶段枚举
- 最小 API 路由
- 会话编排服务
- 内存仓储占位
- Prompt 模板目录
- 架构说明与流程说明

后续我们可以继续往里补：

- 数据库模型
- 教师资料与项目空间
- 多轮状态追踪
- LLM 调用与提示词编排
- 文献证据管理
- 草稿版本管理
- 反思与后续资料收集机制

