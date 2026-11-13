import io
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from .. import pipeline
from ..models import Avatar, Session, User, utcnow
from ..security import hash_password, verify_password
from .auth import UserOut
from .deps import current_user, get_db

router = APIRouter(prefix="/api/profile", tags=["profile"])

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 40_000_000
AVATAR_SIZE = 256
AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}


class ProfileBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    job_description: str = Field(max_length=4000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name can't be empty")
        return value


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.put("", response_model=UserOut)
def save_profile(body: ProfileBody, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    user.name = body.name
    description = body.job_description.strip()
    changed = description != user.job_description
    if changed:
        # Existing selections stay. The past 24 hours of collected jobs get checked against the new text.
        user.job_description = description
        user.description_version += 1
        user.matching_from = utcnow() - timedelta(hours=24)
    db.commit()
    if changed and description:
        pipeline.start_matching_user(user.id)
    return user


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(body: PasswordBody, user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password isn't right.")
    user.password_hash = hash_password(body.new_password)
    # Log out every device, including this one; the page sends the user back to log in.
    db.execute(delete(Session).where(Session.user_id == user.id))
    db.commit()


def _clean_avatar(raw: bytes) -> bytes:
    """Decode and redraw the image, so nothing but pixels from the upload is stored."""
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in AVATAR_FORMATS:
                raise ValueError
            if image.width * image.height > MAX_AVATAR_PIXELS:
                raise ValueError
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE))
            out = io.BytesIO()
            image.save(out, "WEBP", quality=85)
            return out.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please choose a JPG, PNG or WebP image.")


@router.put("/avatar", response_model=UserOut)
def upload_avatar(
    file: UploadFile = File(...), user: User = Depends(current_user), db: DbSession = Depends(get_db)
):
    raw = file.file.read(MAX_AVATAR_BYTES + 1)
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Please choose an image under 5 MB.")
    image = _clean_avatar(raw)
    avatar = db.get(Avatar, user.id)
    if avatar is None:
        db.add(Avatar(user_id=user.id, image=image))
    else:
        avatar.image = image
    user.avatar_updated_at = utcnow()
    db.commit()
    return user


@router.delete("/avatar", response_model=UserOut)
def remove_avatar(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    db.execute(delete(Avatar).where(Avatar.user_id == user.id))
    user.avatar_updated_at = None
    db.commit()
    return user


@router.get("/avatar")
def read_avatar(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    image = db.scalar(select(Avatar.image).where(Avatar.user_id == user.id))
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No avatar set.")
    return Response(
        image,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"},
    )
