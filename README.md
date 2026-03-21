# HAcollabration

这是一个面向“行动研究分阶段引导”的 FastAPI 原型项目。

当前版本的核心能力：
- 用户先输入研究想法，系统生成分阶段对话方案
- 每个 stage 完成后自动生成一个 `docx`
- 用户可下载并修改该 `docx`，再上传修订版
- 进入下一个 stage 前，系统会读取上一阶段修订内容
- 最终总结时保留所有阶段文档下载入口

## 目录结构

```text
.
|-- app.py
|-- backend/
|   |-- api/
|   |-- application/
|   |-- core/
|   |-- domain/
|   `-- infrastructure/
|-- frontend/
|   |-- index.html
|   |-- app.js
|   `-- styles.css
|-- data/
|-- docs/
|-- prompts/
|-- tests/
|-- pyproject.toml
`-- requirements.txt
```

说明：
- `app.py` 是统一启动入口
- `backend/` 只放后端代码
- `frontend/` 只放网页前端资源
- `data/stage_docs/` 是运行时生成的文档目录，已加入 `.gitignore`

## 安装依赖

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 环境变量

在项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=60
```

如果不配置 `DEEPSEEK_API_KEY`，系统会使用本地回退逻辑运行。

## 启动项目

```powershell
python app.py
```

启动后可访问：
- 首页：`http://127.0.0.1:8000/`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 主要模块

- `backend/api/routes/dialogue.py`
  负责会话、阶段推进、文档上传下载等接口

- `backend/application/services/dialogue_service.py`
  负责分阶段对话编排、文档确认状态和最终总结

- `backend/application/services/document_service.py`
  负责生成、读取和保存 `docx`

- `frontend/`
  当前网页前端资源

## 测试

```powershell
python -m pytest -q
```

当前已覆盖：
- 健康检查
- 阶段文档生成
- 修订版上传
- 下一阶段读取修订内容

## 当前限制

- 会话仍然保存在内存中，服务重启后会丢失
- 前端仍是原型实现，暂未引入构建工具链
- 文档修订需要用户手动上传修改后的 `docx`
