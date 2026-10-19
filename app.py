import calendar as month_calendar
from datetime import date, datetime, timedelta, timezone
import csv
from html import escape
from io import StringIO
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import struct
import time
from textwrap import wrap
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "marketingpilot.db"
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="MarketingPilot", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
_app_base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
_session_secret = os.environ.get("APP_SESSION_SECRET", "").strip() or secrets.token_urlsafe(48)
_login_failures = {}


@app.middleware("http")
async def require_login(request: Request, call_next):
    if (os.environ.get("APP_PASSWORD", "").strip()
            and request.url.path not in {"/login"}
            and not request.url.path.startswith("/static/")
            and not request.session.get("authenticated")):
        next_path = request.url.path
        if request.url.query:
            next_path += "?" + request.url.query
        return RedirectResponse("/login?" + urlencode({"next": next_path}), status_code=303)
    return await call_next(request)


app.add_middleware(SessionMiddleware, secret_key=_session_secret, same_site="lax",
                   https_only=_app_base_url.startswith("https://"), max_age=8 * 60 * 60)


def csv_safe(value):
    """Prevent spreadsheet formula execution for user-entered text fields."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def calculate_efficiency(reach, clicks, leads, spend):
    """Derive simple efficiency figures from manually recorded report data."""
    return {
        "click_rate": (clicks / reach * 100) if reach > 0 else None,
        "cost_per_click": (spend / clicks) if clicks > 0 else None,
        "cost_per_lead": (spend / leads) if leads > 0 else None,
    }


def build_metric_trend_svg(metrics, field, color):
    daily = {}
    for metric in metrics:
        day = metric["report_date"]
        daily[day] = daily.get(day, 0) + int(metric[field] or 0)
    days = sorted(daily)
    if not days:
        return ""
    width, height = 520, 150
    left, right, top, bottom = 12, 508, 16, 108
    peak = max(daily.values()) or 1
    points = []
    for index, day in enumerate(days):
        x = left if len(days) == 1 else left + index * (right - left) / (len(days) - 1)
        y = bottom - (daily[day] / peak) * (bottom - top)
        points.append((round(x, 1), round(y, 1)))
    point_list = " ".join(f"{x},{y}" for x, y in points)
    dots = "".join(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{color}"><title>{escape(days[index])}: {daily[days[index]]:,}</title></circle>'
                    for index, (x, y) in enumerate(points))
    first = escape(days[0])
    last = escape(days[-1])
    return (f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Daily trend from {first} to {last}">'
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#dfe7e1"/>'
            f'<line x1="{left}" y1="{top}" x2="{right}" y2="{top}" stroke="#eef2ee"/>'
            f'<polyline points="{point_list}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>'
            f'{dots}<text x="{left}" y="137" fill="#78847e" font-size="11">{first}</text>'
            f'<text x="{right}" y="137" text-anchor="end" fill="#78847e" font-size="11">{last}</text></svg>')


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def meta_config():
    base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    return {
        "app_id": os.environ.get("META_APP_ID", "").strip(),
        "app_secret": os.environ.get("META_APP_SECRET", "").strip(),
        "api_version": os.environ.get("META_GRAPH_API_VERSION", "v23.0").strip(),
        "base_url": base_url,
        "redirect_uri": os.environ.get("META_REDIRECT_URI", "").strip()
        or f"{base_url}/integrations/meta/callback",
        "encryption_key": os.environ.get("META_TOKEN_ENCRYPTION_KEY", "").strip(),
        "instagram_enabled": os.environ.get("META_INSTAGRAM_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
    }


def meta_fernet():
    key = meta_config()["encryption_key"]
    if not key:
        raise ValueError("Token encryption is not configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise ValueError("Token encryption key is invalid") from None


class MetaAPIError(ValueError):
    def __init__(self, code):
        self.code = str(code) if str(code).isdigit() else "unknown"
        super().__init__(f"Meta API error {self.code}")


def meta_http_json(url, params):
    request_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(request_url, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error", {}) if isinstance(body, dict) else {}
            code = error.get("code", exc.code) if isinstance(error, dict) else exc.code
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            code = exc.code
        raise MetaAPIError(code) from None
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise MetaAPIError("network") from None
    if not isinstance(result, dict):
        raise MetaAPIError("invalid-response")
    if result.get("error"):
        error = result["error"]
        raise MetaAPIError(error.get("code", "unknown") if isinstance(error, dict) else "unknown")
    return result


def meta_count_summary(value):
    if not isinstance(value, dict):
        return 0
    summary = value.get("summary") or {}
    count = summary.get("total_count", 0) if isinstance(summary, dict) else 0
    return max(0, int(count)) if str(count).isdigit() else 0


def meta_graph_url(path="oauth/access_token"):
    config = meta_config()
    version = config["api_version"]
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("The Meta Graph API version is not configured")
    return f"https://graph.facebook.com/{version}/{path.lstrip('/')}"


class MetaPublishRejected(Exception):
    pass


class MetaPublishUncertain(Exception):
    pass


def meta_publish_text(page_id, message, page_token):
    endpoint = meta_graph_url(f"{page_id}/feed")
    request = URLRequest(endpoint, data=urlencode({
        "message": message,
        "access_token": page_token,
    }).encode("utf-8"), headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if 400 <= exc.code < 500:
            raise MetaPublishRejected from None
        raise MetaPublishUncertain from None
    except (URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise MetaPublishUncertain from None
    if isinstance(result, dict) and not result.get("error") and result.get("id"):
        return str(result["id"])
    raise MetaPublishRejected


def meta_publish_photo(page_id, caption, page_token, image_bytes):
    endpoint = meta_graph_url(f"{page_id}/photos")
    boundary = "----MarketingPilot" + secrets.token_hex(18)
    pieces = []
    for name, value in (("caption", caption), ("access_token", page_token)):
        pieces.extend((
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
            value.encode("utf-8"), b"\r\n",
        ))
    pieces.extend((
        f"--{boundary}\r\n".encode("ascii"),
        b'Content-Disposition: form-data; name="source"; filename="marketingpilot.png"\r\n',
        b"Content-Type: image/png\r\n\r\n", image_bytes, b"\r\n",
        f"--{boundary}--\r\n".encode("ascii"),
    ))
    request = URLRequest(endpoint, data=b"".join(pieces), headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }, method="POST")
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if 400 <= exc.code < 500:
            raise MetaPublishRejected from None
        raise MetaPublishUncertain from None
    except (URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise MetaPublishUncertain from None
    if isinstance(result, dict) and not result.get("error") and result.get("id"):
        photo_id = str(result["id"])
        post_id = str(result.get("post_id") or photo_id)
        parts = post_id.split("_", 1)
        post_url = (f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}" if len(parts) == 2
                    else f"https://www.facebook.com/photo/?fbid={photo_id}")
        return post_id, post_url
    raise MetaPublishRejected


def meta_publish_instagram_photo(instagram_id, caption, page_token, image_url):
    try:
        container = meta_http_form_post(f"{instagram_id}/media", {
            "image_url": image_url, "caption": caption, "access_token": page_token,
        })
        container_id = str(container.get("id", ""))
        if not container_id:
            raise MetaPublishRejected
        ready = False
        for _ in range(8):
            state = meta_http_json(meta_graph_url(container_id), {
                "fields": "status_code", "access_token": page_token,
            }).get("status_code", "")
            if state == "FINISHED":
                ready = True
                break
            if state == "ERROR":
                raise MetaPublishRejected
            time.sleep(2)
        if not ready:
            raise MetaPublishUncertain
        published = meta_http_form_post(f"{instagram_id}/media_publish", {
            "creation_id": container_id, "access_token": page_token,
        })
        media_id = str(published.get("id", ""))
        if not media_id:
            raise MetaPublishUncertain
    except MetaAPIError as exc:
        if str(exc.code).isdigit() and int(exc.code) in {100, 190, 200, 10, 10_001}:
            raise MetaPublishRejected from None
        raise MetaPublishUncertain from None
    permalink = f"https://www.instagram.com/"
    try:
        details = meta_http_json(meta_graph_url(media_id), {
            "fields": "permalink", "access_token": page_token,
        })
        if details.get("permalink", "").startswith("https://www.instagram.com/"):
            permalink = details["permalink"]
    except MetaAPIError:
        pass
    return media_id, permalink


def meta_http_form_post(path, params):
    request = URLRequest(meta_graph_url(path), data=urlencode(params).encode("utf-8"),
                         headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        with urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error", {}) if isinstance(body, dict) else {}
            code = error.get("code", exc.code) if isinstance(error, dict) else exc.code
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            code = exc.code
        raise MetaAPIError(code) from None
    except (URLError, OSError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        raise MetaAPIError("network") from None
    if not isinstance(result, dict):
        raise MetaAPIError("invalid-response")
    if result.get("error"):
        error = result["error"]
        raise MetaAPIError(error.get("code", "unknown") if isinstance(error, dict) else "unknown")
    return result


def read_generated_png(asset_path):
    match = re.fullmatch(r"/static/creatives/(creative-[0-9a-f]{32})\.png", asset_path or "")
    if not match:
        return None
    image_path = BASE_DIR / "static" / "creatives" / f"{match.group(1)}.png"
    try:
        image_bytes = image_path.read_bytes()
    except OSError:
        return None
    if (len(image_bytes) > 10 * 1024 * 1024 or len(image_bytes) < 24
            or image_bytes[:8] != b"\x89PNG\r\n\x1a\n" or image_bytes[12:16] != b"IHDR"):
        return None
    if struct.unpack(">II", image_bytes[16:24]) not in {(1080, 1080), (1080, 1920), (1200, 628)}:
        return None
    return image_bytes


def read_generated_jpeg(asset_path):
    match = re.fullmatch(r"/static/creatives/(creative-[0-9a-f]{32})\.(?:svg|png)", asset_path or "")
    if not match:
        return None
    image_path = BASE_DIR / "static" / "creatives" / f"{match.group(1)}.jpg"
    try:
        image_bytes = image_path.read_bytes()
    except OSError:
        return None
    dimensions = jpeg_dimensions(image_bytes)
    if len(image_bytes) > 10 * 1024 * 1024 or dimensions not in {(1080, 1080), (1080, 1920), (1200, 628)}:
        return None
    return image_bytes


def jpeg_dimensions(image_bytes):
    if len(image_bytes) < 4 or image_bytes[:3] != b"\xff\xd8\xff":
        return None
    index = 2
    while index + 4 < len(image_bytes):
        if image_bytes[index] != 0xff:
            index += 1
            continue
        marker = image_bytes[index + 1]
        index += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(image_bytes):
            return None
        segment_length = int.from_bytes(image_bytes[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(image_bytes):
            return None
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if segment_length < 7:
                return None
            height = int.from_bytes(image_bytes[index + 3:index + 5], "big")
            width = int.from_bytes(image_bytes[index + 5:index + 7], "big")
            return width, height
        index += segment_length
    return None


def meta_https_ready(config=None):
    config = config or meta_config()
    expected_callback = f"{config['base_url']}/integrations/meta/callback"
    return (config["base_url"].startswith("https://")
            and config["redirect_uri"] == expected_callback)


def init_db():
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            niche TEXT DEFAULT '',
            contact_name TEXT DEFAULT '',
            contact_email TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            scheduled_date TEXT DEFAULT '',
            scheduled_time TEXT NOT NULL DEFAULT '',
            caption TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Draft',
            created_at TEXT NOT NULL,
            client_feedback TEXT NOT NULL DEFAULT '',
            meta_post_id TEXT NOT NULL DEFAULT '',
            meta_post_url TEXT NOT NULL DEFAULT '',
            meta_published_at TEXT NOT NULL DEFAULT '',
            meta_publish_state TEXT NOT NULL DEFAULT 'Not published',
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            report_date TEXT NOT NULL,
            platform TEXT NOT NULL,
            reach INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            leads INTEGER DEFAULT 0,
            spend REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            goal TEXT DEFAULT '',
            platform TEXT NOT NULL DEFAULT 'Facebook',
            audience TEXT DEFAULT '',
            location TEXT DEFAULT '',
            offer TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Planning',
            created_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
        );
        """)
        for table in ("posts", "metrics"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "campaign_id" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL")
            if table == "posts" and "asset_path" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN asset_path TEXT DEFAULT ''")
            if table == "posts" and "client_feedback" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN client_feedback TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "scheduled_time" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN scheduled_time TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "meta_post_id" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN meta_post_id TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "meta_post_url" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN meta_post_url TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "meta_published_at" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN meta_published_at TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "meta_publish_state" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN meta_publish_state TEXT NOT NULL DEFAULT 'Not published'")
            if table == "posts" and "instagram_media_id" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN instagram_media_id TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "instagram_media_url" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN instagram_media_url TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "instagram_published_at" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN instagram_published_at TEXT NOT NULL DEFAULT ''")
            if table == "posts" and "instagram_publish_state" not in columns:
                conn.execute("ALTER TABLE posts ADD COLUMN instagram_publish_state TEXT NOT NULL DEFAULT 'Not published'")
            if table == "posts":
                for column, definition in (
                    ("meta_reactions", "INTEGER"),
                    ("meta_comments", "INTEGER"),
                    ("meta_shares", "INTEGER"),
                    ("meta_engagement_checked_at", "TEXT NOT NULL DEFAULT ''"),
                    ("instagram_likes", "INTEGER"),
                    ("instagram_comments", "INTEGER"),
                    ("instagram_engagement_checked_at", "TEXT NOT NULL DEFAULT ''"),
                ):
                    if column not in columns:
                        conn.execute(f"ALTER TABLE posts ADD COLUMN {column} {definition}")
        client_columns = {row["name"] for row in conn.execute("PRAGMA table_info(clients)")}
        for column, definition in (("brand_color", "TEXT NOT NULL DEFAULT '#1c7552'"),
                                  ("background_color", "TEXT NOT NULL DEFAULT '#e9f5ee'"),
                                  ("brand_voice", "TEXT NOT NULL DEFAULT ''"),
                                  ("products_services", "TEXT NOT NULL DEFAULT ''")):
            if column not in client_columns:
                conn.execute(f"ALTER TABLE clients ADD COLUMN {column} {definition}")
        campaign_columns = {row["name"] for row in conn.execute("PRAGMA table_info(campaigns)")}
        lead_form_fields_missing = "lead_form_fields" not in campaign_columns
        for column, definition in (
            ("budget_amount", "REAL NOT NULL DEFAULT 0"),
            ("budget_period", "TEXT NOT NULL DEFAULT 'Daily'"),
            ("start_date", "TEXT NOT NULL DEFAULT ''"),
            ("end_date", "TEXT NOT NULL DEFAULT ''"),
            ("destination_type", "TEXT NOT NULL DEFAULT 'Meta Instant Form'"),
            ("destination_url", "TEXT NOT NULL DEFAULT ''"),
            ("call_to_action", "TEXT NOT NULL DEFAULT 'Learn more'"),
            ("budget_approved", "INTEGER NOT NULL DEFAULT 0"),
            ("lead_form_fields", "TEXT NOT NULL DEFAULT ''"),
            ("privacy_policy_url", "TEXT NOT NULL DEFAULT ''"),
            ("thank_you_message", "TEXT NOT NULL DEFAULT ''"),
            ("phone_verification_plan", "TEXT NOT NULL DEFAULT 'No phone verification planned'"),
            ("email_verification_plan", "TEXT NOT NULL DEFAULT 'No email verification planned'"),
            ("audience_interests", "TEXT NOT NULL DEFAULT ''"),
            ("audience_needs", "TEXT NOT NULL DEFAULT ''"),
            ("audience_exclusions", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in campaign_columns:
                conn.execute(f"ALTER TABLE campaigns ADD COLUMN {column} {definition}")
        if lead_form_fields_missing:
            conn.execute("""UPDATE campaigns SET lead_form_fields='Full name,Email address,Phone number',
                budget_approved=0 WHERE destination_type='Meta Instant Form'""")
        conn.execute("""CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            inquiry TEXT DEFAULT '',
            campaign TEXT DEFAULT '',
            consent_given INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'New',
            follow_up_date TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'Meta CSV',
            meta_lead_id TEXT DEFAULT '',
            campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES clients(id) ON DELETE CASCADE
        )""")
        lead_columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
        if "follow_up_date" not in lead_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN follow_up_date TEXT NOT NULL DEFAULT ''")
        if "source" not in lead_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN source TEXT NOT NULL DEFAULT 'Meta CSV'")
        if "meta_lead_id" not in lead_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN meta_lead_id TEXT DEFAULT ''")
        if "campaign_id" not in lead_columns:
            conn.execute("ALTER TABLE leads ADD COLUMN campaign_id INTEGER REFERENCES campaigns(id) ON DELETE SET NULL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta_oauth_states (
            state_hash TEXT PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta_pending_connections (
            pending_id TEXT PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            pages_ciphertext TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta_connections (
            client_id INTEGER PRIMARY KEY REFERENCES clients(id) ON DELETE CASCADE,
            page_id TEXT NOT NULL,
            page_name TEXT NOT NULL,
            instagram_account_id TEXT NOT NULL DEFAULT '',
            instagram_username TEXT NOT NULL DEFAULT '',
            encrypted_page_token TEXT NOT NULL,
            connected_at TEXT NOT NULL
        );
        DELETE FROM meta_oauth_states WHERE expires_at < strftime('%s','now');
        DELETE FROM meta_pending_connections WHERE expires_at < strftime('%s','now');
        """)


init_db()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if not os.environ.get("APP_PASSWORD", "").strip():
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request,
        "next_path": request.query_params.get("next", "/"),
        "login_error": request.query_params.get("error", ""),
    })


@app.post("/login")
def login_submit(request: Request, password: str = Form(""), next_path: str = Form("/")):
    expected = os.environ.get("APP_PASSWORD", "").strip()
    if not expected:
        return RedirectResponse("/", status_code=303)
    ip = request.client.host if request.client else "unknown"
    now = int(datetime.now(timezone.utc).timestamp())
    failures, blocked_until = _login_failures.get(ip, (0, 0))
    if blocked_until > now:
        return RedirectResponse("/login?" + urlencode({"error": "locked", "next": next_path}), status_code=303)
    if not hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8")):
        failures += 1
        blocked_until = now + 600 if failures >= 5 else 0
        _login_failures[ip] = (0 if blocked_until else failures, blocked_until)
        return RedirectResponse("/login?" + urlencode({"error": "invalid", "next": next_path}), status_code=303)
    _login_failures.pop(ip, None)
    request.session.clear()
    request.session["authenticated"] = True
    safe_next = next_path if next_path.startswith("/") and not next_path.startswith("//") else "/"
    return RedirectResponse(safe_next, status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/campaigns", response_class=HTMLResponse)
def campaigns_page(request: Request):
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        campaigns = conn.execute("""SELECT campaigns.*, clients.business_name,
            (SELECT COUNT(*) FROM posts WHERE posts.campaign_id=campaigns.id) AS post_count,
            (SELECT COALESCE(SUM(leads),0) FROM metrics WHERE metrics.campaign_id=campaigns.id) AS lead_count,
            (SELECT COUNT(*) FROM leads WHERE leads.campaign_id=campaigns.id) AS inbox_lead_count
            FROM campaigns JOIN clients ON clients.id=campaigns.client_id
            ORDER BY campaigns.id DESC""").fetchall()
    return templates.TemplateResponse(request=request, name="campaigns.html", context={
        "request": request, "clients": clients, "campaigns": campaigns,
    })


@app.get("/connections", response_class=HTMLResponse)
def connections_page(request: Request):
    """Show global connector readiness and per-client Meta connection state."""
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        connected = {row["client_id"]: row for row in conn.execute(
            "SELECT client_id,page_name,instagram_account_id,instagram_username,connected_at FROM meta_connections"
        ).fetchall()}
    config = meta_config()
    api_version_valid = bool(re.fullmatch(r"v\d+\.\d+", config["api_version"]))
    access_protection_ready = bool(os.environ.get("APP_PASSWORD", "").strip()
                                   and os.environ.get("APP_SESSION_SECRET", "").strip())
    https_callback_ready = meta_https_ready(config)
    try:
        meta_fernet()
        encryption_key_ready = True
    except ValueError:
        encryption_key_ready = False
    return templates.TemplateResponse(request=request, name="connections.html", context={
        "request": request,
        "clients": clients,
        "connected": connected,
        "meta_app_id_ready": bool(config["app_id"]),
        "meta_app_secret_ready": bool(config["app_secret"]),
        "meta_api_version_ready": api_version_valid,
        "meta_encryption_key_ready": encryption_key_ready,
        "meta_access_protection_ready": access_protection_ready,
        "meta_https_callback_ready": https_callback_ready,
        "meta_instagram_enabled": config["instagram_enabled"],
        "meta_ready": bool(config["app_id"] and config["app_secret"] and api_version_valid
                           and encryption_key_ready and access_protection_ready and https_callback_ready),
        "meta_redirect_uri": config["redirect_uri"],
        "meta_message": {
            "setup": "Meta connection settings are incomplete. Add the required values to your local .env file, then restart MarketingPilot.",
            "unknown-client": "That business was not found. Refresh the page and try again.",
            "cancelled": "Meta authorization was cancelled. No account was connected.",
            "invalid-callback": "Meta returned an incomplete authorization response. Start again from Connections.",
            "expired-state": "That authorization link expired. Start again from Connections.",
            "authorization-failed": "Meta authorization could not be completed. Check the app setup and requested permissions, then try again.",
            "no-pages": "Meta returned no Pages for the Facebook profile you signed in with. That profile needs access to a Facebook Page with permission to create content; being an admin of the MarketingPilot developer app alone does not grant Page access. Check the Page's Settings → Page setup → Page access (or assign yourself Content access in Business Settings), then connect again.",
            "expired-selection": "The Page selection expired. Start the connection again.",
            "invalid-selection": "That Page was not part of this authorization. Start the connection again.",
            "connected": "Meta account connected to this business. Tokens are stored encrypted on this computer.",
        }.get(request.query_params.get("meta", ""), ""),
    })


@app.get("/integrations/meta/connect/{client_id}")
def meta_connect_start(client_id: int):
    config = meta_config()
    try:
        if (not config["app_id"] or not config["app_secret"]
                or not os.environ.get("APP_PASSWORD", "").strip()
                or not os.environ.get("APP_SESSION_SECRET", "").strip()
                or not meta_https_ready(config)):
            raise ValueError("Secure Meta settings are not configured")
        meta_graph_url()
        meta_fernet()
    except ValueError:
        return RedirectResponse("/connections?meta=setup", status_code=303)
    state = secrets.token_urlsafe(32)
    now = int(datetime.now(timezone.utc).timestamp())
    with connect_db() as conn:
        if not conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone():
            return RedirectResponse("/connections?meta=unknown-client", status_code=303)
        conn.execute("DELETE FROM meta_oauth_states WHERE expires_at < ?", (now,))
        conn.execute("INSERT INTO meta_oauth_states(state_hash,client_id,expires_at) VALUES(?,?,?)",
                     (hashlib.sha256(state.encode()).hexdigest(), client_id, now + 600))
    authorize_url = f"https://www.facebook.com/{config['api_version']}/dialog/oauth?" + urlencode({
        "client_id": config["app_id"],
        "redirect_uri": config["redirect_uri"],
        "state": state,
        "response_type": "code",
        "scope": ("pages_show_list,pages_read_engagement,pages_manage_posts,business_management,instagram_basic,instagram_content_publish"
                  if config["instagram_enabled"] else "pages_show_list,pages_read_engagement,pages_manage_posts"),
    })
    return RedirectResponse(authorize_url, status_code=302)


@app.get("/integrations/meta/callback", name="meta_oauth_callback")
def meta_oauth_callback(request: Request):
    if request.query_params.get("error"):
        return RedirectResponse("/connections?meta=cancelled", status_code=303)
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    if not code or not state or len(state) > 256:
        return RedirectResponse("/connections?meta=invalid-callback", status_code=303)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    now = int(datetime.now(timezone.utc).timestamp())
    with connect_db() as conn:
        state_row = conn.execute("SELECT client_id,expires_at FROM meta_oauth_states WHERE state_hash=?",
                                 (state_hash,)).fetchone()
        conn.execute("DELETE FROM meta_oauth_states WHERE state_hash=?", (state_hash,))
    if not state_row or state_row["expires_at"] < now:
        return RedirectResponse("/connections?meta=expired-state", status_code=303)
    config = meta_config()
    stage = "configuration"
    try:
        if not config["app_id"] or not config["app_secret"]:
            raise ValueError("Meta app credentials are not configured")
        cipher = meta_fernet()
        token_endpoint = meta_graph_url()
        stage = "code-exchange"
        short_token = meta_http_json(token_endpoint, {
            "client_id": config["app_id"],
            "client_secret": config["app_secret"],
            "redirect_uri": config["redirect_uri"],
            "code": code,
        }).get("access_token")
        if not short_token:
            raise ValueError("Meta did not return an access token")
        stage = "long-token-exchange"
        long_token = meta_http_json(token_endpoint, {
            "grant_type": "fb_exchange_token",
            "client_id": config["app_id"],
            "client_secret": config["app_secret"],
            "fb_exchange_token": short_token,
        }).get("access_token")
        if not long_token:
            raise ValueError("Meta did not return a long-lived access token")
        stage = "page-discovery"
        page_fields = "id,name,access_token,tasks"
        if config["instagram_enabled"]:
            page_fields += ",instagram_business_account{id,username}"
        page_data = meta_http_json(meta_graph_url("me/accounts"), {
            "fields": page_fields,
            "limit": "100",
            "access_token": long_token,
        }).get("data", [])
        pages = []
        for page in page_data:
            if not page.get("id") or not page.get("name") or not page.get("access_token"):
                continue
            instagram = page.get("instagram_business_account") or {}
            pages.append({
                "id": str(page["id"]),
                "name": str(page["name"]),
                "token": str(page["access_token"]),
                "instagram_id": str(instagram.get("id", "")),
                "instagram_username": str(instagram.get("username", "")),
            })
        if not pages:
            return RedirectResponse("/connections?meta=no-pages", status_code=303)
        pending_id = secrets.token_urlsafe(32)
        with connect_db() as conn:
            conn.execute("DELETE FROM meta_pending_connections WHERE expires_at < ?", (now,))
            conn.execute("""INSERT INTO meta_pending_connections
                (pending_id,client_id,pages_ciphertext,expires_at) VALUES(?,?,?,?)""",
                (pending_id, state_row["client_id"],
                 cipher.encrypt(json.dumps(pages).encode("utf-8")).decode("ascii"), now + 600))
        return RedirectResponse(f"/integrations/meta/select/{pending_id}", status_code=303)
    except MetaAPIError as exc:
        return RedirectResponse("/connections?" + urlencode({
            "meta": "authorization-failed", "stage": stage, "code": exc.code,
        }), status_code=303)
    except (ValueError, InvalidToken):
        return RedirectResponse("/connections?" + urlencode({
            "meta": "authorization-failed", "stage": stage,
        }), status_code=303)


@app.get("/integrations/meta/select/{pending_id}", response_class=HTMLResponse)
def meta_select_page(request: Request, pending_id: str):
    now = int(datetime.now(timezone.utc).timestamp())
    with connect_db() as conn:
        pending = conn.execute("SELECT * FROM meta_pending_connections WHERE pending_id=? AND expires_at>=?",
                               (pending_id, now)).fetchone()
        client = conn.execute("SELECT business_name FROM clients WHERE id=?",
                              (pending["client_id"],)).fetchone() if pending else None
    if not pending or not client:
        return RedirectResponse("/connections?meta=expired-selection", status_code=303)
    try:
        pages = json.loads(meta_fernet().decrypt(pending["pages_ciphertext"].encode("ascii")).decode("utf-8"))
    except (ValueError, InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
        return RedirectResponse("/connections?meta=authorization-failed", status_code=303)
    return templates.TemplateResponse(request=request, name="meta_select_page.html", context={
        "request": request, "pending_id": pending_id, "client": client, "pages": pages,
    })


@app.post("/integrations/meta/select/{pending_id}")
def meta_select_save(pending_id: str, page_id: str = Form(...)):
    now = int(datetime.now(timezone.utc).timestamp())
    try:
        cipher = meta_fernet()
    except ValueError:
        return RedirectResponse("/connections?meta=setup", status_code=303)
    with connect_db() as conn:
        pending = conn.execute("SELECT * FROM meta_pending_connections WHERE pending_id=? AND expires_at>=?",
                               (pending_id, now)).fetchone()
        if not pending:
            return RedirectResponse("/connections?meta=expired-selection", status_code=303)
        try:
            pages = json.loads(cipher.decrypt(pending["pages_ciphertext"].encode("ascii")).decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError):
            return RedirectResponse("/connections?meta=authorization-failed", status_code=303)
        selected = next((page for page in pages if page["id"] == page_id), None)
        if not selected:
            return RedirectResponse("/connections?meta=invalid-selection", status_code=303)
        conn.execute("""INSERT INTO meta_connections
            (client_id,page_id,page_name,instagram_account_id,instagram_username,encrypted_page_token,connected_at)
            VALUES(?,?,?,?,?,?,?) ON CONFLICT(client_id) DO UPDATE SET
            page_id=excluded.page_id,page_name=excluded.page_name,
            instagram_account_id=excluded.instagram_account_id,
            instagram_username=excluded.instagram_username,
            encrypted_page_token=excluded.encrypted_page_token,connected_at=excluded.connected_at""",
            (pending["client_id"], selected["id"], selected["name"], selected["instagram_id"],
             selected["instagram_username"], cipher.encrypt(selected["token"].encode()).decode("ascii"),
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.execute("DELETE FROM meta_pending_connections WHERE pending_id=?", (pending_id,))
    return RedirectResponse("/connections?meta=connected", status_code=303)


@app.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
def campaign_detail_page(request: Request, campaign_id: int):
    today = date.today()
    with connect_db() as conn:
        campaign = conn.execute("""SELECT campaigns.*, clients.business_name FROM campaigns
            JOIN clients ON clients.id=campaigns.client_id WHERE campaigns.id=?""", (campaign_id,)).fetchone()
        if not campaign:
            return RedirectResponse("/campaigns", status_code=303)
        posts = conn.execute("""SELECT * FROM posts WHERE campaign_id=?
            ORDER BY CASE WHEN scheduled_date='' THEN 1 ELSE 0 END, scheduled_date,
            CASE WHEN scheduled_time='' THEN 1 ELSE 0 END, scheduled_time, id DESC""",
            (campaign_id,)).fetchall()
        leads = conn.execute("""SELECT * FROM leads WHERE campaign_id=?
            ORDER BY created_at DESC, id DESC""", (campaign_id,)).fetchall()
        totals = conn.execute("""SELECT COUNT(*), COALESCE(SUM(reach),0), COALESCE(SUM(clicks),0),
            COALESCE(SUM(leads),0), COALESCE(SUM(spend),0) FROM metrics WHERE campaign_id=?""",
            (campaign_id,)).fetchone()
    return templates.TemplateResponse(request=request, name="campaign_detail.html", context={
        "request": request, "campaign": campaign, "posts": posts, "leads": leads, "totals": totals,
        "efficiency": calculate_efficiency(totals[1], totals[2], totals[3], totals[4]),
        "plan_start_date": (today + timedelta(days=(7 - today.weekday()) % 7)).isoformat(),
        "plan_min_date": today.isoformat(),
        "plan_max_date": (today + timedelta(days=366)).isoformat(),
    })


@app.get("/campaigns/{campaign_id}/review", response_class=HTMLResponse)
def campaign_review_page(request: Request, campaign_id: int):
    with connect_db() as conn:
        campaign = conn.execute("""SELECT campaigns.*, clients.business_name, clients.niche,
            clients.brand_color, clients.brand_voice FROM campaigns
            JOIN clients ON clients.id=campaigns.client_id WHERE campaigns.id=?""",
            (campaign_id,)).fetchone()
        if not campaign:
            return RedirectResponse("/campaigns", status_code=303)
        posts = conn.execute("""SELECT id,platform,scheduled_date,scheduled_time,caption,status,asset_path,client_feedback
            FROM posts WHERE campaign_id=? ORDER BY CASE WHEN scheduled_date='' THEN 1 ELSE 0 END,
            scheduled_date, CASE WHEN scheduled_time='' THEN 1 ELSE 0 END,
            scheduled_time,id""", (campaign_id,)).fetchall()
    return templates.TemplateResponse(request=request, name="campaign_review.html", context={
        "request": request, "campaign": campaign, "posts": posts,
        "generated_date": date.today().isoformat(),
    })


@app.post("/campaigns/{campaign_id}/weekly-plan")
def create_weekly_plan(campaign_id: int, start_date: str = Form(...)):
    try:
        first_day = date.fromisoformat(start_date)
        if first_day.isoformat() != start_date or first_day < date.today() or first_day > date.today() + timedelta(days=366):
            raise ValueError
    except ValueError:
        return RedirectResponse(f"/campaigns/{campaign_id}?error=plan-date", status_code=303)

    with connect_db() as conn:
        campaign = conn.execute("""SELECT campaigns.*, clients.business_name, clients.niche,
            clients.brand_voice, clients.products_services
            FROM campaigns JOIN clients ON clients.id=campaigns.client_id WHERE campaigns.id=?""",
            (campaign_id,)).fetchone()
        if not campaign:
            return RedirectResponse("/campaigns", status_code=303)

        business = campaign["business_name"].strip()
        focus = campaign["goal"].strip() or campaign["offer"].strip() or "your next goal"
        offer = campaign["offer"].strip()
        audience = campaign["audience"].strip()
        interests = campaign["audience_interests"].strip()
        needs = campaign["audience_needs"].strip()
        voice = campaign["brand_voice"].casefold()
        products_services = campaign["products_services"].strip()
        location = campaign["location"].strip()
        niche = campaign["niche"].strip()
        customer_phrase = audience or "our community"
        interest_topic = interests or focus
        need_topic = needs or focus
        location_phrase = f" in {location}" if location else ""
        offer_phrase = f" Offer: {offer}." if offer else ""
        niche_phrase = f", a {niche.lower()} business" if niche else ""
        product_phrase = f" Our products and services include {products_services}." if products_services else ""
        product_topic = products_services or focus
        invitation = "What would you like to know?"
        helpful_close = "We’ll help you explore your options."
        if "playful" in voice or "fun" in voice:
            invitation = "Drop your questions below!"
            helpful_close = "Let’s find the right fit together!"
        elif "professional" in voice or "formal" in voice:
            invitation = "Contact us with your questions."
            helpful_close = f"Contact {business} to discuss the available options."
        elif "confident" in voice or "bold" in voice:
            invitation = "Tell us what you’re looking to achieve."
            helpful_close = f"Take the next step with {business} today."
        elif "warm" in voice or "friendly" in voice:
            invitation = "We’d love to hear what you think."
            helpful_close = "We’d be happy to help you explore your options."
        captions = [
            f"Meet {business}{niche_phrase}{location_phrase}.{product_phrase} This week, we’re sharing practical ideas for {customer_phrase} about {focus}.{offer_phrase} {invitation}",
            f"Curious about {interest_topic}? Learn more about {product_topic} and tell us what you would like to know. {invitation}",
            f"Looking for help with {need_topic}? {business} can help you explore your options{location_phrase}.{offer_phrase} {helpful_close}",
            f"A question for {customer_phrase}{location_phrase}: what matters most to you when choosing a {niche or 'local business'}? {invitation}",
            f"Ready to learn more about {product_topic}?{offer_phrase} Get in touch with {business}{location_phrase}. {helpful_close}",
        ]
        platform = campaign["platform"] if campaign["platform"] in {"Instagram", "Facebook", "Google Ads", "WhatsApp"} else "Facebook"
        plan_days = []
        current_day = first_day
        while len(plan_days) < len(captions):
            if current_day.weekday() < 5:
                plan_days.append(current_day)
            current_day += timedelta(days=1)
        for scheduled_day, caption in zip(plan_days, captions):
            conn.execute("""INSERT INTO posts
                (client_id,platform,scheduled_date,caption,status,created_at,campaign_id)
                VALUES (?,?,?,?,?,?,?)""", (campaign["client_id"], platform,
                scheduled_day.isoformat(), caption, "Draft", datetime.now().isoformat(timespec="seconds"), campaign_id))
    return RedirectResponse(f"/campaigns/{campaign_id}?plan_created=5", status_code=303)


@app.post("/campaigns")
def add_campaign(
    client_id: int = Form(...), name: str = Form(...), goal: str = Form(""),
    platform: str = Form("Facebook"), audience: str = Form(""),
    audience_interests: str = Form(""), audience_needs: str = Form(""),
    audience_exclusions: str = Form(""),
    location: str = Form(""), offer: str = Form(""), status: str = Form("Planning"),
    budget_amount: str = Form("0"), budget_period: str = Form("Daily"),
    start_date: str = Form(""), end_date: str = Form(""),
    destination_type: str = Form("Meta Instant Form"), destination_url: str = Form(""),
    call_to_action: str = Form("Learn more"), budget_approved: bool = Form(False),
    form_fields: list[str] = Form([]), privacy_policy_url: str = Form(""),
    thank_you_message: str = Form(""),
    phone_verification_plan: str = Form("No phone verification planned"),
    email_verification_plan: str = Form("No email verification planned"),
):
    ad_setup = validate_ad_setup(budget_amount, budget_period, start_date, end_date,
                                 destination_type, destination_url, call_to_action)
    lead_form = validate_lead_form_setup(platform, destination_type, form_fields, privacy_policy_url,
                                         thank_you_message, phone_verification_plan, email_verification_plan)
    audience_profile = validate_audience_profile(audience, audience_interests, audience_needs, audience_exclusions)
    if platform not in {"Facebook", "Instagram", "Google Ads", "WhatsApp"} or status not in {"Planning", "Active", "Completed"} or not name.strip() or ad_setup is None or lead_form is None or audience_profile is None:
        return RedirectResponse("/campaigns?error=campaign", status_code=303)
    with connect_db() as conn:
        if conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone():
            conn.execute("""INSERT INTO campaigns
                (client_id,name,goal,platform,audience,location,offer,status,created_at,
                 budget_amount,budget_period,start_date,end_date,destination_type,destination_url,call_to_action,budget_approved,
                 lead_form_fields,privacy_policy_url,thank_you_message,phone_verification_plan,email_verification_plan,
                 audience_interests,audience_needs,audience_exclusions)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (client_id, name.strip(), goal.strip(), platform,
                audience_profile[0], location.strip(), offer.strip(), status, datetime.now().isoformat(timespec="seconds"),
                *ad_setup, int(budget_approved), *lead_form, *audience_profile[1:]))
    return RedirectResponse("/campaigns", status_code=303)


def validate_ad_setup(budget_amount, budget_period, start_date, end_date,
                      destination_type, destination_url, call_to_action):
    periods = {"Daily", "Total"}
    destinations = {"Meta Instant Form", "Website", "WhatsApp conversation", "Profile or page"}
    actions = {"Learn more", "Sign up", "Book now", "Get quote", "Send message"}
    try:
        amount = float(budget_amount)
        if not math.isfinite(amount) or amount < 0:
            return None
        for value in (start_date, end_date):
            if value and date.fromisoformat(value).isoformat() != value:
                return None
        if start_date and end_date and end_date < start_date:
            return None
    except (TypeError, ValueError):
        return None
    url = destination_url.strip()
    if (budget_period not in periods or destination_type not in destinations or call_to_action not in actions
            or (url and not re.match(r"^https?://", url, re.IGNORECASE))):
        return None
    return (amount, budget_period, start_date, end_date, destination_type, url, call_to_action)


def validate_post_time(value):
    value = (value or "").strip()
    if not value:
        return ""
    try:
        if datetime.strptime(value, "%H:%M").strftime("%H:%M") != value:
            return None
    except ValueError:
        return None
    return value


def validate_lead_form_setup(platform, destination_type, form_fields, privacy_policy_url, thank_you_message,
                             phone_verification_plan, email_verification_plan):
    allowed_fields = ("Full name", "Email address", "Phone number")
    selected = [field for field in allowed_fields if field in form_fields]
    if destination_type == "Meta Instant Form" and platform not in {"Facebook", "Instagram"}:
        return None
    if destination_type == "Meta Instant Form" and not selected:
        return None
    policy_url = privacy_policy_url.strip()
    if policy_url and not re.match(r"^https?://", policy_url, re.IGNORECASE):
        return None
    message = thank_you_message.strip()
    if len(message) > 500:
        return None
    phone_plans = {"No phone verification planned", "Meta SMS code (if available)", "SMS code after lead sync (provider required)"}
    email_plans = {"No email verification planned", "Meta work-email check (if available)", "Email confirmation after lead sync (provider required)"}
    if phone_verification_plan not in phone_plans or email_verification_plan not in email_plans:
        return None
    if destination_type != "Meta Instant Form":
        return ("", "", "", "No phone verification planned", "No email verification planned")
    return (", ".join(selected), policy_url, message, phone_verification_plan, email_verification_plan)


def validate_audience_profile(customer_type, interests, needs, exclusions):
    values = tuple(value.strip() for value in (customer_type, interests, needs, exclusions))
    if any(len(value) > 500 for value in values):
        return None
    return values


@app.get("/campaigns/{campaign_id}/edit", response_class=HTMLResponse)
def edit_campaign_page(request: Request, campaign_id: int):
    with connect_db() as conn:
        campaign = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
    if not campaign:
        return RedirectResponse("/campaigns", status_code=303)
    return templates.TemplateResponse(request=request, name="edit_campaign.html", context={
        "request": request, "campaign": campaign, "clients": clients,
    })


@app.post("/campaigns/{campaign_id}/edit")
def save_campaign_edit(
    campaign_id: int, client_id: int = Form(...), name: str = Form(...), goal: str = Form(""),
    platform: str = Form("Facebook"), audience: str = Form(""),
    audience_interests: str = Form(""), audience_needs: str = Form(""),
    audience_exclusions: str = Form(""), location: str = Form(""),
    offer: str = Form(""), status: str = Form("Planning"),
    budget_amount: str = Form("0"), budget_period: str = Form("Daily"),
    start_date: str = Form(""), end_date: str = Form(""),
    destination_type: str = Form("Meta Instant Form"), destination_url: str = Form(""),
    call_to_action: str = Form("Learn more"), budget_approved: bool = Form(False),
    form_fields: list[str] = Form([]), privacy_policy_url: str = Form(""),
    thank_you_message: str = Form(""),
    phone_verification_plan: str = Form("No phone verification planned"),
    email_verification_plan: str = Form("No email verification planned"),
):
    ad_setup = validate_ad_setup(budget_amount, budget_period, start_date, end_date,
                                 destination_type, destination_url, call_to_action)
    lead_form = validate_lead_form_setup(platform, destination_type, form_fields, privacy_policy_url,
                                         thank_you_message, phone_verification_plan, email_verification_plan)
    audience_profile = validate_audience_profile(audience, audience_interests, audience_needs, audience_exclusions)
    if platform not in {"Facebook", "Instagram", "Google Ads", "WhatsApp"} or status not in {"Planning", "Active", "Completed"} or not name.strip() or ad_setup is None or lead_form is None or audience_profile is None:
        return RedirectResponse(f"/campaigns/{campaign_id}/edit?error=campaign", status_code=303)
    with connect_db() as conn:
        existing = conn.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        if conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone():
            if not existing:
                return RedirectResponse("/campaigns", status_code=303)
            approval_fields = ("budget_amount", "budget_period", "start_date", "end_date",
                               "destination_type", "destination_url", "call_to_action",
                               "lead_form_fields", "privacy_policy_url", "thank_you_message",
                               "phone_verification_plan", "email_verification_plan")
            changed = any(existing[key] != value for key, value in zip(approval_fields, (*ad_setup, *lead_form)))
            changed = changed or any((
                existing["client_id"] != client_id,
                existing["goal"] != goal.strip(),
                existing["offer"] != offer.strip(),
                existing["platform"] != platform,
                existing["location"] != location.strip(),
            ))
            changed = changed or any(existing[key] != value for key, value in zip(
                ("audience", "audience_interests", "audience_needs", "audience_exclusions"), audience_profile))
            approved = 0 if changed else int(budget_approved)
            conn.execute("""UPDATE campaigns SET client_id=?,name=?,goal=?,platform=?,audience=?,
                location=?,offer=?,status=?,budget_amount=?,budget_period=?,start_date=?,end_date=?,
                destination_type=?,destination_url=?,call_to_action=?,budget_approved=?,
                lead_form_fields=?,privacy_policy_url=?,thank_you_message=?,phone_verification_plan=?,email_verification_plan=?,
                audience_interests=?,audience_needs=?,audience_exclusions=? WHERE id=?""",
                (client_id, name.strip(), goal.strip(), platform, audience_profile[0], location.strip(),
                 offer.strip(), status, *ad_setup, approved, *lead_form, *audience_profile[1:], campaign_id))
            conn.execute("UPDATE posts SET campaign_id=NULL WHERE campaign_id=? AND client_id!=?", (campaign_id, client_id))
            conn.execute("UPDATE metrics SET campaign_id=NULL WHERE campaign_id=? AND client_id!=?", (campaign_id, client_id))
            conn.execute("UPDATE leads SET campaign_id=NULL WHERE campaign_id=? AND client_id!=?", (campaign_id, client_id))
    return RedirectResponse("/campaigns", status_code=303)


@app.post("/campaigns/{campaign_id}/delete")
def delete_campaign(campaign_id: int):
    with connect_db() as conn:
        conn.execute("UPDATE posts SET campaign_id=NULL WHERE campaign_id=?", (campaign_id,))
        conn.execute("UPDATE metrics SET campaign_id=NULL WHERE campaign_id=?", (campaign_id,))
        conn.execute("UPDATE leads SET campaign_id=NULL WHERE campaign_id=?", (campaign_id,))
        conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
    return RedirectResponse("/campaigns", status_code=303)


@app.get("/creatives", response_class=HTMLResponse)
def creatives_page(request: Request):
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name,brand_color,background_color,brand_voice,products_services FROM clients ORDER BY business_name").fetchall()
        campaigns = conn.execute("""SELECT campaigns.id,campaigns.client_id,campaigns.name,
            campaigns.goal,campaigns.audience,campaigns.audience_needs,campaigns.audience_interests,
            campaigns.location,campaigns.offer,campaigns.call_to_action,
            clients.business_name AS client_name FROM campaigns JOIN clients ON clients.id=campaigns.client_id
            ORDER BY campaigns.name""").fetchall()
        creatives = conn.execute("""SELECT posts.id,posts.caption,posts.platform,posts.created_at,
            posts.asset_path,clients.business_name FROM posts JOIN clients ON clients.id=posts.client_id
            WHERE posts.asset_path!='' ORDER BY posts.id DESC""").fetchall()
    return templates.TemplateResponse(request=request, name="creatives.html", context={
        "request": request, "clients": clients, "campaigns": campaigns, "creatives": creatives,
        "created": request.query_params.get("created", ""),
    })


@app.post("/creatives/save-png")
async def save_creative_png(asset_path: str = Form(...), png_file: UploadFile = File(...)):
    match = re.fullmatch(r"/static/creatives/(creative-[0-9a-f]{32})\.svg", asset_path)
    if not match:
        return Response(status_code=400)
    filename = match.group(1)
    svg_path = BASE_DIR / "static" / "creatives" / f"{filename}.svg"
    if not svg_path.is_file():
        return Response(status_code=404)
    png_bytes = await png_file.read(10 * 1024 * 1024 + 1)
    if (len(png_bytes) > 10 * 1024 * 1024 or len(png_bytes) < 24
            or png_bytes[:8] != b"\x89PNG\r\n\x1a\n" or png_bytes[12:16] != b"IHDR"):
        return Response(status_code=400)
    dimensions = struct.unpack(">II", png_bytes[16:24])
    if dimensions not in {(1080, 1080), (1080, 1920), (1200, 628)}:
        return Response(status_code=400)
    with connect_db() as conn:
        referenced = conn.execute("SELECT 1 FROM posts WHERE asset_path=? LIMIT 1", (asset_path,)).fetchone()
        if not referenced:
            return Response(status_code=404)
        png_path = svg_path.with_suffix(".png")
        temporary_path = png_path.with_name(png_path.name + ".tmp")
        temporary_path.write_bytes(png_bytes)
        temporary_path.replace(png_path)
        new_asset_path = f"/static/creatives/{filename}.png"
        conn.execute("UPDATE posts SET asset_path=? WHERE asset_path=?", (new_asset_path, asset_path))
    return Response(status_code=204)


@app.post("/creatives/save-jpeg")
async def save_creative_jpeg(asset_path: str = Form(...), jpeg_file: UploadFile = File(...)):
    match = re.fullmatch(r"/static/creatives/(creative-[0-9a-f]{32})\.(?:svg|png)", asset_path)
    if not match:
        return Response(status_code=400)
    image_bytes = await jpeg_file.read(10 * 1024 * 1024 + 1)
    if (len(image_bytes) > 10 * 1024 * 1024
            or jpeg_dimensions(image_bytes) not in {(1080, 1080), (1080, 1920), (1200, 628)}):
        return Response(status_code=400)
    with connect_db() as conn:
        referenced = conn.execute("SELECT 1 FROM posts WHERE asset_path=? LIMIT 1", (asset_path,)).fetchone()
        if not referenced:
            return Response(status_code=404)
        jpeg_path = BASE_DIR / "static" / "creatives" / f"{match.group(1)}.jpg"
        temporary_path = jpeg_path.with_name(jpeg_path.name + ".tmp")
        temporary_path.write_bytes(image_bytes)
        temporary_path.replace(jpeg_path)
    return Response(status_code=204)


@app.post("/creatives")
def create_creative(
    client_id: int = Form(...), campaign_id: str = Form(""), platform: str = Form("Instagram"),
    additional_platforms: list[str] = Form([]),
    image_format: str = Form("Square (1080 × 1080)"),
    headline: str = Form(...), message: str = Form(""), call_to_action: str = Form("Learn more"),
    brand_color: str = Form("#1c7552"), background_color: str = Form("#e9f5ee"),
):
    allowed_platforms = {"Instagram", "Facebook", "Google Ads", "WhatsApp"}
    image_dimensions = {
        "Square (1080 × 1080)": (1080, 1080),
        "Vertical (1080 × 1920)": (1080, 1920),
        "Landscape (1200 × 628)": (1200, 628),
    }
    selected_platforms = list(dict.fromkeys([platform, *additional_platforms]))
    if (platform not in allowed_platforms or any(item not in allowed_platforms for item in selected_platforms)
            or image_format not in image_dimensions or not headline.strip()):
        return RedirectResponse("/creatives", status_code=303)
    image_width, image_height = image_dimensions[image_format]
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", brand_color):
        brand_color = "#1c7552"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background_color):
        background_color = "#e9f5ee"

    def svg_lines(value, limit, count):
        lines = wrap(value.strip(), width=limit, break_long_words=True, max_lines=count, placeholder="…") or [""]
        return "".join(f'<tspan x="{image_width // 2}" dy="{0 if i == 0 else 58}">{escape(line)}</tspan>' for i, line in enumerate(lines))

    title_svg = svg_lines(headline, 24, 3)
    message_svg = svg_lines(message, 38, 4)
    cta_svg = escape(call_to_action.strip()[:60] or "Learn more")
    center_x = image_width // 2
    title_y = round(image_height * .34)
    message_y = round(image_height * .53)
    cta_y = round(image_height * .77)
    cta_width = round(image_width * .43)
    cta_x = (image_width - cta_width) // 2
    cta_height = min(100, round(image_height * .09))
    cta_top = cta_y - cta_height // 2
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{image_width}" height="{image_height}" viewBox="0 0 {image_width} {image_height}">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{background_color}"/><stop offset="1" stop-color="#ffffff"/></linearGradient></defs>
<rect width="{image_width}" height="{image_height}" rx="54" fill="url(#bg)"/><circle cx="{round(image_width * .85)}" cy="{round(image_height * .11)}" r="240" fill="{brand_color}" opacity=".10"/><circle cx="{round(image_width * .07)}" cy="{round(image_height * .92)}" r="260" fill="{brand_color}" opacity=".08"/>
<rect x="{round(image_width * .09)}" y="{round(image_height * .11)}" width="110" height="12" rx="6" fill="{brand_color}"/><text x="{center_x}" y="{title_y}" text-anchor="middle" font-family="Arial,sans-serif" font-size="68" font-weight="700" fill="{brand_color}">{title_svg}</text>
<text x="{center_x}" y="{message_y}" text-anchor="middle" font-family="Arial,sans-serif" font-size="34" fill="#26372e">{message_svg}</text>
<rect x="{cta_x}" y="{cta_top}" width="{cta_width}" height="{cta_height}" rx="{cta_height // 2}" fill="{brand_color}"/><text x="{center_x}" y="{cta_y + 12}" text-anchor="middle" font-family="Arial,sans-serif" font-size="32" font-weight="700" fill="#ffffff">{cta_svg}</text></svg>'''
    filename = f"creative-{uuid4().hex}.svg"
    assets_dir = BASE_DIR / "static" / "creatives"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / filename).write_text(svg, encoding="utf-8")
    asset_path = f"/static/creatives/{filename}"
    caption = "\n".join(part.strip() for part in (headline, message) if part.strip())
    with connect_db() as conn:
        if not conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone():
            (assets_dir / filename).unlink(missing_ok=True)
            return RedirectResponse("/creatives", status_code=303)
        campaign = conn.execute("SELECT id FROM campaigns WHERE id=? AND client_id=?",
            (campaign_id, client_id)).fetchone() if campaign_id.isdigit() else None
        for selected_platform in selected_platforms:
            conn.execute("""INSERT INTO posts
                (client_id,platform,scheduled_date,caption,status,created_at,campaign_id,asset_path)
                VALUES (?,?, '',?,'Draft',?,?,?)""", (client_id, selected_platform, caption,
                datetime.now().isoformat(timespec="seconds"), campaign["id"] if campaign else None, asset_path))
    return RedirectResponse(f"/creatives?created={len(selected_platforms)}", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with connect_db() as conn:
        clients = conn.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
        post_count = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        draft_count = conn.execute("SELECT COUNT(*) FROM posts WHERE status='Draft'").fetchone()[0]
        approval_count = conn.execute("SELECT COUNT(*) FROM posts WHERE status='Needs approval'").fetchone()[0]
        active_campaign_count = conn.execute("SELECT COUNT(*) FROM campaigns WHERE status='Active'").fetchone()[0]
        posts_needing_approval = conn.execute("""
            SELECT posts.*, clients.business_name FROM posts
            JOIN clients ON clients.id=posts.client_id
            WHERE posts.status='Needs approval'
            ORDER BY CASE WHEN posts.scheduled_date='' THEN 1 ELSE 0 END,
                posts.scheduled_date, CASE WHEN posts.scheduled_time='' THEN 1 ELSE 0 END,
                posts.scheduled_time, posts.id DESC LIMIT 5
        """).fetchall()
        today = date.today()
        reminder_cutoff = (today + timedelta(days=3)).isoformat()
        reminder_rows = conn.execute("""
            SELECT posts.*, clients.business_name FROM posts
            JOIN clients ON clients.id=posts.client_id
            WHERE posts.scheduled_date!='' AND posts.status!='Published' AND posts.scheduled_date<=?
            ORDER BY CASE WHEN posts.scheduled_date<? THEN 0 ELSE 1 END,
                CASE WHEN posts.scheduled_date<? THEN posts.scheduled_date END DESC,
                posts.scheduled_date ASC, posts.id DESC LIMIT 6
        """, (reminder_cutoff, today.isoformat(), today.isoformat())).fetchall()
        reminder_posts = []
        for row in reminder_rows:
            try:
                days_until = (date.fromisoformat(row["scheduled_date"]) - today).days
            except ValueError:
                continue
            reminder = dict(row)
            if days_until < 0:
                reminder["date_reminder"] = f"Overdue by {-days_until} day(s)"
            elif days_until == 0:
                reminder["date_reminder"] = "Due today"
            elif days_until == 1:
                reminder["date_reminder"] = "Due tomorrow"
            else:
                reminder["date_reminder"] = f"Due in {days_until} days"
            reminder_posts.append(reminder)
        followup_rows = conn.execute("""SELECT leads.id,leads.client_id,leads.full_name,leads.follow_up_date,
            leads.status,clients.business_name FROM leads JOIN clients ON clients.id=leads.client_id
            WHERE leads.follow_up_date!='' AND leads.follow_up_date<=? AND leads.status NOT IN ('Won','Lost')
            ORDER BY CASE WHEN leads.follow_up_date<? THEN 0 ELSE 1 END,
                leads.follow_up_date,leads.id DESC LIMIT 6""",
            (reminder_cutoff, today.isoformat())).fetchall()
        followup_leads = []
        for row in followup_rows:
            try:
                days_until = (date.fromisoformat(row["follow_up_date"]) - today).days
            except ValueError:
                continue
            followup = dict(row)
            if days_until < 0:
                followup["followup_reminder"] = f"Overdue by {-days_until} day(s)"
            elif days_until == 0:
                followup["followup_reminder"] = "Due today"
            elif days_until == 1:
                followup["followup_reminder"] = "Due tomorrow"
            else:
                followup["followup_reminder"] = f"Due in {days_until} days"
            followup_leads.append(followup)
        recent_posts = conn.execute("""
            SELECT posts.*, clients.business_name FROM posts
            JOIN clients ON clients.id=posts.client_id
            ORDER BY posts.id DESC LIMIT 8
        """).fetchall()
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "request": request, "clients": clients, "post_count": post_count,
        "draft_count": draft_count, "approval_count": approval_count,
        "active_campaign_count": active_campaign_count,
        "posts_needing_approval": posts_needing_approval,
        "reminder_posts": reminder_posts, "followup_leads": followup_leads,
        "recent_posts": recent_posts
    })


@app.post("/clients")
def add_client(
    business_name: str = Form(...), niche: str = Form(""),
    contact_name: str = Form(""), contact_email: str = Form(""), notes: str = Form(""),
    brand_color: str = Form("#1c7552"), background_color: str = Form("#e9f5ee"), brand_voice: str = Form(""),
    products_services: str = Form(""),
):
    if not business_name.strip() or len(products_services) > 1000:
        return RedirectResponse("/?error=client", status_code=303)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", brand_color):
        brand_color = "#1c7552"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background_color):
        background_color = "#e9f5ee"
    with connect_db() as conn:
        conn.execute("""INSERT INTO clients
            (business_name,niche,contact_name,contact_email,notes,created_at,brand_color,background_color,brand_voice,products_services)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", (business_name.strip(), niche.strip(), contact_name.strip(),
            contact_email.strip(), notes.strip(), datetime.now().isoformat(timespec="seconds"),
            brand_color, background_color, brand_voice.strip(), products_services.strip()))
    return RedirectResponse("/", status_code=303)


@app.get("/clients/{client_id}/edit", response_class=HTMLResponse)
def edit_client_page(request: Request, client_id: int):
    with connect_db() as conn:
        client = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if not client:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request=request, name="edit_client.html", context={"request": request, "client": client},
    )


@app.post("/clients/{client_id}/edit")
def save_client_edit(
    client_id: int, business_name: str = Form(...), niche: str = Form(""),
    contact_name: str = Form(""), contact_email: str = Form(""), notes: str = Form(""),
    brand_color: str = Form("#1c7552"), background_color: str = Form("#e9f5ee"), brand_voice: str = Form(""),
    products_services: str = Form(""),
):
    if not business_name.strip() or len(products_services) > 1000:
        return RedirectResponse(f"/clients/{client_id}/edit", status_code=303)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", brand_color):
        brand_color = "#1c7552"
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", background_color):
        background_color = "#e9f5ee"
    with connect_db() as conn:
        conn.execute("""UPDATE clients SET business_name=?, niche=?, contact_name=?,
            contact_email=?, notes=?, brand_color=?, background_color=?, brand_voice=?, products_services=? WHERE id=?""", (business_name.strip(), niche.strip(),
            contact_name.strip(), contact_email.strip(), notes.strip(), brand_color, background_color, brand_voice.strip(), products_services.strip(), client_id))
    return RedirectResponse("/", status_code=303)


@app.post("/clients/{client_id}/delete")
def delete_client(client_id: int):
    with connect_db() as conn:
        conn.execute("UPDATE posts SET campaign_id=NULL WHERE client_id=?", (client_id,))
        conn.execute("UPDATE metrics SET campaign_id=NULL WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM campaigns WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM leads WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM posts WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM metrics WHERE client_id=?", (client_id,))
        conn.execute("DELETE FROM clients WHERE id=?", (client_id,))
    return RedirectResponse("/", status_code=303)


@app.get("/leads", response_class=HTMLResponse)
def leads_page(request: Request):
    client_filter = request.query_params.get("client", "")
    status_filter = request.query_params.get("status", "")
    campaign_filter = request.query_params.get("campaign", "")
    search = request.query_params.get("q", "").strip()[:100]
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        campaigns = conn.execute("SELECT campaigns.id,campaigns.client_id,campaigns.name,clients.business_name AS client_name FROM campaigns JOIN clients ON clients.id=campaigns.client_id ORDER BY campaigns.name").fetchall()
        assets = conn.execute("""SELECT DISTINCT posts.client_id, posts.asset_path, posts.caption,
            clients.business_name FROM posts JOIN clients ON clients.id=posts.client_id
            WHERE posts.asset_path!='' ORDER BY posts.id DESC""").fetchall()
        query = """SELECT leads.*, clients.business_name, campaigns.name AS linked_campaign FROM leads
            JOIN clients ON clients.id=leads.client_id
            LEFT JOIN campaigns ON campaigns.id=leads.campaign_id WHERE 1=1"""
        params = []
        if client_filter.isdigit():
            query += " AND leads.client_id=?"
            params.append(int(client_filter))
        else:
            client_filter = ""
        if status_filter in {"New", "Contacted", "Qualified", "Won", "Lost"}:
            query += " AND leads.status=?"
            params.append(status_filter)
        else:
            status_filter = ""
        if campaign_filter.isdigit():
            selected_campaign = next((item for item in campaigns if item["id"] == int(campaign_filter)), None)
            if selected_campaign:
                query += " AND (leads.campaign_id=? OR (leads.campaign_id IS NULL AND leads.client_id=? AND leads.campaign LIKE ?))"
                params.extend((int(campaign_filter), selected_campaign["client_id"], f"%{selected_campaign['name']}%"))
            else:
                campaign_filter = ""
        else:
            campaign_filter = ""
        if search:
            query += " AND (leads.full_name LIKE ? OR leads.email LIKE ? OR leads.phone LIKE ? OR leads.campaign LIKE ? OR leads.inquiry LIKE ?)"
            params.extend([f"%{search}%"] * 5)
        query += " ORDER BY leads.created_at DESC, leads.id DESC"
        leads = conn.execute(query, params).fetchall()
    return templates.TemplateResponse(request=request, name="leads.html", context={
        "request": request, "clients": clients, "campaigns": campaigns, "leads": leads,
        "client_filter": client_filter, "status_filter": status_filter,
        "campaign_filter": campaign_filter, "search": search,
        "imported": request.query_params.get("imported", ""),
        "skipped": request.query_params.get("skipped", ""),
        "import_error": request.query_params.get("error", ""),
        "followup_saved": request.query_params.get("followup_saved", ""),
    })


@app.get("/leads/import-template.csv")
def leads_import_template():
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "created_time", "full_name", "email", "phone_number", "campaign_name", "ad_name", "form_name"])
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="marketingpilot-lead-import-template.csv"'},
    )


@app.post("/leads/import")
async def import_meta_leads(client_id: int = Form(...), file: UploadFile = File(...)):
    with connect_db() as conn:
        if not conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone():
            return RedirectResponse("/leads?error=client", status_code=303)

    raw = await file.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        return RedirectResponse("/leads?error=size", status_code=303)
    try:
        content = raw.decode("utf-8-sig")
        reader = csv.DictReader(StringIO(content))
        if not reader.fieldnames:
            raise ValueError("missing headers")
        headers = {"".join(ch.lower() for ch in name if ch.isalnum()): name for name in reader.fieldnames if name}
        if not any(name in headers for name in ("fullname", "name", "firstname")):
            raise ValueError("missing name column")
        if not any(name in headers for name in ("email", "emailaddress", "phone", "phonenumber", "mobile", "mobilenumber")):
            raise ValueError("missing contact column")
        imported = skipped = 0
        known = {
            "id", "leadid", "createdtime", "fullname", "name", "firstname", "lastname",
            "email", "emailaddress", "phone", "phonenumber", "mobile", "mobilenumber",
            "campaign", "campaignname", "campaignid", "adname", "adid", "adsetname",
            "adsetid", "formname", "formid",
        }
        with connect_db() as conn:
            for row in reader:
                normalized = {"".join(ch.lower() for ch in (key or "") if ch.isalnum()): (value or "").strip()
                              for key, value in row.items() if key}
                def get(*keys):
                    return next((normalized[key] for key in keys if normalized.get(key)), "")
                full_name = get("fullname", "name") or " ".join(filter(None, (get("firstname"), get("lastname"))))
                email = get("email", "emailaddress")
                phone = get("phonenumber", "phone", "mobilenumber", "mobile")
                if not full_name or not (email or phone):
                    skipped += 1
                    continue
                meta_id = get("leadid", "id")
                if meta_id and conn.execute(
                    "SELECT 1 FROM leads WHERE client_id=? AND meta_lead_id=?", (client_id, meta_id)
                ).fetchone():
                    skipped += 1
                    continue
                campaign = " · ".join(filter(None, (
                    get("campaignname", "campaign"), get("adsetname"), get("adname"), get("formname"),
                )))
                campaign_name = get("campaignname", "campaign")
                matched_campaign = conn.execute("""SELECT id FROM campaigns
                    WHERE client_id=? AND name=? COLLATE NOCASE LIMIT 1""",
                    (client_id, campaign_name)).fetchone() if campaign_name else None
                details = [f"{key}: {value}" for key, value in normalized.items() if value and key not in known]
                inquiry = "\n".join(details)
                created = get("createdtime")
                try:
                    if created:
                        created = datetime.fromisoformat(created.replace("Z", "+00:00")).isoformat(timespec="seconds")
                    else:
                        created = datetime.now().isoformat(timespec="seconds")
                except ValueError:
                    created = datetime.now().isoformat(timespec="seconds")
                conn.execute("""INSERT INTO leads
                    (client_id,full_name,email,phone,inquiry,campaign,consent_given,status,source,meta_lead_id,campaign_id,created_at)
                    VALUES (?,?,?,?,?,?,0,'New','Meta CSV',?,?,?)""", (
                    client_id, full_name[:160], email[:254], phone[:60], inquiry[:2000],
                    campaign[:300], meta_id[:160], matched_campaign["id"] if matched_campaign else None, created,
                ))
                imported += 1
    except (UnicodeDecodeError, csv.Error, ValueError):
        return RedirectResponse("/leads?error=format", status_code=303)
    return RedirectResponse(f"/leads?imported={imported}&skipped={skipped}", status_code=303)


@app.get("/leads/export.csv")
def export_leads_csv(request: Request):
    client_filter = request.query_params.get("client", "")
    status_filter = request.query_params.get("status", "")
    campaign_filter = request.query_params.get("campaign", "")
    search = request.query_params.get("q", "").strip()[:100]
    filters = []
    params = []
    if client_filter.isdigit():
        filters.append("leads.client_id=?")
        params.append(int(client_filter))
    if status_filter in {"New", "Contacted", "Qualified", "Won", "Lost"}:
        filters.append("leads.status=?")
        params.append(status_filter)
    if campaign_filter.isdigit():
        with connect_db() as conn:
            selected_campaign = conn.execute("SELECT id,client_id,name FROM campaigns WHERE id=?", (int(campaign_filter),)).fetchone()
        if selected_campaign:
            filters.append("(leads.campaign_id=? OR (leads.campaign_id IS NULL AND leads.client_id=? AND leads.campaign LIKE ?))")
            params.extend((int(campaign_filter), selected_campaign["client_id"], f"%{selected_campaign['name']}%"))
    if search:
        filters.append("(leads.full_name LIKE ? OR leads.email LIKE ? OR leads.phone LIKE ? OR leads.campaign LIKE ? OR leads.inquiry LIKE ?)")
        params.extend([f"%{search}%"] * 5)
    with connect_db() as conn:
        query = """SELECT clients.business_name, leads.full_name, leads.email,
            leads.phone, COALESCE(campaigns.name, leads.campaign), leads.inquiry,
            leads.status, leads.follow_up_date, leads.source, leads.created_at FROM leads
            JOIN clients ON clients.id=leads.client_id
            LEFT JOIN campaigns ON campaigns.id=leads.campaign_id"""
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY leads.created_at DESC, leads.id DESC"
        leads = conn.execute(query, params).fetchall()
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Business", "Full name", "Email", "Phone", "Campaign", "Inquiry", "Status", "Follow-up date", "Source", "Received at"])
    writer.writerows(tuple(csv_safe(value) for value in lead) for lead in leads)
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="marketingpilot-leads.csv"'},
    )


@app.post("/leads/{lead_id}/status")
def update_lead_status(
    lead_id: int, status: str = Form(...), client: str = Form(""),
    status_filter: str = Form(""), campaign: str = Form(""), q: str = Form(""),
):
    if status in {"New", "Contacted", "Qualified", "Won", "Lost"}:
        with connect_db() as conn:
            conn.execute("UPDATE leads SET status=? WHERE id=?", (status, lead_id))
    query = urlencode({key: value for key, value in (
        ("client", client), ("status", status_filter), ("campaign", campaign), ("q", q)
    ) if value})
    return RedirectResponse("/leads" + (f"?{query}" if query else ""), status_code=303)


@app.post("/leads/{lead_id}/follow-up")
def update_lead_followup(
    lead_id: int, follow_up_date: str = Form(""), client: str = Form(""),
    status_filter: str = Form(""), campaign: str = Form(""), q: str = Form(""),
):
    follow_up_date = follow_up_date.strip()
    if follow_up_date:
        try:
            if date.fromisoformat(follow_up_date).isoformat() != follow_up_date:
                raise ValueError
        except ValueError:
            query = urlencode({key: value for key, value in (
                ("client", client), ("status", status_filter), ("campaign", campaign), ("q", q),
                ("error", "follow-up-date"),
            ) if value})
            return RedirectResponse("/leads" + (f"?{query}" if query else ""), status_code=303)
    with connect_db() as conn:
        conn.execute("UPDATE leads SET follow_up_date=? WHERE id=?", (follow_up_date, lead_id))
    query = urlencode({key: value for key, value in (
        ("client", client), ("status", status_filter), ("campaign", campaign), ("q", q),
        ("followup_saved", "1"),
    ) if value})
    return RedirectResponse("/leads" + (f"?{query}" if query else ""), status_code=303)


@app.get("/content", response_class=HTMLResponse)
def content_page(request: Request):
    client_filter = request.query_params.get("client", "")
    status_filter = request.query_params.get("status", "")
    campaign_filter = request.query_params.get("campaign", "")
    platform_filter = request.query_params.get("platform", "")
    from_filter = request.query_params.get("from", "")
    to_filter = request.query_params.get("to", "")
    for key, value in (("from", from_filter), ("to", to_filter)):
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                if key == "from":
                    from_filter = ""
                else:
                    to_filter = ""
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        meta_connected_clients = {row["client_id"] for row in conn.execute(
            "SELECT client_id FROM meta_connections"
        ).fetchall()}
        instagram_connected_clients = {row["client_id"] for row in conn.execute(
            "SELECT client_id FROM meta_connections WHERE instagram_account_id!=''"
        ).fetchall()}
        campaigns = conn.execute("SELECT campaigns.id,campaigns.client_id,campaigns.name,clients.business_name AS client_name FROM campaigns JOIN clients ON clients.id=campaigns.client_id ORDER BY campaigns.name").fetchall()
        assets = conn.execute("""SELECT DISTINCT posts.client_id, posts.asset_path, posts.caption,
            clients.business_name FROM posts JOIN clients ON clients.id=posts.client_id
            WHERE posts.asset_path!='' ORDER BY posts.id DESC""").fetchall()
        query = """SELECT posts.*, clients.business_name, campaigns.name AS campaign_name FROM posts
            JOIN clients ON clients.id=posts.client_id
            LEFT JOIN campaigns ON campaigns.id=posts.campaign_id WHERE 1=1"""
        params = []
        if client_filter.isdigit():
            query += " AND posts.client_id=?"
            params.append(int(client_filter))
        else:
            client_filter = ""
        if status_filter in {"Draft", "Needs approval", "Approved", "Scheduled", "Published"}:
            query += " AND posts.status=?"
            params.append(status_filter)
        else:
            status_filter = ""
        if campaign_filter.isdigit():
            query += " AND posts.campaign_id=?"
            params.append(int(campaign_filter))
        else:
            campaign_filter = ""
        if platform_filter in {"Instagram", "Facebook", "Google Ads", "WhatsApp"}:
            query += " AND posts.platform=?"
            params.append(platform_filter)
        else:
            platform_filter = ""
        if from_filter:
            query += " AND posts.scheduled_date>=? AND posts.scheduled_date!=''"
            params.append(from_filter)
        if to_filter:
            query += " AND posts.scheduled_date<=? AND posts.scheduled_date!=''"
            params.append(to_filter)
        query += " ORDER BY CASE WHEN posts.scheduled_date='' THEN 1 ELSE 0 END, posts.scheduled_date, CASE WHEN posts.scheduled_time='' THEN 1 ELSE 0 END, posts.scheduled_time, posts.id DESC"
        posts = conn.execute(query, params).fetchall()
    return templates.TemplateResponse(
        request=request, name="content.html",
        context={"request": request, "clients": clients, "campaigns": campaigns, "assets": assets, "posts": posts,
                 "meta_connected_clients": meta_connected_clients,
                 "instagram_connected_clients": instagram_connected_clients,
                 "meta_instagram_enabled": meta_config()["instagram_enabled"],
                 "meta_message": {
                     "published": "Facebook confirmed the post. MarketingPilot recorded its link.",
                     "publish-setup": "Meta publishing needs complete credentials, token encryption, workspace password protection, and a matching HTTPS callback.",
                     "publish-not-found": "That content item was not found.",
                     "publish-channel": "This publishing action doesn't match the selected content channel.",
                     "publish-not-approved": "Approve this content with the client before publishing.",
                     "publish-image-unavailable": "This generated image could not be prepared for Facebook, so it was not sent. Reopen the content item and try again.",
                     "publish-already": "This item is already being published, has been published, or needs a manual check. It was not sent again.",
                     "publish-not-connected": "Connect this client's Facebook Page first.",
                     "publish-failed": "Facebook rejected the publish request. The item remains approved; check the permission or content and try again.",
                     "publish-unknown": "Facebook did not confirm whether the post went through. Check the Page before retrying; MarketingPilot has blocked a second send to prevent duplicates.",
                     "instagram-published": "Instagram confirmed the post. MarketingPilot recorded its link.",
                     "instagram-disabled": "Instagram publishing is not enabled in local settings. Add the Instagram API use case and permissions to the Meta app, then set META_INSTAGRAM_ENABLED=1 in .env.",
                     "instagram-not-connected": "No linked Instagram professional account was found for this client's Page. Reconnect it after linking a Business or Creator account in Meta.",
                     "instagram-image-required": "Instagram publishing needs a generated image attached to the approved content.",
                     "instagram-image-unavailable": "The Instagram image could not be prepared. Try again from the content planner.",
                     "instagram-failed": "Instagram rejected the publish request. Check the account, image, and permissions, then retry.",
                     "instagram-unknown": "Instagram did not confirm whether the post went through. Check the account before retrying; MarketingPilot blocked a second send to prevent duplicates.",
                     "instagram-already": "This item is already being published, has been published, or needs a manual check. It was not sent again.",
                     "published-locked": "This content was published through MarketingPilot and is locked to preserve the record. Create a channel draft if you want to reuse it.",
                     "engagement-updated": "Latest available engagement counts were saved from Meta. They show reactions, likes, comments, and shares; Meta does not provide reach, clicks, leads, or spend through this update.",
                     "engagement-unavailable": "Engagement can be refreshed only for Facebook or Instagram posts published through MarketingPilot.",
                     "engagement-not-found": "That content item was not found.",
                     "engagement-setup": "Meta connection settings are unavailable. Reconnect this client's account from Connections and try again.",
                     "engagement-failed": "Meta could not return engagement for this post. Check that the post still exists and the connected account has access, then try again.",
                 }.get(request.query_params.get("meta", ""), ""),
                 "client_filter": client_filter, "status_filter": status_filter,
                 "campaign_filter": campaign_filter, "platform_filter": platform_filter,
                 "from_filter": from_filter, "to_filter": to_filter},
    )


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request):
    today = date.today()
    client_filter = request.query_params.get("client", "")
    try:
        year = int(request.query_params.get("year", today.year))
        month = int(request.query_params.get("month", today.month))
        if not 1 <= month <= 12 or not 1900 <= year <= 9998:
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month

    month_start = date(year, month, 1)
    month_end = date(year + (month == 12), month % 12 + 1, 1)
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        if client_filter.isdigit() and conn.execute("SELECT id FROM clients WHERE id=?", (int(client_filter),)).fetchone():
            posts = conn.execute("""SELECT posts.*, clients.business_name, campaigns.name AS campaign_name FROM posts
            JOIN clients ON clients.id=posts.client_id
            LEFT JOIN campaigns ON campaigns.id=posts.campaign_id
            WHERE posts.scheduled_date >= ? AND posts.scheduled_date < ? AND posts.client_id=?
            ORDER BY posts.scheduled_date, CASE WHEN posts.scheduled_time='' THEN 1 ELSE 0 END,
            posts.scheduled_time, posts.id""",
                (month_start.isoformat(), month_end.isoformat(), int(client_filter))).fetchall()
        else:
            client_filter = ""
            posts = conn.execute("""SELECT posts.*, clients.business_name, campaigns.name AS campaign_name FROM posts
                JOIN clients ON clients.id=posts.client_id
                LEFT JOIN campaigns ON campaigns.id=posts.campaign_id
                WHERE posts.scheduled_date >= ? AND posts.scheduled_date < ?
                ORDER BY posts.scheduled_date, CASE WHEN posts.scheduled_time='' THEN 1 ELSE 0 END,
                posts.scheduled_time, posts.id""",
                (month_start.isoformat(), month_end.isoformat())).fetchall()

    posts_by_day = {}
    for post in posts:
        try:
            day = date.fromisoformat(post["scheduled_date"]).day
        except ValueError:
            continue
        posts_by_day.setdefault(day, []).append(post)
    weeks = [
        [{"day": day, "posts": posts_by_day.get(day, [])} for day in week]
        for week in month_calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    ]
    prev_month = date(year - (month == 1), 12 if month == 1 else month - 1, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return templates.TemplateResponse(request=request, name="calendar.html", context={
        "request": request, "weeks": weeks,
        "month_label": month_start.strftime("%B %Y"),
        "prev_month": prev_month, "next_month": next_month,
        "year": year, "month": month,
        "post_count": len(posts), "clients": clients, "client_filter": client_filter,
    })


@app.get("/calendar/export.ics")
def export_calendar_ics(request: Request):
    client_filter = request.query_params.get("client", "")
    if client_filter and not client_filter.isdigit():
        return RedirectResponse("/calendar", status_code=303)

    with connect_db() as conn:
        if client_filter and not conn.execute("SELECT id FROM clients WHERE id=?", (int(client_filter),)).fetchone():
            return RedirectResponse("/calendar", status_code=303)
        query = """SELECT posts.id, posts.platform, posts.scheduled_date, posts.scheduled_time,
            posts.caption, posts.status,
            clients.business_name, campaigns.name AS campaign_name FROM posts
            JOIN clients ON clients.id=posts.client_id
            LEFT JOIN campaigns ON campaigns.id=posts.campaign_id
            WHERE posts.scheduled_date!=''"""
        params = []
        if client_filter:
            query += " AND posts.client_id=?"
            params.append(int(client_filter))
        query += " ORDER BY posts.scheduled_date, CASE WHEN posts.scheduled_time='' THEN 1 ELSE 0 END, posts.scheduled_time, clients.business_name, posts.id"
        posts = conn.execute(query, params).fetchall()

    def escape_ical_text(value):
        return (str(value or "").replace("\\", "\\\\").replace("\r\n", "\n")
                .replace("\r", "\n").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;"))

    def fold_ical_line(line):
        pieces = []
        current = ""
        for char in line:
            if len((current + char).encode("utf-8")) > 75:
                pieces.append(current)
                current = " " + char
            else:
                current += char
        pieces.append(current)
        return "\r\n".join(pieces)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MarketingPilot//Content Calendar//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:MarketingPilot content plan"]
    for post in posts:
        try:
            event_day = date.fromisoformat(post["scheduled_date"])
        except (ValueError, OverflowError):
            continue
        description = [f"Status: {post['status']}"]
        if post["campaign_name"]:
            description.append(f"Campaign: {post['campaign_name']}")
        event_time = post["scheduled_time"]
        if event_time:
            try:
                start_at = datetime.strptime(f"{event_day.isoformat()} {event_time}", "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            end_at = start_at + timedelta(hours=1)
            start_line = f"DTSTART:{start_at.strftime('%Y%m%dT%H%M%S')}"
            end_line = f"DTEND:{end_at.strftime('%Y%m%dT%H%M%S')}"
            description.insert(0, f"Planned local time: {event_time}")
        else:
            end_day = event_day + timedelta(days=1)
            start_line = f"DTSTART;VALUE=DATE:{event_day.strftime('%Y%m%d')}"
            end_line = f"DTEND;VALUE=DATE:{end_day.strftime('%Y%m%d')}"
        description.extend(["", post["caption"]])
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:marketingpilot-post-{post['id']}@local",
            f"DTSTAMP:{stamp}",
            start_line,
            end_line,
            f"SUMMARY:{escape_ical_text(post['business_name'] + ' · ' + post['platform'] + ' content')}",
            f"DESCRIPTION:{escape_ical_text(chr(10).join(description))}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    content = "\r\n".join(fold_ical_line(line) for line in lines) + "\r\n"
    filename = f"marketingpilot-client-{client_filter}-calendar.ics" if client_filter else "marketingpilot-calendar.ics"
    return Response(content=content, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/content/export.csv")
def export_content_csv(request: Request):
    client_filter = request.query_params.get("client", "")
    status_filter = request.query_params.get("status", "")
    campaign_filter = request.query_params.get("campaign", "")
    platform_filter = request.query_params.get("platform", "")
    from_filter = request.query_params.get("from", "")
    to_filter = request.query_params.get("to", "")
    filters = []
    params = []
    if client_filter.isdigit():
        filters.append("posts.client_id=?")
        params.append(int(client_filter))
    if status_filter in {"Draft", "Needs approval", "Approved", "Scheduled", "Published"}:
        filters.append("posts.status=?")
        params.append(status_filter)
    if campaign_filter.isdigit():
        filters.append("posts.campaign_id=?")
        params.append(int(campaign_filter))
    if platform_filter in {"Instagram", "Facebook", "Google Ads", "WhatsApp"}:
        filters.append("posts.platform=?")
        params.append(platform_filter)
    for column, value in (("posts.scheduled_date>=?", from_filter), ("posts.scheduled_date<=?", to_filter)):
        if value:
            try:
                if date.fromisoformat(value).isoformat() == value:
                    filters.append(column + " AND posts.scheduled_date!=''")
                    params.append(value)
            except ValueError:
                pass
    with connect_db() as conn:
        query = """SELECT clients.business_name, posts.platform, campaigns.name,
            posts.scheduled_date, posts.scheduled_time, posts.status, posts.caption, posts.asset_path, posts.created_at
            FROM posts JOIN clients ON clients.id=posts.client_id
            LEFT JOIN campaigns ON campaigns.id=posts.campaign_id"""
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY posts.scheduled_date, CASE WHEN posts.scheduled_time='' THEN 1 ELSE 0 END, posts.scheduled_time, clients.business_name, posts.id"
        posts = conn.execute(query, params).fetchall()

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Business", "Platform", "Campaign", "Planned date", "Planned time", "Status", "Caption", "Image file", "Created at"])
    writer.writerows(tuple(csv_safe(value) for value in post) for post in posts)
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="marketingpilot-content.csv"'},
    )


@app.post("/posts")
def add_post(
    client_id: int = Form(...), platform: str = Form(...), scheduled_date: str = Form(""), scheduled_time: str = Form(""),
    caption: str = Form(...), status: str = Form("Draft"), campaign_id: str = Form(""),
    asset_path: str = Form("")
):
    allowed_platforms = {"Instagram", "Facebook", "Google Ads", "WhatsApp"}
    allowed_statuses = {"Draft", "Needs approval", "Approved", "Scheduled", "Published"}
    scheduled_time = validate_post_time(scheduled_time)
    if scheduled_time is None:
        return RedirectResponse("/content?error=time", status_code=303)
    if platform not in allowed_platforms or status not in allowed_statuses:
        return RedirectResponse("/content", status_code=303)
    with connect_db() as conn:
        exists = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
        if exists:
            campaign = conn.execute("SELECT id FROM campaigns WHERE id=? AND client_id=?",
                (campaign_id, client_id)).fetchone() if campaign_id.isdigit() else None
            if campaign_id and not campaign:
                return RedirectResponse("/content?error=campaign", status_code=303)
            if asset_path and not conn.execute("SELECT id FROM posts WHERE client_id=? AND asset_path=?",
                                               (client_id, asset_path)).fetchone():
                return RedirectResponse("/content?error=asset", status_code=303)
            conn.execute("""INSERT INTO posts (client_id,platform,scheduled_date,scheduled_time,caption,status,created_at,campaign_id,asset_path)
                VALUES (?,?,?,?,?,?,?,?,?)""", (client_id, platform, scheduled_date.strip(), scheduled_time, caption.strip(),
                status, datetime.now().isoformat(timespec="seconds"), campaign["id"] if campaign else None, asset_path))
    return RedirectResponse("/content", status_code=303)


@app.post("/posts/{post_id}/refresh-engagement")
def refresh_post_engagement(post_id: int):
    try:
        cipher = meta_fernet()
    except ValueError:
        return RedirectResponse("/content?meta=engagement-setup", status_code=303)
    with connect_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            return RedirectResponse("/content?meta=engagement-not-found", status_code=303)
        if post["platform"] == "Facebook" and post["meta_post_id"]:
            connection = conn.execute("SELECT page_id,encrypted_page_token FROM meta_connections WHERE client_id=?",
                                       (post["client_id"],)).fetchone()
            platform_id = post["meta_post_id"]
        elif post["platform"] == "Instagram" and post["instagram_media_id"]:
            connection = conn.execute("SELECT page_id,encrypted_page_token FROM meta_connections WHERE client_id=?",
                                       (post["client_id"],)).fetchone()
            platform_id = post["instagram_media_id"]
        else:
            return RedirectResponse("/content?meta=engagement-unavailable", status_code=303)
        if not connection:
            return RedirectResponse("/content?meta=publish-not-connected", status_code=303)
        try:
            page_token = cipher.decrypt(connection["encrypted_page_token"].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            return RedirectResponse("/content?meta=engagement-setup", status_code=303)
        platform = post["platform"]

    try:
        if platform == "Facebook":
            details = meta_http_json(meta_graph_url(platform_id), {
                "fields": "reactions.limit(0).summary(true),comments.limit(0).summary(true),shares",
                "access_token": page_token,
            })
            reactions = meta_count_summary(details.get("reactions"))
            comments = meta_count_summary(details.get("comments"))
            shares = details.get("shares") or {}
            shares = shares.get("count", 0) if isinstance(shares, dict) else 0
            shares = max(0, int(shares)) if str(shares).isdigit() else 0
            update_sql = "UPDATE posts SET meta_reactions=?,meta_comments=?,meta_shares=?,meta_engagement_checked_at=? WHERE id=?"
            values = (reactions, comments, shares)
        else:
            details = meta_http_json(meta_graph_url(platform_id), {
                "fields": "like_count,comments_count", "access_token": page_token,
            })
            def safe_count(field):
                value = details.get(field, 0)
                return max(0, int(value)) if str(value).isdigit() else 0
            likes, comments = safe_count("like_count"), safe_count("comments_count")
            update_sql = "UPDATE posts SET instagram_likes=?,instagram_comments=?,instagram_engagement_checked_at=? WHERE id=?"
            values = (likes, comments)
    except MetaAPIError as exc:
        code = exc.code if exc.code in {"10", "100", "190", "200"} else "unknown"
        return RedirectResponse(f"/content?meta=engagement-failed&code={code}", status_code=303)

    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_db() as conn:
        conn.execute(update_sql, (*values, checked_at, post_id))
    return RedirectResponse("/content?meta=engagement-updated", status_code=303)


@app.post("/posts/{post_id}/publish-meta")
def publish_meta_post(post_id: int):
    config = meta_config()
    if (not config["app_id"] or not config["app_secret"] or not meta_https_ready(config)
            or not os.environ.get("APP_PASSWORD", "").strip()
            or not os.environ.get("APP_SESSION_SECRET", "").strip()):
        return RedirectResponse("/content?meta=publish-setup", status_code=303)
    try:
        cipher = meta_fernet()
    except ValueError:
        return RedirectResponse("/content?meta=publish-setup", status_code=303)
    with connect_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            return RedirectResponse("/content?meta=publish-not-found", status_code=303)
        if post["platform"] != "Facebook":
            return RedirectResponse("/content?meta=publish-channel", status_code=303)
        if post["status"] != "Approved":
            return RedirectResponse("/content?meta=publish-not-approved", status_code=303)
        image_bytes = read_generated_png(post["asset_path"]) if post["asset_path"] else None
        if post["asset_path"] and not image_bytes:
            return RedirectResponse("/content?meta=publish-image-unavailable", status_code=303)
        if post["meta_post_id"] or post["meta_publish_state"] in {"Publishing", "Published", "Needs review"}:
            return RedirectResponse("/content?meta=publish-already", status_code=303)
        connection = conn.execute("SELECT page_id,encrypted_page_token FROM meta_connections WHERE client_id=?",
                                  (post["client_id"],)).fetchone()
        if not connection:
            return RedirectResponse("/content?meta=publish-not-connected", status_code=303)
        try:
            page_token = cipher.decrypt(connection["encrypted_page_token"].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            return RedirectResponse("/content?meta=publish-setup", status_code=303)
        claimed = conn.execute("""UPDATE posts SET meta_publish_state='Publishing'
            WHERE id=? AND platform='Facebook' AND status='Approved'
            AND meta_post_id='' AND meta_publish_state IN ('Not published','Failed')""",
            (post_id,)).rowcount
        if not claimed:
            return RedirectResponse("/content?meta=publish-already", status_code=303)
        page_id = connection["page_id"]
        message = post["caption"]
    try:
        if image_bytes:
            platform_post_id, post_url = meta_publish_photo(page_id, message, page_token, image_bytes)
        else:
            platform_post_id = meta_publish_text(page_id, message, page_token)
            parts = platform_post_id.split("_", 1)
            post_url = (f"https://www.facebook.com/{parts[0]}/posts/{parts[1]}" if len(parts) == 2
                        else f"https://www.facebook.com/{platform_post_id}")
    except MetaPublishRejected:
        with connect_db() as conn:
            conn.execute("UPDATE posts SET meta_publish_state='Failed' WHERE id=? AND meta_publish_state='Publishing'",
                         (post_id,))
        return RedirectResponse("/content?meta=publish-failed", status_code=303)
    except MetaPublishUncertain:
        with connect_db() as conn:
            conn.execute("UPDATE posts SET meta_publish_state='Needs review' WHERE id=? AND meta_publish_state='Publishing'",
                         (post_id,))
        return RedirectResponse("/content?meta=publish-unknown", status_code=303)
    published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_db() as conn:
        conn.execute("""UPDATE posts SET status='Published',meta_publish_state='Published',
            meta_post_id=?,meta_post_url=?,meta_published_at=? WHERE id=? AND meta_publish_state='Publishing'""",
            (platform_post_id, post_url, published_at, post_id))
    return RedirectResponse("/content?meta=published", status_code=303)


@app.post("/posts/{post_id}/publish-instagram")
def publish_instagram_post(post_id: int):
    config = meta_config()
    if not config["instagram_enabled"]:
        return RedirectResponse("/content?meta=instagram-disabled", status_code=303)
    if (not config["app_id"] or not config["app_secret"] or not meta_https_ready(config)
            or not os.environ.get("APP_PASSWORD", "").strip()
            or not os.environ.get("APP_SESSION_SECRET", "").strip()):
        return RedirectResponse("/content?meta=publish-setup", status_code=303)
    try:
        cipher = meta_fernet()
    except ValueError:
        return RedirectResponse("/content?meta=publish-setup", status_code=303)
    with connect_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            return RedirectResponse("/content?meta=publish-not-found", status_code=303)
        if post["platform"] != "Instagram":
            return RedirectResponse("/content?meta=publish-channel", status_code=303)
        if post["status"] != "Approved":
            return RedirectResponse("/content?meta=publish-not-approved", status_code=303)
        if not post["asset_path"]:
            return RedirectResponse("/content?meta=instagram-image-required", status_code=303)
        jpeg_bytes = read_generated_jpeg(post["asset_path"])
        if not jpeg_bytes:
            return RedirectResponse("/content?meta=instagram-image-unavailable", status_code=303)
        if post["instagram_media_id"] or post["instagram_publish_state"] in {"Publishing", "Published", "Needs review"}:
            return RedirectResponse("/content?meta=instagram-already", status_code=303)
        connection = conn.execute("""SELECT instagram_account_id,encrypted_page_token
            FROM meta_connections WHERE client_id=?""", (post["client_id"],)).fetchone()
        if not connection or not connection["instagram_account_id"]:
            return RedirectResponse("/content?meta=instagram-not-connected", status_code=303)
        try:
            page_token = cipher.decrypt(connection["encrypted_page_token"].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            return RedirectResponse("/content?meta=publish-setup", status_code=303)
        claimed = conn.execute("""UPDATE posts SET instagram_publish_state='Publishing'
            WHERE id=? AND platform='Instagram' AND status='Approved'
            AND instagram_media_id='' AND instagram_publish_state IN ('Not published','Failed')""",
            (post_id,)).rowcount
        if not claimed:
            return RedirectResponse("/content?meta=instagram-already", status_code=303)
        instagram_id = connection["instagram_account_id"]
        message = post["caption"]
        image_name = Path(post["asset_path"]).stem + ".jpg"
        image_url = f"{config['base_url']}/static/creatives/{image_name}"
    try:
        media_id, post_url = meta_publish_instagram_photo(instagram_id, message, page_token, image_url)
    except MetaPublishRejected:
        with connect_db() as conn:
            conn.execute("UPDATE posts SET instagram_publish_state='Failed' WHERE id=? AND instagram_publish_state='Publishing'",
                         (post_id,))
        return RedirectResponse("/content?meta=instagram-failed", status_code=303)
    except MetaPublishUncertain:
        with connect_db() as conn:
            conn.execute("UPDATE posts SET instagram_publish_state='Needs review' WHERE id=? AND instagram_publish_state='Publishing'",
                         (post_id,))
        return RedirectResponse("/content?meta=instagram-unknown", status_code=303)
    published_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect_db() as conn:
        conn.execute("""UPDATE posts SET status='Published',instagram_publish_state='Published',
            instagram_media_id=?,instagram_media_url=?,instagram_published_at=?
            WHERE id=? AND instagram_publish_state='Publishing'""",
            (media_id, post_url, published_at, post_id))
    return RedirectResponse("/content?meta=instagram-published", status_code=303)


@app.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_page(request: Request, post_id: int):
    with connect_db() as conn:
        post = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        campaigns = conn.execute("SELECT campaigns.id,campaigns.client_id,campaigns.name,clients.business_name AS client_name FROM campaigns JOIN clients ON clients.id=campaigns.client_id ORDER BY campaigns.name").fetchall()
        assets = conn.execute("""SELECT DISTINCT posts.client_id, posts.asset_path, posts.caption,
            clients.business_name FROM posts JOIN clients ON clients.id=posts.client_id
            WHERE posts.asset_path!='' ORDER BY posts.id DESC""").fetchall()
    if not post:
        return RedirectResponse("/content", status_code=303)
    if post["meta_post_id"] or post["meta_publish_state"] in {"Publishing", "Needs review"}:
        return RedirectResponse("/content?meta=published-locked", status_code=303)
    return templates.TemplateResponse(
        request=request, name="edit_post.html",
        context={"request": request, "post": post, "clients": clients, "campaigns": campaigns, "assets": assets},
    )


@app.post("/posts/{post_id}/edit")
def save_post_edit(
    post_id: int, client_id: int = Form(...), platform: str = Form(...),
    scheduled_date: str = Form(""), scheduled_time: str = Form(""), caption: str = Form(...), status: str = Form(...), campaign_id: str = Form(""),
    asset_path: str = Form(""), client_feedback: str = Form("")
):
    allowed_platforms = {"Instagram", "Facebook", "Google Ads", "WhatsApp"}
    allowed_statuses = {"Draft", "Needs approval", "Approved", "Scheduled", "Published"}
    client_feedback = client_feedback.strip()
    scheduled_time = validate_post_time(scheduled_time)
    if len(client_feedback) > 2000:
        return RedirectResponse(f"/posts/{post_id}/edit?error=feedback", status_code=303)
    if scheduled_time is None:
        return RedirectResponse(f"/posts/{post_id}/edit?error=time", status_code=303)
    if platform not in allowed_platforms or status not in allowed_statuses or not caption.strip():
        return RedirectResponse(f"/posts/{post_id}/edit", status_code=303)
    approval_reset = False
    with connect_db() as conn:
        existing = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not existing:
            return RedirectResponse("/content", status_code=303)
        if existing["meta_post_id"] or existing["meta_publish_state"] in {"Publishing", "Needs review"}:
            return RedirectResponse("/content?meta=published-locked", status_code=303)
        client_exists = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
        if client_exists:
            campaign = conn.execute("SELECT id FROM campaigns WHERE id=? AND client_id=?",
                (campaign_id, client_id)).fetchone() if campaign_id.isdigit() else None
            if campaign_id and not campaign:
                return RedirectResponse(f"/posts/{post_id}/edit?error=campaign", status_code=303)
            if asset_path and not conn.execute("SELECT id FROM posts WHERE client_id=? AND asset_path=?",
                                               (client_id, asset_path)).fetchone():
                return RedirectResponse(f"/posts/{post_id}/edit?error=asset", status_code=303)
            new_campaign_id = campaign["id"] if campaign else None
            content_changed = any((
                existing["client_id"] != client_id,
                existing["platform"] != platform,
                existing["scheduled_date"] != scheduled_date.strip(),
                existing["scheduled_time"] != scheduled_time,
                existing["caption"] != caption.strip(),
                existing["campaign_id"] != new_campaign_id,
                existing["asset_path"] != asset_path,
            ))
            if content_changed and existing["status"] in {"Approved", "Scheduled"} and status in {"Approved", "Scheduled"}:
                status = "Needs approval"
                approval_reset = True
            if content_changed and client_feedback == existing["client_feedback"]:
                client_feedback = ""
            conn.execute("""UPDATE posts SET client_id=?, platform=?, scheduled_date=?,
                scheduled_time=?, caption=?, status=?, campaign_id=?, asset_path=?, client_feedback=? WHERE id=?""", (client_id, platform,
                scheduled_date.strip(), scheduled_time, caption.strip(), status, new_campaign_id, asset_path, client_feedback, post_id))
    return RedirectResponse("/content?approval_reset=1" if approval_reset else "/content", status_code=303)


@app.post("/posts/{post_id}/status")
def update_post_status(post_id: int, status: str = Form(...)):
    allowed = {"Draft", "Needs approval", "Approved", "Scheduled", "Published"}
    if status in allowed:
        with connect_db() as conn:
            conn.execute("UPDATE posts SET status=? WHERE id=? AND meta_post_id='' AND meta_publish_state NOT IN ('Publishing','Needs review')",
                         (status, post_id))
    return RedirectResponse("/content", status_code=303)


@app.post("/posts/{post_id}/review")
def record_post_review(
    post_id: int, status: str = Form(...), client_feedback: str = Form("")
):
    client_feedback = client_feedback.strip()
    with connect_db() as conn:
        post = conn.execute("SELECT campaign_id,meta_post_id,meta_publish_state FROM posts WHERE id=?", (post_id,)).fetchone()
        if not post:
            return RedirectResponse("/content", status_code=303)
        if post["meta_post_id"] or post["meta_publish_state"] in {"Publishing", "Needs review"}:
            return RedirectResponse("/content?meta=published-locked", status_code=303)
        campaign_id = post["campaign_id"]
        if not campaign_id:
            return RedirectResponse("/content", status_code=303)
        if status not in {"Approved", "Needs approval"}:
            return RedirectResponse(f"/campaigns/{campaign_id}?error=review", status_code=303)
        if len(client_feedback) > 2000:
            return RedirectResponse(f"/campaigns/{campaign_id}?error=review-feedback", status_code=303)
        conn.execute("UPDATE posts SET status=?,client_feedback=? WHERE id=?",
                     (status, client_feedback, post_id))
    return RedirectResponse(f"/campaigns/{campaign_id}?review_saved=1", status_code=303)


@app.post("/posts/{post_id}/repurpose")
def repurpose_post(post_id: int, platform: str = Form(...)):
    allowed_platforms = {"Instagram", "Facebook", "WhatsApp", "Google Ads"}
    if platform not in allowed_platforms:
        return RedirectResponse("/content", status_code=303)
    with connect_db() as conn:
        source = conn.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
        if not source:
            return RedirectResponse("/content", status_code=303)
        if platform == source["platform"]:
            return RedirectResponse(f"/posts/{post_id}/edit", status_code=303)
        cursor = conn.execute("""INSERT INTO posts
            (client_id,platform,scheduled_date,scheduled_time,caption,status,created_at,campaign_id,asset_path)
            VALUES (?,?,?,?,?,?,?,?,?)""", (source["client_id"], platform, source["scheduled_date"], source["scheduled_time"],
            source["caption"], "Draft", datetime.now().isoformat(timespec="seconds"),
            source["campaign_id"], source["asset_path"]))
        new_post_id = cursor.lastrowid
    return RedirectResponse(f"/posts/{new_post_id}/edit", status_code=303)


@app.post("/posts/{post_id}/delete")
def delete_post(post_id: int):
    with connect_db() as conn:
        conn.execute("DELETE FROM posts WHERE id=? AND meta_post_id='' AND meta_publish_state NOT IN ('Publishing','Needs review')",
                     (post_id,))
    return RedirectResponse("/content", status_code=303)


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    client_filter = request.query_params.get("client", "")
    campaign_filter = request.query_params.get("campaign", "")
    platform_filter = request.query_params.get("platform", "")
    from_filter = request.query_params.get("from", "")
    to_filter = request.query_params.get("to", "")
    for key, value in (("from", from_filter), ("to", to_filter)):
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                if key == "from":
                    from_filter = ""
                else:
                    to_filter = ""
    with connect_db() as conn:
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        where = []
        params = []
        if client_filter.isdigit():
            where.append("metrics.client_id=?")
            params.append(int(client_filter))
        else:
            client_filter = ""
        if campaign_filter.isdigit() and conn.execute("SELECT id FROM campaigns WHERE id=?", (int(campaign_filter),)).fetchone():
            where.append("metrics.campaign_id=?")
            params.append(int(campaign_filter))
        else:
            campaign_filter = ""
        if platform_filter in {"Instagram", "Facebook", "Google Ads", "WhatsApp"}:
            where.append("metrics.platform=?")
            params.append(platform_filter)
        else:
            platform_filter = ""
        if from_filter:
            where.append("metrics.report_date>=?")
            params.append(from_filter)
        if to_filter:
            where.append("metrics.report_date<=?")
            params.append(to_filter)
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        campaigns = conn.execute("SELECT campaigns.id,campaigns.client_id,campaigns.name,clients.business_name AS client_name FROM campaigns JOIN clients ON clients.id=campaigns.client_id ORDER BY campaigns.name").fetchall()
        metrics = conn.execute("""SELECT metrics.*, clients.business_name, campaigns.name AS campaign_name FROM metrics
            JOIN clients ON clients.id=metrics.client_id
            LEFT JOIN campaigns ON campaigns.id=metrics.campaign_id""" + where_sql +
            " ORDER BY report_date DESC, metrics.id DESC", params).fetchall()
        totals = conn.execute("""SELECT COALESCE(SUM(reach),0), COALESCE(SUM(clicks),0),
            COALESCE(SUM(leads),0), COALESCE(SUM(spend),0) FROM metrics""" + where_sql,
            params).fetchone()
    efficiency = calculate_efficiency(totals[0], totals[1], totals[2], totals[3])
    metrics = [{**{key: metric[key] for key in metric.keys()}, **calculate_efficiency(
        metric["reach"], metric["clicks"], metric["leads"], metric["spend"]
    )} for metric in metrics]
    return templates.TemplateResponse(
        request=request, name="reports.html",
        context={"request": request, "clients": clients, "campaigns": campaigns, "metrics": metrics, "totals": totals,
                 "efficiency": efficiency,
                 "client_filter": client_filter, "campaign_filter": campaign_filter,
                 "platform_filter": platform_filter, "from_filter": from_filter, "to_filter": to_filter,
                 "imported": request.query_params.get("imported", ""),
                 "duplicates": request.query_params.get("duplicates", "0"),
                 "import_error": request.query_params.get("import_error", "")},
    )


@app.get("/reports/import-template.csv")
def metrics_import_template():
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["report_date", "reach", "clicks", "leads", "spend", "notes"])
    writer.writerow([date.today().isoformat(), "1200", "45", "6", "750.00", "Example row; replace with exported figures"])
    return Response(
        content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="marketingpilot-metrics-template.csv"'},
    )


@app.get("/reports/print", response_class=HTMLResponse)
def print_report_page(request: Request):
    client_filter = request.query_params.get("client", "")
    campaign_filter = request.query_params.get("campaign", "")
    platform_filter = request.query_params.get("platform", "")
    from_filter = request.query_params.get("from", "")
    to_filter = request.query_params.get("to", "")
    for key, value in (("from", from_filter), ("to", to_filter)):
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError
            except ValueError:
                if key == "from":
                    from_filter = ""
                else:
                    to_filter = ""
    filters = []
    params = []
    client_name = "All clients"
    campaign_name = "All campaigns"
    with connect_db() as conn:
        if client_filter.isdigit():
            client = conn.execute("SELECT id,business_name FROM clients WHERE id=?", (int(client_filter),)).fetchone()
            if client:
                filters.append("metrics.client_id=?")
                params.append(client["id"])
                client_name = client["business_name"]
            else:
                client_filter = ""
        else:
            client_filter = ""
        if campaign_filter.isdigit():
            campaign = conn.execute("SELECT id,name FROM campaigns WHERE id=?", (int(campaign_filter),)).fetchone()
            if campaign:
                filters.append("metrics.campaign_id=?")
                params.append(campaign["id"])
                campaign_name = campaign["name"]
            else:
                campaign_filter = ""
        else:
            campaign_filter = ""
        if platform_filter in {"Instagram", "Facebook", "Google Ads", "WhatsApp"}:
            filters.append("metrics.platform=?")
            params.append(platform_filter)
        else:
            platform_filter = ""
        for column, value in (("metrics.report_date>=?", from_filter), ("metrics.report_date<=?", to_filter)):
            if value:
                filters.append(column)
                params.append(value)
        where_sql = " WHERE " + " AND ".join(filters) if filters else ""
        metrics = conn.execute("""SELECT metrics.*,clients.business_name,campaigns.name AS campaign_name
            FROM metrics JOIN clients ON clients.id=metrics.client_id
            LEFT JOIN campaigns ON campaigns.id=metrics.campaign_id""" + where_sql +
            " ORDER BY metrics.report_date,clients.business_name,metrics.id", params).fetchall()
        totals = conn.execute("""SELECT COALESCE(SUM(reach),0),COALESCE(SUM(clicks),0),
            COALESCE(SUM(leads),0),COALESCE(SUM(spend),0) FROM metrics""" + where_sql, params).fetchone()
    efficiency = calculate_efficiency(totals[0], totals[1], totals[2], totals[3])
    metrics = [{**{key: metric[key] for key in metric.keys()}, **calculate_efficiency(
        metric["reach"], metric["clicks"], metric["leads"], metric["spend"]
    )} for metric in metrics]
    period = f"{from_filter or 'Any date'} – {to_filter or 'Any date'}"
    return templates.TemplateResponse(request=request, name="reports_print.html", context={
        "request": request, "metrics": metrics, "totals": totals, "efficiency": efficiency,
        "client_name": client_name, "campaign_name": campaign_name,
        "platform_name": platform_filter or "All channels", "period": period,
        "generated_date": date.today().isoformat(),
        "reach_trend": build_metric_trend_svg(metrics, "reach", "#1c7552"),
        "clicks_trend": build_metric_trend_svg(metrics, "clicks", "#3977b8"),
        "leads_trend": build_metric_trend_svg(metrics, "leads", "#dc8c36"),
    })


@app.post("/reports/import")
async def import_metrics_csv(
    client_id: int = Form(...), campaign_id: str = Form(""),
    platform: str = Form(...), file: UploadFile = File(...),
):
    allowed_platforms = {"Instagram", "Facebook", "Google Ads", "WhatsApp"}
    if platform not in allowed_platforms:
        return RedirectResponse("/reports?import_error=platform", status_code=303)
    if not file.filename or not file.filename.casefold().endswith(".csv"):
        return RedirectResponse("/reports?import_error=type", status_code=303)
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        return RedirectResponse("/reports?import_error=size", status_code=303)
    try:
        reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
        headers = {header.strip().casefold() for header in (reader.fieldnames or []) if header}
        required = {"report_date", "reach", "clicks", "leads", "spend", "notes"}
        if not required.issubset(headers):
            return RedirectResponse("/reports?import_error=headers", status_code=303)
        parsed_rows = []
        for row_number, row in enumerate(reader, start=2):
            if row_number > 5001:
                return RedirectResponse("/reports?import_error=rows", status_code=303)
            if None in row or not any((value or "").strip() for value in row.values()):
                if None in row:
                    return RedirectResponse("/reports?import_error=data", status_code=303)
                continue
            normalized = {(key or "").strip().casefold(): (value or "").strip() for key, value in row.items()}
            report_date = normalized.get("report_date", "")
            if date.fromisoformat(report_date).isoformat() != report_date:
                raise ValueError("date")
            reach = int(normalized["reach"])
            clicks = int(normalized["clicks"])
            leads = int(normalized["leads"])
            spend = float(normalized["spend"])
            notes = normalized.get("notes", "")
            if min(reach, clicks, leads) < 0 or not math.isfinite(spend) or spend < 0 or len(notes) > 2000:
                raise ValueError("values")
            parsed_rows.append((report_date, reach, clicks, leads, spend, notes))
        if not parsed_rows:
            return RedirectResponse("/reports?import_error=empty", status_code=303)
    except (UnicodeDecodeError, csv.Error, KeyError, TypeError, ValueError):
        return RedirectResponse("/reports?import_error=data", status_code=303)

    with connect_db() as conn:
        if not conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone():
            return RedirectResponse("/reports?import_error=client", status_code=303)
        campaign = conn.execute("SELECT id FROM campaigns WHERE id=? AND client_id=?",
            (campaign_id, client_id)).fetchone() if campaign_id.isdigit() else None
        if campaign_id and not campaign:
            return RedirectResponse("/reports?import_error=campaign", status_code=303)
        inserted = 0
        duplicates = 0
        for report_date, reach, clicks, leads, spend, notes in parsed_rows:
            exists = conn.execute("""SELECT id FROM metrics WHERE client_id=? AND report_date=?
                AND platform=? AND campaign_id IS ? AND reach=? AND clicks=? AND leads=? AND spend=? AND notes=? LIMIT 1""",
                (client_id, report_date, platform, campaign["id"] if campaign else None,
                 reach, clicks, leads, spend, notes)).fetchone()
            if exists:
                duplicates += 1
                continue
            conn.execute("""INSERT INTO metrics
                (client_id,report_date,platform,reach,clicks,leads,spend,notes,campaign_id)
                VALUES (?,?,?,?,?,?,?,?,?)""", (client_id, report_date, platform, reach, clicks,
                leads, spend, notes, campaign["id"] if campaign else None))
            inserted += 1
    return RedirectResponse(f"/reports?imported={inserted}&duplicates={duplicates}", status_code=303)


@app.get("/reports/export.csv")
def export_metrics_csv(request: Request):
    client_filter = request.query_params.get("client", "")
    campaign_filter = request.query_params.get("campaign", "")
    platform_filter = request.query_params.get("platform", "")
    from_filter = request.query_params.get("from", "")
    to_filter = request.query_params.get("to", "")
    filters = []
    params = []
    if client_filter.isdigit():
        filters.append("metrics.client_id=?")
        params.append(int(client_filter))
    if campaign_filter.isdigit():
        filters.append("metrics.campaign_id=?")
        params.append(int(campaign_filter))
    if platform_filter in {"Instagram", "Facebook", "Google Ads", "WhatsApp"}:
        filters.append("metrics.platform=?")
        params.append(platform_filter)
    for column, value in (("metrics.report_date>=?", from_filter), ("metrics.report_date<=?", to_filter)):
        if value:
            try:
                if date.fromisoformat(value).isoformat() == value:
                    filters.append(column)
                    params.append(value)
            except ValueError:
                pass
    with connect_db() as conn:
        query = """SELECT clients.business_name, campaigns.name, metrics.report_date,
            metrics.platform, metrics.reach, metrics.clicks, metrics.leads,
            metrics.spend, metrics.notes FROM metrics
            JOIN clients ON clients.id=metrics.client_id
            LEFT JOIN campaigns ON campaigns.id=metrics.campaign_id"""
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY metrics.report_date DESC, clients.business_name"
        metrics = conn.execute(query, params).fetchall()

    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Business", "Campaign", "Report date", "Platform", "Reach", "Clicks", "Leads",
                     "Ad spend (INR)", "Click rate (%)", "Cost per click (INR)",
                     "Cost per lead (INR)", "Notes"])
    for metric in metrics:
        efficiency = calculate_efficiency(metric["reach"], metric["clicks"], metric["leads"], metric["spend"])
        row = tuple(metric[key] for key in ("business_name", "name", "report_date", "platform",
            "reach", "clicks", "leads", "spend"))
        writer.writerow(tuple(csv_safe(value) for value in (*row, efficiency["click_rate"],
            efficiency["cost_per_click"], efficiency["cost_per_lead"], metric["notes"])))
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="marketingpilot-reports.csv"'},
    )


@app.post("/metrics")
def add_metric(
    client_id: int = Form(...), report_date: str = Form(...), platform: str = Form(...),
    reach: int = Form(0), clicks: int = Form(0), leads: int = Form(0), spend: float = Form(0), notes: str = Form(""),
    campaign_id: str = Form("")
):
    with connect_db() as conn:
        exists = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
        if exists:
            campaign = conn.execute("SELECT id FROM campaigns WHERE id=? AND client_id=?",
                (campaign_id, client_id)).fetchone() if campaign_id.isdigit() else None
            if campaign_id and not campaign:
                return RedirectResponse("/reports?error=campaign", status_code=303)
            conn.execute("""INSERT INTO metrics (client_id,report_date,platform,reach,clicks,leads,spend,notes,campaign_id)
                VALUES (?,?,?,?,?,?,?,?,?)""", (client_id, report_date, platform, max(0, reach), max(0, clicks),
                max(0, leads), max(0, spend), notes.strip(), campaign["id"] if campaign else None))
    return RedirectResponse("/reports", status_code=303)


@app.get("/metrics/{metric_id}/edit", response_class=HTMLResponse)
def edit_metric_page(request: Request, metric_id: int):
    with connect_db() as conn:
        metric = conn.execute("SELECT * FROM metrics WHERE id=?", (metric_id,)).fetchone()
        clients = conn.execute("SELECT id,business_name FROM clients ORDER BY business_name").fetchall()
        campaigns = conn.execute("SELECT campaigns.id,campaigns.client_id,campaigns.name,clients.business_name AS client_name FROM campaigns JOIN clients ON clients.id=campaigns.client_id ORDER BY campaigns.name").fetchall()
    if not metric:
        return RedirectResponse("/reports", status_code=303)
    return templates.TemplateResponse(
        request=request, name="edit_metric.html",
        context={"request": request, "metric": metric, "clients": clients, "campaigns": campaigns},
    )


@app.post("/metrics/{metric_id}/edit")
def save_metric_edit(
    metric_id: int, client_id: int = Form(...), report_date: str = Form(...),
    platform: str = Form(...), reach: int = Form(0), clicks: int = Form(0),
    leads: int = Form(0), spend: float = Form(0), notes: str = Form(""), campaign_id: str = Form(""),
):
    if platform not in {"Instagram", "Facebook", "Google Ads", "WhatsApp"} or not report_date.strip():
        return RedirectResponse(f"/metrics/{metric_id}/edit", status_code=303)
    with connect_db() as conn:
        client_exists = conn.execute("SELECT id FROM clients WHERE id=?", (client_id,)).fetchone()
        if client_exists:
            campaign = conn.execute("SELECT id FROM campaigns WHERE id=? AND client_id=?",
                (campaign_id, client_id)).fetchone() if campaign_id.isdigit() else None
            if campaign_id and not campaign:
                return RedirectResponse(f"/metrics/{metric_id}/edit?error=campaign", status_code=303)
            conn.execute("""UPDATE metrics SET client_id=?, report_date=?, platform=?, reach=?,
                clicks=?, leads=?, spend=?, notes=?, campaign_id=? WHERE id=?""", (client_id,
                report_date.strip(), platform, max(0, reach), max(0, clicks), max(0, leads),
                max(0, spend), notes.strip(), campaign["id"] if campaign else None, metric_id))
    return RedirectResponse("/reports", status_code=303)


@app.post("/metrics/{metric_id}/delete")
def delete_metric(metric_id: int):
    with connect_db() as conn:
        conn.execute("DELETE FROM metrics WHERE id=?", (metric_id,))
    return RedirectResponse("/reports", status_code=303)
