from datetime import timedelta
import logging
from pathlib import Path
from typing import BinaryIO
import uuid

from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def sanitize_filename(filename: str | None, default_ext: str = "mp3") -> str:
    """Strips directory traversal sequences and unsafe characters from audio filenames."""
    if not filename:
        return f"audio_{uuid.uuid4().hex[:8]}.{default_ext}"
    base = Path(filename).name.strip()
    if not base or base in (".", ".."):
        return f"audio_{uuid.uuid4().hex[:8]}.{default_ext}"
    clean = "".join(c for c in base if c.isalnum() or c in "._- ")
    clean = clean.replace(" ", "_")
    return clean or f"audio_{uuid.uuid4().hex[:8]}.{default_ext}"


class MinioService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = Minio(
            self.settings.minio_url,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=False,  # Assuming local development over HTTP without SSL
        )
        self.bucket_name = self.settings.minio_bucket_name
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self) -> None:
        """Creates the bucket if it doesn't already exist."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created MinIO bucket: {self.bucket_name}")
        except Exception as e:
            logger.warning(f"Error checking/creating MinIO bucket: {e}")

    def build_audio_object_path(
        self,
        org_id: str,
        user_id: str,
        meeting_id: int | str,
        filename: str | None = None,
    ) -> str:
        """Builds a canonical multi-tenant namespaced MinIO path."""
        safe_name = sanitize_filename(filename)
        return f"{org_id}/{user_id}/{meeting_id}/{safe_name}"

    def upload_audio_file(
        self,
        file_data: BinaryIO,
        file_size: int,
        content_type: str,
        original_filename: str | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
        meeting_id: int | str | None = None,
        object_name: str | None = None,
    ) -> str:
        """
        Uploads an audio file and returns the object path in MinIO.
        Supports multi-tenant namespacing ({org_id}/{user_id}/{meeting_id}/{filename}).
        """
        if not object_name:
            if org_id and user_id and meeting_id is not None:
                object_name = self.build_audio_object_path(
                    org_id=org_id,
                    user_id=user_id,
                    meeting_id=meeting_id,
                    filename=original_filename,
                )
            else:
                ext = original_filename.split(".")[-1] if (original_filename and "." in original_filename) else "mp3"
                object_name = f"meetings/{uuid.uuid4()}.{ext}"

        try:
            self.client.put_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                data=file_data,
                length=file_size,
                content_type=content_type,
            )
            logger.info(f"Successfully uploaded {object_name} to MinIO")
            return object_name
        except S3Error as e:
            logger.error(f"Failed to upload file to MinIO: {e}")
            raise

    def get_presigned_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        """
        Generates a presigned URL valid for temporary frontend audio playback.
        """
        try:
            url = self.client.presigned_get_object(
                bucket_name=self.bucket_name,
                object_name=object_name,
                expires=timedelta(seconds=expires_seconds),
            )
            return url
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL for {object_name}: {e}")
            raise

    def get_audio_url(self, object_name: str, expires_seconds: int = 3600) -> str:
        """
        Backward-compatible alias for get_presigned_url.
        """
        return self.get_presigned_url(object_name, expires_seconds=expires_seconds)

    def get_audio_file_stream(self, object_name: str):
        """
        Retrieves the raw audio stream for background worker RAM transcription.
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response
        except S3Error as e:
            logger.error(f"Failed to get object stream for {object_name}: {e}")
            raise

    def delete_audio_file(self, object_name: str) -> None:
        """
        Deletes the audio file from MinIO bucket to free up storage space.
        """
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.info(f"Successfully deleted {object_name} from MinIO")
        except S3Error as e:
            logger.error(f"Failed to delete {object_name} from MinIO: {e}")


# Singleton instance to be used across the app
minio_service = MinioService()
