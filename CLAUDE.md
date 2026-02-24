# orange-translator

EPUB 双语翻译工具，使用大模型将电子书翻译为目标语言，译文紧跟原文段落之后，生成双语 EPUB。

## 项目配置

- **包管理**：uv
- **Python 版本**：3.12
- **初始化命令**：`uv init --python 3.12`
- **运行命令**：`uv run`
- **添加依赖**：`uv add <package>`

## 技术方案

### 核心流程

```
EPUB 解包 → HTML 解析 → 文本提取 → LLM 翻译 → 双语重组 → EPUB 重新打包
```

### 项目结构

```
orange-translator/
├── core/                    # 核心层：业务逻辑
│   ├── epub/
│   │   ├── parser.py        # EPUB 解包、spine/manifest 解析
│   │   ├── extractor.py     # HTML 文本块提取
│   │   └── packer.py        # 双语重组 + EPUB 打包
│   ├── translator/
│   │   ├── base.py          # TranslatorBase 抽象类
│   │   ├── ollama.py        # Ollama 实现（默认 translategemma:4b）
│   │   └── openai_compat.py # OpenAI 兼容接口（DeepSeek 等）
│   ├── pipeline.py          # 翻译流水线（调度、进度、续翻）
│   └── config.py            # 配置模型：语言对、模式、并发数等
├── app/                     # 应用层：交付方式
│   ├── cli/
│   │   └── main.py          # typer CLI 入口
│   └── web/
│       ├── app.py           # FastAPI 后端
│       ├── routers/
│       └── frontend/        # Vue 3 + Vite
└── pyproject.toml
```

### 翻译引擎（可插拔）

- **抽象基类** `TranslatorBase`，方法：`async translate(text, src, tgt) -> str`
- **OllamaTranslator**：调用本地 `http://localhost:11434/api/chat`，默认模型 `qwen2.5`
- **OpenAICompatTranslator**：兼容 OpenAI 接口（可接 DeepSeek、硅基流动等）

### 质量 vs 速度配置

| 参数 | Speed 模式 | Quality 模式 |
|------|-----------|-------------|
| 默认模型 | `translategemma:4b` | `translategemma:4b` |
| 章节并发数 | 4 | 1 |
| 段落批量大小 | 10 段/次 | 3 段/次（保留上下文） |
| Prompt 策略 | 简洁直译 | 带上下文、风格指引 |
| temperature | 0.3 | 0.7 |

### EPUB 解析策略

- 解压 `.epub`（本质是 ZIP）
- 读取 `content.opf` 获取 spine 阅读顺序和 manifest 文件列表
- 逐章解析 XHTML，以**块级元素**为翻译单元（`<p>`, `<h1-h6>`, `<li>`, `<td>` 等）
- 内联标签（`<em>`, `<strong>`, `<a>`）保留在翻译文本中传入 LLM
- 跳过 `<pre>/<code>` 代码块

### 双语插入格式

```html
<p>Original paragraph.</p>
<p class="ot-translation" lang="zh">译文段落。</p>
```

- 自动注入 CSS：译文用不同颜色/字号视觉区分
- 更新 EPUB 元数据标题加 `[双语]` 标记

### 进度持久化

- 每章翻译完成后写入 `.ot-progress.json`
- 中断重启后跳过已完成章节，支持续翻

### CLI 接口

```bash
ot translate book.epub --from en --to zh
ot translate book.epub --from en --to zh --mode quality --model qwen2.5:72b
ot translate book.epub -o book_bilingual.epub
ot languages       # 查看支持语言
ot models          # 列出本地 Ollama 可用模型
```

### Web UI

- **后端**：FastAPI + SSE 推送实时进度
- **前端**：Vue 3 + Vite（轻量）
- 功能：上传 EPUB → 配置语言对/引擎/模型/模式 → 实时进度 → 下载结果

## 依赖

```toml
[project.dependencies]
ebooklib = "*"
lxml = "*"
beautifulsoup4 = "*"
httpx = "*"
typer = "*"
rich = "*"
fastapi = "*"
uvicorn = "*"
python-multipart = "*"
```

## 实现顺序

1. 核心层：EPUB 解析 → 翻译引擎 → 流水线
2. CLI：端到端验证
3. Web UI：在核心层稳定后叠加
