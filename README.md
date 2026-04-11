# HAcollabration

一个基于 FastAPI 的行动研究协作原型，支持：

- 创建分阶段研究会话
- 每个阶段生成一份 `docx` 文稿
- 在线编辑或上传修订版 `docx`
- 在进入下一阶段前确认当前阶段文稿

## 当前结构

```text
.
|-- app.py
|-- backend/
|   |-- main.py
|   |-- config.py
|   |-- router.py
|   |-- routes/
|   |-- services/
|   |-- models/
|   |-- schemas/
|   |-- clients/
|   `-- repositories/
|-- frontend/
|   |-- index.html
|   |-- app.js
|   `-- styles.css
|-- prompts/
|-- tests/
|-- data/
`-- pyproject.toml
```

## 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

## 环境变量

在项目根目录创建 `.env`：

```env
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=60
```

如果没有配置 `DEEPSEEK_API_KEY`，系统会自动使用本地回退逻辑。

## 启动

```powershell
python app.py
```

启动后可访问：

- 首页：`http://127.0.0.1:8000/`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

## 测试

```powershell
pytest -q
```

## 说明

- `prompts/` 保存可选提示词模板，缺失时会自动回退到内置文案
- `data/stage_docs/` 是运行时生成的文档目录，已在 `.gitignore` 中忽略
- 当前会话仍然保存在内存中，服务重启后不会保留
