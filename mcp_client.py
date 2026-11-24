import os
import sys
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
# LLM
# ==========================================

if GEMINI_API_KEY:
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash",
        google_api_key=GEMINI_API_KEY,
        temperature=0.2,
    )
elif GROQ_API_KEY:
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        api_key=GROQ_API_KEY
    )
else:
    llm = ChatGroq(
        model="openai/gpt-oss-20b",
        api_key="dummy_key"
    )


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
    await initialize_mcp()

    result = await search_tool.ainvoke(
        {
            "query": query
        }
    )

    return result


# ==========================================
# AviationStack MCP tools
# ==========================================

aviation_tools = {}


async def initialize_aviation_tools():
    global aviation_tools

    if aviation_tools:
        return

    # Load only AviationStack.
    # Tavily and Weather will not be initialized here.
    tools = await client.get_tools(
        server_name="aviationstack"
    )

    aviation_tools = {
        tool.name: tool
        for tool in tools
    }

    if not aviation_tools:
        raise RuntimeError(
            "AviationStack MCP connected but "
            "returned no tools."
        )


async def aviation_mcp_call(
    tool_name: str,
    tool_args: dict = None
):
    await initialize_aviation_tools()

    tool = aviation_tools.get(tool_name)

    if tool is None:
        available_tools = ", ".join(
            sorted(aviation_tools.keys())
        )

        raise ValueError(
            f"AviationStack tool '{tool_name}' "
            "was not found. "
            f"Available tools: "
            f"{available_tools or 'none'}"
        )

    result = await tool.ainvoke(
        tool_args or {}
    )

    return result


# ==========================================
# Open-Meteo Weather Tools (Direct HTTP API)
# No API key required, pure Python requests.
# Works in any environment (including Docker/Embarko)
# ==========================================

import requests

def _get_coordinates(location_name: str):
    try:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": location_name, "count": 1, "language": "en", "format": "json"}
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if "results" in data and len(data["results"]) > 0:
            loc = data["results"][0]
            return loc.get("latitude"), loc.get("longitude"), loc.get("name"), loc.get("country", "")
    except Exception as e:
        print(f"Geocoding error for {location_name}: {e}")
    return None, None, location_name, ""


async def weather_mcp_search(city: str):
    lat, lon, name, country = _get_coordinates(city)
    if lat is None or lon is None:
        return f"Could not find coordinates for '{city}'."

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "precipitation", "wind_speed_10m"],
            "timezone": "auto"
        }
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        curr = data.get("current", {})
        units = data.get("current_units", {})
        temp = curr.get("temperature_2m", "N/A")
        t_unit = units.get("temperature_2m", "°C")
        humidity = curr.get("relative_humidity_2m", "N/A")
        feels_like = curr.get("apparent_temperature", "N/A")
        wind = curr.get("wind_speed_10m", "N/A")
        w_unit = units.get("wind_speed_10m", "km/h")
        
        return (
            f"Current Weather in {name}, {country}:\n"
            f"- Temperature: {temp}{t_unit} (Feels like: {feels_like}{t_unit})\n"
            f"- Humidity: {humidity}%\n"
            f"- Wind Speed: {wind} {w_unit}"
        )
    except Exception as e:
        return f"Weather lookup failed for {city}: {e}"


async def forecast_mcp_search(city: str):
    lat, lon, name, country = _get_coordinates(city)
    if lat is None or lon is None:
        return f"Could not find coordinates for '{city}'."

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"],
            "timezone": "auto"
        }
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        rain_prob = daily.get("precipitation_probability_max", [])

        lines = [f"7-Day Weather Forecast for {name}, {country}:"]
        for i in range(min(7, len(dates))):
            date = dates[i]
            t_max = max_temps[i] if i < len(max_temps) else "N/A"
            t_min = min_temps[i] if i < len(min_temps) else "N/A"
            rain = rain_prob[i] if i < len(rain_prob) else "N/A"
            lines.append(f"- {date}: High {t_max}°C, Low {t_min}°C, Rain chance {rain}%")

        return "\n".join(lines)
    except Exception as e:
        return f"Forecast lookup failed for {city}: {e}"


# ==========================================
# Destination extractor
# ==========================================

def extract_destination(query: str):
    prompt = f"""
    Extract only the destination city or country.

    Query:
    {query}

    Return only destination name.
    """

    response = llm.invoke(prompt)

    return extract_text(response.content).strip()