import asyncio
import json
import logging
import os
import re
import subprocess
import time
import uuid
import uuid as _uuid

import psutil
import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

try:
    import mlx.core as mx
except ImportError:
    mx = None
try:
    from huggingface_hub.errors import GatedRepoError as _GatedRepoError
except ImportError:
    _GatedRepoError = None
import image_pipeline
import pdf_pipeline
from agent_utils import (
    AGENT_SYSTEM_PROMPT,
)
from inference_engine import (
    _MODEL_DIR_MAP,
    MLX_MODELS_DIR,
    format_openai_response,
    get_avg_latency,
    get_loaded_models,
    run_inference,
)
from logging_config import setup_logging, task_id_var
from secrets_filter import redact_secrets

setup_logging()
logger = logging.getLogger("gemma_bridge")

app = FastAPI()

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        parts = request.url.path.split("/")
        task_id = ""
        if "stream" in parts:
            idx = parts.index("stream")
            if idx + 1 < len(parts):
                task_id = parts[idx + 1]
        if not task_id:
            task_id = str(_uuid.uuid4())[:8]

        token = task_id_var.set(task_id)
        t0 = time.monotonic()
        try:
            response = await call_next(request)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.info(
                "http request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
            return response
        except Exception:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "http request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "elapsed_ms": elapsed_ms,
                },
                exc_info=True,
            )
            raise
        finally:
            task_id_var.reset(token)


app.add_middleware(RequestLoggingMiddleware)

# Configuration
MEMORY_FILE = os.path.join(os.getcwd(), "USER_MEMORY.md")
PORT = 9379

_current_process = psutil.Process(os.getpid())

# In-memory document store: doc_id -> {filename, page_count, chunks, embeddings}
doc_store: dict = {}

# Pipeline telemetry accumulators
_ingestion_times = []
_embedding_latencies_ms = []


def record_ingestion_time(duration_s: float):
    _ingestion_times.append(duration_s)
    if len(_ingestion_times) > 20:
        _ingestion_times.pop(0)


def record_embedding_latency(latency_ms: float):
    _embedding_latencies_ms.append(latency_ms)
    if len(_embedding_latencies_ms) > 50:
        _embedding_latencies_ms.pop(0)


def get_thermal_pressure():
    """Get macOS thermal pressure level."""
    try:
        # 0=Nominal, 1=Fair, 2=Serious, 3=Critical
        result = subprocess.run(
            ["sysctl", "-n", "kern.thermal_level"],
            capture_output=True,
            text=True,
            check=True,
        )
        level = int(result.stdout.strip())
        mapping = {0: "nominal", 1: "fair", 2: "serious", 3: "critical"}
        return mapping.get(level, "unknown")
    except Exception:
        return "nominal"  # Default if not on macOS or sysctl fails


def get_user_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return f.read()
    except Exception as e:
        logger.error(f"Error reading memory: {e}")
    return ""


def write_user_memory(content: str):
    """Write USER_MEMORY.md atomically with a guaranteed trailing newline.

    Both writers (background learner + manual save) route through here so
    prettier --check stays green; otherwise the file ends without a newline
    and CI fails on every run that observes it.
    """
    # Guard: strip any credentials/secrets the learner may have captured before
    # they are persisted to a file that can be synced or committed.
    safe = redact_secrets(content or "")
    normalized = safe.rstrip("\n") + "\n"
    with open(MEMORY_FILE, "w") as f:
        f.write(normalized)


def strip_thinking(text):
    """Helper to remove common thinking tags from model output"""
    # Handle Gemma 4 specific channel markers: <|channel>thought\n...<channel|>
    # We use multiple patterns to be robust to minor variations
    text = re.sub(r"<\|channel\|?>thought\n?.*?<channel\|?>", "", text, flags=re.DOTALL)
    text = re.sub(
        r"<\|channel\|?>thought\n?.*?<\|channel\|?>", "", text, flags=re.DOTALL
    )

    # Remove <thought>...</thought>
    text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL)

    # Remove ***Thinking*** ...
    text = re.sub(r"\*\*\*Thinking\*\*\*.*?\*\*\*", "", text, flags=re.DOTALL)

    # Remove turn markers if any leaked
    text = re.sub(r"<\|turn\|?>.*", "", text)
    return text.strip()


from agent import (
    confirm_queues,
    load_scheduler_tasks_on_startup,
    react_loop_sse,
    scheduler,
    sse_queues,
)
from agent import router as agent_router
from agent_utils import TelemetryManager

app.include_router(agent_router, prefix="/v1/agent")


@app.on_event("startup")
async def startup():
    scheduler.start()
    load_scheduler_tasks_on_startup()


@app.get("/v1/system_prompt")
async def get_system_prompt_endpoint():
    return {"system_prompt": AGENT_SYSTEM_PROMPT}


async def update_memory_task(user_msg, assistant_msg):
    """Background task to learn from the interaction and update USER_MEMORY.md"""
    try:
        current_memory = get_user_memory()

        learning_prompt = f"""You are a specialized Memory Subagent. Your task is to update a User Memory file based on a new interaction.
        
CURRENT MEMORY FILE:
---
{current_memory}
---

NEW INTERACTION:
User: {user_msg}
Assistant: {assistant_msg}

INSTRUCTIONS:
1. Identify any new facts, preferences, or technical context about the user.
2. If new information exists, integrate it into the appropriate section of the Memory File.
3. Keep the same Markdown format. Use only H1, H3, and list items.
4. If no meaningful new info is found, output the EXACT same Memory File.
5. NEVER record secrets or credentials — passwords, API keys/tokens, private keys, one-time/verification codes, SSNs, or full card numbers. Omit them entirely.
6. Output ONLY the updated Markdown content. Do NOT include any reasoning, thoughts, or preamble.
"""

        raw_content = await run_inference(
            [{"role": "user", "content": learning_prompt}], "gemma4-e4b"
        )
        updated_content = strip_thinking(raw_content)

        if updated_content.strip() and "# User Memory" in updated_content:
            # Strip wrapping code fences the model sometimes adds
            updated_content = re.sub(r"^```\w*\n", "", updated_content)
            updated_content = re.sub(r"\n```$", "", updated_content)
            # Deduplicate horizontal lines
            updated_content = re.sub(r"\n---+\n---+", "\n---", updated_content)
            write_user_memory(updated_content.strip())
            logger.info("Memory updated successfully.")

    except Exception as e:
        logger.error(f"Memory update failed: {e}")


@app.get("/v1/models")
async def list_models():
    _reverse_map = {v: k for k, v in _MODEL_DIR_MAP.items()}
    available = []
    if os.path.exists(MLX_MODELS_DIR):
        for d in os.listdir(MLX_MODELS_DIR):
            if os.path.isdir(os.path.join(MLX_MODELS_DIR, d)):
                model_id = _reverse_map.get(d, d)
                available.append(
                    {"id": model_id, "object": "model", "provider": "mlx_vlm"}
                )
    return {"data": available}


@app.get("/v1/stats")
async def get_stats():
    """Exposes system, agent, and pipeline telemetry."""
    # 1. System Telemetry
    try:
        ram_usage_mb = _current_process.memory_info().rss / (1024 * 1024)
    except Exception:
        ram_usage_mb = 0

    vram_usage_gb = 0
    if mx is not None:
        try:
            if hasattr(mx, "get_active_memory"):
                vram_usage_gb = mx.get_active_memory() / (1024 * 1024 * 1024)
            elif hasattr(mx, "metal") and hasattr(mx.metal, "get_active_memory"):
                vram_usage_gb = mx.metal.get_active_memory() / (1024 * 1024 * 1024)
        except Exception as e:
            logger.warning(f"Failed to gather MLX memory stats: {e}")

    system_block = {
        "ram_mb": round(ram_usage_mb, 2),
        "vram_gb": round(vram_usage_gb, 2),
        "cpu_percent": psutil.cpu_percent(),
        "thermal_pressure": get_thermal_pressure(),
        "latency_ms": round(get_avg_latency(), 2),
        "models": get_loaded_models(),
    }

    # 2. Agent Telemetry
    agent_block = TelemetryManager().get_stats()

    # 3. Pipeline Telemetry
    total_chunks = sum(len(doc["chunks"]) for doc in doc_store.values())
    avg_ingestion_s = (
        sum(_ingestion_times) / len(_ingestion_times) if _ingestion_times else 0
    )
    avg_embedding_ms = (
        sum(_embedding_latencies_ms) / len(_embedding_latencies_ms)
        if _embedding_latencies_ms
        else 0
    )

    pipeline_block = {
        "doc_count": len(doc_store),
        "chunk_count": total_chunks,
        "ingestion_avg_s": round(avg_ingestion_s, 3),
        "embedding_latency_ms": round(avg_embedding_ms, 2),
    }

    return {"system": system_block, "agent": agent_block, "pipeline": pipeline_block}


@app.get("/v1/memory")
async def get_memory_endpoint():
    return {"memory": get_user_memory()}


@app.post("/v1/title")
async def generate_title(request: Request):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        if not messages:
            return {"title": "New Chat"}

        # We only need the first few messages for a title
        conversation_context = ""
        for msg in messages[:5]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    [c.get("text", "") for c in content if c.get("type") == "text"]
                )
            conversation_context += f"{role}: {content}\n"

        title_prompt = f"""You are a Title Generator Subagent.
Summarize the following conversation into a VERY concise, catchy title (MAX 5 WORDS).

CONVERSATION:
{conversation_context}

INSTRUCTIONS:
- Be descriptive but brief.
- Avoid generic titles like "Chat about..." or "User question".
- Output ONLY the title text.
- No quotes, no preamble, no thinking.
"""
        raw_title = await run_inference(
            [{"role": "user", "content": title_prompt}], "gemma4-e4b"
        )
        title = strip_thinking(raw_title).strip().strip('"').strip("'")

        # If model fails or produces empty, fallback
        if not title:
            title = "New Chat"
        return {"title": title}
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        return {"title": "New Chat"}


@app.put("/v1/memory")
async def update_memory_manual(request: Request):
    try:
        body = await request.json()
        new_content = body.get("memory", "")
        write_user_memory(new_content)
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/v1/document")
async def upload_document(file: UploadFile = File(...)):
    try:
        t0 = time.monotonic()
        file_bytes = await file.read()
        filename = file.filename or "document.pdf"

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext in ("docx", "xlsx"):
            import office_pipeline

            doc = office_pipeline.ingest_office(file_bytes, filename)
        else:
            doc = pdf_pipeline.ingest_pdf(file_bytes, filename)

        if doc is None:
            return JSONResponse(
                content={
                    "doc_id": None,
                    "filename": filename,
                    "page_count": 0,
                    "chunk_count": 0,
                    "warnings": ["no_text_found"],
                },
                status_code=200,
            )

        ingestion_time = time.monotonic() - t0
        record_ingestion_time(ingestion_time)
        if "embedding_latency_ms" in doc:
            record_embedding_latency(doc["embedding_latency_ms"])

        doc_store[doc["doc_id"]] = {
            "filename": doc["filename"],
            "page_count": doc["page_count"],
            "chunks": doc["chunks"],
            "embeddings": doc["embeddings"],
        }
        logger.info(
            f"Indexed {filename}: {len(doc['chunks'])} chunks, doc_id={doc['doc_id']}"
        )

        return {
            "doc_id": doc["doc_id"],
            "filename": doc["filename"],
            "page_count": doc["page_count"],
            "chunk_count": len(doc["chunks"]),
            "warnings": [],
        }
    except Exception as e:
        logger.error(f"Document ingestion failed: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/v1/rag/search")
async def rag_search(request: Request):
    body = await request.json()
    query = body.get("query", "")
    top_k = int(body.get("top_k", 5))
    doc_ids = list(doc_store.keys())
    if not doc_ids:
        return {"results": "", "count": 0}
    loop = asyncio.get_running_loop()
    chunks, _ = await loop.run_in_executor(
        None,
        lambda: pdf_pipeline.retrieve_chunks(query, doc_ids, doc_store, top_k=top_k),
    )
    return {
        "results": pdf_pipeline.build_numbered_document_context(chunks),
        "count": len(chunks),
    }


@app.post("/v1/image/generate")
async def generate_image_route(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "prompt_required"}, status_code=400)
    size = body.get("size", "512x512")
    steps = int(body.get("steps", 4))
    style = body.get("style", "default")

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: image_pipeline.generate_image(prompt, size, steps, style),
            ),
            timeout=120.0,
        )
        return JSONResponse(result)
    except asyncio.TimeoutError:
        return JSONResponse({"error": "timeout"}, status_code=504)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except FileNotFoundError:
        return JSONResponse({"error": "model_not_found"}, status_code=503)
    except ImportError as e:
        logger.error("image backend unavailable: %s", e, exc_info=True)
        return JSONResponse({"error": "image_backend_unavailable"}, status_code=503)
    except MemoryError:
        return JSONResponse({"error": "insufficient_memory"}, status_code=507)
    except Exception as e:
        if _GatedRepoError is not None and isinstance(e, _GatedRepoError):
            logger.error("image model access denied: %s", e)
            return JSONResponse({"error": "model_access_denied"}, status_code=403)
        logger.error("image generation failed: %s", e, exc_info=True)
        return JSONResponse({"error": "generation_failed"}, status_code=500)


@app.get("/v1/image/models")
async def image_models_route():
    downloaded = image_pipeline.get_downloaded_models()
    return JSONResponse({"available": ["flux-schnell"], "downloaded": downloaded})


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        model_id = body.get("model", "gemma4-e4b")
        doc_ids = body.get("doc_ids", [])

        logger.info(f"Received request for model {model_id}")

        if not messages:
            return JSONResponse(
                content={"error": "No messages provided"}, status_code=400
            )

        # Inject Memory into System Prompt
        user_memory = get_user_memory()
        if user_memory:
            for msg in messages:
                if msg.get("role") == "system":
                    msg["content"] = (
                        f"{msg['content']}\n\nRELEVANT CONTEXT ABOUT THE USER:\n{user_memory}"
                    )
                    break

        # RAG: inject retrieved document chunks into system prompt
        if doc_ids:
            last_content = messages[-1].get("content", "") if messages else ""
            if isinstance(last_content, list):
                last_user_text = " ".join(
                    item.get("text", "")
                    for item in last_content
                    if item.get("type") == "text"
                )
            else:
                last_user_text = last_content

            chunks, emb_latency = pdf_pipeline.retrieve_chunks(
                last_user_text, doc_ids, doc_store, top_k=5
            )
            record_embedding_latency(emb_latency)
            if chunks:
                context_block = pdf_pipeline.build_document_context(chunks)
                system_injected = False
                for msg in messages:
                    if msg.get("role") == "system":
                        msg["content"] = f"{context_block}\n\n{msg['content']}"
                        system_injected = True
                        break
                if not system_injected:
                    messages.insert(0, {"role": "system", "content": context_block})

        # Decide which engine to use
        content = await run_inference(messages, model_id)
        response = format_openai_response(model_id, content)

        # Trigger background learning
        last_user_msg = messages[-1].get("content")
        if isinstance(last_user_msg, list):
            last_user_msg = " ".join(
                [m.get("text", "") for m in last_user_msg if m.get("type") == "text"]
            )

        assistant_reply = response["choices"][0]["message"]["content"]
        background_tasks.add_task(update_memory_task, last_user_msg, assistant_reply)

        return response

    except Exception as e:
        logger.error(f"Error during inference: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/v1/chat/stream")
async def chat_stream(request: Request):
    """
    Unified streaming endpoint.
    Standard chat messages that can trigger tools via ReAct loop.
    """
    try:
        body = await request.json()
        messages = body.get("messages", [])
        model_id = body.get("model", "gemma4-e4b")
        doc_ids = body.get("doc_ids", [])
        deep_think = body.get("deep_think", False)

        if not messages:
            return JSONResponse(
                content={"error": "No messages provided"}, status_code=400
            )

        # Inject Memory into System Prompt
        user_memory = get_user_memory()
        if user_memory:
            system_injected = False
            for msg in messages:
                if msg.get("role") == "system":
                    msg["content"] = (
                        f"{msg['content']}\n\nRELEVANT CONTEXT ABOUT THE USER:\n{user_memory}"
                    )
                    system_injected = True
                    break
            if not system_injected:
                messages.insert(
                    0,
                    {
                        "role": "system",
                        "content": f"RELEVANT CONTEXT ABOUT THE USER:\n{user_memory}",
                    },
                )

        # RAG: inject retrieved document chunks into system prompt
        pending_rag_sources: list[dict] = []
        if doc_ids:
            last_content = messages[-1].get("content", "") if messages else ""
            if isinstance(last_content, list):
                last_user_text = " ".join(
                    item.get("text", "")
                    for item in last_content
                    if item.get("type") == "text"
                )
            else:
                last_user_text = last_content

            chunks, emb_latency = pdf_pipeline.retrieve_chunks(
                last_user_text, doc_ids, doc_store, top_k=5
            )
            record_embedding_latency(emb_latency)
            if chunks:
                context_block = pdf_pipeline.build_numbered_document_context(chunks)
                system_injected = False
                for msg in messages:
                    if msg.get("role") == "system":
                        msg["content"] = f"{context_block}\n\n{msg['content']}"
                        system_injected = True
                        break
                if not system_injected:
                    messages.insert(0, {"role": "system", "content": context_block})

                from citations import assign_indices

                rag_sources = pdf_pipeline.chunks_to_sources(chunks)
                pending_rag_sources = assign_indices(rag_sources, existing_count=0)

        # Start ReAct loop as background task
        task_id = str(uuid.uuid4())
        sse_queues[task_id] = asyncio.Queue()
        confirm_queues[task_id] = asyncio.Queue()

        if pending_rag_sources:
            await sse_queues[task_id].put(
                json.dumps({"type": "sources", "items": pending_rag_sources})
            )

        asyncio.create_task(
            react_loop_sse(task_id, messages, model_id, deep_think=deep_think)
        )

        return {"task_id": task_id}

    except Exception as e:
        logger.error(f"Error in chat_stream: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)


if __name__ == "__main__":
    logger.info(f"Starting mlx_vlm Gemma Bridge on port {PORT}...")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_config=None)
