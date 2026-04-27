const express = require("express");
const cors = require("cors");
const axios = require("axios");
const multer = require("multer");
const FormData = require("form-data");

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

app.listen(port, () => {
  console.log(`Gemma Bridge running at http://localhost:${port}`);
});
