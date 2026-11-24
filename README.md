# ✈️ TripMate AI — Multi-Agent Travel Planner

[![Live Demo](https://img.shields.io/badge/Demo-Live%20on%20Embarko-brightgreen)](https://tripmate-ai.embarko.app)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-blue)](https://www.langchain.com/langgraph)
[![Groq](https://img.shields.io/badge/LLM-Groq-orange)](https://groq.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An intelligent, multi-agent AI travel planning assistant that transforms natural-language travel prompts into detailed, practical trip plans complete with live flight options, hotel suggestions, real-time weather forecasts, and structured day-by-day itineraries.

Built using **LangGraph**, **LangChain**, **FastAPI**, **Model Context Protocol (MCP)**, and free weather services from **Open-Meteo**.

🌐 **Live Demo:** [https://tripmate-ai.embarko.app](https://tripmate-ai.embarko.app)

---

## 🌟 Why TripMate AI?

Planning a trip usually involves context-switching across airline portals, hotel aggregators, weather forecasts, and note apps. TripMate AI brings that entire flow into a unified, autonomous agent pipeline:

```mermaid
flowchart TD
    %% Subgraph: User Input
    subgraph UI["USER INPUT"]
        User["👤 User<br/><b>TRAVEL REQUEST</b>"]
    end

    %% Subgraph: AI Agents Layer
    subgraph AGENTS["AI AGENTS"]
        FA["✈️ Flight Agent<br/><small>ROUTE & FARE SEARCH</small>"]
        HA["🏨 Hotel Agent<br/><small>AVAILABILITY & PRICING</small>"]
        WA["🌤️ Weather Agent<br/><small>FORECAST & ALERTS</small>"]
        IA["📋 Itinerary Agent<br/><small>PLAN & SCHEDULE</small>"]
        FinA["🏆 Final Agent<br/><small>FINAL RESPONSE</small>"]

        FA --> HA --> WA --> IA --> FinA
    end

    %% Subgraph: Tooling & Integrations
    subgraph TOOLS["TOOL INTEGRATIONS & LLMS"]
        T_Flight["📡 AviationStack MCP<br/><small>LOCAL / STDIO MCP</small>"]
        T_Hotel["🌐 Tavily MCP<br/><small>REMOTE HTTP MCP</small>"]
        T_Weather["⚡ Open-Meteo API<br/><small>ZERO-KEY WEATHER REST</small>"]
        T_LLM1["🤖 Groq LLM<br/><small>GENERATIVE PLANNER</small>"]
        T_LLM2["💬 Groq LLM<br/><small>RESPONSE FORMATTER</small>"]
    end

    %% Subgraph: Persistence Layer
    subgraph PERSIST["PERSISTENCE & STATE"]
        DB[("🐘 PostgreSQL / MemorySaver<br/><small>CHECKPOINTER / LONG-TERM MEMORY</small>")]
        State["🔗 Shared State<br/><small>CROSS-AGENT CONTEXT</small>"]
    end

    %% Connections
    User --> FA

    FA --- T_Flight
    HA --- T_Hotel
    WA --- T_Weather
    IA --- T_LLM1
    FinA --- T_LLM2

    T_Flight -.- State
    T_Hotel -.- DB
    T_Weather -.- State
    T_LLM1 -.- State
    T_LLM2 -.- DB

    %% Styling
    classDef userBox fill:#eef2ff,stroke:#6366f1,stroke-width:2px,color:#1e1b4b;
    classDef agentBox fill:#f0fdf4,stroke:#16a34a,stroke-width:2px,color:#14532d;
    classDef toolBox fill:#f8fafc,stroke:#0284c7,stroke-width:1.5px,color:#0f172a;
    classDef persistBox fill:#fdf4ff,stroke:#a855f7,stroke-width:2px,color:#581c87;

    class User userBox;
    class FA,HA,WA,IA,FinA agentBox;
    class T_Flight,T_Hotel,T_Weather,T_LLM1,T_LLM2 toolBox;
    class DB,State persistBox;
```

- **✈️ Flight Agent**: Uses AviationStack (via local stdio MCP / fallback) to resolve IATA codes and find live routes.
- **🏨 Hotel Agent**: Uses Tavily Remote MCP search to gather up-to-date lodging recommendations.
- **🌤️ Weather Agent**: Integrates Open-Meteo's REST API for coordinates geocoding, current conditions, and 7-day outlooks (no API key needed).
- **📝 Itinerary Agent**: Formulates a personalized, realistic day-by-day itinerary considering flight and weather context.
- **🎯 Final Synthesizer**: Formats a polished, budget-aware summary for the traveler.

---

## ⚡ Features

- **Autonomous Multi-Agent Workflow:** Orchestrated via stateful LangGraph pipelines.
- **Model Context Protocol (MCP) Integration:** Remote Streamable HTTP (Tavily) & local stdio adapters.
- **Zero-Key Weather Tracking:** Pure Python geocoding and weather/forecast lookups via Open-Meteo.
- **Robust State Persistence:** Uses PostgreSQL checkpointer with automatic fallback to in-memory `MemorySaver`.
- **FastAPI Modern Web UI:** Clean, responsive, glassmorphism UI with real-time markdown streaming and status indicators.
- **Production-Ready Hosting:** Deployable directly to managed platforms like Embarko or Docker-friendly environments with zero configuration.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/) |
| **Agent Orchestration** | [LangGraph](https://www.langchain.com/langgraph), [LangChain](https://www.langchain.com/) |
| **LLM Inference** | [Groq](https://groq.com/) (`openai/gpt-oss-20b`, `llama-3.3-70b`) |
| **Tool Protocol** | [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) (`langchain-mcp-adapters`) |
| **Search & Travel APIs** | [Tavily](https://tavily.com/), [AviationStack](https://aviationstack.com/), [Open-Meteo](https://open-meteo.com/) |
| **State & Checkpointing** | [PostgreSQL](https://www.postgresql.org/) (`psycopg[binary]`), `MemorySaver` |
| **Frontend** | HTML5, CSS3 Glassmorphism, Vanilla JavaScript |

---

## 📁 Project Structure

```text
TripMate-AI/
├── app.py                  # FastAPI server with frontend & REST endpoints
├── main.py                 # Production container entrypoint (0.0.0.0 & dynamic PORT)
├── backend.py              # LangGraph state machine, nodes, and checkpointer setup
├── mcp_client.py           # MultiServerMCPClient & Open-Meteo API integrations
├── start.bat               # Windows one-click local server launcher
├── requirements.txt        # Python dependency manifest
├── static/                 # Frontend assets (CSS styles & JavaScript client)
├── templates/              # Jinja2 index.html frontend interface
├── tools/                  # Direct fallback search & flight tooling
│   ├── flight_tool.py
│   └── tavily_tool.py
├── .env.example            # Environment variables template
└── embarko.json            # Deployment configuration
```

---

## 🚀 Quickstart & Local Setup

### 1. Clone the repository
```bash
git clone https://github.com/cartibhati/TripMate.git
cd TripMate
```

### 2. Set up virtual environment
```bash
python -m venv .venv

# On Windows:
.venv\Scripts\activate

# On macOS/Linux:
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your credentials:
```env
GROQ_API_KEY="your_groq_api_key"
AVIATIONSTACK_API_KEY="your_aviationstack_api_key"
TAVILY_API_KEY="your_tavily_api_key"
DATABASE_URL="postgresql://user:password@host/dbname?sslmode=require"
DEFAULT_ORIGIN_IATA="DAC"
```
*(Note: If `DATABASE_URL` is omitted or unavailable, TripMate AI automatically switches to ephemeral memory storage).*

### 5. Run the Application
You can run:
```bash
python app.py
```
*(On Windows, you can also simply double-click `start.bat`)*

Open your browser at:
👉 **`http://127.0.0.1:8000`**

---

## 📡 API Reference

### Health Check
```http
GET /health
```
**Response:**
```json
{
  "status": "ok",
  "message": "AI Travel Planner API is running"
}
```

### Generate Travel Plan
```http
POST /api/travel
Content-Type: application/json
```
**Request Body:**
```json
{
  "message": "Plan a 5-day trip to Tokyo from Delhi with budget hotels and top food spots",
  "thread_id": "optional_conversation_id"
}
```
**Response:**
```json
{
  "success": true,
  "thread_id": "user_...",
  "answer": "### Trip Summary\n...",
  "flight_results": "...",
  "hotel_results": "...",
  "itinerary": "...",
  "llm_calls": 4
}
```

---

## ☁️ Deployment

### Embarko (Zero-Config)
The project includes automated deployment settings for [Embarko](https://embarko.ai):
1. Install the Embarko deploy skill or script.
2. Provide your `DEPLOY_TOKEN`.
3. Add your `GROQ_API_KEY`, `TAVILY_API_KEY`, and `AVIATIONSTACK_API_KEY` under the app's **Details / Secrets** tab.
4. Your application will be live at `https://<your-app-name>.embarko.app`.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!
1. Fork the repo.
2. Create your feature branch (`git checkout -b feature/amazing-feature`).
3. Commit your changes (`git commit -m 'Add amazing feature'`).
4. Push to the branch (`git push origin feature/amazing-feature`).
5. Open a Pull Request.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
