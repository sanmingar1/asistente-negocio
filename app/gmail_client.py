import os
import re
import base64
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime
from typing import List, Dict, Optional, Set

import yaml
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",   # create/edit events
    "https://www.googleapis.com/auth/calendar.readonly",  # freebusy queries
]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


class GmailClient:
    def __init__(self):
        with open("config.yaml", "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.max_emails = self.config["email_provider"].get("max_emails_per_sync", 20)
        self._service = None

    def authenticate(self) -> Credentials:
        """Run OAuth flow, refreshing or creating a token as needed."""
        creds: Optional[Credentials] = None

        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Gmail token.")
                creds.refresh(Request())
            else:
                logger.info("Starting Gmail OAuth flow.")
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(TOKEN_FILE, "w", encoding="utf-8") as token_file:
                token_file.write(creds.to_json())
            logger.info("Gmail token saved to %s", TOKEN_FILE)

        return creds

    def get_service(self):
        """Return an authenticated Gmail API service, caching it."""
        if self._service is None:
            creds = self.authenticate()
            self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_sender(raw_from: str):
        """Split 'Display Name <email@example.com>' into (name, email)."""
        match = re.match(r"^(.*?)\s*<([^>]+)>$", raw_from.strip())
        if match:
            name = match.group(1).strip().strip('"')
            email = match.group(2).strip()
            return name or email, email
        # Plain email address with no display name
        email = raw_from.strip()
        return email, email

    @staticmethod
    def _get_header(headers: List[Dict], name: str) -> str:
        """Extract a header value by name (case-insensitive)."""
        for h in headers:
            if h.get("name", "").lower() == name.lower():
                return h.get("value", "")
        return ""

    @staticmethod
    def _decode_body(data: str) -> str:
        """Base64-urlsafe decode a Gmail message part body."""
        try:
            decoded_bytes = base64.urlsafe_b64decode(data + "==")
            return decoded_bytes.decode("utf-8", errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _strip_html(html: str) -> str:
        """Strip HTML to plain text, removing style/script blocks first."""
        clean = re.sub(r"<(style|script)[^>]*>.*?</(style|script)>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"&nbsp;", " ", clean)
        clean = re.sub(r"&amp;", "&", clean)
        clean = re.sub(r"&lt;", "<", clean)
        clean = re.sub(r"&gt;", ">", clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()

    def _extract_body(self, payload: Dict) -> str:
        """
        Recursively walk the MIME tree and return the best available text body.
        Prefers text/plain; falls back to text/html (stripped).
        """
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime_type == "text/plain" and body_data:
            return self._decode_body(body_data)

        if mime_type == "text/html" and body_data:
            return self._strip_html(self._decode_body(body_data))

        # Walk multipart parts, prefer plain first
        parts = payload.get("parts", [])
        plain_text = ""
        html_text = ""

        for part in parts:
            part_mime = part.get("mimeType", "")
            part_data = part.get("body", {}).get("data", "")

            if part_mime == "text/plain" and part_data and not plain_text:
                plain_text = self._decode_body(part_data)
            elif part_mime == "text/html" and part_data and not html_text:
                html_text = self._strip_html(self._decode_body(part_data))
            elif part_mime.startswith("multipart/"):
                nested = self._extract_body(part)
                if nested and not plain_text:
                    plain_text = nested

        return plain_text or html_text

    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """Parse an RFC 2822 date string to a timezone-aware datetime."""
        if not date_str:
            return None
        try:
            dt = parsedate_to_datetime(date_str)
            return dt.astimezone(timezone.utc).replace(tzinfo=None)  # store as UTC naive
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_emails(
        self,
        max_results: Optional[int] = None,
        existing_ids: Optional[Set[str]] = None,
    ) -> List[Dict]:
        """
        Fetch up to max_results emails from INBOX.

        Args:
            max_results: Override the configured limit.
            existing_ids: Set of gmail_ids already in the database to skip.

        Returns:
            List of dicts with keys: gmail_id, sender, sender_email, subject,
            body_preview, received_at, raw_labels.
        """
        if max_results is None:
            max_results = self.max_emails
        if existing_ids is None:
            existing_ids = set()

        service = self.get_service()
        results = []

        try:
            response = (
                service.users()
                .messages()
                .list(userId="me", labelIds=["INBOX"], maxResults=max_results, q="-in:sent")
                .execute()
            )
        except HttpError as exc:
            logger.error("Failed to list Gmail messages: %s", exc)
            raise

        messages = response.get("messages", [])
        logger.info("Gmail returned %d message IDs.", len(messages))

        for msg_meta in messages:
            gmail_id = msg_meta["id"]

            if gmail_id in existing_ids:
                logger.debug("Skipping already-imported email %s", gmail_id)
                continue

            try:
                msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=gmail_id, format="full")
                    .execute()
                )
            except HttpError as exc:
                logger.warning("Could not fetch message %s: %s", gmail_id, exc)
                continue

            payload = msg.get("payload", {})
            headers = payload.get("headers", [])

            raw_from = self._get_header(headers, "From")
            sender_name, sender_email = self._parse_sender(raw_from)
            subject = self._get_header(headers, "Subject") or "(Sin asunto)"
            date_str = self._get_header(headers, "Date")

            body = self._extract_body(payload)
            snippet = msg.get("snippet", "")
            body_preview = body[:500].strip() if body.strip() else snippet

            raw_labels = msg.get("labelIds", [])

            results.append(
                {
                    "gmail_id": gmail_id,
                    "thread_id": msg.get("threadId"),
                    "sender": sender_name,
                    "sender_email": sender_email,
                    "subject": subject,
                    "body_preview": body_preview,
                    "body_full": body[:3000],  # Pass more context to AI, not stored
                    "received_at": self._parse_date(date_str),
                    "raw_labels": str(raw_labels),
                }
            )

        logger.info("Fetched %d new emails to process.", len(results))
        return results

    def send_reply(self, gmail_id: str, to_email: str, subject: str, body: str, thread_id: Optional[str] = None) -> str:
        """
        Send a reply to an email. Returns the sent message's Gmail ID.
        Fetches the original Message-ID header to set In-Reply-To for proper threading.
        """
        service = self.get_service()

        # Fetch original message to get Message-ID header for threading
        in_reply_to = ""
        try:
            orig = service.users().messages().get(
                userId="me", id=gmail_id, format="metadata",
                metadataHeaders=["Message-ID"]
            ).execute()
            in_reply_to = self._get_header(orig.get("payload", {}).get("headers", []), "Message-ID")
        except Exception as exc:
            logger.warning("Could not fetch original Message-ID for threading: %s", exc)

        reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to_email
        msg["Subject"] = reply_subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body_payload: Dict = {"raw": raw}
        if thread_id:
            body_payload["threadId"] = thread_id

        sent = service.users().messages().send(userId="me", body=body_payload).execute()
        logger.info("Reply sent, message ID: %s", sent.get("id"))
        return sent["id"]
