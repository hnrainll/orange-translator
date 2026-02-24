# 🍊 orange-translator

EPUB 双语翻译工具，使用大模型将电子书翻译为目标语言，译文紧跟原文段落之后，生成双语 EPUB。

## 特性

- **双语排版**：译文紧跟原文段落，保留原有 HTML 结构与样式（含居中、加粗等）
- **本地优先**：默认使用 [Ollama](https://ollama.com) 本地大模型（`translategemma:4b`），无需联网
- **可扩展引擎**：支持任意 OpenAI 兼容接口（DeepSeek、硅基流动等）
- **任意语言对**：不限翻译方向，支持 17 种常用语言
- **续翻支持**：中断后自动从上次进度继续，并记录每章耗时
- **双入口**：CLI 命令行工具 + Web UI

## 项目结构

```
orange-translator/
├── core/                    # 核心层：业务逻辑
│   ├── epub/
│   │   ├── parser.py        # EPUB 解包、spine/manifest 解析
│   │   ├── extractor.py     # HTML 文本块提取
│   │   └── packer.py        # 双语重组 + EPUB 打包
│   ├── translator/
│   │   ├── base.py          # TranslatorBase 抽象类
│   │   ├── ollama.py        # Ollama 实现
│   │   └── openai_compat.py # OpenAI 兼容接口
│   ├── pipeline.py          # 翻译流水线（调度、进度、续翻）
│   └── config.py            # 配置模型
├── app/                     # 应用层：交付方式
│   ├── cli/
│   │   └── main.py          # CLI 入口（typer）
│   └── web/
│       ├── app.py           # FastAPI 后端
│       ├── routers/
│       └── frontend/        # Vue 3 + Vite 前端
└── pyproject.toml
```

## 安装

依赖 [uv](https://docs.astral.sh/uv/) 管理环境，Python 3.12+。

```bash
git clone https://github.com/yourname/orange-translator
cd orange-translator
uv pip install -e .
```

## 使用

### 前提

启动 Ollama 并拉取默认模型：

```bash
ollama serve
ollama pull translategemma:4b
```

### CLI

```bash
# 基础用法（英 → 中，speed 模式）
ot translate book.epub --from en --to zh

# 指定模式和模型
ot translate book.epub --from en --to zh --mode quality --model translategemma:12b

# 指定输出路径
ot translate book.epub -o book_bilingual.epub

# 使用 OpenAI 兼容引擎
ot translate book.epub --engine openai --api-key sk-... --model gpt-4o-mini

# 查看支持的语言
ot languages

# 列出本地 Ollama 可用模型
ot models
```

### Web UI

```bash
# 启动服务
uv run uvicorn app.web.app:app --reload --port 8000
```

浏览器访问 [http://localhost:8000](http://localhost:8000)，上传 EPUB 文件并配置翻译参数，实时查看进度，完成后下载双语版本。

## 翻译模式

| | Speed | Quality |
|---|---|---|
| 默认模型 | `translategemma:4b` | `translategemma:4b` |
| 章节并发 | 4 | 1 |
| 批量大小 | 10 段/批 | 3 段/批 |
| temperature | 0.3 | 0.7 |

## 进度文件

翻译过程中生成 `<epub名>.ot-progress.json`，按完成顺序记录每章耗时，支持中断续翻：

```json
{
  "completed": [
    { "path": "text/part0001.html", "duration_sec": 0.7 },
    { "path": "text/part0004.html", "duration_sec": 45.1 }
  ]
}
```

翻译全部完成后该文件自动删除。

## 双语样式

译文节点格式：

```html
<p>Original paragraph.</p>
<p class="ot-translation" lang="zh">译文段落。</p>
```

- 译文默认蓝色、左边框区分
- 居中文字自动继承对齐方式，改用底部细线区分
- 样式通过注入的 `ot-translation.css` 控制，可自定义覆盖
