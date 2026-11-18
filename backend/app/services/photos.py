"""Photo intake: content sniffing, re-encoding without EXIF/GPS, WebP previews."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import ValidationFailed
from app.integrations.storage.base import Storage

try:  # HEIC support is optional at runtime (wheels exist for Linux x86_64/arm64).
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_AVAILABLE = True
except ImportError:  # pragma: no cover
    HEIF_AVAILABLE = False

PREVIEW_SIZE = 640
MAX_ORIGINAL_SIDE = 2560
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif"}


def sniff_image_type(data: bytes) -> str | None:
    """Detect the real format by magic bytes, ignoring the client's filename and content type."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "heic"
    return None


@dataclass(frozen=True)
class ProcessedPhoto:
    original: bytes
    original_ext: str
    original_content_type: str
    preview: bytes
    width: int
    height: int
    sha256: str


def process_image(data: bytes, max_pixels: int) -> ProcessedPhoto:
    """Decode, auto-rotate, strip all metadata (EXIF incl. GPS, XMP, ICC comments) and re-encode."""
    kind = sniff_image_type(data)
    if kind is None or (kind == "heic" and not HEIF_AVAILABLE):
        raise ValueError("unsupported")
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            if img.width * img.height > max_pixels:
                raise ValueError("too_many_pixels")
            img.load()
            image = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise ValueError("corrupt") from exc

    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    image.thumbnail((MAX_ORIGINAL_SIDE, MAX_ORIGINAL_SIDE))

    out = io.BytesIO()
    # Re-encoding from raw pixels drops every metadata block; we never pass exif=... to save().
    if kind == "png" or has_alpha:
        image.save(out, "PNG", optimize=True)
        ext, ctype = "png", "image/png"
    elif kind == "webp":
        image.save(out, "WEBP", quality=85)
        ext, ctype = "webp", "image/webp"
    else:  # jpeg and heic → jpeg (browsers can't show HEIC)
        image.save(out, "JPEG", quality=85, optimize=True, progressive=True)
        ext, ctype = "jpg", "image/jpeg"
    original = out.getvalue()

    preview_img = image.copy()
    preview_img.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
    prev = io.BytesIO()
    preview_img.save(prev, "WEBP", quality=78)
    return ProcessedPhoto(
        original=original,
        original_ext=ext,
        original_content_type=ctype,
        preview=prev.getvalue(),
        width=image.width,
        height=image.height,
        sha256=hashlib.sha256(original).hexdigest(),
    )


@dataclass(frozen=True)
class StoredPhoto:
    id: uuid.UUID
    original_key: str
    preview_key: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str


@dataclass(frozen=True)
class UploadedFile:
    filename: str
    data: bytes


class PhotoService:
    def __init__(self, storage: Storage, *, max_files: int, max_bytes: int, max_pixels: int) -> None:
        self.storage = storage
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.max_pixels = max_pixels

    def check_limits(self, files: list[UploadedFile]) -> None:
        if len(files) > self.max_files:
            raise ValidationFailed("Слишком много файлов", fields={"photos": f"Не больше {self.max_files} фото"})
        for f in files:
            if len(f.data) > self.max_bytes:
                raise ValidationFailed(
                    "Файл слишком большой",
                    fields={"photos": f"«{f.filename[:60]}» больше {self.max_bytes // (1024 * 1024)} МБ"},
                )
            if not f.data:
                raise ValidationFailed("Пустой файл", fields={"photos": f"«{f.filename[:60]}» пустой"})

    async def store(self, prefix: str, files: list[UploadedFile]) -> list[StoredPhoto]:
        """Validate and store photos; on any failure nothing stays on disk."""
        self.check_limits(files)
        processed: list[ProcessedPhoto] = []
        for f in files:
            try:
                processed.append(await asyncio.to_thread(process_image, f.data, self.max_pixels))
            except ValueError as exc:
                raise ValidationFailed(
                    "Неподдерживаемый файл",
                    fields={"photos": f"«{f.filename[:60]}» — не изображение JPG/PNG/WebP/HEIC или файл повреждён"},
                ) from exc

        stored: list[StoredPhoto] = []
        try:
            for p in processed:
                pid = uuid.uuid4()
                short = p.sha256[:10]
                original_key = f"{prefix}/{pid.hex}-{short}.{p.original_ext}"
                preview_key = f"{prefix}/{pid.hex}-{short}-preview.webp"
                await self.storage.save(original_key, p.original, p.original_content_type)
                await self.storage.save(preview_key, p.preview, "image/webp")
                stored.append(
                    StoredPhoto(
                        pid,
                        original_key,
                        preview_key,
                        p.original_content_type,
                        len(p.original),
                        p.width,
                        p.height,
                        p.sha256,
                    )
                )
        except Exception:
            await self.discard(stored)
            raise
        return stored

    async def discard(self, photos: list[StoredPhoto]) -> None:
        for p in photos:
            await self.storage.delete(p.original_key)
            await self.storage.delete(p.preview_key)
