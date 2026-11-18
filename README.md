# Asistente Inmobiliario: AI inbox for real estate agencies

[![CI](https://github.com/sanmingar1/asistente-negocio/actions/workflows/ci.yml/badge.svg)](https://github.com/sanmingar1/asistente-negocio/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)

Small real estate agencies get leads from many places: Idealista, Fotocasa, Airbnb and direct email. Those leads land in the same Gmail inbox as newsletters and paperwork. Answer a hot buyer too late and the deal is gone.

This app connects to the agency's Gmail and turns the inbox into a prioritised work queue. An LLM reads each email, assigns a category and priority, scores the lead and writes a one-line summary. From there the agent can answer, book a viewing or move the contact through a mini-CRM, all without leaving the page.

> The UI and prompts are in Spanish because the target users are agencies in Spain.

## Features
- **Classification with structured output.** Each email gets a category, a priority, a summary and a **lead score from 0 to 10**. Categories: purchase offer, viewing request, price enquiry, paperwork, general enquiry and spam. They are defined in `config.yaml`, so the same code can serve another kind of business. The prompt uses chain-of-thought plus few-shot examples, the JSON is validated, and on any error it falls back to a safe default.
- **Portal lead detection.** It recognises emails from Idealista, Fotocasa, Airbnb, Habitaclia, Pisos.com, Kyero and ThinkSpain, and extracts the buyer's contact details.
- **Reply drafts and thread summaries**, generated on demand. The agent always reviews a draft before it's sent.
- **Viewing scheduling.** It reads free slots from Google Calendar within business hours and creates the event.
- **Mini-CRM.** Contacts are created automatically from emails and move through a pipeline (lead → viewing → offer → closed/discarded), with notes.
- **Inbox tools.** Manual reclassification, snooze until a given date and time, bulk archive and mark-as-read, and several Gmail accounts in one inbox.
- **Telegram alerts** for urgent emails.
- **Demo mode** with realistic sample emails, so you can try it without connecting a mailbox.

## Architecture
```
Gmail API ──► sync ──► AIClassifier (LLM via OpenAI-compatible API) ──► SQLite (SQLAlchemy)
                │                                                         │
          portal_parser                                         FastAPI REST API (/api/*)
                                                                          │
Google Calendar ◄── scheduling ◄────────────────────── Single-page frontend (Tailwind)
Telegram ◄── notifier (urgent emails)
```
- **Backend:** FastAPI, SQLAlchemy and SQLite. The code is split into modules for Gmail, Calendar, classification, portal parsing, notifications and the CRM.
- **LLM:** Llama 3.1 70B through NVIDIA NIM's OpenAI-compatible endpoint. To use another provider, change `config.yaml`.
- **Frontend:** one HTML file with Tailwind, served by FastAPI.
- **Deployment:** Docker, plus scripts for an Ubuntu server where each agency runs its own isolated container on its own port (`scripts/add_client.sh`).

## Run it locally
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your NVIDIA_API_KEY (Telegram is optional)
uvicorn main:app --reload     # http://localhost:8000
```
Demo mode is on by default (`demo.enabled: true` in `config.yaml`), so the inbox opens with sample emails.

To connect a real Gmail account, create an OAuth client (Desktop app) in Google Cloud with the Gmail and Calendar APIs enabled. Save it as `credentials.json` in the project root and add the account from the UI.

With Docker:
```bash
docker build -t asistente-inmobiliario .
docker run -p 8000:8000 --env-file .env asistente-inmobiliario
```

## Tests
```bash
pip install pytest httpx
pytest -q     # 148 tests: Gmail, Calendar and the LLM are mocked
```

## Status
v0.1, a working prototype. It hasn't been used by a real agency yet.
