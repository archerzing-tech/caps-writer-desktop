<div align="center">

# ◉ CapsWriter Desktop

**完全离线的语音输入桌面应用**

基于 [Tauri](https://tauri.app) + **Qwen3-ASR 1.7B GGUF 混合引擎**（ONNX 编码器 + llama.cpp LLM 解码器）构建，支持中文 / 英文实时语音识别，无需联网，数据安全无忧。

[![Tauri](https://img.shields.io/badge/Tauri-2.x-blue?logo=tauri)](https://tauri.app)
[![Rust](https://img.shields.io/badge/Rust-1.70+-orange?logo=rust)](https://rust-lang.org)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| 🎙 **实时语音输入** | 点击麦克风即可语音输入，识别结果实时显示，支持一键复制/粘贴到当前窗口 |
| 🌐 **完全离线运行** | 基于 Qwen3-ASR GGUF 混合引擎 本地推理，无需网络，隐私安全 |
| 📁 **文件转录** | 拖拽或选择音频文件（WAV/MP3/M4A/FLAC/OGG/AAC）进行转录，支持导出 SRT/TXT/JSON |
| 📋 **历史记录** | 按日期归档所有转录记录，支持全文搜索、单条删除、一键清空 |
| 🔄 **实时翻译** | 支持中英互译（英→中 / 中→英），基于 LLM API |
| 📝 **热词管理** | 自定义热词列表，支持正则规则替换（如 `大语言模型 -> LLM`） |
| 🤖 **LLM 润色** | 接入 DeepSeek / OpenAI / Ollama 等大语言模型，对识别结果进行智能润色 |
| ⚡ **GPU 加速** | 支持 CPU 和 DirectML（GPU）两种推理后端 |
| 🔧 **系统托盘** | 最小化到系统托盘，后台运行不打扰工作 |
| 🎨 **现代 UI** | 暗色主题，动态波形可视化，流畅动画过渡 |

> **注意**: LLM 翻译和润色功能为可选功能，需要用户自行在「设置 → LLM 角色」中配置 API 地址和密钥。项目默认不包含任何第三方 API Key。

---

## 📸 界面预览

### 🎙 语音输入

<p align="center">
  <img src="screenshots/view-record.png" alt="语音输入界面" width="700" />
</p>

实时语音输入，动态波形可视化，一键复制/粘贴到当前窗口。

### 📁 文件转录

<p align="center">
  <img src="screenshots/view-transcribe.png" alt="文件转录界面" width="700" />
</p>

拖拽或选择音频文件进行转录，支持 WAV/MP3/M4A/FLAC/OGG/AAC，可导出 SRT/TXT/JSON。

### 📋 历史记录

<p align="center">
  <img src="screenshots/view-history.png" alt="历史记录界面" width="700" />
</p>

按日期归档所有转录记录，支持全文搜索、单条删除、一键清空。

### ⚙ 设置

<p align="center">
  <img src="screenshots/view-settings.png" alt="设置界面" width="700" />
</p>

模型配置、快捷键、热词管理、LLM 润色、输出设置一目了然。

---

## 🛠 技术栈

```
┌─────────────────────────────────────────────────────┐
│              CapsWriter Desktop 架构                  │
├─────────────────────────────────────────────────────┤
│                                                     │
│   ┌───────────────────────────────────────────┐     │
│   │            Tauri 2 (Rust)                  │     │
│   │  ┌─────────────┐  ┌──────────────────┐   │     │
│   │  │ 系统托盘    │  │ 剪贴板/快捷键    │   │     │
│   │  │ 窗口管理    │  │ 文件对话框       │   │     │
│   │  └─────────────┘  └──────────────────┘   │     │
│   │  ┌────────────────────────────────────┐   │     │
│   │  │ Sidecar Manager (WebSocket:6016)   │   │     │
│   │  └──────────────┬─────────────────────┘   │     │
│   └─────────────────┼─────────────────────────┘     │
│                     │                               │
│   ┌─────────────────▼─────────────────────────┐     │
│   │        Python ASR Server (sidecar)         │     │
│   │  ┌─────────────────────────────────────┐   │     │
│   │  │  Qwen3-ASR 1.7B GGUF 混合引擎    │   │     │
│   │  │  (ONNX 编码器 + llama.cpp LLM)     │   │     │
│   │  └─────────────────────────────────────┘   │     │
│   └───────────────────────────────────────────┘     │
│                                                     │
│   ┌───────────────────────────────────────────┐     │
│   │        Vite + Vanilla JS (Frontend)        │     │
│   │  ┌────────┐ ┌──────┐ ┌──────┐ ┌──────┐  │     │
│   │  │ 语音   │ │ 转录 │ │ 历史 │ │ 设置 │  │     │
│   │  └────────┘ └──────┘ └──────┘ └──────┘  │     │
│   └───────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

| 层级 | 技术 | 用途 |
|------|------|------|
| **桌面框架** | Tauri 2 | 窗口管理、系统托盘、原生对话框、剪贴板 |
| **后端语言** | Rust | 音频采集 (cpal)、WebSocket 通信、配置管理 |
| **ASR 引擎** | Qwen3-ASR 1.7B GGUF 混合引擎 | ONNX 编码器 + llama.cpp LLM 解码器（~1.7B 参数） |
| **备选引擎** | sherpa-onnx Qwen3-ASR 0.6B | int8 量化，~600M 参数，更快但精度略低 |
| **AI 服务** | Python WebSocket Server | ASR 推理服务，自动随应用启停 |
| **前端** | Vite + Vanilla JS | UI 渲染、波形动画、交互逻辑 |
| **LLM 集成** | DeepSeek / OpenAI / Ollama | 可选的翻译与文本润色（需用户自行配置 API Key） |

---

## 🚀 快速开始

### 方式一：下载预编译安装包

前往 [Releases](https://github.com/archerzing-tech/caps-writer-desktop/releases) 页面下载最新版本：

- **`CapsWriter-Desktop_0.3.0_x64-setup.exe`** — Windows NSIS 安装程序（推荐）
- **`CapsWriter-Desktop_0.3.0_x64_en-US.msi`** — Windows MSI 安装程序
- **`CapsWriter-Desktop_0.3.0_aarch64.dmg`** — macOS Apple Silicon 安装包
- **`CapsWriter-Desktop_0.3.0_x64.dmg`** — macOS Intel 安装包

> ⚠️ 首次运行需要下载模型文件和安装 Python 依赖（见下方 [模型下载](#模型下载) 和 [Python 环境准备](#python-环境准备)）。

### 方式二：从源码构建

#### 环境要求

| 工具 | 版本要求 | 说明 |
|------|----------|------|
| [Node.js](https://nodejs.org) | ≥ 18 | 前端构建 |
| [Rust](https://rustup.rs) | ≥ 1.70 | Tauri 后端编译 |
| [Python](https://python.org) | ≥ 3.10 | ASR 推理服务 |
| [Tauri CLI](https://tauri.app) | 2.x | `cargo install tauri-cli` |

#### 模型下载

模型文件较大（约 1.2~2.3GB），已从 Git 仓库中排除。你可以通过以下任一方式获取模型：

##### 方式一：应用内一键下载（推荐）

应用启动后，如果检测到模型未安装，会在录音页面显示「⬇ 一键下载模型」按钮。点击即可自动从 HuggingFace 下载所需模型到 `models/` 目录。

> ⚠️ 国内用户如遇下载慢或连接失败，建议使用方式二（手动下载），并使用 HuggingFace 镜像或 ModelScope。

##### 方式二：手动下载

根据你的硬件配置，从以下来源下载模型文件。

---

##### 模型下载来源

##### 1.7B GGUF 混合引擎（Qwen3-ASR 1.7B — 推荐）

混合引擎 = ONNX 编码器 + GGUF LLM 解码器。需要同时下载编码器和解码器文件。

| 文件 | 下载地址 | 说明 |
|------|---------|------|
| **ONNX 编码器** | | |
| `qwen3_asr_encoder_frontend.onnx` | [🤗 cgisky/ai00-x](https://huggingface.co/cgisky/ai00-x/tree/main/asr) | 音频特征提取前端 (~40MB) |
| `qwen3_asr_encoder_backend.onnx` | [🤗 cgisky/ai00-x](https://huggingface.co/cgisky/ai00-x/tree/main/asr) | 音频编码后端 (~350MB) |
| **GGUF 解码器** | | |
| Q4_K_M 量化 | [🤗 mradermacher/Qwen3-ASR-1.7B-GGUF](https://huggingface.co/mradermacher/Qwen3-ASR-1.7B-GGUF) | ~1.4GB，推荐集显 / 低内存 |
| Q5_K_M 量化 | 同上仓库 | ~1.6GB，推荐独显 (NVIDIA/AMD) |
| Q8_0 量化 | 同上仓库 | ~2.3GB，最佳精度，需大显存 |

> 🇨🇳 **国内用户**: 可使用 [ModelScope 镜像](https://modelscope.cn/models/qwen/Qwen3-ASR-1.7B) 或 HuggingFace 镜像站（如 `hf-mirror.com`）加速下载。
>
> 📌 **重要**: 从 HuggingFace 下载的 GGUF 文件默认命名为 `Qwen3-ASR-1.7B.Q5_K_M.gguf` 等格式。应用已支持自动识别此命名，但如果你使用旧版本，请重命名为 `qwen3_asr_llm.gguf`。
>
> ```bash
> # HuggingFace 镜像示例
> export HF_ENDPOINT=https://hf-mirror.com
> huggingface-cli download mradermacher/Qwen3-ASR-1.7B-GGUF \
>   Qwen3-ASR-1.7B.Q5_K_M.gguf --local-dir models/Qwen3-ASR-1.7B/
> ```

##### 0.6B int8 轻量引擎（sherpa-onnx）

更小更快，适合低配机器或追求低延迟的场景。

| 文件 | 下载地址 | 说明 |
|------|---------|------|
| 完整模型包 | [🤗 csukuangfj2/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25](https://huggingface.co/csukuangfj2/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25) | 包含所有 ONNX + tokenizer (~850MB) |

---

##### 硬件环境与模型匹配指南

选择合适的模型直接影响识别速度和准确度。以下是详细的匹配建议：

#### 场景一：独立显卡（NVIDIA GTX 1060+ / RTX 系列 / AMD RX 系列）

| 显存 | 推荐模型 | 量化 | 大小 | 预计识别速度 |
|------|---------|------|------|-------------|
| ≥ 6GB | **1.7B Q8_0** | 8-bit | ~2.3GB | <0.3x 实时 |
| ≥ 4GB | **1.7B Q5_K_M** | 5-bit | ~1.6GB | <0.4x 实时 |
| ≥ 2GB | **1.7B Q4_K_M** | 4-bit | ~1.4GB | <0.5x 实时 |

> 💡 独显用户建议在「设置 → GPU 加速」中选择 **DirectML**（Windows）或 **CoreML**（macOS），可大幅提升推理速度。

#### 场景二：集成显卡 / Apple Silicon（M1/M2/M3/M4）

| 内存 | 推荐模型 | 量化 | 大小 | 预计识别速度 |
|------|---------|------|------|-------------|
| ≥ 16GB | **1.7B Q5_K_M** | 5-bit | ~1.6GB | <0.5x 实时 (M系列) |
| ≥ 8GB | **1.7B Q4_K_M** | 4-bit | ~1.4GB | <0.7x 实时 (M系列) |
| 8GB | **0.6B int8** | 8-bit | ~850MB | <0.3x 实时 |

> 🍎 Apple Silicon (M1+) 用户：llama.cpp 原生支持 Metal 加速，推理效率极佳。1.7B 模型在 M2/M3 上可达实时甚至超实时识别。

#### 场景三：CPU Only / 低配机器

| 内存 | 推荐模型 | 量化 | 大小 | 预计识别速度 |
|------|---------|------|------|-------------|
| ≥ 16GB | **1.7B Q4_K_M** | 4-bit | ~1.4GB | ~1-2x 实时 |
| ≥ 8GB | **0.6B int8** | 8-bit | ~850MB | ~0.5-1x 实时 |
| 4-8GB | **0.6B int8** | 8-bit | ~850MB | ~0.8-1.5x 实时 |

> ⚠️ CPU 推理速度取决于核心数和频率。建议至少 4 核处理器。首次加载模型约需 5-15 秒（视磁盘速度）。

#### 量化级别说明

| 量化 | 比特数 | 精度保持 | 内存占用 | 适用场景 |
|------|--------|---------|---------|---------|
| **Q8_0** | 8-bit | ~99.5% | 大 | 大显存独显，追求最高精度 |
| **Q5_K_M** | 5-bit | ~98.5% | 中 | 独显 / 高性能集显，推荐日常使用 |
| **Q4_K_M** | 4-bit | ~97% | 小 | 集成显卡 / CPU，内存受限环境 |
| **int8** (sherpa) | 8-bit | — | ~850MB | 轻量级场景，低配机器 |

---

##### 📁 下载后配置

解压或下载文件后，确保 `models/` 目录结构如下：

```
caps-writer-desktop/
├── models/
│   ├── Qwen3-ASR-1.7B/               # ← 1.7B GGUF 混合引擎（推荐）
│   │   ├── qwen3_asr_encoder_frontend.onnx   # 从 cgisky/ai00-x 下载
│   │   ├── qwen3_asr_encoder_backend.onnx    # 从 cgisky/ai00-x 下载
│   │   └── qwen3_asr_llm.gguf               # 从 mradermacher/GGUF 下载（任意量化）
│   └── sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/  # 可选
│       ├── conv_frontend.onnx
│       ├── encoder.int8.onnx
│       ├── decoder.int8.onnx
│       └── tokenizer/
└── ...
```

> 📌 **多量化并存**: 可以将不同量化的 `.gguf` 文件放入同一目录（如 `Qwen3-ASR-1.7B.Q5_K_M.gguf` + `Qwen3-ASR-1.7B.Q4_K_M.gguf`）。应用会按精度从高到低搜索匹配（Q8_0 → Q5_K → Q4_K → 任意 .gguf），找到的第一个文件即为当前使用的模型。如需切换量化，重命名不需要的文件前缀即可。

> 📌 **自定义模型目录**: 如果不想将模型放在项目目录，可在「设置 → 识别引擎」中指定自定义路径。

#### 克隆并构建

```bash
# 1. 克隆仓库
git clone https://github.com/archerzing-tech/caps-writer-desktop.git
cd caps-writer-desktop

# 2. 安装前端依赖
npm install

# 3. 安装 Python 依赖（ASR 服务端，详见下方 Python 环境准备）
cd sidecar && pip install -r requirements.txt && cd ..

# 4. 开发模式运行
npm run dev

# 5. 或构建生产版本
npm run build
```

> 📦 模型下载请参见上方 [📦 模型下载来源](#-模型下载来源) 章节。

#### Python 环境准备

ASR 引擎需要 Python 运行时和相关依赖：

```bash
cd sidecar
pip install -r requirements.txt
```

> 💡 应用启动时会自动查找 `python` 命令，请确保 Python 已添加到系统 PATH。
> 首次启动时，1.7B GGUF 模型加载约需 5~10 秒（视磁盘速度而定）。
> macOS 用户需要预先编译 llama.cpp 依赖（macOS 的 `.dylib` 已预编译在 `sidecar/server/llama/` 目录下，通常无需额外操作）。

构建产物位于：`src-tauri/target/release/bundle/`

---

## 📖 使用指南

### 🎙 语音输入

1. 启动应用后，点击界面中央的**麦克风按钮**开始录音
2. 开始说话，界面会显示动态波形和录音状态
3. 再次点击麦克风停止录音，识别结果将自动显示在右侧区域
4. 点击结果条目上的 **复制** 或 **粘贴** 按钮

> **录音模式**: 点击麦克风按钮切换录音开始/停止（与原版 CapsWriter 的按住录音不同）。鼠标侧键也可触发。

#### 🔄 服务端自动启动

应用启动时，Python ASR 服务会作为子进程（sidecar）自动启动，无需手动运行。标题栏会显示连接状态：
- 🟢 **服务已连接** — ASR 引擎就绪，可正常使用
- 🟡 **启动服务中** — 正在加载模型，请稍等
- 🔴 **服务未连接** — Python 服务未启动，可点击「↻ 重试」

#### 快捷设置栏

| 开关 | 说明 |
|------|------|
| 自动粘贴 | 识别完成后自动粘贴到当前活动窗口 |
| 热词替换 | 启用自定义热词和正则规则替换 |
| LLM 润色 | 启用大语言模型对识别结果进行润色 |
| 自动翻译 | 识别完成后自动翻译（中英互译） |

### 📁 文件转录

1. 切换到 **转录** 页面
2. 拖拽音频文件到指定区域，或点击 **选择文件** 按钮
3. 支持格式：WAV、MP3、M4A、FLAC、OGG、AAC
4. 转录完成后，可导出为 **SRT**（字幕）、**TXT**（纯文本）或 **JSON** 格式

### 📋 历史记录

- 左侧按日期归档所有识别记录
- 支持**全文搜索**，输入关键词即可快速定位
- 每条记录支持复制、翻译、删除
- 右上角可**清空全部**历史

### ⚙ 设置

| 设置项 | 说明 |
|--------|------|
| 识别引擎 | Qwen3-ASR 1.7B GGUF 混合引擎 / sherpa-onnx 0.6B |
| 识别语言 | 自动检测 / 中文 / 英文 |
| GPU 加速 | CPU 或 DirectML (GPU) |
| 数字格式化 | 十五六 → 15~16 |
| 热词管理 | 编辑热词列表（支持 `原词 -> 替换词` 格式） |
| LLM 配置 | 选择 LLM 后端，配置 API 地址和密钥（**需用户自行配置，不自带 API Key**） |
| 输出设置 | 末尾标点去除、录音保存、粘贴行为 |

### 🔑 LLM API 配置

LLM 翻译和润色功能需要用户自行配置 API Key：

1. 打开 **设置 → LLM 角色**
2. 选择后端（DeepSeek / OpenAI / Ollama）
3. 填写 **API 地址**、**模型名称** 和 **API Key**
4. 点击「🔌 测试连接」验证配置
5. 保存设置

> ⚠️ **安全提示**: API Key 保存在本地配置文件中（`%APPDATA%/caps-writer-desktop/llm_config.json`），请勿将此文件分享给他人。

---

## 🗂 项目结构

```
caps-writer-desktop/
├── src/                          # 前端源码
│   ├── index.html                #   HTML 入口
│   ├── app.js                    #   主应用逻辑
│   └── styles.css                #   样式文件
├── src-tauri/                    # Rust 后端
│   ├── src/
│   │   ├── main.rs               #   应用入口
│   │   ├── lib.rs                #   Tauri 插件注册
│   │   ├── commands.rs           #   IPC 命令（录音/配置/历史/翻译）
│   │   ├── sidecar.rs            #   Python 服务进程管理
│   │   ├── state.rs              #   应用状态定义
│   │   └── tray.rs               #   系统托盘
│   ├── Cargo.toml                #   Rust 依赖
│   └── tauri.conf.json           #   Tauri 配置
├── sidecar/                      # Python ASR 服务
│   ├── caps-writer-server.py     #   服务入口
│   ├── requirements.txt          #   Python 依赖
│   └── server/
│       ├── server.py             #   WebSocket ASR 服务
│       ├── asr_engine.py         #   ASR 引擎抽象层
│       ├── qwen_asr_gguf.py      #   GGUF 混合引擎
│       ├── qwen_encoder.py       #   ONNX 音频编码器
│       ├── llama_bindings.py     #   llama.cpp ctypes 绑定
│       ├── protocol.py           #   通信协议定义
│       └── llama/                #   编译好的 llama.cpp dylib
│           ├── libllama.dylib
│           └── libggml*.dylib
├── models/                       # 预训练模型
│   ├── Qwen3-ASR-1.7B/           # 1.7B GGUF 混合引擎
│   │   ├── qwen3_asr_encoder_frontend.onnx
│   │   ├── qwen3_asr_encoder_backend.onnx
│   │   ├── qwen3_asr_llm.gguf
│   │   └── qwen3_asr_llm.q4_k.gguf
│   └── sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25/
│       ├── conv_frontend.onnx
│       ├── encoder.int8.onnx
│       ├── decoder.int8.onnx
│       └── tokenizer/
├── dist/                         # Vite 构建产物
├── package.json
└── vite.config.js
```

---

## 🔧 配置文件

应用配置存储在用户目录下：

```
%APPDATA%/caps-writer-desktop/    # Windows
~/.config/caps-writer-desktop/    # Linux/macOS
├── config.json                    # 主配置
├── llm_config.json               # LLM API 配置（含 API Key，请勿分享）
├── hotwords.txt                   # 热词列表
└── history/                       # 历史记录
    ├── 2025-07-05.json
    ├── 2025-07-04.json
    └── ...
```

---

## 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！

```bash
# Fork 并克隆
git clone https://github.com/archerzing-tech/caps-writer-desktop.git

# 创建特性分支
git checkout -b feature/amazing-feature

# 提交更改
git commit -m 'Add amazing feature'

# 推送分支
git push origin feature/amazing-feature

# 发起 Pull Request
```

### 开发调试

```bash
# 安装所有依赖
npm install
cd sidecar && pip install -r requirements.txt && cd ..

# 启动开发模式（热重载前端）
npm run dev
```

---

## 🙏 致谢

- [CapsWriter-Offline](https://github.com/HaujetZhao/CapsWriter-Offline) — 原版 CapsWriter + GGUF 混合引擎方案灵感来源
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — 备选 ASR 推理引擎
- [llama.cpp](https://github.com/ggerganov/llama.cpp) — LLM 推理框架
- [Tauri](https://tauri.app) — 跨平台桌面应用框架
- [Qwen3-ASR](https://github.com/QwenLM) — 通义千问语音识别模型

---

## 📄 许可证

本项目采用 [MIT License](LICENSE) 开源许可证。

---

<div align="center">

**如果这个项目对你有帮助，请给个 ⭐ Star 支持一下！**

</div>
