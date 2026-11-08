"""Python hooks for app.velo.json: plain functions the Studio app can call.

Open it in the builder:   velo studio examples/no_code/app.velo.json
Run it:                   velo run examples/no_code/app.velo.json
"""


def email_everyone(ctx):
    """Button action ("Run Python hook" → email_everyone)."""
    people = ctx["entries"]
    if not people:
        ctx.toast("Nobody has registered yet", "warning")
        return
    # Plug in smtplib / an email API here.
    ctx.toast(f"Sent a welcome email to {len(people)} people ✉️", "success")


FAQ = {
    "when": "Saturday, 10am to 4pm.",
    "where": "Room 204, main campus (bring a laptop).",
    "price": "It's free!",
    "track": "Pick Python basics, Data analysis or Web apps on the Register page.",
}


def answer(ctx, message):
    """Chat hook: receives what the visitor typed and returns the reply (markdown allowed).
    Swap this for a call to any AI model."""
    text = message.lower()
    for word, reply in FAQ.items():
        if word in text:
            return reply
    n = len(ctx["entries"])
    return f"I can answer questions about **when**, **where**, **price** and **tracks**. ({n} registered so far.)"
