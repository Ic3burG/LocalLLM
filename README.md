# LocalLLM

An elite, high-performance, and multimodal local AI suite optimized for Apple Silicon (MLX). LocalLLM transforms your local machine into a powerful agentic workstation, capable of reasoning, vision tasks, and complex tool orchestration without ever leaving your hardware.

## 🚀 Key Features

- **Multimodal by Default**: Full vision support for Gemma 4 (4B, 26B, 31B), Phi-4 Mini, and more.
- **Agentic Layer (ReAct)**: A robust autonomous loop with 30+ tools for filesystem interaction, web research, shell execution, and Git management.
- **Deep Thinking Mode**: A "Council of Three" reasoning pipeline (Diversify, Critique, Synthesize) for tackling complex logical problems.
- **Native RAG Pipeline**: Intelligent ingestion and retrieval for PDF, Word (.docx), and Excel (.xlsx) documents.
- **Autonomous Learning**: Persistent long-term memory that adapts to your preferences and technical context over time.
- **Vitals Dashboard**: Real-time telemetry for system resources (RAM, GPU, Thermals), agent performance, and pipeline health.

## 🛠 Tool Registry (30+ Tools)

LocalLLM empowers the AI with a wide array of capabilities, including:
- **Web**: Google Search, Web Fetch, URL Validation.
- **Office**: Read/Write PDF, Word, and Excel.
- **System**: Shell execution, SQLite query, System Info, Clipboard access.
- **Development**: Git management (diff, log, status), Codebase navigation, Python interpreter.
- **Automation**: Scheduled tasks and Cron job management.

## 🏗 Architecture

- **Backend**: FastAPI (Python 3.10+) utilizing `mlx-vlm` for unified text and vision inference.
- **Proxy**: Node.js Express server for robust SSE streaming and request handling.
- **Frontend**: Clean, minimalist Web UI with Markdown rendering, syntax highlighting, and Dark/Light mode.

## 🔒 Security & Privacy

- **100% Local**: No data ever leaves your machine.
- **Sandbox Validation**: All filesystem tools are sandboxed with path validation.
- **Confirmation Gate**: Risky tools (shell, write_file, etc.) require explicit user approval before execution.

---

*Built with Gemma 4, MLX, and a lot of caffeine.*
