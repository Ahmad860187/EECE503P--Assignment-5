import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal, NotRequired, TypedDict

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

mcp = FastMCP("clean-break", instructions="Tools for Clean Break, a Beirut company that handles the practical "
                                           "side of a breakup: moving out, swapping belongings, storage, cleaning.")

BOOKINGS_FILE = Path(__file__).parent / "data" / "bookings.jsonl"
JOBS_PER_DAY = 2

PRICES = {
    "silent move-out": {"studio": 150, "1-bedroom": 150, "2-bedroom": 220, "3+ bedrooms": 300},
    "fresh start": {"studio": 120, "1-bedroom": 120, "2+ bedrooms": 170},
    "the swap": {"beirut": 40, "metn": 55},
    "memory vault": {"3 months": 45, "6 months": 90, "12 months": 150},
    "full clean break": {"studio": 210, "1-bedroom": 210},
}
RULES = [
    "We cover Beirut and Metn only.",
    "We work Monday to Saturday, 9 to 7, with 48 hours' notice. Less notice is an Express booking (+50%).",
    "Booking takes a 30% deposit, in cash (USD), Whish or card.",
    "The Swap is priced by area, per trip. The Memory Vault is priced per box.",
    "Full Clean Break is a Silent Move-Out, one Swap and 3 months of Memory Vault, studio or 1-bedroom only.",
]

Service = Literal["silent move-out", "the swap", "memory vault", "fresh start", "full clean break"]
Area = Literal["beirut", "metn"]
Day = Annotated[date, Field(description="Day of the job, YYYY-MM-DD")]
Contact = Annotated[str, Field(description="Lebanese phone number or email address")]


class Quote(TypedDict):
    service: str
    option: str
    area: str
    job_date: str
    weekday: str
    express: bool
    price_usd: float
    deposit_usd: float


class BookingRequest(TypedDict):
    request_id: str
    status: str
    name: str
    contact: str
    job_date: str
    items: list[str]
    total_usd: float
    deposit_usd: float


class Job(TypedDict):
    service: Service
    option: NotRequired[str]


class Plan(TypedDict):
    quotes: list[Quote]
    booking: BookingRequest


def log(text):
    print(f"[server] {text}", file=sys.stderr, flush=True)


def clean_number(value):
    value = round(value, 2)
    return int(value) if float(value).is_integer() else value


def read_bookings():
    if not BOOKINGS_FILE.exists():
        return []
    with open(BOOKINGS_FILE, encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


@mcp.resource("cleanbreak://price-list")
def price_list() -> dict:
    """Clean Break's full price list in USD and the booking rules."""
    return {"prices_usd": PRICES, "rules": RULES}


@mcp.tool
def get_quote(
    service: Service,
    job_date: Day,
    area: Area,
    option: Annotated[str, Field(description="Home size for silent move-out, fresh start and full clean break "
                                             "(studio, 1-bedroom, 2-bedroom, 3+ bedrooms, 2+ bedrooms), or "
                                             "storage length for memory vault (3 months, 6 months, 12 months). "
                                             "Leave empty for the swap, it is priced by area.")] = "",
) -> Quote:
    """Price one Clean Break job from the price list, including the Express surcharge under 48 hours' notice
    and the 30% deposit. Read-only, it doesn't book anything."""
    log(f"get_quote({service!r}, {job_date}, {area!r}, {option!r})")
    options = PRICES[service]
    key = area if service == "the swap" else option.strip().lower()
    if key not in options:
        raise ToolError(f"'{option}' isn't an option for {service}. Use one of: {', '.join(options)}.")
    days_ahead = (job_date - date.today()).days
    if days_ahead < 0:
        raise ToolError(f"{job_date} has already passed.")
    if job_date.weekday() == 6:
        raise ToolError(f"{job_date} is a Sunday and we're closed. Pick a day from Monday to Saturday.")
    express = days_ahead < 2
    price = options[key] * (1.5 if express else 1)
    return {"service": service, "option": key, "area": area, "job_date": job_date.isoformat(),
            "weekday": job_date.strftime("%A"), "express": express,
            "price_usd": clean_number(price), "deposit_usd": clean_number(price * 0.3)}


@mcp.tool
def create_booking_request(
    name: str,
    contact: Contact,
    job_date: Day,
    items: Annotated[list[str], Field(description="One line per job, for example 'silent move-out, 2-bedroom'")],
    total_usd: float,
) -> BookingRequest:
    """Save a booking request for the Clean Break team. It is not a confirmed booking: the team calls the
    customer to confirm, so the status is always 'pending team confirmation'."""
    log(f"create_booking_request({name!r}, {job_date}, {items}, {total_usd})")
    contact = contact.strip()
    phone = re.sub(r"[\s-]", "", contact)
    if not (re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact) or re.fullmatch(r"(\+961|0)?\d{7,8}", phone)):
        raise ToolError(f"'{contact}' isn't a valid phone number or email address.")
    if not items or total_usd <= 0:
        raise ToolError("A booking request needs at least one item and a total above 0.")
    existing = read_bookings()
    for booking in existing:
        if (booking["name"].lower(), booking["job_date"], booking["items"]) == \
                (name.strip().lower(), job_date.isoformat(), items):
            raise ToolError(f"{booking['request_id']} already has this exact request for {booking['name']} on "
                            f"{job_date}. It wasn't created twice.")
    if sum(booking["job_date"] == job_date.isoformat() for booking in existing) >= JOBS_PER_DAY:
        raise ToolError(f"{job_date} is fully booked ({JOBS_PER_DAY} jobs already). Pick another day.")
    booking = {"request_id": f"CB-{len(existing) + 1:04d}", "status": "pending team confirmation",
               "name": name.strip(), "contact": contact, "job_date": job_date.isoformat(), "items": items,
               "total_usd": clean_number(total_usd), "deposit_usd": clean_number(total_usd * 0.3)}
    BOOKINGS_FILE.parent.mkdir(exist_ok=True)
    with open(BOOKINGS_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps({"created": datetime.now().isoformat(timespec="seconds"), **booking}) + "\n")
    return booking


@mcp.tool
def plan_clean_break(
    name: str,
    contact: Contact,
    job_date: Day,
    area: Area,
    jobs: Annotated[list[Job], Field(description="The services the customer wants, each with its option "
                                                 "as in get_quote")],
) -> Plan:
    """Turn a customer's whole request into one booking request: price every job with get_quote, then send
    the total to create_booking_request so the prices are never retyped. If any job can't be priced,
    nothing is booked."""
    log(f"plan_clean_break({name!r}, {job_date}, {area!r}, {len(jobs)} job(s))")
    if not jobs:
        raise ToolError("Give at least one job to plan.")
    quotes = []
    for number, job in enumerate(jobs, 1):
        try:
            quotes.append(get_quote(job["service"], job_date, area, job.get("option", "")))
        except ToolError as error:
            raise ToolError(f"Job {number} ({job['service']}): {error} Nothing was booked.") from error
    items = [f"{quote['service']}, {quote['option']}" + (" (express)" if quote["express"] else "")
             for quote in quotes]
    booking = create_booking_request(name, contact, job_date, items, sum(quote["price_usd"] for quote in quotes))
    return {"quotes": quotes, "booking": booking}


if __name__ == "__main__":
    mcp.run(show_banner=False)
