"""Agentic investigation workflow for risky cold-chain events."""

from typing import Any

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)
from langgraph.graph import (
    END,
    START,
    StateGraph,
)
from agent.graph_compat import (
    ToolNode,
    tools_condition,
)

from agent.schemas import (
    ActionOutput,
    AgentState,
)
from agent.tools import (
    INVESTIGATION_TOOLS,
)
from agent.model_factory import create_chat_model


INVESTIGATION_PROMPT = """
You are the cold-chain risk investigation agent.

A deterministic risk engine has identified a risky condition.

Your job is to investigate the condition and determine the
appropriate operational response.

Available tools:

- current telemetry
- ETA and next station
- weather at ETA
- deterministic risk evaluation
- SOP retrieval

RULES:

1. Never invent telemetry.

2. Never invent weather.

3. Never invent ETA.

4. Never invent truck-specific safe temperature limits.

5. The deterministic risk engine is authoritative for risk status.

6. SOP documents provide operational guidance.

7. SOP does not override configured safety limits.

8. Use the current time when determining freshness.

9. Avoid calling tools unnecessarily when sufficiently fresh
   evidence already exists.

10. If more evidence is needed, select the appropriate tool.

11. Weather should be retrieved at the truck's next station
    and ETA when weather could influence the situation.

12. Retrieve an SOP when operational procedure is needed.

13. Distinguish measured facts from conclusions.

14. Never claim an alert was sent unless a real notification
    tool exists.

15. Stop once enough evidence exists for a justified action.

You are an agentic investigator.
Do not follow a fixed tool sequence.
"""


def create_model():
    """Create the investigation model."""

    return create_chat_model(tools=INVESTIGATION_TOOLS)


def investigation_agent(
    state: AgentState,
) -> dict[str, Any]:
    """Run one investigation reasoning step."""

    model = create_model()

    messages = [
        SystemMessage(
            content=INVESTIGATION_PROMPT
        )
    ]

    if state.messages:
        messages.extend(
            state.messages
        )

    else:
        messages.append(
            HumanMessage(
                content=(
                    f"Current time: "
                    f"{state.current_time}\n\n"
                    f"Truck: "
                    f"{state.truck_id}\n\n"
                    f"Risk data:\n"
                    f"{state.risk_data}\n\n"
                    "Investigate this event."
                )
            )
        )

    response = model.invoke(
        messages
    )

    return {
        "messages": [response]
    }


def final_investigation_action(
    state: AgentState,
) -> dict[str, Any]:
    """Create final structured action."""

    model = create_chat_model()

    structured = model.with_structured_output(
        ActionOutput
    )

    result = structured.invoke(
        [
            SystemMessage(
                content="""
Produce the final cold-chain risk action.

Use only facts contained in the state and tool results.

Rules:

- Deterministic risk is authoritative.
- Do not invent safe limits.
- Do not invent measurements.
- Do not claim an alert was sent.
- recommended_actions are recommendations.
- Use REQUEST_HUMAN_REVIEW when evidence indicates
  human intervention is required.
"""
            ),
            HumanMessage(
                content=(
                    "Investigation state:\n\n"
                    f"{state.model_dump_json(indent=2)}"
                )
            ),
        ]
    )

    return {
        "action": result
    }


def build_risk_investigation_graph():
    """Build the investigation graph."""

    graph = StateGraph(
        AgentState
    )

    graph.add_node(
        "investigation_agent",
        investigation_agent,
    )

    graph.add_node(
        "tools",
        ToolNode(
            INVESTIGATION_TOOLS
        ),
    )

    graph.add_node(
        "final_action",
        final_investigation_action,
    )

    graph.add_edge(
        START,
        "investigation_agent",
    )

    graph.add_conditional_edges(
        "investigation_agent",
        tools_condition,
        {
            "tools": "tools",
            END: "final_action",
        },
    )

    graph.add_edge(
        "tools",
        "investigation_agent",
    )

    graph.add_edge(
        "final_action",
        END,
    )

    return graph.compile()


risk_investigation_graph = (
    build_risk_investigation_graph()
)


def run_risk_investigation(
    state: AgentState,
) -> ActionOutput:
    """Run investigation and return structured action."""

    result = risk_investigation_graph.invoke(
        state
    )

    return result["action"]
