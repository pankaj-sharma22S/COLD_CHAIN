"""Single LangChain chat-model factory for the agent graphs."""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()


def create_chat_model(*, tools=None) -> ChatOpenAI:
    """Create the configured OpenAI-compatible chat model.

    OpenRouter is selected when ``LLM_PROVIDER=openrouter`` or when an
    ``OPENROUTER_API_KEY`` is present. The key is read only from the
    environment and is never logged or committed.
    """
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    use_openrouter = provider == "openrouter" or bool(os.getenv("OPENROUTER_API_KEY"))

    if use_openrouter:
        model = os.getenv("OPENROUTER_MODEL") or os.getenv("OPENAI_MODEL")
        if not model:
            raise RuntimeError("Set OPENROUTER_MODEL in .env before starting the agent.")
        chat = ChatOpenAI(
            model=model,
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            temperature=0,
            default_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost:5173"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "Cold Chain Control Center"),
            },
        )
    else:
        model = os.getenv("OPENAI_MODEL")
        if not model:
            raise RuntimeError("Set OPENAI_MODEL or configure OPENROUTER_API_KEY/OPENROUTER_MODEL in .env.")
        chat = ChatOpenAI(
            model=model,
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0,
        )

    return chat.bind_tools(tools) if tools else chat
