import logging
import os
from typing import Dict

import requests
import yaml

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

PRIORITY_EMOJI = {
    "urgente": "🚨",
    "alta": "🔴",
    "media": "🟡",
    "baja": "⚪",
}


def _load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def notify(email_data: Dict, classification: Dict) -> None:
    """
    Send a notification for a newly classified email if its priority
    matches the configured trigger list. Silently skips if notifications
    are disabled or credentials are missing.
    """
    try:
        config = _load_config()
        notif_cfg = config.get("notifications", {})

        if not notif_cfg.get("enabled", False):
            return

        trigger_priorities = set(notif_cfg.get("trigger_priorities", ["urgente"]))
        priority = classification.get("priority", "")

        if priority not in trigger_priorities:
            return

        channel = notif_cfg.get("channel", "telegram")
        if channel == "telegram":
            _send_telegram(email_data, classification, config)

    except Exception as exc:
        logger.error("Notification failed: %s", exc)


def _send_telegram(email_data: Dict, classification: Dict, config: Dict) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials not set — skipping notification.")
        return

    business_name = config.get("business", {}).get("name", "Asistente")
    priority = classification.get("priority", "")
    category = classification.get("category", "")
    summary = classification.get("summary", "")
    sender = email_data.get("sender", "Desconocido")
    sender_email = email_data.get("sender_email", "")
    subject = email_data.get("subject", "(Sin asunto)")
    emoji = PRIORITY_EMOJI.get(priority, "📩")

    text = (
        f"{emoji} *Correo {priority.upper()}* — {business_name}\n\n"
        f"*De:* {sender} \\<{sender_email}\\>\n"
        f"*Asunto:* {subject}\n"
        f"*Categoría:* {category}\n\n"
        f"*Resumen IA:*\n{summary}"
    )

    response = requests.post(
        TELEGRAM_API.format(token=token),
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=10,
    )

    if response.ok:
        logger.info("Telegram notification sent for email '%s'", subject)
    else:
        logger.error("Telegram API error %s: %s", response.status_code, response.text)
