import asyncio
import json
from datetime import date, timedelta

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import server

TODAY = date.today()


def open_day(days_ahead):
    day = TODAY + timedelta(days=days_ahead)
    return day + timedelta(days=1) if day.weekday() == 6 else day


NEXT_WEEK = open_day(7)
SOON = TODAY + timedelta(days=1) if (TODAY + timedelta(days=1)).weekday() != 6 else TODAY
SUNDAY = TODAY + timedelta(days=(6 - TODAY.weekday()) % 7 or 7)


@pytest.fixture(autouse=True)
def bookings_file(tmp_path, monkeypatch):
    path = tmp_path / "bookings.jsonl"
    monkeypatch.setattr(server, "BOOKINGS_FILE", path)
    return path


# get_quote (data tool)

def test_quote_normal_price():
    quote = server.get_quote("silent move-out", NEXT_WEEK, "beirut", "2-bedroom")
    assert quote["price_usd"] == 220
    assert quote["deposit_usd"] == 66
    assert quote["express"] is False


def test_quote_express_under_48_hours():
    quote = server.get_quote("the swap", SOON, "metn")
    assert quote["express"] is True
    assert quote["price_usd"] == 82.5


def test_quote_doesnt_write_anything(bookings_file):
    server.get_quote("fresh start", NEXT_WEEK, "beirut", "studio")
    assert not bookings_file.exists()


def test_quote_wrong_option_lists_the_right_ones():
    with pytest.raises(ToolError, match="studio, 1-bedroom, 2\\+ bedrooms"):
        server.get_quote("fresh start", NEXT_WEEK, "beirut", "2-bedroom")


def test_quote_sunday_is_closed():
    with pytest.raises(ToolError, match="Sunday"):
        server.get_quote("silent move-out", SUNDAY, "beirut", "studio")


def test_quote_past_date():
    with pytest.raises(ToolError, match="already passed"):
        server.get_quote("silent move-out", TODAY - timedelta(days=3), "beirut", "studio")


# create_booking_request (action tool)

SWAP = [{"service": "the swap"}]
STUDIO_MOVE = [{"service": "silent move-out", "option": "studio"}]


def test_booking_is_saved_with_the_area(bookings_file):
    booking = server.create_booking_request("Rana", "03 123 456", NEXT_WEEK, "metn", STUDIO_MOVE, 150)
    assert booking["request_id"] == "CB-0001"
    assert booking["status"] == "pending team confirmation"
    saved = json.loads(bookings_file.read_text())
    assert saved["name"] == "Rana" and saved["area"] == "metn" and saved["total_usd"] == 150
    assert saved["items"] == ["silent move-out, studio"]


def test_booking_bad_contact(bookings_file):
    with pytest.raises(ToolError, match="isn't a valid phone number or email"):
        server.create_booking_request("Karim", "karim at gmail", NEXT_WEEK, "metn", SWAP, 55)
    assert not bookings_file.exists()


def test_booking_needs_a_name(bookings_file):
    with pytest.raises(ToolError, match="needs the customer's name"):
        server.create_booking_request("  ", "03123456", NEXT_WEEK, "beirut", SWAP, 40)
    assert not bookings_file.exists()


def test_booking_past_date_or_sunday(bookings_file):
    with pytest.raises(ToolError, match="already passed"):
        server.create_booking_request("Old", "03123456", date(2000, 1, 1), "beirut", SWAP, 40)
    with pytest.raises(ToolError, match="Sunday"):
        server.create_booking_request("Sam", "03123456", SUNDAY, "beirut", SWAP, 40)
    assert not bookings_file.exists()


def test_booking_wrong_total(bookings_file):
    with pytest.raises(ToolError, match="cost \\$220 .* not \\$1"):
        server.create_booking_request("Cheap", "03123456", NEXT_WEEK, "beirut",
                                      [{"service": "silent move-out", "option": "2-bedroom"}], 1)
    assert not bookings_file.exists()


def test_booking_wrong_option(bookings_file):
    with pytest.raises(ToolError, match="Job 1 \\(fresh start\\)"):
        server.create_booking_request("Lea", "03123456", NEXT_WEEK, "beirut",
                                      [{"service": "fresh start", "option": "mansion"}], 120)
    assert not bookings_file.exists()


def test_booking_not_created_twice():
    server.create_booking_request("Lea", "lea@mail.com", NEXT_WEEK, "metn", SWAP, 55)
    with pytest.raises(ToolError, match="CB-0001 already has this exact request"):
        server.create_booking_request("lea", "lea@mail.com", NEXT_WEEK, "metn", SWAP, 55)


def test_booking_full_day():
    server.create_booking_request("A", "a@mail.com", NEXT_WEEK, "beirut", SWAP, 40)
    server.create_booking_request("B", "b@mail.com", NEXT_WEEK, "beirut", SWAP, 40)
    with pytest.raises(ToolError, match="fully booked"):
        server.create_booking_request("C", "c@mail.com", NEXT_WEEK, "beirut", SWAP, 40)


# plan_clean_break (orchestration tool)

def test_plan_quotes_then_books_once(bookings_file):
    plan = server.plan_clean_break("Rana", "03123456", NEXT_WEEK, "beirut", [
        {"service": "silent move-out", "option": "1-bedroom"},
        {"service": "the swap"},
        {"service": "memory vault", "option": "6 months"},
    ])
    assert [quote["price_usd"] for quote in plan["quotes"]] == [150, 40, 90]
    assert plan["booking"]["total_usd"] == 280
    assert plan["booking"]["area"] == "beirut"
    assert len(bookings_file.read_text().splitlines()) == 1


def test_plan_books_nothing_if_one_job_fails(bookings_file):
    with pytest.raises(ToolError, match="Job 2 .* Nothing was booked"):
        server.plan_clean_break("Rana", "03123456", NEXT_WEEK, "beirut", [
            {"service": "silent move-out", "option": "studio"},
            {"service": "fresh start", "option": "mansion"},
        ])
    assert not bookings_file.exists()


def test_plan_needs_at_least_one_job():
    with pytest.raises(ToolError, match="at least one job"):
        server.plan_clean_break("Rana", "03123456", NEXT_WEEK, "beirut", [])


# the same tools going through an MCP client

def test_through_mcp_client():
    async def run():
        async with Client(server.mcp) as client:
            names = sorted(tool.name for tool in await client.list_tools())
            assert names == ["create_booking_request", "get_quote", "plan_clean_break"]
            prices = json.loads((await client.read_resource("cleanbreak://price-list"))[0].text)
            assert prices["prices_usd"]["the swap"]["metn"] == 55
            good = await client.call_tool("get_quote", {"service": "fresh start", "option": "studio",
                                                        "job_date": NEXT_WEEK.isoformat(), "area": "metn"})
            assert good.structured_content["price_usd"] == 120
            bad = await client.call_tool("get_quote", {"service": "fresh start", "option": "studio",
                                                       "job_date": NEXT_WEEK.isoformat(), "area": "jounieh"},
                                         raise_on_error=False)
            assert bad.is_error
    asyncio.run(run())
