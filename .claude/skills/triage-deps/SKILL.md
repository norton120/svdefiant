---
name: triage-deps
description: Reviews recent inbound mail (orders, shipping, deliveries) from the SES inbox and updates `blocked:parts` labels on GitHub issues accordingly. Adds the label when an issue mentions an outstanding part order; removes it when delivery is confirmed. Auto-applies. Use when the user asks to "triage parts", "update blocked labels", or after new orders/deliveries have come in.
---

# Triage parts dependencies

Reads SES inbound mail, cross-references with open issues on `norton120/svdefiant`, and updates the `blocked:parts` label. Auto-applies; reports what changed; acks every email it processed so the next run skips them.

## Steps

1. **Fetch unprocessed emails** (default: unprocessed in last 14 days). The CLI already filters out anything previously acked:
   ```
   defiant inbox list --since 14d
   ```
   Then narrow by subject/sender to delivery-relevant items. Reasonable patterns:
   `amazon|ups|fedex|usps|defender|west.?marine|jamestown|hamilton|sailrite|harken|raymarine|shipped|delivered|tracking|order.confirmation|out.for.delivery`.

   If an email obviously isn't delivery-related (e.g. a newsletter), still ack it with a note (step 6) so it doesn't keep showing up.

2. **Pull open issues with bodies + labels**:
   ```
   defiant task list --limit 300 --with-body
   ```

3. **For each delivery-relevant email**, fetch the full body when needed:
   ```
   defiant inbox get <message_id_or_s3_key>
   ```
   Look for: vendor, order ID, parts/SKUs, status (ordered / shipped / out for delivery / delivered), tracking number, ETA.

4. **Match emails ↔ issues** using Claude judgment. Strong matches require:
   - vendor or part name from the email appears in the issue body, OR
   - a tracking number / order ID from the email appears in the issue body.

5. **Decide label changes**:
   - Issue currently has `blocked:parts` AND a delivery confirmation email exists for the part(s) → **remove** the label.
   - Issue does NOT have `blocked:parts` AND its body mentions an outstanding order with a recent order/shipping email and no delivery confirmation → **add** the label.
   - Anything ambiguous → leave as-is and mention in the summary.

6. **Apply** (auto-apply, no confirmation):
   ```
   defiant task update <number> --blocked-parts        # add the label
   defiant task update <number> --no-blocked-parts     # remove it
   ```
   `defiant task update` is idempotent — re-running with the same flag is a no-op.

7. **Ack each processed email** so it doesn't get reconsidered next run:
   ```
   defiant inbox ack <id> --note "<one-line reason>"
   ```
   Always ack, including emails you decided weren't actionable — the note explains why for future-you.

8. **Report** a final summary table:
   | Issue | Title | Action | Why (1 line) |

   Plus a "stragglers" section: relevant emails with no matching issue (so the user can decide whether to open one). Stragglers should still be acked unless you genuinely want them to re-surface next run.

## Conservatism

- Don't add the label without an actual order/shipping email referenced in the issue.
- Don't remove without an explicit delivery confirmation (not just "shipped").
- "Out for delivery" is not delivery — keep blocked.
- If multiple parts are tracked in one issue, only remove `blocked:parts` when *all* parts have delivery confirmations.

## Notes

- The dedup is durable across runs (state lives in `~/.defiant/inbox-state.json`). If you accidentally ack the wrong email, `defiant inbox unack <id>` reverses it.
- Issues need to mention vendor / order info in their body for matching to work. If an issue has no body context, you cannot match it — leave alone.
