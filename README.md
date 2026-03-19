# HAcollabration

这是一个面向“行动研究流程引导型 AI”的后端原型项目。

它不是通用聊天机器人，而是一个会：

- 读取教师输入的研究想法
- 自动拆分成若干推进阶段
- 先征求教师对阶段安排的确认
- 每轮提出少量聚焦问题
- 在每轮回答后给出一点反馈、建议思路和阶段草稿
- 最后汇总整段对话

当前项目已经接入 DeepSeek API，并提供：

- 命令行对话模式
- 简单网页前端
- FastAPI 接口

## 当前结构

```text
.
|-- app.py
|-- backend
|   |-- api
|   |   |-- router.py
|   |   `-- routes
|   |       |-- dialogue.py
|   |       |-- frontend.py
|   |       |-- health.py
|   |       `-- sessions.py
|   |-- application
|   |   |-- schemas
|   |   `-- services
|   |-- cli
|   |-- core
|   |-- domain
|   |   |-- models
|   |   `-- services
|   |-- infrastructure
|   |   |-- llm
|   |   |-- persistence
|   |   `-- repositories
|   `-- static
|-- data
|-- docs
|-- prompts
|-- tests
|-- pyproject.toml
`-- requirements.txt
```

说明：

- 根目录的 `app.py` 是整个项目的统一启动入口
- `backend/` 是实际业务代码
- `backend/static/` 是当前网页前端资源

## 安装依赖

推荐先创建虚拟环境，再安装依赖：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置 DeepSeek API

在项目根目录创建 `.env` 文件，内容如下：

```env
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=60
```

## 启动项目

直接运行：

```powershell
python app.py
```

启动后可访问：

- 首页：`http://127.0.0.1:8000/`
- 接口文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 命令行对话模式

如果你想直接在 PyCharm Terminal 里测试：

```powershell
python -m backend.cli.chat
```

它会按以下流程工作：

1. 读取你的研究想法
2. 自动拆分阶段
3. 询问你阶段安排是否合理
4. 逐轮提问
5. 每轮输出反馈、建议和草稿
6. 最后输出总结

## 网页前端

网页端目前支持：

- 输入研究想法
- 生成阶段方案
- 确认或调整阶段安排
- 逐轮回答问题
- 查看每轮反馈、建议思路和阶段草稿
- 查看最终总结

## 当前核心模块

- `backend/application/services/dialogue_service.py`
  负责 staged dialogue 的主要编排逻辑

- `backend/api/routes/dialogue.py`
  提供网页前端使用的对话 API

- `backend/static/`
  提供最小网页前端

- `backend/infrastructure/llm/deepseek_client.py`
  负责调用 DeepSeek API

## 当前限制

- 对话历史目前只保存在内存中，服务重启后会丢失
- 还没有接入数据库
- 前端还是原型版，偏演示用途
- 旧的空 `app/` 残留目录如果还在，是之前结构迁移时留下的，不参与当前运行

## 下一步建议

后续可以继续补：

- SQLite / PostgreSQL 持久化
- 多项目管理
- 草稿版本历史
- 文献证据管理
- 更成熟的前端交互
