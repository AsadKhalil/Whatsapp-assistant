# Client onboarding playbook (operator's runbook)

The model: **one Meta business (ours) hosts every client's number. Clients set up nothing.**
This runbook is for the operator. A client's total involvement: buy a SIM, hand it over.

## Test number vs a client number

| | Test number (`+1 555 …`) | Client number |
|---|---|---|
| Who can chat | Only numbers whitelisted in the Meta console (max 5) | Anyone |
| Token | 24-hour test token | Permanent System-User token (set once on the server) |
| Cost | Free | Free tier per number/month, then Meta's per-conversation billing |
| Good for | Demos, your own testing | Real customers |

## One-time, before client #1 (~30 min)

1. **Permanent token.** business.facebook.com → Business settings → System users → Add
   (name: `bot-engine`, role: Admin) → Generate token → select the app **Bot** with the
   permissions `whatsapp_business_messaging` and `whatsapp_business_management` → copy.
   Paste it into the server `.env` (`META_ACCESS_TOKEN=...`) and restart the engine.
   This replaces the 24-hour test token; it does not expire.
2. **Payment method.** WhatsApp Manager → Billing: add a card. Meta bills conversations
   past the free monthly tier for each number.
3. **Business verification** (deferrable): Business settings → Security Center → Start
   verification. Unverified accounts run at the lowest messaging limit — fine for a pilot;
   verify when a client's volume grows.

The webhook never changes: the app-level subscription already delivers every number in the
WhatsApp Business Account to `https://whatsapp.try-nova.shop/webhooks/meta/<business-id>`,
and the engine routes by phone number ID.

## Per client (~30–40 min, zero client setup)

1. **Collect the SIM.** The client buys a **new** SIM dedicated to the bot. A Cloud-API
   number must not be logged into the WhatsApp app, so never use their personal number.
   Put the SIM in any phone to receive the verification code.
2. **Register the number in WhatsApp Manager** (our account): Manager → Phone numbers →
   **Add phone number** → country + number → verify by the SMS code from the SIM →
   display name = the client's business name, category = their trade. Display-name review
   is usually minutes.
3. **Register for the Cloud API:** ask the engine operator to run
   `POST /v26.0/<phone-number-id>/register` (`messaging_product=whatsapp`, a 6-digit PIN) —
   the same call that unblocked the test number. Without it every send fails
   `#133010 Account not registered`.
4. **Create the client's Sheet** from our template (tabs: `Knowledge`, `Handoffs`, their
   business tabs) and share it with the service account
   `whatsapp@whatsapp-510314.iam.gserviceaccount.com` as **Editor**.
5. **Dashboard → Add a business**: web id, business name, bot name, timezone
   (`Asia/Karachi`), the Sheet id → *Check Sheet access* → create. Then inside:
   - **Sheet** page: pick Knowledge/Handoffs tabs and customer permissions per tab.
   - **Staff & groups**: staff WhatsApp numbers (they save rows without YES).
   - **Official number**: paste only the new **phone number ID** — token/secret stay empty
     because the server-wide System-User token is used.
6. **Groups (if bought):** spare phone + our SIM → dashboard **Numbers** → add → scan QR →
   add the number to the client's groups → tick staff groups in the business page.
   Keep the phone online at least every 14 days.
7. **Hand over:** a card with the bot's number ("message us anytime") and, optionally, a
   dashboard login (dashboard → business → Logins → invite). Their choice.

## Client checklist to print

- [ ] Client bought new SIM, handed it over
- [ ] Number added in WhatsApp Manager, code verified, display name approved
- [ ] Cloud-API register call done
- [ ] Sheet created from template, shared with the service account
- [ ] Business added in dashboard, Sheet access check passed
- [ ] Tabs/permissions + staff numbers configured
- [ ] Phone number ID saved on Official number page
- [ ] Test message answered end-to-end
- [ ] (If groups) WAHA number linked, added to groups
- [ ] Client card / login delivered
