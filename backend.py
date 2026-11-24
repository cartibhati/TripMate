import os 
import certifi
from dotenv import load_dotenv

load_dotenv()

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import TypedDict, Annotated
import operator
import uuid
import asyncio
import psycopg
from psycopg.rows import dict_row

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
# from tools.tavily_tool import tavily_search
# from tools.flight_tool import search_flights
from mcp_client import tavily_mcp_search, aviation_mcp_call, extract_destination, forecast_mcp_search, weather_mcp_search


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def extract_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                texts.append(item["text"])
            elif isinstance(item, str):
                texts.append(item)
            elif hasattr(item, "text"):
                texts.append(getattr(item, "text"))
            else:
                texts.append(str(item))
        return "".join(texts)
    return str(content)


# =========================
# LLM (Ultra-Fast Groq LPU + Gemini Fallback Chain)
# =========================

def build_llm(temperature=0.7):
    models = []

    if GROQ_API_KEY:
        models.append(
            ChatGroq(
                model="qwen/qwen3.8-27b",
                api_key=GROQ_API_KEY,
                temperature=temperature,
                max_retries=1,
            )
        )
        models.append(
            ChatGroq(
                model="openai/gpt-oss-20b",
                api_key=GROQ_API_KEY,
                temperature=temperature,
                max_retries=1,
            )
        )

    if GEMINI_API_KEY:
        models.append(
            ChatGoogleGenerativeAI(
                model="gemini-flash-lite-latest",
                google_api_key=GEMINI_API_KEY,
                temperature=temperature,
                max_retries=0,
            )
        )
        models.append(
            ChatGoogleGenerativeAI(
                model="gemini-3.5-flash-lite",
                google_api_key=GEMINI_API_KEY,
                temperature=temperature,
                max_retries=0,
            )
        )

    if not models:
        print("Warning: Neither GROQ_API_KEY nor GEMINI_API_KEY found.")
        return ChatGroq(
            model="qwen/qwen3.8-27b",
            api_key="dummy_key"
        )

    if len(models) == 1:
        return models[0]

    return models[0].with_fallbacks(models[1:])


llm = build_llm(temperature=0.7)


# =========================
# State
# =========================

class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: Annotated[int, operator.add]
    weather_results: str


# =========================
# Flight Agent
# =========================

# def flight_agent(state: TravelState):
#     query = state["user_query"]
#     flight_data = search_flights(query)

#     return {
#         "flight_results": flight_data,
#         "messages": [
#             AIMessage(content="Flight results fetched.")
#         ],
#         "llm_calls": state.get("llm_calls", 0) + 1
#     }




# Flight Tool Router Prompt
FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

Generate:

1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""




# =========================
# Flight Agent (Instant Local Airport Resolution)
# =========================

def flight_agent(state: TravelState):
    query = state["user_query"]
    dest = extract_destination(query)
    flight_data = (
        f"Flight Route Guidance for {query}:\n"
        f"- Destination Hub: {dest}\n"
        f"- Recommendations: Search major international and regional carriers serving {dest}. "
        f"Compare aggregators like Google Flights, Skyscanner, or Kayak for real-time fare alerts."
    )

    return {
        "flight_results": flight_data
    }


# =========================
# Hotel Agent (Fast Direct Search)
# =========================

def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    hotel_results = ""
    try:
        from tools.tavily_tool import tavily_search
        hotel_results = tavily_search(query)
    except Exception as e:
        print(f"Tavily search error ({e}). Trying MCP or fallback...")
        try:
            hotel_results = asyncio.run(tavily_mcp_search(query))
        except Exception:
            hotel_results = f"Hotel recommendations for {state['user_query']}: Top rated hotels and boutique stays."

    return {
        "hotel_results": hotel_results
    }


# =========================
# Weather Agent (Combined Single REST Call)
# =========================

def weather_agent(state: TravelState):
    try:
        city = extract_destination(state["user_query"])
        weather_results = asyncio.run(weather_mcp_search(city))
    except Exception as e:
        print(f"Weather lookup error: {e}")
        weather_results = "Weather information currently unavailable."

    return {
        "weather_results": weather_results
    }


# =========================
# Final Response Agent (Single-Pass Comprehensive Plan)
# =========================

def final_agent(state: TravelState):
    final_prompt = f"""
Generate the complete travel response for the user.

User Request:
{state['user_query']}

Flight Information:
{state['flight_results']}

Hotel Suggestions:
{state['hotel_results']}

Weather Information:
{state['weather_results']}

Format the final answer beautifully using these sections:

1. Trip Summary
2. Flight Information (Recommended routes, airports, and booking advice)
3. Hotel Suggestions
4. Weather Information & Travel Advice
5. Day-by-Day Itinerary (Morning, Afternoon, Evening activities)
6. Estimated Budget
7. Final Recommendations & Practical Travel Tips

Important:
- Be clear, practical, inspiring, and concise.
- Include weather-based travel and packing advice.
"""

    response = llm.invoke([
        SystemMessage(content="You are a professional AI travel booking assistant."),
        HumanMessage(content=final_prompt)
    ])
    clean_final = extract_text(response.content)

    return {
        "itinerary": clean_final,
        "messages": [AIMessage(content=clean_final)],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


# =========================
# Build Graph (Parallel Fan-Out / Fan-In)
# =========================

graph = StateGraph(TravelState)

graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("final_agent", final_agent)

# Fan-Out: Run flight, hotel, and weather concurrently
graph.add_edge(START, "flight_agent")
graph.add_edge(START, "hotel_agent")
graph.add_edge(START, "weather_agent")

# Fan-In: Wait for all 3 agents to finish, then synthesize
graph.add_edge("flight_agent", "final_agent")
graph.add_edge("hotel_agent", "final_agent")
graph.add_edge("weather_agent", "final_agent")
graph.add_edge("final_agent", END)


# =========================
# Checkpointer Setup
# =========================
DATABASE_URL = os.getenv("DATABASE_URL")
checkpointer = None

if DATABASE_URL:
    try:
        if "sslmode=" not in DATABASE_URL:
            separator = "&" if "?" in DATABASE_URL else "?"
            DATABASE_URL = f"{DATABASE_URL}{separator}sslmode=require"

        _conn = psycopg.connect(
            DATABASE_URL,
            autocommit=True,
            row_factory=dict_row
        )
        checkpointer = PostgresSaver(_conn)
        checkpointer.setup()
    except Exception as e:
        print(f"Warning: Failed to connect to PostgreSQL ({e}). Falling back to MemorySaver.")
        checkpointer = MemorySaver()
else:
    checkpointer = MemorySaver()

travel_graph = graph.compile(checkpointer=checkpointer)



# =========================
# Function for FastAPI
# =========================

def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = travel_graph.invoke(
        {
            "messages": [
                HumanMessage(content=user_input)
            ],
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )

    final_answer = result["messages"][-1].content

    return {
        "thread_id": thread_id,
        "answer": final_answer,
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "itinerary": result.get("itinerary", ""),
        "llm_calls": result.get("llm_calls", 0),
    }