# Changelog

## [0.3.0] - 2026-07-07

### Added
- 📦 详细的模型下载指南：含 HuggingFace 真实链接、ModelScope 镜像、量化级别对比
- 🖥 硬件与模型匹配指南：3 种场景（独显 / 集显 & Apple Silicon / 纯 CPU）
- 📸 macOS 截图脚本 `scripts/capture_views_macos.py`
- 🔍 GGUF 文件名自动识别：支持 HuggingFace 原始命名（`Qwen3-ASR-1.7B.Q5_K_M.gguf` 等）

### Changed
- 📝 重写 README 模型下载章节，提供完整的手动下载来源
- 🖼 更新所有 4 个视图截图（record / transcribe / history / settings）
- 🔧 `qwen_asr_gguf.py` 扩展 GGUF 文件搜索模式，兼容 HF 命名

### Fixed
- 🐛 修复 README 中重复的 pip install 命令
- 🐛 修复 README 标题层级混乱问题

## [0.2.0] - 2026-07-03

### Added
- 🎙 Qwen3-ASR 1.7B GGUF 混合引擎（ONNX 编码器 + llama.cpp LLM 解码器）
- 📁 文件转录功能（WAV/MP3/M4A/FLAC/OGG/AAC）
- 📋 历史记录（按日期归档、全文搜索）
- 🤖 LLM 润色（DeepSeek / OpenAI / Ollama）
- ⚡ GPU 加速（DirectML / CoreML）
- 🔧 系统托盘、热词管理、实时翻译

## [0.1.0] - 2026-06-23

### Added
- 🎉 初始版本
- 🎙 基础语音输入
- 🖥 Tauri 2 桌面框架
- 🐍 Python sidecar ASR 服务
