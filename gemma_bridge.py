import os
import time
import uuid
import base64
import tempfile
import threading
import json
import logging
import re
from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import litert_lm
from litert_lm import Backend
import uvicorn
import pdf_pipeline

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gemma_bridge")

# MLX-LM is loaded only when needed to save memory
mlx_lm_module = None

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
MODELS_BASE_DIR = os.path.expanduser("~/.litert-lm/models")
MLX_MODELS_DIR = os.path.join(os.getcwd(), "mlx_models")
MEMORY_FILE = os.path.join(os.getcwd(), "USER_MEMORY.md")
PORT = 9379

# Model cache
litert_engines = {}
mlx_models_cache = {}

# In-memory document store: doc_id -> {filename, page_count, chunks, embeddings}
doc_store: dict = {}

def get_litert_engine(model_id):
    if model_id in litert_engines:
        return litert_engines[model_id]
    
    model_path = os.path.join(MODELS_BASE_DIR, model_id, "model.litertlm")
    if not os.path.exists(model_path):
        if os.path.exists(os.path.join(MODELS_BASE_DIR, model_id)):
             if os.path.isfile(os.path.join(MODELS_BASE_DIR, model_id)):
                 model_path = os.path.join(MODELS_BASE_DIR, model_id)
    
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"LiteRT model file not found at {model_path}")
        
    logger.info(f"Loading LiteRT engine for {model_id}...")
    engine = litert_lm.Engine(model_path, vision_backend=Backend.CPU)
    litert_engines[model_id] = engine
    return engine

def get_mlx_model(model_id):
    global mlx_lm_module
    if mlx_lm_module is None:
        import mlx_lm
        mlx_lm_module = mlx_lm
        
    if model_id in mlx_models_cache:
        return mlx_models_cache[model_id]
    
    model_path = os.path.join(MLX_MODELS_DIR, model_id)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"MLX model directory not found at {model_path}")
        
    logger.info(f"Loading MLX model {model_id}...")
    model, tokenizer = mlx_lm_module.load(model_path)
    mlx_models_cache[model_id] = (model, tokenizer)
    return model, tokenizer

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
    # Remove <|channel|>thought...<|channel|>
    text = re.sub(r'<\|channel\|>thought.*?<\|channel\|>', '', text, flags=re.DOTALL)
    # Remove <thought>...</thought>
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    # Remove ***Thinking*** ...
    text = re.sub(r'\*\*\*Thinking\*\*\*.*?\*\*\*', '', text, flags=re.DOTALL)
    # Remove Gemma 4 specific channel markers
    text = re.sub(r'<\|channel\|>thought\n.*<channel\|>', '', text, flags=re.DOTALL)
    # Remove turn markers if any leaked
    text = re.sub(r'<\|turn\|>.*', '', text)
    return text.strip()

async def run_inference(messages: list, model_id: str = "gemma4-e4b") -> str:
    """Shared inference helper — routes to LiteRT or MLX and returns response text."""
    is_mlx = "26b" in model_id.lower() or "31b" in model_id.lower() or "mlx" in model_id.lower()
    if is_mlx:
        result = await handle_mlx_request(model_id, messages)
    else:
        result = await handle_litert_request(model_id, messages)
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

def update_memory_task(user_msg, assistant_msg):
    """Background task to learn from the interaction and update USER_MEMORY.md"""
    try:
        current_memory = get_user_memory()
        engine = get_litert_engine("gemma4-e4b")
        
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

        with engine.create_conversation() as conversation:
            response_data = conversation.send_message(learning_prompt)
            raw_content = "".join([item.get("text", "") for item in response_data.get("content", []) if item.get("type") == "text"])
            
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
    available = []
    if os.path.exists(MODELS_BASE_DIR):
        for d in os.listdir(MODELS_BASE_DIR):
            if os.path.isdir(os.path.join(MODELS_BASE_DIR, d)):
                available.append({"id": d, "object": "model", "provider": "litert"})
    if os.path.exists(MLX_MODELS_DIR):
        for d in os.listdir(MLX_MODELS_DIR):
            if os.path.isdir(os.path.join(MLX_MODELS_DIR, d)):
                available.append({"id": d, "object": "model", "provider": "mlx"})
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

        engine = get_litert_engine("gemma4-e4b")
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
        with engine.create_conversation() as conversation:
            response_data = conversation.send_message(title_prompt)
            raw_title = "".join([item.get("text", "") for item in response_data.get("content", []) if item.get("type") == "text"])
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

def process_multimodal_content(content, current_temp_files):
    if not isinstance(content, list):
        return content
    
    processed_content = []
    has_image = False
    for item in content:
        if item.get("type") == "text":
            processed_content.append({"type": "text", "text": item.get("text")})
        elif item.get("type") == "image_url":
            url = item.get("image_url", {}).get("url", "")
            if url.startswith("data:image"):
                try:
                    logger.info("Processing base64 image...")
                    header, encoded = url.split(",", 1)
                    ext = header.split(";")[0].split("/")[1]
                    data = base64.b64decode(encoded)
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
                        tmp.write(data)
                        processed_content.append({"type": "image", "path": tmp.name})
                        current_temp_files.append(tmp.name)
                        has_image = True
                        logger.info(f"Saved temp image to {tmp.name}")
                except Exception as e:
                    logger.error(f"Failed to decode image: {e}")
            else:
                processed_content.append({"type": "image", "path": url})
                has_image = True
        else:
            processed_content.append(item)
    
    # The LiteRT engine's internal chat template already inserts <|image|> tokens
    # when it encounters {"type": "image", ...} items. Injecting them manually
    # causes an INVALID_ARGUMENT: token count > image count mismatch.
    return processed_content

async def handle_litert_request(model_id, messages):
    engine = get_litert_engine(model_id)
    current_temp_files = []
    processed_messages = []
    
    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")
        if i == len(messages) - 1:
            processed_content = process_multimodal_content(content, current_temp_files)
            processed_messages.append({"role": role, "content": processed_content})
        else:
            if isinstance(content, list):
                text_content = " ".join([item.get("text", "") for item in content if item.get("type") == "text"])
                processed_messages.append({"role": role, "content": text_content})
            else:
                processed_messages.append({"role": role, "content": content})

    last_msg = processed_messages[-1]
    preface = processed_messages[:-1]

    try:
        logger.info(f"Starting LiteRT inference for {model_id}...")
        with engine.create_conversation(messages=preface) as conversation:
            # send_message requires a dict (containing role and content) or a str.
            # Passing only the content list causes a RuntimeError.
            response_data = conversation.send_message(last_msg)
            content = "".join([item.get("text", "") for item in response_data.get("content", []) if item.get("type") == "text"])
            return format_openai_response(model_id, content)
    finally:
        for f in current_temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except: pass

async def handle_mlx_request(model_id, messages):
    # mlx_lm does not support multimodal inputs; mlx_vlm is required for images.
    for m in messages:
        content = m.get("content")
        if isinstance(content, list) and any(c.get("type") == "image_url" for c in content):
            raise ValueError(
                f"Model '{model_id}' uses mlx_lm which does not support images. "
                "Use the Gemma 4 E4B (LiteRT) model for image inputs, or switch to mlx_vlm."
            )

    model, tokenizer = get_mlx_model(model_id)
    clean_messages = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            text_only = " ".join([c.get("text", "") for c in content if c.get("type") == "text"])
            clean_messages.append({"role": role, "content": text_only})
        else:
            clean_messages.append(m)
            
    prompt = tokenizer.apply_chat_template(clean_messages, tokenize=False, add_generation_prompt=True)
    logger.info(f"Starting MLX inference for {model_id}...")
    response = mlx_lm_module.generate(model, tokenizer, prompt=prompt, verbose=False, max_tokens=2048)
    return format_openai_response(model_id, response)

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
    logger.info(f"Starting Multi-Engine Gemma Bridge on port {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
