# Eatery inquiry plan

Prepared October 6, 2026. The user approved a 20-eatery pilot and Gmail organization setup. The `Eatery inquiries` label and both incoming filters are created and verified in the personal mailbox. The authorized 20-eatery email pilot has been sent sequentially from `andrew.p.council@gmail.com`. All sent-message IDs, sender headers, bodies, and labels were verified. No forms were submitted.

## Setup status

- Confirmed `andrew.p.council@gmail.com` in the actual Chromium session.
- Created and verified the visible `Eatery inquiries` label through Composio.
- Created both filters through the authorized Gmail settings UI. Composio API read-back confirmed their exact criteria and label-only actions.
- Neither rule archives, marks messages read, forwards, deletes, changes importance, or overrides spam filtering. Existing messages were not bulk-labeled.
- Created `private-outreach/gmail-setup.json` and `private-outreach/outreach-ledger.json`. Git ignores the directory. The directory has permissions 700 and the files have permissions 600. The ledger records the 20 pilot inquiries, draft/message/thread IDs, source evidence, approvals, and verification results. No restaurant correspondence belongs in committed files.
- The 20-recipient pilot is complete. Each draft was checked before sending, and each sent message was checked against its approved recipient/body and labeled. Final Gmail read-back matched all 20 recorded sent-message IDs. No immediate delivery-failure notices or labeled incoming replies were found in the initial check; this does not establish delivery.
- Further sending is disabled in the local ledger. No follow-ups, additional batches, or form submissions are scheduled.

Both rules apply `Eatery inquiries`:

1. Subject contains `Peanut allergy question before visiting`.
2. To address is `andrew.p.council+eateries@gmail.com`, for future form replies.

The Composio filter-creation action failed without exposing an underlying cause. The browser fallback succeeded. During initial browser attachment, `127.0.0.1:9222` reached an Electron work-mail window, not Chromium. The correct Chromium endpoint on this machine is `http://[::1]:9222`. Personal Gmail was already open there. No work-mailbox filters were changed. Verify the browser account rather than assuming a loopback port identifies the intended browser.

## Scope

The current selected worksheet has 345 eateries. Keep the four already-visited eateries excluded.

| Route | Eateries |
| --- | ---: |
| General-purpose email available | 197 |
| General form but no general-purpose email | 39 |
| Neither general-purpose route confirmed | 109 |

Twelve of the 197 email-covered eateries also have a general form. Use email first, not both channels at once.

There are 238 general-role email entries, representing 236 distinct addresses. Do not send to every address. Choose one suitable recipient for each inquiry after checking purpose and branch attribution.

Two mailboxes cover multiple saved branches: `team@sendo.nyc` and `hello@xiebao.com`. These are distinct branch records, not duplicates to delete. Where appropriate, send one inquiry that identifies both branch addresses and asks for branch-specific answers. The Coffee Project Chelsea and Hell's Kitchen records also share a corporate contact form. Avoid duplicate submissions to that same team.

## Risk to the primary Gmail account

Google says personal Gmail can restrict sending after more than 500 emails in a day or more than 500 recipients in one email. Many invalid addresses or bounced messages can also cause restrictions. Google describes temporary sending blocks lasting 1 to 24 hours, depending on the problem.

Our intended volume is below that published daily limit, but this does not establish a safe volume. Other personal email activity also counts. Google does not publish an account-specific spam threshold we can validate. Some messages can go to recipients' spam folders without a bounce, and successful API submission does not prove delivery.

These are genuine prospective-customer questions, not marketing messages. That makes a reviewed inquiry to a published customer-contact address more appropriate than a bulk campaign. Still, recipients can report unwanted mail, and Google prohibits spam. I recommend proceeding in small batches rather than sending the entire list at once.

Suggested operating limits, not Google-approved safe limits:

- Start with 20 carefully checked eateries, as requested by the user. Send sequentially, not as a parallel burst.
- Check for bounces, account warnings, and recipient responses before continuing.
- If there are no problems, use about 15 to 20 new inquiries per day, split into small batches. Leave capacity for ordinary personal mail and replies.
- Send individual messages. Do not put restaurants together in To, CC, or BCC.
- Use the approved template, an eatery-specific subject and greeting, and no attachments, tracking pixels, promotional links, or fabricated personalization.
- Pause on a delivery failure to investigate that address. Stop the batch on an account restriction, rate-limit warning, repeated bounces, or a complaint.
- Do not automatically chase unanswered inquiries. Any follow-up should be reviewed separately. Respect requests for no further contact.

If even a temporary restriction on the primary account would be unacceptable, use a distinct mailbox for this project before starting. That separates routine personal email from this activity, but a new mailbox does not guarantee better delivery. Do not rotate accounts to evade restrictions.

## Sender and reply organization

Composio checks confirmed the connected mailbox is `andrew.p.council@gmail.com`. Only the primary sender address is currently configured. The project label and both incoming filters are now created and verified.

Recommended starting setup:

1. Keep the normal primary From address for outbound emails.
2. Create a Gmail label named `Eatery inquiries`.
3. Create an incoming filter for the approved subject phrase, `Peanut allergy question before visiting`, that applies that label.
4. Label each successfully sent inquiry and retain its Gmail message ID and thread ID.
5. Check the tracked conversations for new replies and label each new matching message. Identify replies by the recorded conversation and message references, not just the sender's address. A restaurant may reply through a different staff address or support platform.
6. Keep replies unread and in the inbox during the pilot. After checking the filter, optionally archive only matched inquiry messages so they appear under the project label instead of the main inbox. Do not mark replies read or exempt them from spam filtering automatically.

Gmail labels on an existing conversation do not automatically apply to future messages in that conversation. The filter and subsequent checks must handle new replies. A reply with a changed subject may miss the subject filter, so the tracked thread IDs remain important. A new conversation with neither a matching subject nor another identifying cue may need manual matching. Do not label unrelated correspondence merely because it comes from a restaurant.

### Optional plus address

`andrew.p.council+eateries@gmail.com` receives mail in the same Gmail inbox. It needs no new receiving account. For forms, use it as the contact email and filter mail addressed or delivered to that exact alias into `Eatery inquiries`.

A plus address provides organization, not separate sending limits, reputation, or account protection. If a form rejects plus addresses, use the primary address and record the submission for manual matching.

To receive outbound-email replies at the plus address, it must actually be the reply destination. Merely mentioning it in the body or creating a filter does not do that. The discovered Composio send tool supports an explicitly configured send-as address, but does not expose a per-message Reply-To parameter. Its draft tools do not expose a From parameter either. Do not invent unsupported parameters or change the account's global reply-to/default sender for this project.

If an outbound plus alias is desired, configure and verify it in Gmail, inspect its reply-to settings, and test the headers and reply behavior with a message to an address you control before using it for restaurants. That test would require separate approval. The primary-address-and-label plan avoids this extra setup.

## Email execution through Composio and code mode

Prepare a local review queue keyed by stable Maps CID and cache file. Include the venue and branch address, selected contact, publication source, routing caveat, subject, rendered body, and approval/send status. Do not modify the approved questions or ask for recommended safe menu items.

Hold candidate, press, careers, legal/privacy, classes, accessibility, hidden form-routing, and otherwise unsuitable recipients. Inspect reservations-only addresses before treating them as customer-question contacts. Confirm group/branch routing where the evidence requires it.

After approval:

- Pin every Gmail call to the confirmed personal Composio account, not an inferred default connection.
- For primary-address sending, create a small set of drafts with `GMAIL_CREATE_EMAIL_DRAFT`, inspect them with `GMAIL_GET_DRAFT`, and send approved drafts with `GMAIL_SEND_DRAFT`. Confirm the actual From header before sending. Draft creation is a mailbox change and is not part of this research step.
- If a verified alias is chosen instead, use an explicitly supported sender path such as `GMAIL_SEND_EMAIL` with `from_email`. Do not assume the standard draft tool can select that alias.
- Apply the project label to sent messages using the actual label ID. Gmail's API does not allow labels on draft messages, so track draft IDs in the review queue. The available tools support label creation, incoming filters, message-label changes, and fetching messages in a recorded thread.
- Send sequentially. Use code mode to validate inputs and record each result, not to launch a parallel send fan-out.
- Save returned message/thread IDs and timestamps after each confirmed send. Separate sent, replied, automatic acknowledgment, bounced, blocked, and uncertain outcomes.
- If a send times out or returns an ambiguous failure, inspect Sent and the draft state before any retry. Never blindly retry an action that may already have sent a message.

Code mode does not provide a persistent scheduler or timers. Daily batches would run when explicitly requested unless a separate scheduling arrangement is approved. Nothing is scheduled by this plan.

Store sent-mail metadata and replies only in `private-outreach/`, which is now Git-ignored and access-restricted. Do not commit restaurant replies, personal headers, or medical correspondence to the public repository.

## Contact forms

The 39 form-only eateries have previously inspected general-inquiry forms. They still need a fresh check before submission. Inspection does not prove the form works or that the restaurant receives it.

Use `agent-browser` for the public website forms. The available Composio connection is Gmail, not a universal website-form submission service.

For each approved form inquiry:

1. Confirm the venue, branch, actual message field, required fields, and intended inquiry category.
2. Choose the relevant branch and General Inquiry or Allergy category where available. For example, Nan Xiang offers Flushing and Allergic / Q&A options. CHELI has a branch-specific General Inquiry option. HAND Hospitality is a group route, so confirm OKONOMI routing before disclosing the allergy.
3. Fill the approved message and name. Use the plus address if accepted. Include a subject where the form permits one.
4. Leave optional phone fields blank, marketing signup unchecked, and honeypot fields untouched. If a phone number is mandatory, hold the form for the user rather than inventing a number or reusing the restaurant's number. Tènten's retained form evidence shows a required phone field.
5. Submit only after explicit authorization for that venue or batch. Stop at a CAPTCHA, login, unexpected consent requirement, or ambiguous routing. Do not bypass protections or silently choose another purpose-specific form.
6. Record the submitted text, venue CID, URL, timestamp, and observed confirmation. A success page or automatic acknowledgment is not a substantive restaurant response.
7. If the result is unclear, do not immediately submit again. Review the page state and any acknowledgment first to avoid duplicates.

Combine inquiries to a shared corporate form only after checking that the team handles both saved branches. Do not submit both email and form inquiries simultaneously for the same eatery.

The remaining 109 eateries need further contact research, a clearly documented public business messaging route, or a user-handled phone/in-person question. They are not currently ready for automated general email or form outreach. Restricted contacts and social-profile leads are not substitutes without review.

## Review order

The user approved the sender/organization plan and a 20-eatery pilot. Filtering and the 20-eatery pilot are complete and verified. Review delivery outcomes and replies before expanding. Match future batches against the private ledger by venue CID and recipient to prevent duplicate inquiries. Review form submissions separately, starting with forms that require only name, email, and message.

Retain restaurant answers as written. Separate their statements about peanut-containing dishes and cross-contact practices from any interpretation. An unanswered inquiry, automatic acknowledgment, or vague reassurance is not evidence that a meal is safe.

## Sources

- Google, [personal Gmail sending limits](https://support.google.com/mail/answer/22839?hl=en).
- Google, [email sender guidelines](https://support.google.com/mail/answer/81126?hl=en), including avoiding bursts and reducing volume on bounces or deferrals. The 5,000-message bulk-sender rules are not the personal Gmail account's daily sending allowance.
- Google, [Gmail program policies](https://support.google.com/mail/answer/16734397?hl=en), especially spam, bulk mail, and restrictions on circumvention.
- Google, [filters and reply matching](https://support.google.com/mail/answer/6579?hl=en).
- Google, [aliases and reply-to configuration](https://support.google.com/mail/answer/22370?hl=en).
- Google, [message and thread label behavior](https://developers.google.com/workspace/gmail/api/guides/labels).
- Read-only Composio account/alias/label checks and discovered Gmail tool schemas, October 6, 2026. Label creation succeeded through Composio. Both filters were created in the authorized Chromium UI and verified by Composio API read-back. The cause of the Composio filter-creation failure remains unconfirmed.
