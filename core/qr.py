from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


def make_qr_bytes(text: str) -> bytes:
    """
    Generate a QR code PNG for the given text and return raw bytes.
    Returns empty bytes if qrcode or Pillow is not installed.
    """
    try:
        import qrcode
        from qrcode.image.pil import PilImage

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img: PilImage = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        logger.warning("qrcode or Pillow not installed — QR codes disabled.")
        return b""
    except Exception as exc:
        logger.error("QR code generation failed: %s", exc)
        return b""
