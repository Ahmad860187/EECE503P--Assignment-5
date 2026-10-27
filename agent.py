import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from agents.mcp import MCPServerStdio
from dotenv import load_dotenv
from openai import AsyncOpenAI

HERE = Path(__file__).parent
load_dotenv(HERE / ".env", override=True)
set_tracing_disabled(True)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
gemini = AsyncOpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                     api_key=os.environ["GOOGLE_API_KEY"])
server_params = {"command": sys.executable, "args": [str(HERE / "server.py")]}

INSTRUCTIONS = """You are the booking assistant of Clean Break, a small Beirut company that handles the
practical side of a breakup. People talking to you are usually stressed and on their phone, so keep it short
and kind, and don't take sides.

Today is {today} ({weekday}).

Price list and rules:
{price_list}

How to use your tools:
- For any price, call get_quote. Never work out a price yourself.
- When someone wants to book, make sure you have their name, a phone number or email, the date, the area
  (Beirut or Metn) and the services with their options, then call plan_clean_break once with all of it.
- If they already got a quote from you in this chat and just want to book exactly that, you can call
  create_booking_request with the quoted total instead.
- Pass the phone number or email exactly as the customer wrote it. Never guess or fix it yourself, the tool
  checks it.
- If a tool returns an error, tell the customer what went wrong in plain words and ask for what you need.
- A booking request is not a confirmed booking. Give them the request id and say the team will call to
  confirm and take the 30% deposit.
- We carry belongings, never messages, and we don't give legal advice. If someone feels unsafe, tell them
  to call 112."""


def short(output, limit=300):
    parts = output if isinstance(output, list) else [output]
    text = " ".join(part["text"] if isinstance(part, dict) and "text" in part else str(part) for part in parts)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


async def ask(agent, history, message):
    history = history + [{"role": "user", "content": message}]
    result = Runner.run_streamed(agent, history)
    async for event in result.stream_events():
        if event.type != "run_item_stream_event":
            continue
        if event.name == "tool_called":
            call = event.item.raw_item
            print(f"  [agent -> MCP] {call.name}({call.arguments})")
        elif event.name == "tool_output":
            print(f"  [MCP -> agent] {short(event.item.output)}")
    print(f"\nClean Break: {result.final_output}\n")
    return result.to_input_list()


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
            model=OpenAIChatCompletionsModel(model=MODEL, openai_client=gemini),
            mcp_servers=[server],
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
