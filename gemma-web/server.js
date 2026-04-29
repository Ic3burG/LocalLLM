const express = require("express");
const cors = require("cors");
const axios = require("axios");
const multer = require("multer");
const FormData = require("form-data");
const http = require("http");
const { execFile, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const app = express();
const port = 3001;
const upload = multer({ storage: multer.memoryStorage() });
const LOG_FILE = path.join(__dirname, "server.log");

function log(level, msg, fields = {}) {
  const entry = JSON.stringify({ ts: new Date().toISOString(), level, msg, ...fields });
  fs.appendFileSync(LOG_FILE, entry + "\n");
  if (level === "ERROR") {
    console.error(`${new Date().toISOString()} ${level} [server] ${msg}`, Object.keys(fields).length ? fields : "");
  } else {
    console.log(`${new Date().toISOString()} ${level} [server] ${msg}`, Object.keys(fields).length ? fields : "");
  }
}

app.use(cors());
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ limit: "50mb", extended: true }));

app.post("/api/document", upload.single("file"), async (req, res) => {
  const t0 = Date.now();
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }
    const form = new FormData();
    form.append("file", req.file.buffer, {
      filename: req.file.originalname,
      contentType: req.file.mimetype || "application/pdf",
    });
    const response = await axios.post(
      "http://localhost:9379/v1/document",
      form,
      { headers: form.getHeaders() },
    );
    log("INFO", "document upload", { elapsed_ms: Date.now() - t0, filename: req.file.originalname });
    res.json(response.data);
  } catch (error) {
    log("ERROR", "document upload failed", { elapsed_ms: Date.now() - t0, error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to upload document to bridge" });
  }
});

app.post("/api/chat", async (req, res) => {
  const t0 = Date.now();
  try {
    const { messages, model, doc_ids } = req.body;
    log("INFO", "chat request", { model: model || "gemma4-e4b", msg_count: messages?.length });
    const response = await axios.post(
      "http://localhost:9379/v1/chat/completions",
      {
        model: model || "gemma4-e4b",
        messages: messages,
        doc_ids: doc_ids || [],
        stream: false,
      },
    );
    log("INFO", "chat response", { elapsed_ms: Date.now() - t0 });
    res.json(response.data);
  } catch (error) {
    log("ERROR", "chat completion failed", { elapsed_ms: Date.now() - t0, error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to connect to Gemma 4 server" });
  }
});

app.post("/api/chat/stream", async (req, res) => {
  const t0 = Date.now();
  try {
    const response = await axios.post(
      "http://localhost:9379/v1/chat/stream",
      req.body,
    );
    log("INFO", "chat stream started", { elapsed_ms: Date.now() - t0 });
    res.json(response.data);
  } catch (error) {
    log("ERROR", "chat stream start failed", { elapsed_ms: Date.now() - t0, error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to start chat stream" });
  }
});

app.get("/api/chat/stream/:taskId", (req, res) => {
  const taskId = req.params.taskId;
  const options = {
    hostname: "localhost",
    port: 9379,
    path: `/v1/agent/stream/${taskId}`,
    method: "GET",
  };
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  res.flushHeaders();
  const proxyReq = http.request(options, (proxyRes) => {
    proxyRes.pipe(res);
  });
  proxyReq.on("error", (err) => {
    log("ERROR", "SSE proxy error", { task_id: taskId, error: err.message });
    res.end();
  });
  req.on("close", () => proxyReq.destroy());
  proxyReq.end();
});

app.post("/api/title", async (req, res) => {
  try {
    const { messages } = req.body;
    const response = await axios.post("http://localhost:9379/v1/title", {
      messages,
    });
    res.json(response.data);
  } catch (error) {
    log("ERROR", "title generation failed", { error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to generate title" });
  }
});

// Agent routes

app.post("/api/agent/confirm/:taskId", async (req, res) => {
  try {
    const { taskId } = req.params;
    const response = await axios.post(
      `http://localhost:9379/v1/agent/confirm/${taskId}`,
      req.body,
    );
    res.json(response.data);
  } catch (error) {
    log("ERROR", "agent confirm failed", { task_id: req.params.taskId, error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to confirm agent task" });
  }
});

app.get("/api/agent/schedule", async (req, res) => {
  try {
    const response = await axios.get(
      "http://localhost:9379/v1/agent/schedule",
    );
    res.json(response.data);
  } catch (error) {
    log("ERROR", "fetch schedule failed", { error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to fetch agent schedule" });
  }
});

app.post("/api/agent/schedule", async (req, res) => {
  try {
    const response = await axios.post(
      "http://localhost:9379/v1/agent/schedule",
      req.body,
    );
    res.json(response.data);
  } catch (error) {
    log("ERROR", "create schedule failed", { error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to create agent schedule" });
  }
});

app.delete("/api/agent/schedule/:name", async (req, res) => {
  try {
    const { name } = req.params;
    const response = await axios.delete(
      `http://localhost:9379/v1/agent/schedule/${name}`,
    );
    res.json(response.data);
  } catch (error) {
    log("ERROR", "delete schedule failed", { name: req.params.name, error: error.message, upstream_status: error.response?.status });
    res.status(500).json({ error: "Failed to delete agent schedule" });
  }
});

app.get("/api/backend/status", async (req, res) => {
  try {
    await axios.get("http://localhost:9379/v1/models", { timeout: 3000 });
    res.json({ online: true });
  } catch {
    res.json({ online: false });
  }
});

app.post("/api/backend/restart", (req, res) => {
  const projectDir = path.resolve(__dirname, "..");
  const pythonPath = path.join(projectDir, ".venv/bin/python");
  const bridgePath = path.join(projectDir, "gemma_bridge.py");

  execFile("pkill", ["-f", "gemma_bridge.py"], () => {
    setTimeout(() => {
      const child = spawn(pythonPath, [bridgePath], {
        cwd: projectDir,
        detached: true,
        stdio: "ignore",
      });
      child.unref();
      res.json({ ok: true });
    }, 1500);
  });
});

app.listen(port, () => {
  log("INFO", "server started", { port });
});
