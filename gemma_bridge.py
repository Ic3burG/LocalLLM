import asyncio
import os
import time
import uuid
import base64
import tempfile
import threading
import queue
import json
import logging
import re
from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import pdf_pipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gemma_bridge")

# ---------------------------------------------------------------------------
# Single dedicated inference thread
# ---------------------------------------------------------------------------
# mlx GPU streams are thread-local objects.  mlx_vlm creates its
# `generation_stream` at module-import time, so it must be imported — and all
# subsequent inference calls must run — on the same OS thread.  We achieve
# this with a single persistent worker thread backed by a job queue.

_inference_queue: queue.Queue = queue.Queue()

# These are populated inside the worker thread after mlx_vlm is imported there.
_mlx_vlm_load = None
_mlx_vlm_generate = None

def _inference_worker():
    """Long-lived thread that owns all mlx GPU state."""
    global _mlx_vlm_load, _mlx_vlm_generate
    # Import mlx_vlm here so that generation_stream is created in this thread.
    from mlx_vlm import load as _load, generate as _gen
    _mlx_vlm_load = _load
    _mlx_vlm_generate = _gen
    logger.info("Inference worker thread ready (mlx_vlm imported in this thread).")

    while True:
        item = _inference_queue.get()
        if item is None:
            break  # shutdown signal
        fn, args, future = item
        try:
            result = fn(*args)
            future.get_loop().call_soon_threadsafe(future.set_result, result)
        except Exception as exc:
            future.get_loop().call_soon_threadsafe(future.set_exception, exc)

_inference_thread = threading.Thread(target=_inference_worker, daemon=True, name="mlx-inference")
_inference_thread.start()


async def _run_in_inference_thread(fn, *args):
    """Submit *fn(*args)* to the inference thread and await the result."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _inference_queue.put((fn, args, future))
    return await future

app = FastAPI()

# Add CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
MLX_MODELS_DIR = os.path.join(os.getcwd(), "mlx_models")
MEMORY_FILE = os.path.join(os.getcwd(), "USER_MEMORY.md")
PORT = 9379

# Model cache: model_id -> (model, processor)
# Only accessed from the single inference thread — no lock needed.
_vlm_cache: dict = {}

_MODEL_DIR_MAP = {
    "gemma4-e4b":     "gemma-3-4b-it-4bit",
    "gemma4-26b-mlx": "gemma-4-26b-it-4bit",
    "gemma4-31b-mlx": "gemma-4-31b-it-4bit",
}

# In-memory document store: doc_id -> {filename, page_count, chunks, embeddings}
doc_store: dict = {}

def get_mlx_vlm_model(model_id: str):
    """Must only be called from the inference thread."""
    if model_id in _vlm_cache:
        return _vlm_cache[model_id]
    # No lock needed — only the inference thread calls this.
    dir_name = _MODEL_DIR_MAP.get(model_id, model_id)
    model_path = os.path.join(MLX_MODELS_DIR, dir_name)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"mlx_vlm model directory not found: {model_path}")
    logger.info(f"Loading mlx_vlm model {model_id} from {model_path}...")
    model, processor = _mlx_vlm_load(model_path)
    _vlm_cache[model_id] = (model, processor)
    return model, processor


def handle_mlx_vlm_request(model_id: str, messages: list) -> dict:
    model, processor = get_mlx_vlm_model(model_id)

    # Build clean message list; only the final message may carry an image
    clean_messages = []
    temp_image_path = None

    for i, msg in enumerate(messages):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        is_last = i == len(messages) - 1

        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            text = " ".join(text_parts)
            if is_last and temp_image_path is None:
                for c in content:
                    if c.get("type") == "image_url":
                        url = c.get("image_url", {}).get("url", "")
                        if url.startswith("data:image"):
                            try:
                                header, encoded = url.split(",", 1)
                                ext = header.split(";")[0].split("/")[1]
                                data = base64.b64decode(encoded)
                                with tempfile.NamedTemporaryFile(
                                    delete=False, suffix=f".{ext}"
                                ) as tmp:
                                    tmp.write(data)
                                    temp_image_path = tmp.name
                                logger.info(f"Saved temp image for mlx_vlm: {temp_image_path}")
                            except Exception as e:
                                logger.error(f"Failed to decode image, continuing text-only: {e}")
                            break
            clean_messages.append({"role": role, "content": text})
        else:
            clean_messages.append({"role": role, "content": content or ""})

    # Render the prompt string using the processor's chat template
    try:
        prompt = processor.apply_chat_template(
            clean_messages, tokenize=False, add_generation_prompt=True
        )
    except Exception as e:
        logger.warning(f"processor.apply_chat_template failed ({e}), trying tokenizer fallback")
        prompt = processor.tokenizer.apply_chat_template(
            clean_messages, tokenize=False, add_generation_prompt=True
        )

    has_image = temp_image_path is not None
    logger.info(f"Starting mlx_vlm inference for {model_id} (image={'yes' if has_image else 'no'})...")
    try:
        result = _mlx_vlm_generate(
            model, processor, prompt,
            image=temp_image_path,
            max_tokens=2048,
            verbose=False,
        )
    finally:
        if temp_image_path and os.path.exists(temp_image_path):
            try:
                os.remove(temp_image_path)
            except Exception:
                pass

    # mlx_vlm.generate returns a GenerationResult object; extract text
    generated_text = result.text if hasattr(result, "text") else str(result)
    return format_openai_response(model_id, generated_text)


def get_user_memory():
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return f.read()
    except Exception as e:
        logger.error(f"Error reading memory: {e}")
    return ""

def strip_thinking(text):
    """Helper to remove common thinking tags from model output"""
    # Handle Gemma 4 specific channel markers: <|channel>thought\n...<channel|>
    # We use multiple patterns to be robust to minor variations
    text = re.sub(r'<\|channel\|?>thought\n?.*?<channel\|?>', '', text, flags=re.DOTALL)
    text = re.sub(r'<\|channel\|?>thought\n?.*?<\|channel\|?>', '', text, flags=re.DOTALL)
    
    # Remove <thought>...</thought>
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    
    # Remove ***Thinking*** ...
    text = re.sub(r'\*\*\*Thinking\*\*\*.*?\*\*\*', '', text, flags=re.DOTALL)
    
    # Remove turn markers if any leaked
    text = re.sub(r'<\|turn\|?>.*', '', text)
    return text.strip()

async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — runs blocking inference in the dedicated mlx
    thread so the asyncio event loop stays responsive and mlx GPU streams remain
    valid (streams are thread-local in mlx)."""
    result = await _run_in_inference_thread(handle_mlx_vlm_request, model_id, messages)
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"run_inference: unexpected response structure: {e}") from e

from agent import router as agent_router, scheduler, load_scheduler_tasks_on_startup
app.include_router(agent_router, prefix="/v1/agent")

@app.on_event("startup")
async def startup():
    scheduler.start()
    load_scheduler_tasks_on_startup()

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
5. Output ONLY the updated Markdown content. Do NOT include any reasoning, thoughts, or preamble.
"""

        raw_content = await run_inference([{"role": "user", "content": learning_prompt}], "gemma4-e4b")
        updated_content = strip_thinking(raw_content)
        
        if updated_content.strip() and "# User Memory" in updated_content:
            # Deduplicate horizontal lines
            updated_content = re.sub(r'\n---+\n---+', '\n---', updated_content)
            with open(MEMORY_FILE, "w") as f:
                f.write(updated_content.strip())
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
                available.append({"id": model_id, "object": "model", "provider": "mlx_vlm"})
    return {"data": available}

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
                content = " ".join([c.get("text", "") for c in content if c.get("type") == "text"])
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
        raw_title = await run_inference([{"role": "user", "content": title_prompt}], "gemma4-e4b")
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
        with open(MEMORY_FILE, "w") as f:
            f.write(new_content)
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/v1/document")
async def upload_document(file: UploadFile = File(...)):
    try:
        file_bytes = await file.read()
        filename = file.filename or "document.pdf"

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

        doc_store[doc["doc_id"]] = {
            "filename": doc["filename"],
            "page_count": doc["page_count"],
            "chunks": doc["chunks"],
            "embeddings": doc["embeddings"],
        }
        logger.info(f"Indexed {filename}: {len(doc['chunks'])} chunks, doc_id={doc['doc_id']}")

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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, background_tasks: BackgroundTasks):
    try:
        body = await request.json()
        messages = body.get("messages", [])
        model_id = body.get("model", "gemma4-e4b")
        doc_ids = body.get("doc_ids", [])

        logger.info(f"Received request for model {model_id}")

        if not messages:
            return JSONResponse(content={"error": "No messages provided"}, status_code=400)

        # Inject Memory into System Prompt
        user_memory = get_user_memory()
        if user_memory:
            for msg in messages:
                if msg.get("role") == "system":
                    msg["content"] = f"{msg['content']}\n\nRELEVANT CONTEXT ABOUT THE USER:\n{user_memory}"
                    break

        # RAG: inject retrieved document chunks into system prompt
        if doc_ids:
            last_content = messages[-1].get("content", "") if messages else ""
            if isinstance(last_content, list):
                last_user_text = " ".join(
                    item.get("text", "") for item in last_content if item.get("type") == "text"
                )
            else:
                last_user_text = last_content

            chunks = pdf_pipeline.retrieve_chunks(last_user_text, doc_ids, doc_store, top_k=5)
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
            last_user_msg = " ".join([m.get("text", "") for m in last_user_msg if m.get("type") == "text"])
        
        assistant_reply = response["choices"][0]["message"]["content"]
        background_tasks.add_task(update_memory_task, last_user_msg, assistant_reply)

        return response

    except Exception as e:
        logger.error(f"Error during inference: {e}", exc_info=True)
        return JSONResponse(content={"error": str(e)}, status_code=500)

def format_openai_response(model_id, content):
    completion_id = f"chatcmpl-{uuid.uuid4()}"
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    }

if __name__ == "__main__":
    logger.info(f"Starting mlx_vlm Gemma Bridge on port {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
