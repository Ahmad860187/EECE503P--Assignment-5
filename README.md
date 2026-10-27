# Clean Break MCP toolkit

EECE 503P/798S, Assignment C5 (Agent Tools)

Demo video: (add link)

Clean Break is the small Beirut moving company I used in the last two assignments. It handles the practical
side of a breakup: moving out, swapping belongings with the ex, storing the sentimental stuff and cleaning the
flat after. For this assignment I turned the pricing and booking part into an MCP server with three tools, and
connected it to an agent built with the OpenAI Agents SDK.

## The three tools

- `get_quote` is the data tool. It prices one job from the price list, adds 50% if the date is less than 48
  hours away and gives the 30% deposit. It only reads, it never saves anything.
- `create_booking_request` is the action tool. It saves a booking request to `data/bookings.jsonl` and gives
  it an id like CB-0001. It's a request and not a confirmed booking, because the team still calls the customer.
- `plan_clean_break` is the orchestration tool. It takes everything the customer wants, prices each job with
  `get_quote`, adds it up and sends one booking request with `create_booking_request`. If one job can't be
  priced, nothing gets booked.

There is also a resource, `cleanbreak://price-list`, with the prices and the rules. The agent reads it when it
starts and puts it in its instructions.

When something is wrong, the tools give a clear error instead of failing silently:

| Tool | Errors |
|---|---|
| get_quote | wrong option (it lists the right ones), a Sunday, a date in the past, an area outside Beirut and Metn |
| create_booking_request | phone or email not valid, the same request twice, the day already has 2 jobs |
| plan_clean_break | passes on the error of the job that failed and books nothing |

## Setup

I used Python 3.13 (3.11 or newer should work).

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On Mac or Linux, activate with `source .venv/bin/activate` instead.

The agent runs on Gemini, not on an OpenAI model. Gemini has an OpenAI-compatible endpoint, so the Agents SDK
can use it through `OpenAIChatCompletionsModel`. Copy `.env.example` to `.env` and put your key in it. A free
key from Google AI Studio is enough. Tracing is turned off because it tries to send the traces to OpenAI.

## Running it

```
python agent.py
```

This starts the MCP server as a subprocess (stdio), lists its tools and opens a chat in the terminal. Every
tool call is printed so you can follow the round trip:

- `[agent -> MCP]` is the call the agent sends
- `[server]` is the server receiving it
- `[MCP -> agent]` is what comes back to the agent

You can also pass the messages directly to run a fixed conversation:

```
python agent.py "How much is a silent move-out for a 2 bedroom in Beirut next Monday?" "ok book it, I'm Rana, 03 123 456"
```

Some things to try:

- "How much is a fresh start for a studio in Metn this Thursday?", then "book that, Karim, karim at gmail".
  The email gets rejected and the agent asks for it again.
- "I need to move out of my studio this Sunday". We're closed on Sundays.
- "Move-out for a 1 bedroom, one swap and 6 months of storage next Saturday in Beirut, I'm Rana 03123456".
  This one goes through `plan_clean_break`.

## Tests

```
pytest
```

There are 14 tests. They call each tool directly, check every error in the table above and run a few calls
through an in-memory MCP client. They write to a temporary file, so they don't touch `data/bookings.jsonl`.

## Files

- `server.py`: the FastMCP server with the three tools and the resource
- `agent.py`: the agent, connects to the server with `MCPServerStdio`
- `test_tools.py`: the tests
- `data/bookings.jsonl`: created when the first booking request is saved

## Limits

- The date check works on days, not times, and doesn't know public holidays.
- `create_booking_request` doesn't check the date itself. It trusts it because `get_quote` already did.
- Prices only come from the price list, so no discounts.
- The Swap is priced as one trip and the Memory Vault as one box.
