import os
import certifi
from dotenv import load_dotenv

load_dotenv()
os.environ["SSL_CERT_FILE"] = certifi.where()
os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from typing import Any, TypedDict, Annotated
import operator
import uuid
import asyncio
import json
import psycopg
from psycopg.rows import dict_row
import requests
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command, Send, interrupt
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_groq import ChatGroq


from mcp_client import (
    llm,
    tavily_mcp_search,
    aviation_mcp_call,
    extract_destination,
    forecast_mcp_search,
    weather_mcp_search,
)


def get_database_url():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. "
            "Please add your Render PostgreSQL External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url


# =========================
# LLM - shared fallback chain from mcp_client
# =========================
# (`llm` is imported from mcp_client)

# =========================
# State - original fields kept, new control fields added
# =========================
class TravelState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str

    # Supervisor + guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # Original specialist results
    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str

    # New budget + HITL state
    budget_results: str
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str

    llm_calls: Annotated[int, operator.add]


# =========================
# Shared helpers
# =========================
KNOWN_AGENTS = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
}

AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent",
]


def _content_to_str(content: Any) -> str:
    """Normalize LangChain message content (str or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p).strip()
    return str(content or "")


def _llm_text(system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    return _content_to_str(response.content)


def _json_from_llm(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object returned by the model."""
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start : end + 1])


def _empty_constraints() -> dict[str, Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }


# =========================
# Supervisor Agent + Input Guardrail (single fast LLM call)
# =========================
def supervisor_agent(state: TravelState):
    query = state["user_query"]

    combined_prompt = f"""
You are the input guardrail AND supervisor of a multi-agent travel-planning system.

Step 1 - Guardrail:
Determine whether the request belongs to travel planning or travel information
(destinations, flights, hotels, weather, budgets, visas, transportation,
sightseeing, food, packing, or itineraries). Block clearly unrelated requests
and harmful/illegal instructions. Do not block valid travel requests merely
because some details are missing.

Step 2 - Supervisor Routing (only if allowed=true):
Choose only the specialist agents needed:
- flight_agent: flights, airports, airlines, routes, airfare, or booking advice
- hotel_agent: hotels, accommodation, neighborhoods, or places to stay
- weather_agent: weather, climate, season, forecast, or packing advice
- budget_agent: cost, affordability, price limits, or budget feasibility
- itinerary_agent: creates the integrated travel plan and must always be included

Return strict JSON only using this schema:
{{
  "allowed": true,
  "reason": "",
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}

User request:
{query}
"""

    try:
        raw = _llm_text(
            "You are the travel input guardrail and multi-agent supervisor. Return strict JSON only.",
            combined_prompt,
        )
        parsed = _json_from_llm(raw)
        allowed = bool(parsed.get("allowed", True))
        guardrail_reason = str(parsed.get("reason", "")).strip()
        llm_calls = 1
    except Exception as exc:
        print(f"Supervisor/Guardrail fallback used: {exc}")
        allowed = True
        guardrail_reason = "Guardrail validation fallback allowed the request."
        parsed = {}
        llm_calls = 1

    if not allowed:
        reason = guardrail_reason or (
            "TripMate AI can only help with travel-planning requests. "
            "Please ask about a destination, flight, hotel, weather, budget, "
            "or itinerary."
        )
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    requested_agents = parsed.get("selected_agents", []) if isinstance(parsed, dict) else []
    selected_agents = [
        name for name in AGENT_ORDER
        if name in requested_agents and name in KNOWN_AGENTS
    ]
    if not selected_agents:
        selected_agents = AGENT_ORDER.copy()
    elif "itinerary_agent" not in selected_agents:
        selected_agents.append("itinerary_agent")

    constraints = _empty_constraints()
    parsed_constraints = parsed.get("trip_constraints", {}) if isinstance(parsed, dict) else {}
    if isinstance(parsed_constraints, dict):
        constraints.update(parsed_constraints)

    reasoning = str(parsed.get("reasoning", "")).strip() if isinstance(parsed, dict) else ""

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": llm_calls,
    }


# =========================
# Guardrail blocked response
# =========================
def guardrail_blocked_agent(state: TravelState):
    reason = state.get("final_response") or state.get("guardrail_reason") or (
        "This request was blocked by the travel input guardrail."
    )
    return {
        "final_response": reason,
        "messages": [AIMessage(content=reason)],
    }


# =========================
# Flight Agent - original behavior kept
# =========================
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


def flight_agent(state: TravelState):
    query = state["user_query"]
    constraints = state.get("trip_constraints", {})
    airport_text = f"Origin: {constraints.get('origin') or 'Auto-detect from query'}, Destination: {constraints.get('destination') or 'Auto-detect from query'}"
    airline_text = "Use major international and regional carriers serving this route."

    try:
        prompt = FLIGHT_AGENT_PROMPT.format(
            query=query,
            airport_data=airport_text,
            airline_data=airline_text,
        )

        response = llm.invoke(
            [
                SystemMessage(content="You are an expert travel flight planner."),
                HumanMessage(content=prompt),
            ]
        )
        flight_data = _content_to_str(response.content)
    except Exception as exc:
        flight_data = f"Flight information unavailable: {exc}"

    return {
        "flight_results": flight_data,
        "messages": [AIMessage(content="Flight recommendations generated")],
        "llm_calls": 1,
    }


# =========================
# Hotel Agent - original behavior kept
# =========================
def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"

    try:
        from tools.tavily_tool import tavily_search
        hotel_results = tavily_search(query)
    except Exception as sdk_exc:
        print(f"HOTEL AGENT SDK ERROR: {sdk_exc}", flush=True)
        hotel_results = (
            "Live hotel search is temporarily unavailable. "
            "Provide general accommodation and neighborhood "
            "guidance based on the destination and clearly "
            "label it as non-live advice."
        )

    return {
        "hotel_results": hotel_results,
        "messages": [AIMessage(content="Hotel information processed.")],
        "llm_calls": 0,
    }


# =========================
# Weather Agent - original behavior kept
# =========================
def _open_meteo_weather(city: str) -> str:
    """Fetch current weather and 7-day forecast using Open-Meteo REST API."""
    geo = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=8,
    )
    geo.raise_for_status()
    results = geo.json().get("results") or []
    if not results:
        raise ValueError(f"Could not geocode destination '{city}'.")

    loc = results[0]
    lat, lon = loc["latitude"], loc["longitude"]
    resolved_name = f"{loc.get('name', city)}, {loc.get('country', '')}".strip(", ")

    wx = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": 7,
        },
        timeout=8,
    )
    wx.raise_for_status()
    data = wx.json()
    current = data.get("current", {})
    daily = data.get("daily", {})

    lines = [
        f"Current Weather in {resolved_name}: "
        f"{current.get('temperature_2m', 'N/A')}°C, "
        f"Humidity {current.get('relative_humidity_2m', 'N/A')}%, "
        f"Wind {current.get('wind_speed_10m', 'N/A')} km/h",
        "",
        "7-Day Forecast:",
    ]
    dates = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    rain = daily.get("precipitation_probability_max", [])
    for d, hi, lo, r in zip(dates, tmax, tmin, rain):
        lines.append(f"- {d}: {lo}°C to {hi}°C, rain chance {r}%")
    return "\n".join(lines)


def weather_agent(state: TravelState):
    city = str(state.get("trip_constraints", {}).get("destination", "")).strip()
    if not city:
        try:
            city = extract_destination(state["user_query"])
        except Exception:
            city = state["user_query"]

    try:
        weather_results = _open_meteo_weather(city)
    except Exception as rest_exc:
        print(f"OPEN-METEO ERROR: {rest_exc}", flush=True)
        weather_results = (
            f"Live weather information for {city} "
            "is temporarily unavailable. Give general "
            "seasonal guidance and advise the traveler "
            "to verify the forecast before departure."
        )

    return {
        "weather_results": weather_results,
        "messages": [AIMessage(content="Weather information processed.")],
        "llm_calls": 0,
    }


# =========================
# Budget Agent - new specialist
# =========================
def budget_agent(state: TravelState):
    prompt = f"""
Analyze whether this trip is realistic for the user's budget. Keep it concise.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{str(state.get('flight_results', ''))[:1200]}

Hotel Results:
{str(state.get('hotel_results', ''))[:1200]}

Weather Results:
{str(state.get('weather_results', ''))[:800]}

Return concise bullets:
1. Estimated cost categories
2. Budget risk areas
3. Money-saving suggestions
4. Overall feasibility

If exact live prices are unavailable, clearly label estimates as approximate.
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are a practical travel budget analyst."),
            HumanMessage(content=prompt),
        ]
    )

    return {
        "budget_results": _content_to_str(response.content),
        "messages": [AIMessage(content="Budget assessment generated.")],
        "llm_calls": 1,
    }


# =========================
# Itinerary Agent - original behavior extended with selected results
# =========================
def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete, practical travel plan ready for human review.

User Query:
{state['user_query']}

Trip Constraints:
{state.get('trip_constraints', {})}

Flight Results:
{str(state.get('flight_results', ''))[:1400]}

Hotel Results:
{str(state.get('hotel_results', ''))[:1400]}

Weather Results:
{str(state.get('weather_results', ''))[:900]}

Budget Results:
{str(state.get('budget_results', ''))[:1200]}

Format the draft cleanly using these sections:
1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Note when live flight ticket prices are unavailable and include weather-based packing/travel advice.
"""

    response = llm.invoke(
        [
            SystemMessage(content="You are an expert travel planner."),
            HumanMessage(content=prompt),
        ]
    )

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create the "
        "final polished plan, or provide feedback for revision."
    )

    return {
        "itinerary": _content_to_str(response.content),
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": 1,
    }


# =========================
# Human-in-the-Loop approval
# =========================
def human_approval_agent(state: TravelState):
    # Do not wrap interrupt() in try/except. LangGraph uses it to pause execution.
    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )

    if isinstance(review, dict):
        approved = bool(review.get("approved", False))
        human_feedback = str(review.get("feedback", "")).strip()
    elif isinstance(review, bool):
        approved = review
        human_feedback = ""
    else:
        approved = False
        human_feedback = str(review or "").strip()

    return {
        "approved": approved,
        "human_feedback": human_feedback,
        "messages": [AIMessage(content="Human approval step completed.")],
    }


# =========================
# Final Response Agent - original format kept, HITL feedback added
# =========================
def final_agent(state: TravelState):
    draft = state.get("itinerary", "")
    feedback = str(state.get("human_feedback", "")).strip()

    # Fast path: user approved the draft without requesting edits.
    if state.get("approved", False) and not feedback and draft:
        return {
            "final_response": draft,
            "messages": [AIMessage(content=draft)],
            "llm_calls": 0,
        }

    review_instruction = (
        f"The user approved the draft with this note: {feedback}"
        if state.get("approved", False)
        else f"The user requested a revision. Apply this feedback carefully:\n{feedback or 'Improve the draft before finalizing it.'}"
    )

    final_prompt = f"""
Revise and finalize the travel response for the user.

Human Review:
{review_instruction}

User Request:
{state['user_query']}

Supervisor Constraints:
{state.get('trip_constraints', {})}

Draft Itinerary:
{draft[:3500]}

Keep the 7-section structure (Trip Summary, Flight Information, Hotel Suggestions, Weather Information, Day-by-Day Itinerary, Estimated Budget, Final Recommendations) and apply all human feedback.
"""

    response = llm.invoke(
        [
            SystemMessage(
                content="You are a professional AI travel booking assistant."
            ),
            HumanMessage(content=final_prompt),
        ]
    )

    return {
        "final_response": _content_to_str(response.content),
        "messages": [response],
        "llm_calls": 1,
    }


# =========================
# Dynamic Parallel Supervisor Routing
# =========================
PARALLEL_SPECIALISTS = ("flight_agent", "hotel_agent", "weather_agent")


def _selected_agents(state: TravelState) -> list[str]:
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent in selected]


def route_from_supervisor(state: TravelState):
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"

    selected = _selected_agents(state)
    parallel = [agent for agent in PARALLEL_SPECIALISTS if agent in selected]
    if parallel:
        return [Send(agent, state) for agent in parallel]

    if "budget_agent" in selected:
        return "budget_agent"
    return "itinerary_agent"


def join_specialists(state: TravelState):
    return {}


def route_after_join(state: TravelState) -> str:
    selected = _selected_agents(state)
    if "budget_agent" in selected:
        return "budget_agent"
    return "itinerary_agent"


# =========================
# Build Graph
# =========================
graph = StateGraph(TravelState)

graph.add_node("supervisor", supervisor_agent)
graph.add_node("guardrail_blocked", guardrail_blocked_agent)
graph.add_node("flight_agent", flight_agent)
graph.add_node("hotel_agent", hotel_agent)
graph.add_node("weather_agent", weather_agent)
graph.add_node("join_specialists", join_specialists)
graph.add_node("budget_agent", budget_agent)
graph.add_node("itinerary_agent", itinerary_agent)
graph.add_node("human_approval", human_approval_agent)
graph.add_node("final_agent", final_agent)

graph.add_edge(START, "supervisor")
graph.add_conditional_edges(
    "supervisor",
    route_from_supervisor,
    ["guardrail_blocked", "flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
)

graph.add_edge("flight_agent", "join_specialists")
graph.add_edge("hotel_agent", "join_specialists")
graph.add_edge("weather_agent", "join_specialists")
graph.add_conditional_edges(
    "join_specialists",
    route_after_join,
    {"budget_agent": "budget_agent", "itinerary_agent": "itinerary_agent"},
)
graph.add_edge("budget_agent", "itinerary_agent")

graph.add_edge("itinerary_agent", "human_approval")
graph.add_edge("human_approval", "final_agent")
graph.add_edge("final_agent", END)
graph.add_edge("guardrail_blocked", END)

# =========================
# PostgreSQL Checkpointer - with graceful MemorySaver fallback
# =========================
try:
    DATABASE_URL = get_database_url()
    _conn = psycopg.connect(
        DATABASE_URL,
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=5,
    )
    checkpointer = PostgresSaver(_conn)
    checkpointer.setup()
except Exception as db_exc:
    print(f"PostgreSQL checkpointer unavailable ({db_exc}); falling back to MemorySaver.")
    checkpointer = MemorySaver()

travel_graph = graph.compile(checkpointer=checkpointer)


# =========================
# FastAPI-facing helpers
# =========================
def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None

    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value": payload}


def _serialize_result(
    result: dict[str, Any],
    thread_id: str,
) -> dict[str, Any]:
    messages = result.get("messages", [])
    last_message = _content_to_str(messages[-1].content) if messages else ""
    answer = _content_to_str(result.get("final_response")) or last_message
    interrupt_payload = _interrupt_payload(result)

    if interrupt_payload:
        answer = interrupt_payload.get("draft_itinerary") or result.get(
            "itinerary", ""
        )

    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": result.get("flight_results", ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "itinerary": (
            interrupt_payload.get("draft_itinerary", "")
            if interrupt_payload
            else result.get("itinerary", "")
        ),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback", ""),
        "llm_calls": result.get("llm_calls", 0),
    }


def run_travel_agent(user_input: str, thread_id: str | None = None):
    """Start a new travel-planning run and pause at human approval."""
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {"configurable": {"thread_id": thread_id}}

    result = travel_graph.invoke(
        {
            "messages": [HumanMessage(content=user_input)],
            "user_query": user_input,
            "guardrail_allowed": True,
            "guardrail_reason": "",
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": "",
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "budget_results": "",
            "itinerary": "",
            "approval_request": "",
            "approved": False,
            "human_feedback": "",
            "final_response": "",
            "llm_calls": 0,
        },
        config=config,
    )

    return _serialize_result(result, thread_id)


def resume_travel_agent(
    thread_id: str,
    approved: bool,
    feedback: str = "",
):
    """Resume the paused LangGraph thread after human review."""
    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        Command(
            resume={
                "approved": approved,
                "feedback": feedback.strip(),
            }
        ),
        config=config,
    )

    return _serialize_result(result, thread_id)