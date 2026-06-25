"""Quick test: DeepSeek LLM call via Anthropic-compatible API."""
import asyncio, os
from app.services.ai.llm_client import LLMClient, LLMProvider, LLMMessage

async def main():
    client = LLMClient(
        provider=LLMProvider.ANTHROPIC,
        model=os.getenv("AI_PRIMARY_MODEL", "deepseek-v4-pro"),
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
    )
    print(f"Provider : {client.provider.value}")
    print(f"Model    : {client.model}")
    print(f"API key  : {'SET' if client.api_key else 'MISSING'}")
    print()

    try:
        response = await client.chat(
            messages=[LLMMessage(role="user", content="Say hello in one sentence.")],
            max_tokens=100,
        )
        print("=== SUCCESS ===")
        print(f"Content : {response.content}")
        print(f"Model   : {response.model}")
        print(f"Tokens  : {response.token_usage}")
    except Exception as e:
        import traceback
        print(f"ERROR [{type(e).__name__}]: {e}")
        traceback.print_exc()

asyncio.run(main())
