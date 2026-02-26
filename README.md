# 🍊 orange-translator

EPUB 双语翻译工具，使用大模型将电子书翻译为目标语言，译文紧跟原文段落之后，生成双语 EPUB。

## 特性

- **双语排版**：译文紧跟原文段落，保留原有块级 HTML 结构与样式（含居中、加粗等）
- **高质量翻译**：预处理阶段剥离装饰性内联标签，让 LLM 看到接近纯文本的输入，翻译更自然
- **本地优先**：默认使用 [Ollama](https://ollama.com) 本地大模型（`translategemma:4b`），无需联网
- **可扩展引擎**：支持任意 OpenAI 兼容接口（DeepSeek、硅基流动等）
- **任意语言对**：不限翻译方向，支持 17 种常用语言
- **续翻支持**：章节级磁盘缓存，中断后自动跳过已完成章节，支持大部头书籍分多次翻译
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
```

### 作为系统命令安装（推荐）

将 `ot` 命令安装到 `~/.local/bin/`，在任意目录可用：

```bash
make install      # 标准安装
make dev          # 可编辑模式（修改代码立即生效，无需重装）
make reinstall    # 重新安装（更新依赖或版本后使用）
make uninstall    # 卸载
```

如果 `ot` 命令找不到，确认 `~/.local/bin` 已加入 PATH（在 `~/.zshrc` 或 `~/.bashrc` 中添加）：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 开发时在项目目录运行

无需安装，直接通过 `make ot` 调用：

```bash
make ot book.epub
make ot book.epub --from en --to ja
```

等价于 `uv run ot <args>`，日志通过 `.env` 自动写入项目 `log/` 目录（见下方日志说明）。

## 使用

### 前提

启动 Ollama 并拉取默认模型：

```bash
ollama serve
ollama pull translategemma:4b
```

### CLI

```bash
# 简写（使用默认参数：英 → 中）
ot book.epub

# 完整形式
ot translate book.epub --from en --to zh

# 指定模型
ot translate book.epub --from en --to zh --model translategemma:12b

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

## 翻译参数

默认值（`TranslateConfig`）：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `chapter_concurrency` | `1` | 章节并发数，Ollama 本地模型建议保持 1 |
| `batch_size` | `7` | 每批最多段落数 |
| `batch_char_limit` | `3000` | 每批剥离后字符数上限，超过则提前截断 |
| `temperature` | `0.3` | 翻译温度 |

## 缓存目录

翻译过程中在 `<epub名>.ot-cache/` 目录下生成以下文件：

```
book.ot-cache/
├── progress.json        # 进度记录，按完成顺序记录每章耗时
├── <md5>.xhtml          # 各章节翻译结果缓存（可断点续翻）
└── translate.log        # 本次翻译日志（成功后随缓存一起删除）
```

`progress.json` 格式：

```json
{
  "completed": [
    { "path": "text/part0001.html", "duration_sec": 0.7 },
    { "path": "text/part0004.html", "duration_sec": 45.1 }
  ]
}
```

- **全部成功**：翻译完成后缓存目录自动删除
- **有章节失败**：缓存目录保留，重新运行时自动跳过已成功章节、重翻失败章节

**持久化日志**位置取决于运行方式：

| 方式 | 日志位置 |
|---|---|
| `ot book.epub`（系统命令） | `~/.local/share/orange-translator/ot-translate.log` |
| `make ot book.epub`（开发） | `log/ot-translate.log`（项目目录，via `.env`） |

日志自动轮转，保留最近 10 个文件。开发时可用 `make log` 实时查看全局日志。

`.env` 文件（项目根目录，已加入 `.gitignore`）：

```bash
OT_LOG_DIR=log   # 将日志重定向到项目 log/ 目录
```

## 双语样式

译文节点格式：

```html
<p>Original paragraph.</p>
<p class="ot-translation" lang="zh">译文段落。</p>
```

- 译文默认蓝色、左边框区分
- 居中文字自动继承对齐方式，改用底部细线区分
- 样式通过注入的 `ot-translation.css` 控制，可自定义覆盖
