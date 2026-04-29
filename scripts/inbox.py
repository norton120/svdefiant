#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["boto3", "pypdf", "html2text"]
# ///
"""
Read parsed inbound mail from the SES → S3 bucket as JSON.

Usage:
  inbox.py list [--since 7d] [--from REGEX] [--subject REGEX]
  inbox.py get <id>          # id = substring of s3 key or Message-ID

Output: JSON to stdout. AWS creds via standard env / SSO.
"""
from __future__ import annotations

import argparse
import email
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email import policy

import boto3
import html2text
from pypdf import PdfReader

BUCKET = "svdefiant-inbound-mail"
PREFIX = "inbound/"
REGION = "us-east-1"
SETUP_NOTIFICATION_KEY = f"{PREFIX}AMAZON_SES_SETUP_NOTIFICATION"


def parse_since(s: str) -> datetime:
    if s.endswith("d"):
        return datetime.now(timezone.utc) - timedelta(days=int(s[:-1]))
    if s.endswith("h"):
        return datetime.now(timezone.utc) - timedelta(hours=int(s[:-1]))
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def list_objects(s3, since: datetime | None):
    paginator = s3.get_paginator("list_objects_v2")
    out = []
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"] == SETUP_NOTIFICATION_KEY:
                continue
            if since and obj["LastModified"] < since:
                continue
            out.append(obj)
    out.sort(key=lambda o: o["LastModified"], reverse=True)
    return out


def fetch_msg(s3, key: str):
    raw = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    return email.message_from_bytes(raw, policy=policy.default)


def extract_body(msg) -> str:
    plain, html = None, None
    for part in msg.walk():
        if part.is_multipart():
            continue
        cd = str(part.get("Content-Disposition", "")).lower()
        if "attachment" in cd:
            continue
        ctype = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:
            continue
        if ctype == "text/plain" and plain is None:
            plain = content
        elif ctype == "text/html" and html is None:
            html = content
    if plain:
        return plain.strip()
    if html:
        h = html2text.HTML2Text()
        h.ignore_images = True
        h.body_width = 0
        return h.handle(html).strip()
    return ""


def extract_attachments(msg) -> list[dict]:
    out = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        cd = str(part.get("Content-Disposition", "")).lower()
        if "attachment" not in cd:
            continue
        filename = part.get_filename() or ""
        ctype = part.get_content_type()
        att = {"filename": filename, "content_type": ctype}
        payload = part.get_payload(decode=True) or b""
        att["size_bytes"] = len(payload)
        if ctype == "application/pdf":
            try:
                pdf = PdfReader(io.BytesIO(payload))
                att["text"] = "\n".join((p.extract_text() or "") for p in pdf.pages).strip()
            except Exception as e:
                att["text_error"] = str(e)
        elif ctype.startswith("text/"):
            try:
                att["text"] = payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()
            except Exception as e:
                att["text_error"] = str(e)
        out.append(att)
    return out


def summarize(msg, key: str, last_modified: datetime, snippet_len: int = 240) -> dict:
    body = extract_body(msg)
    return {
        "s3_key": key,
        "message_id": (msg.get("Message-ID") or "").strip("<>"),
        "date": str(msg.get("Date") or ""),
        "received": last_modified.isoformat(),
        "from": str(msg.get("From") or ""),
        "to": str(msg.get("To") or ""),
        "subject": str(msg.get("Subject") or ""),
        "snippet": re.sub(r"\s+", " ", body)[:snippet_len],
    }


def full(msg, key: str, last_modified: datetime) -> dict:
    d = summarize(msg, key, last_modified, snippet_len=10_000_000)
    d["body_text"] = d.pop("snippet")
    d["attachments"] = extract_attachments(msg)
    return d


def cmd_list(args, s3):
    since = parse_since(args.since) if args.since else None
    from_re = re.compile(args.from_pat, re.I) if args.from_pat else None
    subj_re = re.compile(args.subject_pat, re.I) if args.subject_pat else None
    out = []
    for obj in list_objects(s3, since):
        msg = fetch_msg(s3, obj["Key"])
        d = summarize(msg, obj["Key"], obj["LastModified"])
        if from_re and not from_re.search(d["from"]):
            continue
        if subj_re and not subj_re.search(d["subject"]):
            continue
        out.append(d)
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_get(args, s3):
    target = args.id
    for obj in list_objects(s3, since=None):
        msg = fetch_msg(s3, obj["Key"])
        msg_id = (msg.get("Message-ID") or "").strip("<>")
        if target in obj["Key"] or target == msg_id or target in msg_id:
            json.dump(full(msg, obj["Key"], obj["LastModified"]), sys.stdout, indent=2, default=str)
            sys.stdout.write("\n")
            return
    json.dump({"error": f"not found: {target}"}, sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser(prog="inbox")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="list messages with metadata + snippet")
    p.add_argument("--since", default="7d", help="e.g. 7d, 24h, or ISO date")
    p.add_argument("--from", dest="from_pat", help="regex for From header")
    p.add_argument("--subject", dest="subject_pat", help="regex for Subject")

    p = sub.add_parser("get", help="full message + attachments by id")
    p.add_argument("id", help="substring of s3 key or Message-ID")

    args = ap.parse_args()
    s3 = boto3.client("s3", region_name=REGION)
    {"list": cmd_list, "get": cmd_get}[args.cmd](args, s3)


if __name__ == "__main__":
    main()
