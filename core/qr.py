from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def make_qr_bytes(text: str) -> bytes:
    """
    Generate a QR code PNG using segno (pure Python, no Pillow needed).
    Returns empty bytes if segno is not installed.
    """
    try:
        import segno

        qr = segno.make_qr(text, error="L")
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=10, border=4)
        return buf.getvalue()
    except ImportError:
        logger.warning("segno not installed — QR codes disabled.")
        return b""
    except Exception as exc:
        logger.error("QR code generation failed: %s", exc)
        return b""
