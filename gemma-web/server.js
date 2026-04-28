const express = require("express");
const cors = require("cors");
const axios = require("axios");
const multer = require("multer");
const FormData = require("form-data");
const http = require("http");

const app = express();
const port = 3001;
const upload = multer({ storage: multer.memoryStorage() });

app.use(cors());
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ limit: "50mb", extended: true }));

app.post("/api/document", upload.single("file"), async (req, res) => {
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
    res.json(response.data);
  } catch (error) {
    console.error("Error uploading document:", error.message);
    res.status(500).json({ error: "Failed to upload document to bridge" });
  }
});

app.post("/api/chat", async (req, res) => {
  try {
    const { messages, model, doc_ids } = req.body;

    const response = await axios.post(
      "http://localhost:9379/v1/chat/completions",
      {
        model: model || "gemma4-e4b",
        messages: messages,
        doc_ids: doc_ids || [],
        stream: false,
      },
    );
    res.json(response.data);
  } catch (error) {
    console.error("Error communicating with LiteRT-LM:", error.message);
    res.status(500).json({ error: "Failed to connect to Gemma 4 server" });
  }
});

app.post("/api/title", async (req, res) => {
  try {
    const { messages } = req.body;
    const response = await axios.post("http://localhost:9379/v1/title", {
      messages,
    });
    res.json(response.data);
  } catch (error) {
    console.error("Error generating title:", error.message);
    res.status(500).json({ error: "Failed to generate title" });
  }
});

// Agent routes

app.post("/api/agent/run", async (req, res) => {
  try {
    const response = await axios.post(
      "http://localhost:9379/v1/agent/run",
      req.body,
    );
    res.json(response.data);
  } catch (error) {
    console.error("Error starting agent run:", error.message);
    res.status(500).json({ error: "Failed to start agent run" });
  }
});

app.get("/api/agent/stream/:taskId", (req, res) => {
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
    console.error("SSE proxy error:", err);
    res.end();
  });
  req.on("close", () => proxyReq.destroy());
  proxyReq.end();
});

app.post("/api/agent/confirm/:taskId", async (req, res) => {
  try {
    const { taskId } = req.params;
    const response = await axios.post(
      `http://localhost:9379/v1/agent/confirm/${taskId}`,
      req.body,
    );
    res.json(response.data);
  } catch (error) {
    console.error("Error confirming agent task:", error.message);
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
    console.error("Error fetching agent schedule:", error.message);
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
    console.error("Error creating agent schedule:", error.message);
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
    console.error("Error deleting agent schedule:", error.message);
    res.status(500).json({ error: "Failed to delete agent schedule" });
  }
});

app.listen(port, () => {
  console.log(`Gemma Bridge running at http://localhost:${port}`);
});
