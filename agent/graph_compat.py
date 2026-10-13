"""Compatibility imports for LangGraph's optional prebuilt package."""

from typing import Any

try:  # LangGraph distributions that include the prebuilt package.
    from langgraph.prebuilt import ToolNode, tools_condition  # type: ignore
except ImportError:  # pragma: no cover - only for incomplete local installs.
    from langchain_core.messages import ToolMessage

    def tools_condition(state: Any) -> str:
        messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
        if messages and getattr(messages[-1], "tool_calls", None):
            return "tools"
        return "__end__"

    class ToolNode:
        """Small adapter matching the prebuilt ToolNode contract."""

        def __init__(self, tools):
            self.tools = {tool.name: tool for tool in tools}

        def __call__(self, state):
            messages = state.get("messages", []) if isinstance(state, dict) else state.messages
            last = messages[-1]
            results = []
            for call in getattr(last, "tool_calls", []):
                tool = self.tools.get(call["name"])
                if tool is None:
                    raise ValueError(f"Unknown tool requested: {call['name']}")
                results.append(
                    ToolMessage(
                        content=str(tool.invoke(call.get("args", {}))),
                        tool_call_id=call["id"],
                    )
                )
            return {"messages": results}
