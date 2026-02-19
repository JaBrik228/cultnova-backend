import boto3
import uuid
import mimetypes
from django.core.files.uploadedfile import UploadedFile
from django.conf import settings


class VKCloudStorage:
    def __init__(self):
        self.bucket = settings.VK_CLOUD_BUCKET_NAME

        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.VK_CLOUD_S3_ENDPOINT,
            aws_access_key_id=settings.VK_CLOUD_ACCESS_KEY,
            aws_secret_access_key=settings.VK_CLOUD_SECRET_KEY,
        )

    def upload_media(self, file, folder: str = "media") -> str:
        """
        file: Django UploadedFile (ImageField / FileField)
        folder: путь внутри bucket
        return: CDN URL
        """

        ext = file.name.split(".")[-1]
        filename = f"{uuid.uuid4()}.{ext}"
        key = f"{folder}/{filename}"

        content_type, _ = mimetypes.guess_type(file.name)

        extra_args = {
            "ACL": "public-read",
            "ContentType": content_type or "application/octet-stream",
        }

        self.s3.upload_fileobj(
            Fileobj=file,
            Bucket=self.bucket,
            Key=key,
            ExtraArgs=extra_args,
        )

        return f"https://{settings.VK_CLOUD_BUCKET_NAME}.{settings.VK_CLOUD_S3_DOMAIN}{key}"


def upload_media_to_vk_cloud(file_obj: UploadedFile, folder: str = "media") -> str:
    vk_cloud_storage = VKCloudStorage()
    return vk_cloud_storage.upload_media(file_obj, folder)
