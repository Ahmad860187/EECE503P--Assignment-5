import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, RunHooks, Runner, set_tracing_disabled
from agents.mcp import MCPServerStdio
from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, InternalServerError, RateLimitError

HERE = Path(__file__).parent
load_dotenv(HERE / ".env", override=True)
set_tracing_disabled(True)

MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"), "gemini-3.5-flash", "gemini-flash-lite-latest"]
skip_today = set()
gemini = AsyncOpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                     api_key=os.environ["GOOGLE_API_KEY"], timeout=45, max_retries=1)
server_params = {"command": sys.executable, "args": [str(HERE / "server.py")]}

INSTRUCTIONS = """You are the booking assistant of Clean Break, a small Beirut company that handles the
practical side of a breakup. People talking to you are usually stressed and on their phone, so keep it short
and kind, and don't take sides.

Today is {today} ({weekday}).

Price list and rules:
{price_list}

How to use your tools:
- For any price, call get_quote. Never work out a price yourself.
- To book you need their name, a phone number or email, the date, the area (Beirut or Metn) and the services
  with their options. Never call plan_clean_break or create_booking_request without the customer's real name
  and contact. If something is missing, ask for it. You can still use get_quote to check the price and date.
- If they want to book exactly what get_quote already priced for them in this chat, call
  create_booking_request with the same date, area and jobs and the quoted total.
- Otherwise, as soon as you have everything, call plan_clean_break once with all of it. Don't get separate
  quotes first, plan_clean_break returns the prices too.
- Pass the phone number or email exactly as the customer wrote it. Never guess or fix it yourself, the tool
  checks it.
- If a tool returns an error, tell the customer what went wrong in plain words and ask for what you need.
- A booking request is not a confirmed booking. Give them the request id and say the team will call to
  confirm and take the 30% deposit.
- We carry belongings, never messages, and we don't give legal advice.
- Only if someone says they feel unsafe or mentions violence, tell them to call 112. Don't bring it up
  otherwise."""


def short(output, limit=300):
    parts = output if isinstance(output, list) else [output]
    text = " ".join(part["text"] if isinstance(part, dict) and "text" in part else str(part) for part in parts)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


class ShowToolCalls(RunHooks):
    async def on_tool_start(self, context, agent, tool):
        print(f"  [agent -> MCP] {tool.name}({getattr(context, 'tool_arguments', '')})")

    async def on_tool_end(self, context, agent, tool, result):
        print(f"  [MCP -> agent] {short(result)}")


async def ask(agent, history, message):
    # not streamed: Gemini's streamed parallel tool calls get merged into one broken call
    turn = history + [{"role": "user", "content": message}]
    for name in dict.fromkeys(MODELS):
        if name in skip_today:
            continue
        model = OpenAIChatCompletionsModel(model=name, openai_client=gemini)
        try:
            result = await Runner.run(agent.clone(model=model), turn, hooks=ShowToolCalls())
        except (RateLimitError, InternalServerError, APITimeoutError):
            print(f"  ({name} is busy or out of free quota, trying the next model)")
            skip_today.add(name)
            continue
        except APIConnectionError:
            print("\nClean Break: I can't reach Gemini right now. Check the internet and send that again.\n")
            return history
        print(f"\nClean Break: {result.final_output}\n")
        return result.to_input_list()
    print("\nClean Break: Sorry, all the Gemini models are busy right now. Try again in a minute.\n")
    skip_today.clear()
    return history


async def main():
    async with MCPServerStdio(params=server_params, name="clean-break", client_session_timeout_seconds=30,
                              cache_tools_list=True) as server:
        tools = await server.list_tools()
        print(f"Connected to the clean-break MCP server, tools: {', '.join(tool.name for tool in tools)}")
        price_list = (await server.read_resource("cleanbreak://price-list")).contents[0].text
        today = date.today()
        agent = Agent(
            name="Clean Break assistant",
            instructions=INSTRUCTIONS.format(today=today.isoformat(), weekday=today.strftime("%A"),
                                             price_list=json.dumps(json.loads(price_list), indent=1)),
            mcp_servers=[server],
            model_settings=ModelSettings(temperature=0),
        )
        history = []
        if len(sys.argv) > 1:
            for message in sys.argv[1:]:
                print(f"You: {message}")
                history = await ask(agent, history, message)
            return
        print("Type your message, or 'quit' to stop.\n")
        while True:
            message = input("You: ").strip()
            if message.lower() in ("quit", "exit"):
                break
            if message:
                history = await ask(agent, history, message)


if __name__ == "__main__":
    asyncio.run(main())
