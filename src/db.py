"""CRM Database persistence, Brand DNA, dual-tier atomic quotas, and dedup locks.

Supports PostgreSQL (via psycopg / psycopg2 when DATABASE_URL is a postgres DSN)
and local SQLite fallback for offline development and deterministic testing.
"""

import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import (
    BONUS_RUNS_DEFAULT,
    DAILY_USER_RUN_LIMIT,
    DAILY_USER_SPEND_LIMIT_INR,
    DAILY_USER_TOKEN_LIMIT,
    DATABASE_URL,
    DEFAULT_CLIENT_MONTHLY_BUDGET_INR,
    DUPLICATE_SUBMIT_WINDOW_SECONDS,
    LOW_BALANCE_WARNING_RATIO,
    QUOTA_RESERVATION_TTL_SECONDS,
    SQLITE_DB_PATH,
)
from src.models import BrandDNA, FullDeliverable

logger = logging.getLogger(__name__)

IST_TZ = timezone(timedelta(hours=5, minutes=30))


class QuotaError(Exception):
    """Base error for CRM quota operations."""


class InsufficientQuotaError(QuotaError):
    """Raised when available client INR balance is below the required reservation."""


class DailyLimitExceededError(QuotaError):
    """Raised when an employee exceeds their daily ScriptFalcon run/token/spend cap."""


class DuplicateRequestError(QuotaError):
    """Raised when an identical script request is submitted within the dedup lock window."""


class ClientNotFoundError(Exception):
    """Raised when a requested CRM client does not exist."""


class DeliverableNotFoundError(Exception):
    """Raised when a persisted deliverable ID is not found."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_date_str(dt: Optional[datetime] = None) -> str:
    """Return current usage date in IST (resets daily at 00:00 IST)."""
    return (dt or _utc_now()).astimezone(IST_TZ).strftime("%Y-%m-%d")


def _ist_date_str(dt: Optional[datetime] = None) -> str:
    """Explicit alias returning YYYY-MM-DD in Asia/Kolkata (IST)."""
    return _utc_date_str(dt)


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def build_dedup_key(
    client_id: str, user_id: str, topic: str, duration: int, mode: str = "full_script"
) -> str:
    """Create deterministic SHA-256 key for 30-second duplicate submission locking."""
    raw = f"{client_id.strip()}|{user_id.strip()}|{topic.strip().lower()}|{duration}|{mode}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class CRMDatabase:
    """Thread-safe atomic repository for clients, dual-tier quotas, dedup locks, and deliverables."""

    def __init__(self, database_url: Optional[str] = None):
        raw_url = (database_url if database_url is not None else DATABASE_URL).strip()
        self.is_postgres = raw_url.startswith("postgresql://") or raw_url.startswith(
            "postgres://"
        )
        self.database_url = raw_url
        self._lock = threading.RLock()
        self._shared_sqlite_conn: Optional[sqlite3.Connection] = None
        self._pg_driver = None

        if self.is_postgres:
            try:
                import psycopg

                self._pg_driver = ("psycopg", psycopg)
            except ImportError:
                try:
                    import psycopg2

                    self._pg_driver = ("psycopg2", psycopg2)
                except ImportError as exc:
                    raise RuntimeError(
                        "PostgreSQL DATABASE_URL configured, but neither 'psycopg' nor 'psycopg2' is installed."
                    ) from exc
        else:
            if raw_url.startswith("sqlite:///"):
                sqlite_target = raw_url[len("sqlite:///") :]
            elif raw_url == ":memory:":
                sqlite_target = ":memory:"
            else:
                sqlite_target = str(SQLITE_DB_PATH)
            self._sqlite_target = sqlite_target
            if sqlite_target != ":memory:":
                Path(sqlite_target).parent.mkdir(parents=True, exist_ok=True)
            else:
                self._shared_sqlite_conn = sqlite3.connect(
                    ":memory:", check_same_thread=False
                )
                self._shared_sqlite_conn.row_factory = sqlite3.Row

        self.init_schema()

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        if self._shared_sqlite_conn is not None:
            return self._shared_sqlite_conn
        conn = sqlite3.connect(
            self._sqlite_target, timeout=15.0, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _get_pg_conn(self):
        _, driver_mod = self._pg_driver
        return driver_mod.connect(self.database_url)

    def init_schema(self) -> None:
        """Create CRM tables and apply additive column migrations if needed."""
        if self.is_postgres:
            schema_sql = (
                Path(__file__).resolve().parent.parent / "sql" / "schema.sql"
            ).read_text(encoding="utf-8")
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(schema_sql)
                conn.commit()
            return

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.executescript(
                    """
                    PRAGMA foreign_keys = ON;

                    CREATE TABLE IF NOT EXISTS clients (
                        client_id TEXT PRIMARY KEY,
                        client_name TEXT NOT NULL,
                        target_audience TEXT,
                        industry TEXT,
                        brand_tone TEXT,
                        forbidden_words TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS client_quotas (
                        client_id TEXT PRIMARY KEY REFERENCES clients(client_id) ON DELETE CASCADE,
                        balance_inr REAL NOT NULL DEFAULT 0.0,
                        reserved_inr REAL NOT NULL DEFAULT 0.0,
                        monthly_budget_inr REAL NOT NULL DEFAULT 0.0,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS quota_reservations (
                        reservation_id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                        user_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        reserved_amount_inr REAL NOT NULL,
                        actual_cost_inr REAL,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        tokens_used INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL CHECK (status IN ('RESERVED', 'SETTLED', 'REFUNDED', 'EXPIRED')),
                        dedup_key TEXT,
                        usage_date TEXT,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        settled_at TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_quota_res_client_status
                        ON quota_reservations (client_id, status, expires_at);

                    CREATE TABLE IF NOT EXISTS user_daily_usage (
                        user_id TEXT NOT NULL,
                        usage_date TEXT NOT NULL,
                        run_count INTEGER NOT NULL DEFAULT 0,
                        bonus_runs_granted INTEGER NOT NULL DEFAULT 0,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        tokens_used INTEGER NOT NULL DEFAULT 0,
                        cost_inr REAL NOT NULL DEFAULT 0.0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, usage_date)
                    );

                    CREATE TABLE IF NOT EXISTS script_runs (
                        run_id TEXT PRIMARY KEY,
                        reservation_id TEXT REFERENCES quota_reservations(reservation_id) ON DELETE SET NULL,
                        deliverable_id TEXT,
                        client_id TEXT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                        user_id TEXT NOT NULL,
                        operation TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        tokens_used INTEGER NOT NULL DEFAULT 0,
                        cost_inr REAL NOT NULL DEFAULT 0.0,
                        usage_date TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS request_dedup_locks (
                        dedup_key TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS script_deliverables (
                        deliverable_id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                        user_id TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        duration INTEGER NOT NULL,
                        tone TEXT NOT NULL,
                        objective TEXT NOT NULL,
                        deliverable_json TEXT NOT NULL,
                        model_used TEXT NOT NULL DEFAULT '',
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        tokens_used INTEGER NOT NULL DEFAULT 0,
                        cost_inr REAL NOT NULL DEFAULT 0.0,
                        parent_deliverable_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_script_deliverables_client_created
                        ON script_deliverables (client_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS standalone_deliverables (
                        deliverable_id TEXT PRIMARY KEY,
                        topic TEXT NOT NULL,
                        platform TEXT NOT NULL DEFAULT '',
                        duration INTEGER NOT NULL,
                        tone TEXT NOT NULL DEFAULT '',
                        word_count INTEGER NOT NULL DEFAULT 0,
                        deliverable_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_standalone_deliverables_updated
                        ON standalone_deliverables (updated_at DESC);
                    """
                )
                # Additive column migrations for pre-existing local SQLite databases
                cq_cols = {
                    r["name"]
                    for r in conn.execute("PRAGMA table_info(client_quotas)").fetchall()
                }
                if "monthly_budget_inr" not in cq_cols:
                    conn.execute(
                        "ALTER TABLE client_quotas ADD COLUMN monthly_budget_inr REAL NOT NULL DEFAULT 0.0"
                    )
                qr_cols = {
                    r["name"]
                    for r in conn.execute(
                        "PRAGMA table_info(quota_reservations)"
                    ).fetchall()
                }
                if "dedup_key" not in qr_cols:
                    conn.execute(
                        "ALTER TABLE quota_reservations ADD COLUMN dedup_key TEXT"
                    )
                if "usage_date" not in qr_cols:
                    conn.execute(
                        "ALTER TABLE quota_reservations ADD COLUMN usage_date TEXT"
                    )
                if "input_tokens" not in qr_cols:
                    conn.execute(
                        "ALTER TABLE quota_reservations ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0"
                    )
                if "output_tokens" not in qr_cols:
                    conn.execute(
                        "ALTER TABLE quota_reservations ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0"
                    )
                if "tokens_used" not in qr_cols:
                    conn.execute(
                        "ALTER TABLE quota_reservations ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0"
                    )
                udu_cols = {
                    r["name"]
                    for r in conn.execute(
                        "PRAGMA table_info(user_daily_usage)"
                    ).fetchall()
                }
                if "bonus_runs_granted" not in udu_cols:
                    conn.execute(
                        "ALTER TABLE user_daily_usage ADD COLUMN bonus_runs_granted INTEGER NOT NULL DEFAULT 0"
                    )
                if "input_tokens" not in udu_cols:
                    conn.execute(
                        "ALTER TABLE user_daily_usage ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0"
                    )
                if "output_tokens" not in udu_cols:
                    conn.execute(
                        "ALTER TABLE user_daily_usage ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0"
                    )
                if "tokens_used" not in udu_cols:
                    conn.execute(
                        "ALTER TABLE user_daily_usage ADD COLUMN tokens_used INTEGER NOT NULL DEFAULT 0"
                    )
                if "cost_inr" not in udu_cols:
                    conn.execute(
                        "ALTER TABLE user_daily_usage ADD COLUMN cost_inr REAL NOT NULL DEFAULT 0.0"
                    )
                conn.commit()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

    def upsert_client(
        self,
        client_id: str,
        client_name: str,
        target_audience: Optional[str] = None,
        industry: Optional[str] = None,
        brand_tone: Optional[str] = None,
        forbidden_words: Optional[List[str]] = None,
        initial_balance_inr: Optional[float] = None,
        monthly_budget_inr: Optional[float] = None,
    ) -> BrandDNA:
        """Create or update a CRM client and optionally seed its INR quota & monthly budget."""
        now_iso = _iso_utc(_utc_now())
        fw_json = json.dumps(forbidden_words or [], ensure_ascii=False)
        budget_val = float(
            monthly_budget_inr
            if monthly_budget_inr is not None
            else (initial_balance_inr or 0.0)
        )

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO clients (client_id, client_name, target_audience, industry, brand_tone, forbidden_words, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
                        ON CONFLICT (client_id) DO UPDATE SET
                            client_name = EXCLUDED.client_name,
                            target_audience = EXCLUDED.target_audience,
                            industry = EXCLUDED.industry,
                            brand_tone = EXCLUDED.brand_tone,
                            forbidden_words = EXCLUDED.forbidden_words,
                            updated_at = NOW()
                        """,
                        (
                            client_id,
                            client_name,
                            target_audience,
                            industry,
                            brand_tone,
                            fw_json,
                        ),
                    )
                    if initial_balance_inr is not None:
                        cur.execute(
                            """
                            INSERT INTO client_quotas (client_id, balance_inr, reserved_inr, monthly_budget_inr, updated_at)
                            VALUES (%s, %s, 0.0, %s, NOW())
                            ON CONFLICT (client_id) DO NOTHING
                            """,
                            (client_id, float(initial_balance_inr), budget_val),
                        )
                conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_conn()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        """
                        INSERT INTO clients (client_id, client_name, target_audience, industry, brand_tone, forbidden_words, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(client_id) DO UPDATE SET
                            client_name = excluded.client_name,
                            target_audience = excluded.target_audience,
                            industry = excluded.industry,
                            brand_tone = excluded.brand_tone,
                            forbidden_words = excluded.forbidden_words,
                            updated_at = excluded.updated_at
                        """,
                        (
                            client_id,
                            client_name,
                            target_audience,
                            industry,
                            brand_tone,
                            fw_json,
                            now_iso,
                            now_iso,
                        ),
                    )
                    if initial_balance_inr is not None:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO client_quotas (client_id, balance_inr, reserved_inr, monthly_budget_inr, updated_at)
                            VALUES (?, ?, 0.0, ?, ?)
                            """,
                            (
                                client_id,
                                float(initial_balance_inr),
                                budget_val,
                                now_iso,
                            ),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    if self._shared_sqlite_conn is None:
                        conn.close()

        return BrandDNA(
            client_id=client_id,
            client_name=client_name,
            target_audience=target_audience,
            industry=industry,
            brand_tone=brand_tone,
            forbidden_words=forbidden_words or [],
        )

    def get_client_brand_dna(self, client_id: str) -> Optional[BrandDNA]:
        """Fetch Client Brand DNA from the clients table."""
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT client_id, client_name, target_audience, industry, brand_tone, forbidden_words
                        FROM clients WHERE client_id = %s
                        """,
                        (client_id,),
                    )
                    row = cur.fetchone()
            if not row:
                return None
            fw = row[5] if isinstance(row[5], list) else json.loads(row[5] or "[]")
            return BrandDNA(
                client_id=row[0],
                client_name=row[1],
                target_audience=row[2],
                industry=row[3],
                brand_tone=row[4],
                forbidden_words=fw,
            )

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                row = conn.execute(
                    """
                    SELECT client_id, client_name, target_audience, industry, brand_tone, forbidden_words
                    FROM clients WHERE client_id = ?
                    """,
                    (client_id,),
                ).fetchone()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

        if not row:
            return None
        fw = json.loads(row["forbidden_words"] or "[]")
        return BrandDNA(
            client_id=row["client_id"],
            client_name=row["client_name"],
            target_audience=row["target_audience"],
            industry=row["industry"],
            brand_tone=row["brand_tone"],
            forbidden_words=fw,
        )

    def _release_expired_sqlite(
        self, conn: sqlite3.Connection, client_id: str, now: datetime
    ) -> None:
        now_iso = _iso_utc(now)
        expired_rows = conn.execute(
            """
            SELECT reservation_id, reserved_amount_inr
            FROM quota_reservations
            WHERE client_id = ? AND status = 'RESERVED' AND expires_at <= ?
            """,
            (client_id, now_iso),
        ).fetchall()
        if not expired_rows:
            return
        total_expired = sum(float(r["reserved_amount_inr"]) for r in expired_rows)
        ids = [r["reservation_id"] for r in expired_rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE quota_reservations SET status = 'EXPIRED', settled_at = ? WHERE reservation_id IN ({placeholders})",
            [now_iso, *ids],
        )
        conn.execute(
            """
            UPDATE client_quotas
            SET reserved_inr = MAX(0.0, reserved_inr - ?), updated_at = ?
            WHERE client_id = ?
            """,
            (total_expired, now_iso, client_id),
        )

    def _release_expired_pg(self, cur, client_id: str) -> None:
        cur.execute(
            """
            UPDATE quota_reservations
            SET status = 'EXPIRED', settled_at = NOW()
            WHERE client_id = %s AND status = 'RESERVED' AND expires_at <= NOW()
            RETURNING reserved_amount_inr
            """,
            (client_id,),
        )
        expired = cur.fetchall()
        if expired:
            total_expired = sum(float(r[0]) for r in expired)
            cur.execute(
                """
                UPDATE client_quotas
                SET reserved_inr = GREATEST(0, reserved_inr - %s), updated_at = NOW()
                WHERE client_id = %s
                """,
                (total_expired, client_id),
            )

    @staticmethod
    def _format_quota_status(
        bal: float,
        res: float,
        monthly_budget: float,
        daily_runs_used: Optional[int] = None,
        daily_usage: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        available = round(bal - res, 4)
        budget = round(
            monthly_budget
            if monthly_budget > 0
            else (bal if bal > 0 else DEFAULT_CLIENT_MONTHLY_BUDGET_INR),
            4,
        )
        used_pct = (
            round(((budget - available) / budget) * 100.0, 2) if budget > 0 else 0.0
        )
        low_warning = budget > 0 and available <= (LOW_BALANCE_WARNING_RATIO * budget)
        status_dict: Dict[str, Any] = {
            "balance_inr": round(bal, 4),
            "reserved_inr": round(res, 4),
            "available_inr": available,
            "monthly_budget_inr": budget,
            "spent_inr": round(max(0.0, budget - available), 4),
            "auto_paused": available <= 0.0,
            "used_percentage": max(0.0, min(100.0, used_pct)),
            "low_balance_warning": low_warning,
            "low_balance_message": (
                f"Low quota alert: ₹{available:.2f} remaining out of ₹{budget:.2f} ({used_pct:.0f}% used)."
                if low_warning
                else None
            ),
        }
        if daily_usage is not None:
            bonus = int(daily_usage.get("bonus_runs_granted", 0))
            status_dict["daily_runs_used"] = int(daily_usage.get("run_count", 0))
            status_dict["daily_runs_limit"] = DAILY_USER_RUN_LIMIT + bonus
            status_dict["bonus_runs_granted"] = bonus
            status_dict["daily_tokens_used"] = int(daily_usage.get("tokens_used", 0))
            status_dict["daily_tokens_limit"] = DAILY_USER_TOKEN_LIMIT + (bonus * 3000)
            status_dict["daily_spend_inr"] = round(
                float(daily_usage.get("cost_inr", 0.0)), 4
            )
            status_dict["daily_spend_limit_inr"] = round(
                DAILY_USER_SPEND_LIMIT_INR + (bonus * 0.50), 4
            )
        elif daily_runs_used is not None:
            status_dict["daily_runs_used"] = daily_runs_used
            status_dict["daily_runs_limit"] = DAILY_USER_RUN_LIMIT
        return status_dict

    def get_user_daily_usage(
        self, user_id: str, usage_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return runs, bonus_runs_granted, token counts, and INR spend today (IST) for a teammate."""
        date_str = usage_date or _ist_date_str()
        empty = {
            "user_id": user_id,
            "usage_date": date_str,
            "run_count": 0,
            "bonus_runs_granted": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "tokens_used": 0,
            "cost_inr": 0.0,
        }
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT run_count, bonus_runs_granted, input_tokens, output_tokens, tokens_used, cost_inr
                        FROM user_daily_usage WHERE user_id = %s AND usage_date = %s
                        """,
                        (user_id, date_str),
                    )
                    row = cur.fetchone()
            if not row:
                return empty
            return {
                "user_id": user_id,
                "usage_date": date_str,
                "run_count": int(row[0]),
                "bonus_runs_granted": int(row[1]),
                "input_tokens": int(row[2]),
                "output_tokens": int(row[3]),
                "tokens_used": int(row[4]),
                "cost_inr": float(row[5]),
            }

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                row = conn.execute(
                    """
                    SELECT run_count, bonus_runs_granted, input_tokens, output_tokens, tokens_used, cost_inr
                    FROM user_daily_usage WHERE user_id = ? AND usage_date = ?
                    """,
                    (user_id, date_str),
                ).fetchone()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()
        if not row:
            return empty
        return {
            "user_id": user_id,
            "usage_date": date_str,
            "run_count": int(row["run_count"]),
            "bonus_runs_granted": int(row["bonus_runs_granted"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "tokens_used": int(row["tokens_used"]),
            "cost_inr": float(row["cost_inr"]),
        }

    def get_user_daily_runs(
        self, user_id: str, usage_date: Optional[str] = None
    ) -> int:
        """Return number of ScriptFalcon runs used today (IST) by a teammate."""
        return int(
            self.get_user_daily_usage(user_id, usage_date=usage_date)["run_count"]
        )

    def grant_bonus_runs(
        self,
        user_id: str,
        bonus_runs: int = BONUS_RUNS_DEFAULT,
        usage_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Admin override granting +N bonus runs (and proportional token/spend headroom) for today (IST)."""
        if bonus_runs <= 0:
            raise ValueError("bonus_runs must be a positive integer.")
        date_str = usage_date or _ist_date_str()
        now_iso = _iso_utc(_utc_now())

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO user_daily_usage (user_id, usage_date, run_count, bonus_runs_granted, updated_at)
                        VALUES (%s, %s, 0, %s, NOW())
                        ON CONFLICT (user_id, usage_date) DO UPDATE SET
                            bonus_runs_granted = user_daily_usage.bonus_runs_granted + EXCLUDED.bonus_runs_granted,
                            updated_at = NOW()
                        """,
                        (user_id, date_str, int(bonus_runs)),
                    )
                conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_conn()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        """
                        INSERT INTO user_daily_usage (user_id, usage_date, run_count, bonus_runs_granted, updated_at)
                        VALUES (?, ?, 0, ?, ?)
                        ON CONFLICT(user_id, usage_date) DO UPDATE SET
                            bonus_runs_granted = user_daily_usage.bonus_runs_granted + excluded.bonus_runs_granted,
                            updated_at = excluded.updated_at
                        """,
                        (user_id, date_str, int(bonus_runs), now_iso),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    if self._shared_sqlite_conn is None:
                        conn.close()
        return self.get_user_daily_usage(user_id, usage_date=date_str)

    def get_quota_status(
        self, client_id: str, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Return balance, reserved, available INR, 80% low-balance warning, and optional user daily stats."""
        now = _utc_now()
        today = _ist_date_str(now)
        daily_usage: Optional[Dict[str, Any]] = None

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT balance_inr, reserved_inr, monthly_budget_inr FROM client_quotas WHERE client_id = %s FOR UPDATE",
                        (client_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise ClientNotFoundError(
                            f"Quota record not found for client_id='{client_id}'"
                        )
                    self._release_expired_pg(cur, client_id)
                    cur.execute(
                        "SELECT balance_inr, reserved_inr, monthly_budget_inr FROM client_quotas WHERE client_id = %s",
                        (client_id,),
                    )
                    row = cur.fetchone()
                    if user_id:
                        cur.execute(
                            """
                            SELECT run_count, bonus_runs_granted, input_tokens, output_tokens, tokens_used, cost_inr
                            FROM user_daily_usage WHERE user_id = %s AND usage_date = %s
                            """,
                            (user_id, today),
                        )
                        u_row = cur.fetchone()
                        daily_usage = {
                            "run_count": int(u_row[0]) if u_row else 0,
                            "bonus_runs_granted": int(u_row[1]) if u_row else 0,
                            "input_tokens": int(u_row[2]) if u_row else 0,
                            "output_tokens": int(u_row[3]) if u_row else 0,
                            "tokens_used": int(u_row[4]) if u_row else 0,
                            "cost_inr": float(u_row[5]) if u_row else 0.0,
                        }
                conn.commit()
            return self._format_quota_status(
                float(row[0]), float(row[1]), float(row[2]), daily_usage=daily_usage
            )

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT balance_inr, reserved_inr, monthly_budget_inr FROM client_quotas WHERE client_id = ?",
                    (client_id,),
                ).fetchone()
                if not row:
                    raise ClientNotFoundError(
                        f"Quota record not found for client_id='{client_id}'"
                    )
                self._release_expired_sqlite(conn, client_id, now)
                row = conn.execute(
                    "SELECT balance_inr, reserved_inr, monthly_budget_inr FROM client_quotas WHERE client_id = ?",
                    (client_id,),
                ).fetchone()
                if user_id:
                    u_row = conn.execute(
                        """
                        SELECT run_count, bonus_runs_granted, input_tokens, output_tokens, tokens_used, cost_inr
                        FROM user_daily_usage WHERE user_id = ? AND usage_date = ?
                        """,
                        (user_id, today),
                    ).fetchone()
                    daily_usage = {
                        "run_count": int(u_row["run_count"]) if u_row else 0,
                        "bonus_runs_granted": int(u_row["bonus_runs_granted"])
                        if u_row
                        else 0,
                        "input_tokens": int(u_row["input_tokens"]) if u_row else 0,
                        "output_tokens": int(u_row["output_tokens"]) if u_row else 0,
                        "tokens_used": int(u_row["tokens_used"]) if u_row else 0,
                        "cost_inr": float(u_row["cost_inr"]) if u_row else 0.0,
                    }
                conn.commit()
                return self._format_quota_status(
                    float(row["balance_inr"]),
                    float(row["reserved_inr"]),
                    float(row["monthly_budget_inr"]),
                    daily_usage=daily_usage,
                )
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

    def credit_quota(
        self, client_id: str, amount_inr: float, update_monthly_budget: bool = False
    ) -> Dict[str, Any]:
        """Add INR quota balance to a client."""
        if amount_inr <= 0:
            raise ValueError("Credit amount must be positive.")
        now_iso = _iso_utc(_utc_now())
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    if update_monthly_budget:
                        cur.execute(
                            """
                            INSERT INTO client_quotas (client_id, balance_inr, reserved_inr, monthly_budget_inr, updated_at)
                            VALUES (%s, %s, 0.0, %s, NOW())
                            ON CONFLICT (client_id) DO UPDATE SET
                                balance_inr = client_quotas.balance_inr + EXCLUDED.balance_inr,
                                monthly_budget_inr = client_quotas.monthly_budget_inr + EXCLUDED.monthly_budget_inr,
                                updated_at = NOW()
                            """,
                            (client_id, float(amount_inr), float(amount_inr)),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO client_quotas (client_id, balance_inr, reserved_inr, monthly_budget_inr, updated_at)
                            VALUES (%s, %s, 0.0, %s, NOW())
                            ON CONFLICT (client_id) DO UPDATE SET
                                balance_inr = client_quotas.balance_inr + EXCLUDED.balance_inr,
                                updated_at = NOW()
                            """,
                            (client_id, float(amount_inr), float(amount_inr)),
                        )
                conn.commit()
        else:
            with self._lock:
                conn = self._get_sqlite_conn()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    if update_monthly_budget:
                        conn.execute(
                            """
                            INSERT INTO client_quotas (client_id, balance_inr, reserved_inr, monthly_budget_inr, updated_at)
                            VALUES (?, ?, 0.0, ?, ?)
                            ON CONFLICT(client_id) DO UPDATE SET
                                balance_inr = client_quotas.balance_inr + excluded.balance_inr,
                                monthly_budget_inr = client_quotas.monthly_budget_inr + excluded.monthly_budget_inr,
                                updated_at = excluded.updated_at
                            """,
                            (client_id, float(amount_inr), float(amount_inr), now_iso),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT INTO client_quotas (client_id, balance_inr, reserved_inr, monthly_budget_inr, updated_at)
                            VALUES (?, ?, 0.0, ?, ?)
                            ON CONFLICT(client_id) DO UPDATE SET
                                balance_inr = client_quotas.balance_inr + excluded.balance_inr,
                                updated_at = excluded.updated_at
                            """,
                            (client_id, float(amount_inr), float(amount_inr), now_iso),
                        )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    if self._shared_sqlite_conn is None:
                        conn.close()
        return self.get_quota_status(client_id)

    def reserve_quota(
        self,
        client_id: str,
        user_id: str,
        operation: str,
        amount_inr: float,
        ttl_seconds: int = QUOTA_RESERVATION_TTL_SECONDS,
        dedup_key: Optional[str] = None,
        is_admin: bool = False,
        daily_limit: int = DAILY_USER_RUN_LIMIT,
        daily_token_limit: int = DAILY_USER_TOKEN_LIMIT,
        daily_spend_limit_inr: float = DAILY_USER_SPEND_LIMIT_INR,
        dedup_window_seconds: int = DUPLICATE_SUBMIT_WINDOW_SECONDS,
    ) -> str:
        """Atomically enforce dedup lock, employee daily cap (25 runs / 75k tokens / ₹9 IST), and client INR bucket."""
        reservation_id = f"res_{uuid.uuid4().hex[:16]}"
        now = _utc_now()
        today = _ist_date_str(now)
        expires_at = now + timedelta(seconds=ttl_seconds)
        dedup_expires = now + timedelta(seconds=dedup_window_seconds)

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    # 1. Duplicate submit lock check
                    if dedup_key:
                        cur.execute(
                            "DELETE FROM request_dedup_locks WHERE expires_at <= NOW()"
                        )
                        cur.execute(
                            "SELECT dedup_key FROM request_dedup_locks WHERE dedup_key = %s AND expires_at > NOW()",
                            (dedup_key,),
                        )
                        if cur.fetchone():
                            raise DuplicateRequestError(
                                f"Duplicate request blocked: identical request already submitted within {dedup_window_seconds}s."
                            )

                    # 2. Teammate daily cap (25 runs / 75,000 tokens / ₹9 spend per IST day + bonus_runs_granted)
                    # Checked BEFORE deducting or reserving client INR balance.
                    cur.execute(
                        """
                        SELECT run_count, bonus_runs_granted, tokens_used, cost_inr
                        FROM user_daily_usage WHERE user_id = %s AND usage_date = %s FOR UPDATE
                        """,
                        (user_id, today),
                    )
                    u_row = cur.fetchone()
                    current_runs = int(u_row[0]) if u_row else 0
                    bonus_runs = int(u_row[1]) if u_row else 0
                    current_tokens = int(u_row[2]) if u_row else 0
                    current_spend = float(u_row[3]) if u_row else 0.0

                    eff_runs = daily_limit + bonus_runs
                    eff_tokens = daily_token_limit + (bonus_runs * 3000)
                    eff_spend = daily_spend_limit_inr + (bonus_runs * 0.50)
                    if not is_admin and (
                        current_runs >= eff_runs
                        or current_tokens >= eff_tokens
                        or current_spend + 1e-9 >= eff_spend
                    ):
                        raise DailyLimitExceededError(
                            "Daily teammate limit reached (25 runs / 75k tokens). Request bonus runs from Admin."
                        )

                    # 3. Client INR balance lock
                    cur.execute(
                        "SELECT balance_inr, reserved_inr FROM client_quotas WHERE client_id = %s FOR UPDATE",
                        (client_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise ClientNotFoundError(
                            f"Quota record not found for client_id='{client_id}'"
                        )
                    self._release_expired_pg(cur, client_id)
                    cur.execute(
                        "SELECT balance_inr, reserved_inr FROM client_quotas WHERE client_id = %s",
                        (client_id,),
                    )
                    bal, res = (float(x) for x in cur.fetchone())
                    available = bal - res
                    if available + 1e-9 < amount_inr:
                        raise InsufficientQuotaError(
                            f"Insufficient quota for client '{client_id}': available ₹{available:.2f}, required ₹{amount_inr:.2f}"
                        )

                    cur.execute(
                        "UPDATE client_quotas SET reserved_inr = reserved_inr + %s, updated_at = NOW() WHERE client_id = %s",
                        (float(amount_inr), client_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO quota_reservations
                            (reservation_id, client_id, user_id, operation, reserved_amount_inr, status, dedup_key, usage_date, expires_at, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'RESERVED', %s, %s, %s, NOW())
                        """,
                        (
                            reservation_id,
                            client_id,
                            user_id,
                            operation,
                            float(amount_inr),
                            dedup_key,
                            today,
                            expires_at,
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO user_daily_usage (user_id, usage_date, run_count, updated_at)
                        VALUES (%s, %s, 1, NOW())
                        ON CONFLICT (user_id, usage_date) DO UPDATE SET
                            run_count = user_daily_usage.run_count + 1,
                            updated_at = NOW()
                        """,
                        (user_id, today),
                    )
                    if dedup_key:
                        cur.execute(
                            """
                            INSERT INTO request_dedup_locks (dedup_key, client_id, user_id, expires_at, created_at)
                            VALUES (%s, %s, %s, %s, NOW())
                            ON CONFLICT (dedup_key) DO UPDATE SET expires_at = EXCLUDED.expires_at
                            """,
                            (dedup_key, client_id, user_id, dedup_expires),
                        )
                conn.commit()
            return reservation_id

        now_iso = _iso_utc(now)
        exp_iso = _iso_utc(expires_at)
        dedup_exp_iso = _iso_utc(dedup_expires)
        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")

                if dedup_key:
                    conn.execute(
                        "DELETE FROM request_dedup_locks WHERE expires_at <= ?",
                        (now_iso,),
                    )
                    dup_row = conn.execute(
                        "SELECT dedup_key FROM request_dedup_locks WHERE dedup_key = ? AND expires_at > ?",
                        (dedup_key, now_iso),
                    ).fetchone()
                    if dup_row:
                        raise DuplicateRequestError(
                            f"Duplicate request blocked: identical request already submitted within {dedup_window_seconds}s."
                        )

                u_row = conn.execute(
                    """
                    SELECT run_count, bonus_runs_granted, tokens_used, cost_inr
                    FROM user_daily_usage WHERE user_id = ? AND usage_date = ?
                    """,
                    (user_id, today),
                ).fetchone()
                current_runs = int(u_row["run_count"]) if u_row else 0
                bonus_runs = int(u_row["bonus_runs_granted"]) if u_row else 0
                current_tokens = int(u_row["tokens_used"]) if u_row else 0
                current_spend = float(u_row["cost_inr"]) if u_row else 0.0

                eff_runs = daily_limit + bonus_runs
                eff_tokens = daily_token_limit + (bonus_runs * 3000)
                eff_spend = daily_spend_limit_inr + (bonus_runs * 0.50)
                if not is_admin and (
                    current_runs >= eff_runs
                    or current_tokens >= eff_tokens
                    or current_spend + 1e-9 >= eff_spend
                ):
                    raise DailyLimitExceededError(
                        "Daily teammate limit reached (25 runs / 75k tokens). Request bonus runs from Admin."
                    )

                row = conn.execute(
                    "SELECT balance_inr, reserved_inr FROM client_quotas WHERE client_id = ?",
                    (client_id,),
                ).fetchone()
                if not row:
                    raise ClientNotFoundError(
                        f"Quota record not found for client_id='{client_id}'"
                    )
                self._release_expired_sqlite(conn, client_id, now)
                row = conn.execute(
                    "SELECT balance_inr, reserved_inr FROM client_quotas WHERE client_id = ?",
                    (client_id,),
                ).fetchone()
                bal, res = float(row["balance_inr"]), float(row["reserved_inr"])
                available = bal - res
                if available + 1e-9 < amount_inr:
                    raise InsufficientQuotaError(
                        f"Insufficient quota for client '{client_id}': available ₹{available:.2f}, required ₹{amount_inr:.2f}"
                    )

                conn.execute(
                    "UPDATE client_quotas SET reserved_inr = reserved_inr + ?, updated_at = ? WHERE client_id = ?",
                    (float(amount_inr), now_iso, client_id),
                )
                conn.execute(
                    """
                    INSERT INTO quota_reservations
                        (reservation_id, client_id, user_id, operation, reserved_amount_inr, status, dedup_key, usage_date, expires_at, created_at)
                    VALUES (?, ?, ?, ?, ?, 'RESERVED', ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        client_id,
                        user_id,
                        operation,
                        float(amount_inr),
                        dedup_key,
                        today,
                        exp_iso,
                        now_iso,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO user_daily_usage (user_id, usage_date, run_count, updated_at)
                    VALUES (?, ?, 1, ?)
                    ON CONFLICT(user_id, usage_date) DO UPDATE SET
                        run_count = user_daily_usage.run_count + 1,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, today, now_iso),
                )
                if dedup_key:
                    conn.execute(
                        """
                        INSERT INTO request_dedup_locks (dedup_key, client_id, user_id, expires_at, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(dedup_key) DO UPDATE SET expires_at = excluded.expires_at
                        """,
                        (dedup_key, client_id, user_id, dedup_exp_iso, now_iso),
                    )
                conn.commit()
                return reservation_id
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

    def settle_quota(
        self,
        reservation_id: str,
        actual_cost_inr: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tokens_used: Optional[int] = None,
        deliverable_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Settle exact actual cost, token counts, user daily usage, and script_runs upon completion."""
        actual = max(0.0, round(float(actual_cost_inr), 4))
        in_tok = max(0, int(input_tokens or 0))
        out_tok = max(0, int(output_tokens or 0))
        tot_tok = max(
            0, int(tokens_used if tokens_used is not None else (in_tok + out_tok))
        )
        now_iso = _iso_utc(_utc_now())
        run_id = f"run_{uuid.uuid4().hex[:16]}"

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT client_id, user_id, operation, reserved_amount_inr, status, usage_date
                        FROM quota_reservations WHERE reservation_id = %s FOR UPDATE
                        """,
                        (reservation_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise QuotaError(f"Reservation '{reservation_id}' not found.")
                    client_id, user_id, operation, reserved_amt, status, usage_date = (
                        row[0],
                        row[1],
                        row[2],
                        float(row[3]),
                        row[4],
                        row[5] or _ist_date_str(),
                    )
                    if status != "RESERVED":
                        return self.get_quota_status(client_id, user_id=user_id)

                    cur.execute(
                        """
                        UPDATE quota_reservations
                        SET status = 'SETTLED',
                            actual_cost_inr = %s,
                            input_tokens = %s,
                            output_tokens = %s,
                            tokens_used = %s,
                            settled_at = NOW()
                        WHERE reservation_id = %s
                        """,
                        (actual, in_tok, out_tok, tot_tok, reservation_id),
                    )
                    cur.execute(
                        """
                        UPDATE client_quotas
                        SET balance_inr = GREATEST(0, balance_inr - %s),
                            reserved_inr = GREATEST(0, reserved_inr - %s),
                            updated_at = NOW()
                        WHERE client_id = %s
                        """,
                        (actual, reserved_amt, client_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO user_daily_usage
                            (user_id, usage_date, run_count, input_tokens, output_tokens, tokens_used, cost_inr, updated_at)
                        VALUES (%s, %s, 0, %s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id, usage_date) DO UPDATE SET
                            input_tokens = user_daily_usage.input_tokens + EXCLUDED.input_tokens,
                            output_tokens = user_daily_usage.output_tokens + EXCLUDED.output_tokens,
                            tokens_used = user_daily_usage.tokens_used + EXCLUDED.tokens_used,
                            cost_inr = user_daily_usage.cost_inr + EXCLUDED.cost_inr,
                            updated_at = NOW()
                        """,
                        (user_id, usage_date, in_tok, out_tok, tot_tok, actual),
                    )
                    cur.execute(
                        """
                        INSERT INTO script_runs
                            (run_id, reservation_id, deliverable_id, client_id, user_id, operation, input_tokens, output_tokens, tokens_used, cost_inr, usage_date, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            run_id,
                            reservation_id,
                            deliverable_id,
                            client_id,
                            user_id,
                            operation,
                            in_tok,
                            out_tok,
                            tot_tok,
                            actual,
                            usage_date,
                        ),
                    )
                conn.commit()
            return self.get_quota_status(client_id, user_id=user_id)

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT client_id, user_id, operation, reserved_amount_inr, status, usage_date FROM quota_reservations WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone()
                if not row:
                    raise QuotaError(f"Reservation '{reservation_id}' not found.")
                client_id = row["client_id"]
                user_id = row["user_id"]
                operation = row["operation"]
                reserved_amt = float(row["reserved_amount_inr"])
                usage_date = row["usage_date"] or _ist_date_str()
                if row["status"] != "RESERVED":
                    conn.commit()
                    return self.get_quota_status(client_id, user_id=user_id)

                conn.execute(
                    """
                    UPDATE quota_reservations
                    SET status = 'SETTLED',
                        actual_cost_inr = ?,
                        input_tokens = ?,
                        output_tokens = ?,
                        tokens_used = ?,
                        settled_at = ?
                    WHERE reservation_id = ?
                    """,
                    (actual, in_tok, out_tok, tot_tok, now_iso, reservation_id),
                )
                conn.execute(
                    """
                    UPDATE client_quotas
                    SET balance_inr = MAX(0.0, balance_inr - ?),
                        reserved_inr = MAX(0.0, reserved_inr - ?),
                        updated_at = ?
                    WHERE client_id = ?
                    """,
                    (actual, reserved_amt, now_iso, client_id),
                )
                conn.execute(
                    """
                    INSERT INTO user_daily_usage
                        (user_id, usage_date, run_count, input_tokens, output_tokens, tokens_used, cost_inr, updated_at)
                    VALUES (?, ?, 0, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, usage_date) DO UPDATE SET
                        input_tokens = user_daily_usage.input_tokens + excluded.input_tokens,
                        output_tokens = user_daily_usage.output_tokens + excluded.output_tokens,
                        tokens_used = user_daily_usage.tokens_used + excluded.tokens_used,
                        cost_inr = user_daily_usage.cost_inr + excluded.cost_inr,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, usage_date, in_tok, out_tok, tot_tok, actual, now_iso),
                )
                conn.execute(
                    """
                    INSERT INTO script_runs
                        (run_id, reservation_id, deliverable_id, client_id, user_id, operation, input_tokens, output_tokens, tokens_used, cost_inr, usage_date, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        reservation_id,
                        deliverable_id,
                        client_id,
                        user_id,
                        operation,
                        in_tok,
                        out_tok,
                        tot_tok,
                        actual,
                        usage_date,
                        now_iso,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()
        return self.get_quota_status(client_id, user_id=user_id)

    def link_run_deliverable(self, reservation_id: str, deliverable_id: str) -> None:
        """Attach persisted deliverable_id to the settled script_runs audit record."""
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE script_runs SET deliverable_id = %s WHERE reservation_id = %s",
                        (deliverable_id, reservation_id),
                    )
                conn.commit()
            return

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute(
                    "UPDATE script_runs SET deliverable_id = ? WHERE reservation_id = ?",
                    (deliverable_id, reservation_id),
                )
                conn.commit()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

    def get_script_runs(
        self,
        client_id: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query completed script_runs audit log rows (user_id, client_id, tokens, cost_inr)."""
        clauses = []
        params: List[Any] = []
        if client_id:
            clauses.append("client_id = %s" if self.is_postgres else "client_id = ?")
            params.append(client_id)
        if user_id:
            clauses.append("user_id = %s" if self.is_postgres else "user_id = ?")
            params.append(user_id)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        limit_val = min(max(1, int(limit)), 200)

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT run_id, reservation_id, deliverable_id, client_id, user_id, operation,
                               input_tokens, output_tokens, tokens_used, cost_inr, usage_date, created_at
                        FROM script_runs {where_sql}
                        ORDER BY created_at DESC LIMIT %s
                        """,
                        (*params, limit_val),
                    )
                    rows = cur.fetchall()
            return [
                {
                    "run_id": r[0],
                    "reservation_id": r[1],
                    "deliverable_id": r[2],
                    "client_id": r[3],
                    "user_id": r[4],
                    "operation": r[5],
                    "input_tokens": int(r[6]),
                    "output_tokens": int(r[7]),
                    "tokens_used": int(r[8]),
                    "cost_inr": float(r[9]),
                    "usage_date": r[10],
                    "created_at": str(r[11]),
                }
                for r in rows
            ]

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                rows = conn.execute(
                    f"""
                    SELECT run_id, reservation_id, deliverable_id, client_id, user_id, operation,
                           input_tokens, output_tokens, tokens_used, cost_inr, usage_date, created_at
                    FROM script_runs {where_sql}
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (*params, limit_val),
                ).fetchall()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()
        return [dict(r) for r in rows]

    def refund_quota(self, reservation_id: str) -> bool:
        """Roll back reservation, daily run count, and dedup lock on pipeline failure."""
        now_iso = _iso_utc(_utc_now())

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT client_id, user_id, reserved_amount_inr, status, dedup_key, usage_date
                        FROM quota_reservations WHERE reservation_id = %s FOR UPDATE
                        """,
                        (reservation_id,),
                    )
                    row = cur.fetchone()
                    if not row or row[3] != "RESERVED":
                        conn.commit()
                        return False
                    client_id, user_id, reserved_amt, _, dedup_key, usage_date = row
                    cur.execute(
                        """
                        UPDATE quota_reservations
                        SET status = 'REFUNDED', actual_cost_inr = 0.0, settled_at = NOW()
                        WHERE reservation_id = %s
                        """,
                        (reservation_id,),
                    )
                    cur.execute(
                        """
                        UPDATE client_quotas
                        SET reserved_inr = GREATEST(0, reserved_inr - %s), updated_at = NOW()
                        WHERE client_id = %s
                        """,
                        (float(reserved_amt), client_id),
                    )
                    if usage_date:
                        cur.execute(
                            """
                            UPDATE user_daily_usage
                            SET run_count = GREATEST(0, run_count - 1), updated_at = NOW()
                            WHERE user_id = %s AND usage_date = %s
                            """,
                            (user_id, usage_date),
                        )
                    if dedup_key:
                        cur.execute(
                            "DELETE FROM request_dedup_locks WHERE dedup_key = %s",
                            (dedup_key,),
                        )
                conn.commit()
            return True

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT client_id, user_id, reserved_amount_inr, status, dedup_key, usage_date
                    FROM quota_reservations WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                ).fetchone()
                if not row or row["status"] != "RESERVED":
                    conn.commit()
                    return False
                client_id = row["client_id"]
                user_id = row["user_id"]
                reserved_amt = float(row["reserved_amount_inr"])
                dedup_key = row["dedup_key"]
                usage_date = row["usage_date"]

                conn.execute(
                    """
                    UPDATE quota_reservations
                    SET status = 'REFUNDED', actual_cost_inr = 0.0, settled_at = ?
                    WHERE reservation_id = ?
                    """,
                    (now_iso, reservation_id),
                )
                conn.execute(
                    """
                    UPDATE client_quotas
                    SET reserved_inr = MAX(0.0, reserved_inr - ?), updated_at = ?
                    WHERE client_id = ?
                    """,
                    (reserved_amt, now_iso, client_id),
                )
                if usage_date:
                    conn.execute(
                        """
                        UPDATE user_daily_usage
                        SET run_count = MAX(0, run_count - 1), updated_at = ?
                        WHERE user_id = ? AND usage_date = ?
                        """,
                        (now_iso, user_id, usage_date),
                    )
                if dedup_key:
                    conn.execute(
                        "DELETE FROM request_dedup_locks WHERE dedup_key = ?",
                        (dedup_key,),
                    )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

    def save_deliverable(
        self,
        deliverable: FullDeliverable,
        client_id: str,
        user_id: str,
        parent_deliverable_id: Optional[str] = None,
    ) -> str:
        """Persist complete deliverable JSON and cost/usage metadata in script_deliverables."""
        deliverable_id = deliverable.deliverable_id or f"del_{uuid.uuid4().hex[:16]}"
        deliverable.deliverable_id = deliverable_id
        deliverable.client_id = client_id
        deliverable.user_id = user_id

        payload_json = deliverable.model_dump_json()
        now_iso = _iso_utc(_utc_now())

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO script_deliverables (
                            deliverable_id, client_id, user_id, topic, duration, tone, objective,
                            deliverable_json, model_used, input_tokens, output_tokens, tokens_used,
                            cost_inr, parent_deliverable_id, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        ON CONFLICT (deliverable_id) DO UPDATE SET
                            deliverable_json = EXCLUDED.deliverable_json,
                            model_used = EXCLUDED.model_used,
                            input_tokens = EXCLUDED.input_tokens,
                            output_tokens = EXCLUDED.output_tokens,
                            tokens_used = EXCLUDED.tokens_used,
                            cost_inr = EXCLUDED.cost_inr,
                            updated_at = NOW()
                        """,
                        (
                            deliverable_id,
                            client_id,
                            user_id,
                            deliverable.input_data.topic,
                            deliverable.input_data.duration,
                            deliverable.input_data.tone,
                            deliverable.input_data.objective,
                            payload_json,
                            deliverable.model_used,
                            deliverable.input_tokens,
                            deliverable.output_tokens,
                            deliverable.tokens_used,
                            deliverable.cost_inr,
                            parent_deliverable_id,
                        ),
                    )
                conn.commit()
            return deliverable_id

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO script_deliverables (
                        deliverable_id, client_id, user_id, topic, duration, tone, objective,
                        deliverable_json, model_used, input_tokens, output_tokens, tokens_used,
                        cost_inr, parent_deliverable_id, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(deliverable_id) DO UPDATE SET
                        deliverable_json = excluded.deliverable_json,
                        model_used = excluded.model_used,
                        input_tokens = excluded.input_tokens,
                        output_tokens = excluded.output_tokens,
                        tokens_used = excluded.tokens_used,
                        cost_inr = excluded.cost_inr,
                        updated_at = excluded.updated_at
                    """,
                    (
                        deliverable_id,
                        client_id,
                        user_id,
                        deliverable.input_data.topic,
                        deliverable.input_data.duration,
                        deliverable.input_data.tone,
                        deliverable.input_data.objective,
                        payload_json,
                        deliverable.model_used,
                        deliverable.input_tokens,
                        deliverable.output_tokens,
                        deliverable.tokens_used,
                        deliverable.cost_inr,
                        parent_deliverable_id,
                        now_iso,
                        now_iso,
                    ),
                )
                conn.commit()
                return deliverable_id
            except Exception:
                conn.rollback()
                raise
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

    def get_deliverable(self, deliverable_id: str) -> Optional[FullDeliverable]:
        """Load a persisted deliverable from script_deliverables by ID."""
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT deliverable_json FROM script_deliverables WHERE deliverable_id = %s",
                        (deliverable_id,),
                    )
                    row = cur.fetchone()
            if not row:
                return None
            raw_json = row[0] if isinstance(row[0], str) else json.dumps(row[0])
            return FullDeliverable.model_validate_json(raw_json)

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                row = conn.execute(
                    "SELECT deliverable_json FROM script_deliverables WHERE deliverable_id = ?",
                    (deliverable_id,),
                ).fetchone()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

        if not row:
            return None
        return FullDeliverable.model_validate_json(row["deliverable_json"])

    # ------------------------------------------------------------------
    # Standalone (non-CRM) deliverables: persisted so they survive redeploys
    # on hosts with ephemeral disks (Render, Cloud Run, Railway).
    # ------------------------------------------------------------------
    def save_standalone_deliverable(self, deliverable: FullDeliverable) -> str:
        """Upsert a standalone studio deliverable and return its ID."""
        deliverable_id = deliverable.deliverable_id or f"sa_{uuid.uuid4().hex[:16]}"
        deliverable.deliverable_id = deliverable_id
        inp = deliverable.input_data
        params = (
            deliverable_id,
            inp.topic,
            inp.platform or "",
            int(inp.duration),
            inp.tone or "",
            int(deliverable.script.word_count or 0),
            deliverable.model_dump_json(),
        )

        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO standalone_deliverables (
                            deliverable_id, topic, platform, duration, tone, word_count,
                            deliverable_json, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
                        ON CONFLICT (deliverable_id) DO UPDATE SET
                            deliverable_json = EXCLUDED.deliverable_json,
                            word_count = EXCLUDED.word_count,
                            updated_at = NOW()
                        """,
                        params,
                    )
                conn.commit()
            return deliverable_id

        now_iso = _iso_utc(_utc_now())
        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO standalone_deliverables (
                        deliverable_id, topic, platform, duration, tone, word_count,
                        deliverable_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(deliverable_id) DO UPDATE SET
                        deliverable_json = excluded.deliverable_json,
                        word_count = excluded.word_count,
                        updated_at = excluded.updated_at
                    """,
                    (*params, now_iso, now_iso),
                )
                conn.commit()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()
        return deliverable_id

    def list_standalone_deliverables(self, limit: int = 5) -> List[Dict[str, Any]]:
        """List recent standalone deliverables (summary fields only), newest first."""
        query = (
            "SELECT deliverable_id, topic, platform, duration, tone, word_count "
            "FROM standalone_deliverables ORDER BY updated_at DESC LIMIT {ph}"
        )
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query.format(ph="%s"), (limit,))
                    rows = cur.fetchall()
        else:
            with self._lock:
                conn = self._get_sqlite_conn()
                try:
                    rows = [
                        tuple(r)
                        for r in conn.execute(query.format(ph="?"), (limit,)).fetchall()
                    ]
                finally:
                    if self._shared_sqlite_conn is None:
                        conn.close()
        return [
            {
                "stem": r[0],
                "topic": r[1],
                "platform": r[2],
                "duration": r[3],
                "tone": r[4],
                "word_count": r[5],
            }
            for r in rows
        ]

    def get_standalone_deliverable(
        self, deliverable_id: str
    ) -> Optional[FullDeliverable]:
        """Load a standalone deliverable by ID, or None if missing."""
        query = "SELECT deliverable_json FROM standalone_deliverables WHERE deliverable_id = {ph}"
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(query.format(ph="%s"), (deliverable_id,))
                    row = cur.fetchone()
        else:
            with self._lock:
                conn = self._get_sqlite_conn()
                try:
                    row = conn.execute(
                        query.format(ph="?"), (deliverable_id,)
                    ).fetchone()
                finally:
                    if self._shared_sqlite_conn is None:
                        conn.close()
        if not row:
            return None
        raw = row[0] if isinstance(row[0], str) else json.dumps(row[0])
        return FullDeliverable.model_validate_json(raw)

    def get_client_history(
        self, client_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """List recent generated deliverables for a CRM client."""
        if self.is_postgres:
            with self._get_pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT deliverable_id, client_id, user_id, topic, duration, tone, objective,
                               model_used, input_tokens, output_tokens, tokens_used, cost_inr,
                               parent_deliverable_id, created_at, updated_at
                        FROM script_deliverables
                        WHERE client_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (client_id, limit),
                    )
                    rows = cur.fetchall()
            return [
                {
                    "deliverable_id": r[0],
                    "client_id": r[1],
                    "user_id": r[2],
                    "topic": r[3],
                    "duration": r[4],
                    "tone": r[5],
                    "objective": r[6],
                    "model_used": r[7],
                    "input_tokens": r[8],
                    "output_tokens": r[9],
                    "tokens_used": r[10],
                    "cost_inr": float(r[11]),
                    "parent_deliverable_id": r[12],
                    "created_at": str(r[13]),
                    "updated_at": str(r[14]),
                }
                for r in rows
            ]

        with self._lock:
            conn = self._get_sqlite_conn()
            try:
                rows = conn.execute(
                    """
                    SELECT deliverable_id, client_id, user_id, topic, duration, tone, objective,
                           model_used, input_tokens, output_tokens, tokens_used, cost_inr,
                           parent_deliverable_id, created_at, updated_at
                    FROM script_deliverables
                    WHERE client_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (client_id, limit),
                ).fetchall()
            finally:
                if self._shared_sqlite_conn is None:
                    conn.close()

        return [dict(r) for r in rows]
