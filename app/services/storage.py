from pathlib import Path
from urllib.parse import quote

import boto3


class ProductImageStorage:
    def __init__(self, settings, project_root: Path):
        self.settings = settings
        self.project_root = project_root

    def _is_s3(self) -> bool:
        return self.settings.media_backend == "s3"

    def _media_dir(self) -> Path:
        media_dir = self.project_root / "media" / "products"
        media_dir.mkdir(parents=True, exist_ok=True)
        return media_dir

    def _s3_client(self):
        if not self.settings.aws_s3_bucket:
            raise ValueError("AWS_S3_BUCKET is required when MEDIA_BACKEND=s3")
        kwargs = {}
        if self.settings.aws_region:
            kwargs["region_name"] = self.settings.aws_region
        return boto3.client("s3", **kwargs)

    def _s3_public_url(self, key: str) -> str:
        if self.settings.aws_s3_public_base_url:
            return f"{self.settings.aws_s3_public_base_url}/{quote(key)}"

        bucket = self.settings.aws_s3_bucket
        region = self.settings.aws_region
        if region:
            return f"https://{bucket}.s3.{region}.amazonaws.com/{quote(key)}"
        return f"https://{bucket}.s3.amazonaws.com/{quote(key)}"

    def save_product_image(
        self,
        product_id: str,
        filename: str,
        image_bytes: bytes,
        content_type: str | None,
    ) -> str:
        if self._is_s3():
            key = f"products/{product_id}/{filename}"
            client = self._s3_client()
            put_kwargs = {
                "Bucket": self.settings.aws_s3_bucket,
                "Key": key,
                "Body": image_bytes,
            }
            if content_type:
                put_kwargs["ContentType"] = content_type
            client.put_object(**put_kwargs)
            return self._s3_public_url(key)

        product_dir = self._media_dir() / product_id
        product_dir.mkdir(parents=True, exist_ok=True)
        file_path = product_dir / filename
        file_path.write_bytes(image_bytes)
        return f"/media/products/{product_id}/{filename}"

    def delete_product_media(self, product_id: str) -> None:
        if self._is_s3():
            client = self._s3_client()
            bucket = self.settings.aws_s3_bucket
            prefix = f"products/{product_id}/"

            continuation = None
            while True:
                list_kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
                if continuation:
                    list_kwargs["ContinuationToken"] = continuation
                response = client.list_objects_v2(**list_kwargs)

                contents = response.get("Contents", [])
                if contents:
                    client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": [{"Key": obj["Key"]} for obj in contents], "Quiet": True},
                    )

                if not response.get("IsTruncated"):
                    break
                continuation = response.get("NextContinuationToken")
            return

        product_dir = self._media_dir() / product_id
        if product_dir.exists():
            for child in product_dir.iterdir():
                if child.is_file():
                    child.unlink()
            product_dir.rmdir()
