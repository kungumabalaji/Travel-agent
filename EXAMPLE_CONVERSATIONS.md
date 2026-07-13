# Example Conversations

Real transcripts captured while testing against the live booking API — not
scripted/fabricated examples. Booking `LH123456` (Emma, Noah, and Maya
Rivers, flying Jet2 to Palma de Mallorca) is a real record in the hosted
mock API.

## 1. Happy path — text chat, multi-passenger

> **Customer:** Hi, my booking reference is LH123456, I want to add luggage
>
> **Assistant:** I've found your booking, LH123456. You're traveling to
> Palma de Mallorca with Jet2, departing on August 12th. I see you have
> three passengers: Emma, Noah, and Maya. Would you like to add luggage,
> check prices, or see what luggage is already included?
>
> **Customer:** I want to add luggage, check prices, and see what is included
>
> **Assistant:** I've retrieved the available luggage options for your
> booking. Here are the options:
> - 20kg Checked Bag: £38
> - 26kg Checked Bag: £55
> - Cabin Overhead Bag: £24
> - Sports Equipment Case: £68
>
> These options are available for each passenger: Emma, Noah, and Maya.
> Which passenger(s) would you like to add luggage for, and which type of
> luggage would you like to add?
>
> **Customer:** i will go for 26kg Checked Bag for 55 pounds, for Emma
>
> **Assistant:** I've added a 26kg Checked Bag for Emma. The total added
> cost is £55.

Confirmed against the live API afterward — the booking's `add-luggage`
endpoint returned `success: true` with a real `confirmationCode`, not just
a plausible-sounding reply.

## 2. Three invalid references → escalation

Tests the code-enforced 3-strikes counter (see `DESIGN_NOTES.md`), not just
prompt instructions.

> **Customer:** my booking reference is ZZ999999
>
> **Assistant:** I couldn't find a booking with that reference. Could you
> please check it and send it again?
>
> **Customer:** my booking reference is FAKE12345
>
> **Assistant:** I couldn't find a booking with that reference. Could you
> please check it and send it again?
>
> **Customer:** my booking reference is NOTREAL99
>
> **Assistant:** I'll hand this over to a human agent so they can help you
> further. Please keep your booking reference ready.

The 3rd failed lookup returned `should_escalate: true` from
`get_booking_details`, which is what actually triggered the
`escalate_to_human` call — not the model deciding on its own to give up.

## 3. Closing message (loveholidays-branded sign-off)

> **Customer:** my booking reference is LH123456
>
> **Assistant:** I've found your booking, LH123456. You're traveling with
> Jet2 to Palma de Mallorca on August 12th. I see you have three
> passengers: Emma, Noah, and Maya. Would you like to add luggage, check
> prices, or see what luggage is already included?
>
> **Customer:** no that is everything, thanks a lot!
>
> **Assistant:** You're welcome! Enjoy your holiday with loveholidays!

## 4. Voice agent — same booking, via Retell custom functions

Not a live phone call transcript — the exact `/functions` request/response
trace from testing the custom-function integration directly, in call
order, same `call_id` throughout. Real live call transcripts follow below
(§5–8), captured once the voice agent was fully deployed.

**`get_booking_details`** — `{"booking_reference": "LH123456"}` →
booking found, 3 passengers, `canAddLuggage: true`.

**`get_luggage_options`** — `{"booking_reference": "LH123456"}` → 12
flattened options (4 bag types × 3 passengers), e.g.
`"ANC-BAG20::PAX-1002"` = 20kg Checked Bag, £38, for passenger `PAX-1002`
(Noah).

**`add_luggage`** — `{"booking_reference": "LH123456", "selected_option_id": "ANC-BAG20::PAX-1002"}` →

```json
{
  "success": true,
  "bookingReference": "LH123456",
  "message": "Luggage added successfully.",
  "addedItems": [{
    "name": "20kg Checked Bag",
    "passengerRefIds": ["PAX-1002"],
    "quantity": 1,
    "unitPrice": 38,
    "totalPrice": 38,
    "currency": "GBP",
    "confirmationCode": "LUG-B25587B4D6"
  }],
  "confirmationCode": "LUG-687F994DB1"
}
```

A real `confirmationCode` from the live API — confirms the voice agent's
`/functions` dispatch builds the correct nested request shape
(`serviceDefinitionId`, `ancillaryServiceId`, passenger + flight segment
refs, priced item) that the chat agent's tools also produce.

## 5. Live voice call — duplicate item blocked, then recovered

**Booking:** LH123456. Real call, evaluated against the golden dataset
(see `EVALUATION.md`). Asked for a 20kg bag for Emma, which had already
been added earlier — the system correctly blocked the duplicate instead of
silently double-adding it, then the agent recovered by offering what was
still actually available and completing a different item.

| Step | Evidence (quoted from the call) |
|---|---|
| Booking lookup | *"I've found your booking ending in Palma de Mallorca... 20 kilo checked bag for 38 pounds, 26 kilo... cabin overhead... sports equipment case"* |
| Duplicate blocked | *"a 20 kilo checked bag has already been added for Emma... the system won't let me add the same item again"* |
| Escalation logged | *"I'll hand this over to a human agent so they can help you further"* — logged as a ticket; see the note on escalation behavior below |
| Recovery | *"the remaining options I can see are: 26 kilo... cabin overhead... sports equipment case... All right, that's done — I've added one Sports Equipment Case for Emma"* |
| Final confirmation | *"I've added one Sports Equipment Case for Emma on booking LH123456... for an extra 68 pounds"* |

This call also produced the finding, since resolved, that escalation logs
a ticket without ending the conversation — the agent stayed fully
functional and completed the task itself right after escalating. See
`DESIGN_NOTES.md`'s "What escalation actually does once it fires" for why
that's the intended behavior, not a bug.

## 6. Live voice call — multi-passenger addition, no detours

**Booking:** LH654321 (Sofia and Daniel Lane, Faro). Real call — the
cleanest of the four, and the one to point to as the primary
"successful addition" example: no duplicate, no escalation, both
passengers added off a single confirmation.

| Step | Evidence |
|---|---|
| Misheard reference | *"is your booking reference 'LAT654321'?"* → *"I couldn't find a booking with the reference LAT654321"* — asked for confirmation rather than guessing, then correctly reported not-found rather than forcing a match |
| Corrected reference | *"I've found your booking for Sofia and Daniel Lane to Faro"* |
| Multi-passenger request itemized | *"one 20 kilo checked bag for Sofia Lane and one 20 kilo checked bag for Daniel Lane, at 39 pounds each, total 78 pounds. Is that correct?"* |
| Single "yes" → both added | *"All done. I've added one 20 kilo checked bag for Sofia and one 20 kilo checked bag for Daniel... total 78 pounds"* |

## 7. Live voice call — edge-case marathon (cancelled, fare-blocked, invalid refs, privacy)

**Bookings touched:** LH123456 (success), LH000111 (cancelled), LH777888
(fare-blocked), plus several invalid references. Real call, deliberately
run long to stack multiple golden-dataset scenarios into one recording —
the primary "escalation" example, since it demonstrates escalation for
three distinct, valid reasons in a single call.

| Scenario | Evidence |
|---|---|
| Mid-confirmation change of mind | *"Oh, actually, wait. Make it, uh, twenty kgs, not twenty six kgs"* — re-confirmed the corrected item before adding, didn't silently apply either the old or new choice |
| Cancelled booking | *"it's showing as cancelled and it can't be changed or have luggage added... I've now passed booking LH000111 to a human agent"* |
| Fare-blocked booking | *"the airline fare type on this one doesn't allow luggage changes... you'd usually have to sort it directly with the airline"* — a genuinely distinct reason from the cancellation case, not a generic refusal |
| Repeated invalid references | *"I still can't find a booking under LH12345. Can you have another look..."* — no hallucinated match across LH999999, LH12345 (twice) |
| Bounded retries → escalation | *"after a few tries I need to pass this on. I've handed your request to a human agent"* — matches the code-enforced 3-strikes design, not an endless loop |
| Friend's-booking privacy refusal | *"I can't do that. I'm not allowed to share or discuss someone else's booking without their permission"* — caught the "without them knowing" framing specifically |
| Out-of-scope request | *"I can't book cinema tickets or movies, as I can only help with luggage"* |

## 8. Live voice call — direct request for a human, no booking context

**Outcome:** clean, fast escalation with no booking reference ever given.
Real call, short by design — useful specifically because it proves the
agent doesn't force a customer through the full booking flow if they just
want a human.

| Step | Evidence |
|---|---|
| Vague opening | Customer said "For me, do it" with no context — agent asked for a booking reference first rather than guessing intent |
| Direct escalation request | *"Can I speak to a human agent?"* → *"I've passed this over to a human agent now, and your support ticket number is ESC-32E74765"* — honored immediately, with a real ticket number rather than a vague promise |
