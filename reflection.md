# Reflection

I drew the line between the tools by asking one question about each one: does it only read, does it change
something, or does it connect the other two? get_quote only reads the price list, so the agent can call it as many
times as it wants without any risk. create_booking_request is the only tool that writes anything. plan_clean_break
has no rules of its own, it just calls the other two in order and stops if one of them fails. In Assignment 4 the
price and the date were two separate tools, but here I put the date check inside get_quote, because the price
depends on the date (less than 48 hours is Express) and splitting them would mean two calls for one answer. The
part I'm least happy with is the option argument. It means home size for most services, storage length for the
Memory Vault and nothing at all for the Swap. Testing with the real model also showed me things I didn't plan for.
Gemini turned "karim at gmail" into a full email by itself and booked it, so now the agent has to pass the contact
exactly as written and the server decides if it's valid. When the customer then corrected the email, the agent
made a second booking, so I added a duplicate check. Calling the booking tool directly showed one more problem.
It trusted whatever it got, so I could save a booking for 2000-01-01, one on a Sunday and a $220 move-out for $1,
and it didn't even keep the area. I moved the date and price rules into two small helper functions that get_quote
and create_booking_request both use, so the booking tool now checks everything before saving and I still have
exactly three tools.

Three tools was enough for a booking demo, but it felt a bit tight. The duplicate problem came from the fact that
there is no tool to update a booking. The booking tool also repeats the price check that get_quote already did,
which is a bit of extra work, but it means the action tool can't save something the business would never accept.
If I kept working on it, I would add a tool to update or cancel a request, check public holidays and the team's
real schedule instead of a fixed limit of two jobs a day, allow more than one Swap trip or Vault box, and save the
bookings in SQLite instead of a JSON lines file. I would also want the team to get a notification when a request
comes in, so it doesn't just sit in a file.
