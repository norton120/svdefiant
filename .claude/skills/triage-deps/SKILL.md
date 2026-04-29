---
name: triage-deps
description: Reviews recent inbound mail (orders, shipping, deliveries) from the SES inbox and updates `blocked:parts` labels on GitHub issues accordingly. Adds the label when an issue mentions an outstanding part order; removes it when delivery is confirmed. Auto-applies. Use when the user asks to "triage parts", "update blocked labels", or after new orders/deliveries have come in.
---

# Triage parts dependencies

Reads the SES inbound bucket via `scripts/inbox.py`, cross-references with open issues on `norton120/svdefiant`, and updates the `blocked:parts` label. Auto-applies; reports what changed.

## Pre-flight

- Repo: `norton120/svdefiant`
- Label: `blocked:parts` (already exists — do not create)
- Email source: `scripts/inbox.py` (CLI in this repo, returns JSON)

## Steps

1. **Fetch recent emails** (default last 14 days; widen if user mentions an older order):
   ```
   scripts/inbox.py list --since 14d
   ```
   Filter the result for delivery-relevant senders/subjects. Reasonable patterns: `amazon|ups|fedex|usps|defender|west.?marine|jamestown|hamilton|sailrite|harken|raymarine|shipped|delivered|tracking|order.confirmation|out.for.delivery`.

2. **Pull open issues with bodies + labels**:
   ```
   gh issue list --repo norton120/svdefiant --state open --limit 300 --json number,title,body,labels
   ```

3. **For each email of interest**, fetch the full body when needed:
   ```
   scripts/inbox.py get <s3_key>
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
   gh issue edit <number> --repo norton120/svdefiant --add-label "blocked:parts"
   gh issue edit <number> --repo norton120/svdefiant --remove-label "blocked:parts"
   ```

7. **Report** a final summary table:
   | Issue | Title | Action | Why (1 line) |

   Plus a "stragglers" section: relevant emails with no matching issue (so the user can decide whether to open one).

## Conservatism

- Don't add the label without an actual order/shipping email referenced in the issue.
- Don't remove without an explicit delivery confirmation (not just "shipped").
- "Out for delivery" is not delivery — keep blocked.
- If multiple parts are tracked in one issue, only remove `blocked:parts` when *all* parts have delivery confirmations.

## Notes

- The inbox bucket is `svdefiant-inbound-mail` (us-east-1); `inbox.py` handles the AWS calls.
- Issues need to mention vendor / order info in their body for matching to work. If an issue has no body context, you cannot match it — leave alone.
