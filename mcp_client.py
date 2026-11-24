import os
import sys
import shutil
import asyncio
from pathlib import Path

import certifi
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI


# ==========================================
# Environment configuration
# ==========================================

os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
AVIATION_STACK_API_KEY = os.getenv("AVIATIONSTACK_API_KEY")
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


# Preserve the complete Windows environment when starting
# local stdio MCP servers.
AVIATION_ENV = os.environ.copy()
AVIATION_ENV["AVIATION_STACK_API_KEY"] = (
    AVIATION_STACK_API_KEY or ""
)


# ==========================================
# LLM (Ultra-Fast Groq LPU + Gemini Fallback Chain)
# ==========================================

def build_llm(temperature=0.2):
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

    if GEMINI_API_KEY:
        models.append(
            ChatGoogleGenerativeAI(
                model="gemini-flash-lite-latest",
                google_api_key=GEMINI_API_KEY,
                temperature=temperature,
                max_retries=0,
            )
        )

    if not models:
        return ChatGroq(
            model="qwen/qwen3.8-27b",
            api_key="dummy_key"
        )

    if len(models) == 1:
        return models[0]

    return models[0].with_fallbacks(models[1:])


llm = build_llm(temperature=0.2)


# ==========================================
# MCP client configuration
# ==========================================

client = MultiServerMCPClient(
    {
        "tavily": {
            "transport": "streamable_http",
            "url": (
                "https://mcp.tavily.com/mcp/"
                f"?tavilyApiKey={TAVILY_API_KEY}"
            )
        },

        "aviationstack": {
            "transport": "stdio",
            "command": "uvx",
            "args": [
                "aviationstack-mcp"
            ],
            "env": AVIATION_ENV
        }
    }
)


# ==========================================
# Diagnostic function
# ==========================================

async def get_all_tools():
    """
    Load each MCP server separately.

    A broken server will no longer prevent the other
    working servers from loading.
    """

    all_tools = []

    for server_name in (
        "tavily",
        "aviationstack",
        "weather"
    ):
        try:
            tools = await client.get_tools(
                server_name=server_name
            )

            all_tools.extend(tools)

            print(
                f"\nAvailable tools from "
                f"{server_name} MCP:\n"
            )

            for tool in tools:
                print(tool.name)

        except Exception as error:
            print(
                f"\nCould not connect to "
                f"{server_name} MCP:\n{error}\n"
            )

    return all_tools


# ==========================================
# Tavily MCP tool
# ==========================================

search_tool = None


async def initialize_mcp():
    """
    Initialize only Tavily.

    Previously this function initialized all MCP servers,
    so an AviationStack or Weather failure also caused
    Tavily hotel search to fail.
    """

    global search_tool

    if search_tool is not None:
        return

    tools = await client.get_tools(
        server_name="tavily"
    )

    tools_by_name = {
        tool.name: tool
        for tool in tools
    }

    search_tool = tools_by_name.get(
        "tavily_search"
    )

    if search_tool is None:
        available_tools = ", ".join(
            tools_by_name.keys()
        )

        raise RuntimeError(
            "Tavily MCP connected, but the "
            "'tavily_search' tool was not found. "
            f"Available tools: "
            f"{available_tools or 'none'}"
        )


async def tavily_mcp_search(query: str):
    try:
        await asyncio.wait_for(initialize_mcp(), timeout=6.0)
        if search_tool is not None:
            result = await asyncio.wait_for(
                search_tool.ainvoke({"query": query}),
                timeout=8.0
            )
            return result
    except Exception as e:
        print(f"Tavily MCP search failed or timed out: {e}")

    # Fallback to direct Tavily SDK
    try:
        from tools.tavily_tool import tavily_search
        return tavily_search(query)
    except Exception as e2:
        print(f"Tavily SDK fallback failed: {e2}")
        return f"Hotel and attraction options for {query}."


# ==========================================
# AviationStack MCP tools
# ==========================================

aviation_tools = {}


async def initialize_aviation_tools():
    global aviation_tools

    if aviation_tools:
        return

    if not shutil.which("uvx"):
        print("Notice: 'uvx' not found in system PATH. Skipping AviationStack stdio MCP.")
        return

    try:
        tools = await asyncio.wait_for(
            client.get_tools(server_name="aviationstack"),
            timeout=5.0
        )
        aviation_tools = {tool.name: tool for tool in tools}
    except Exception as e:
        print(f"Warning: AviationStack MCP initialization failed: {e}")


async def aviation_mcp_call(
    tool_name: str,
    tool_args: dict = None
):
    if not shutil.which("uvx"):
        return f"AviationStack stdio tool unavailable (uvx not installed)."

    await initialize_aviation_tools()

    tool = aviation_tools.get(tool_name)

    if tool is None:
        return f"AviationStack tool '{tool_name}' not available."

    try:
        result = await asyncio.wait_for(
            tool.ainvoke(tool_args or {}),
            timeout=5.0
        )
        return result
    except Exception as e:
        return f"Aviation tool error: {e}"


# ==========================================
# Open-Meteo Weather Tools (Combined Single HTTP Call)
# No API key required, pure Python requests.
# Works in any environment (including Docker/Embarko)
# ==========================================

import requests

def _get_coordinates(location_name: str):
    try:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": location_name, "count": 1, "language": "en", "format": "json"}
        res = requests.get(url, params=params, timeout=5)
        data = res.json()
        if "results" in data and len(data["results"]) > 0:
            loc = data["results"][0]
            return loc.get("latitude"), loc.get("longitude"), loc.get("name"), loc.get("country", "")
    except Exception as e:
        print(f"Geocoding error for {location_name}: {e}")
    return None, None, location_name, ""


def get_weather_and_forecast(location: str):
    """
    Fetch both current weather and 7-day daily forecast in a single HTTP request (~0.3s).
    """
    lat, lon, name, country = _get_coordinates(location)
    if lat is None or lon is None:
        return f"Weather information currently unavailable for '{location}'."

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "wind_speed_10m"],
            "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"],
            "timezone": "auto"
        }
        res = requests.get(url, params=params, timeout=6)
        data = res.json()
        curr = data.get("current", {})
        units = data.get("current_units", {})
        temp = curr.get("temperature_2m", "N/A")
        t_unit = units.get("temperature_2m", "°C")
        humidity = curr.get("relative_humidity_2m", "N/A")
        feels_like = curr.get("apparent_temperature", "N/A")
        wind = curr.get("wind_speed_10m", "N/A")
        w_unit = units.get("wind_speed_10m", "km/h")

        daily = data.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        rain_prob = daily.get("precipitation_probability_max", [])

        lines = [
            f"Current Weather in {name}, {country}:",
            f"- Temperature: {temp}{t_unit} (Feels like: {feels_like}{t_unit})",
            f"- Humidity: {humidity}%, Wind: {wind} {w_unit}",
            f"\n5-Day Forecast:"
        ]
        for i in range(min(5, len(dates))):
            date = dates[i]
            t_max = max_temps[i] if i < len(max_temps) else "N/A"
            t_min = min_temps[i] if i < len(min_temps) else "N/A"
            rain = rain_prob[i] if i < len(rain_prob) else "N/A"
            lines.append(f"- {date}: High {t_max}°C / Low {t_min}°C (Rain {rain}%)")

        return "\n".join(lines)
    except Exception as e:
        return f"Weather lookup failed for {location}: {e}"


async def weather_mcp_search(city: str):
    return get_weather_and_forecast(city)


async def forecast_mcp_search(city: str):
    return ""


# ==========================================
# Fast Destination Extractor (Regex + Fallback)
# ==========================================

import re

def extract_destination(query: str):
    """
    Sub-millisecond regex extraction for common trip queries,
    with an LLM fallback only when necessary.
    """
    patterns = [
        r'(?:trip to|travel to|vacation in|visit|flying to|going to|tour to|in)\s+([A-Za-z\s]+?)(?:\s+(?:from|for|including|with|under|in [0-9]|on [0-9]|next|this)|$)',
        r'(?:days?|weeks?)\s+(?:in|at|to)\s+([A-Za-z\s]+?)(?:\s+(?:from|for|including|with|under)|$)',
        r'^([A-Za-z\s]+?)\s+trip\b',
    ]
    for pattern in patterns:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            candidate = re.sub(r'^(a|an|the)\s+', '', candidate, flags=re.IGNORECASE).strip()
            if candidate and len(candidate.split()) <= 4:
                return candidate.title()

    # Fast fallback to LLM
    try:
        prompt = f"Extract only the destination city or country from: '{query}'. Return only the name."
        response = llm.invoke(prompt)
        text = extract_text(response.content).strip().strip('"').strip("'")
        return text if text else query
    except Exception:
        return query