"""
Automated backup job — runs every 6 hours.
Backs up:
  1. Bot's PostgreSQL database (pg_dump)
  2. X-UI Sanaei panel databases (via /server/getDb API)
Sends both as files to all admin users via Telegram.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from models.user import User
from models.xui import XUIInboundRecord, XUIServerRecord
from services.xui.client import XUIClientError
from services.xui.runtime import create_xui_client_for_server

logger = logging.getLogger(__name__)


async def _get_admin_telegram_ids(session: AsyncSession) -> set[int]:
    """Get all admin/owner Telegram IDs."""
    ids: set[int] = set()
    if settings.owner_telegram_id:
        ids.add(settings.owner_telegram_id)
    try:
        result = await session.execute(
            select(User.telegram_id).where(User.role.in_(["admin", "owner"]))
        )
        for row in result.scalars().all():
            ids.add(row)
    except Exception as exc:
        logger.warning("Failed to query admin users: %s", exc)
    return ids


async def _dump_postgres() -> bytes | None:
    """Dump PostgreSQL database using pg_dump."""
    # Parse database URL for connection params
    db_url = settings.database_url
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    try:
        # Remove driver prefix
        clean = db_url.split("://", 1)[1]  # user:pass@host:port/dbname
        userpass, hostdb = clean.rsplit("@", 1)
        user, password = userpass.split(":", 1)
        hostport, dbname = hostdb.split("/", 1)
        if ":" in hostport:
            host, port = hostport.split(":", 1)
        else:
            host, port = hostport, "5432"
    except (ValueError, IndexError) as exc:
        logger.error("Failed to parse DATABASE_URL for pg_dump: %s", exc)
        return None

    env = {"PGPASSWORD": password}
    cmd = [
        "pg_dump",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", dbname,
        "--no-owner",
        "--no-privileges",
        "-F", "c",  # Custom format (compressed)
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**dict(__import__("os").environ), **env},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            logger.error("pg_dump failed (code %d): %s", proc.returncode, stderr.decode()[:500])
            return None
        if len(stdout) < 50:
            logger.error("pg_dump produced suspiciously small output (%d bytes)", len(stdout))
            return None
        logger.info("pg_dump successful: %d bytes", len(stdout))
        return stdout
    except asyncio.TimeoutError:
        logger.error("pg_dump timed out after 120 seconds")
        return None
    except FileNotFoundError:
        logger.error("pg_dump not found — is postgresql-client installed in the container?")
        return None
    except Exception as exc:
        logger.error("pg_dump failed: %s", exc)
        return None


async def _dump_xui_databases(session: AsyncSession) -> list[tuple[str, bytes]]:
    """Download X-UI databases from all active servers."""
    # Get unique active servers
    result = await session.execute(
        select(XUIServerRecord)
        .options(selectinload(XUIServerRecord.credentials))
        .where(
            XUIServerRecord.is_active.is_(True),
            XUIServerRecord.health_status != "deleted",
        )
    )
    servers = list(result.scalars().all())

    backups: list[tuple[str, bytes]] = []
    for server in servers:
        if server.credentials is None:
            logger.warning("Skipping backup for server '%s' — no credentials", server.name)
            continue
        try:
            async with create_xui_client_for_server(server) as xui_client:
                db_bytes = await xui_client.get_db_backup()
                backups.append((server.name, db_bytes))
                logger.info("Downloaded X-UI DB from '%s': %d bytes", server.name, len(db_bytes))
        except XUIClientError as exc:
            logger.error("Failed to download X-UI DB from '%s': %s", server.name, exc)
        except Exception as exc:
            logger.error("Unexpected error downloading X-UI DB from '%s': %s", server.name, exc)

    return backups


async def run_backup(session: AsyncSession, bot: Bot) -> None:
    """Main backup job — dump databases and send to admins."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d_%H%M")
    logger.info("[BACKUP] Starting automated backup at %s", timestamp)

    admin_ids = await _get_admin_telegram_ids(session)
    if not admin_ids:
        logger.warning("[BACKUP] No admin IDs found — skipping backup send")
        return

    files_to_send: list[BufferedInputFile] = []

    # 1. PostgreSQL backup
    pg_data = await _dump_postgres()
    if pg_data:
        files_to_send.append(
            BufferedInputFile(
                pg_data,
                filename=f"marzbot_db_{timestamp}.dump",
            )
        )
    else:
        logger.warning("[BACKUP] PostgreSQL backup failed — will still try X-UI backups")

    # 2. X-UI database backups
    xui_backups = await _dump_xui_databases(session)
    for server_name, db_bytes in xui_backups:
        safe_name = server_name.replace(" ", "_").replace("/", "_")[:30]
        files_to_send.append(
            BufferedInputFile(
                db_bytes,
                filename=f"xui_{safe_name}_{timestamp}.db",
            )
        )

    if not files_to_send:
        logger.error("[BACKUP] All backups failed — nothing to send")
        # Still notify admins about failure
        for tg_id in admin_ids:
            try:
                await bot.send_message(tg_id, "⚠️ بکاپ اتوماتیک ناموفق بود. هیچ فایلی تولید نشد.")
            except Exception:
                pass
        return

    # Send files to all admins
    caption = (
        f"🗄 بکاپ اتوماتیک\n"
        f"📅 {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"📦 {len(files_to_send)} فایل"
    )

    for tg_id in admin_ids:
        try:
            # Send caption message
            await bot.send_message(tg_id, caption)
            # Send each file
            for file in files_to_send:
                await bot.send_document(tg_id, file)
                await asyncio.sleep(0.5)  # Rate limiting
            logger.info("[BACKUP] Sent %d backup files to admin %s", len(files_to_send), tg_id)
        except Exception as exc:
            logger.error("[BACKUP] Failed to send backups to admin %s: %s", tg_id, exc)

    logger.info("[BACKUP] Backup job completed successfully")
