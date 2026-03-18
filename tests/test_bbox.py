import sys, io
import pytest
sys.path.insert(0, "/app")

@pytest.mark.skip(reason="requires real Cloudflare R2 credentials — run manually")
def test_bbox():
    import boto3
    from botocore.config import Config
    from config import settings
    from PIL import Image

    client = boto3.client(
        "s3",
        endpoint_url=settings.cloudflare_r2_endpoint,
        aws_access_key_id=settings.cloudflare_r2_access_key,
        aws_secret_access_key=settings.cloudflare_r2_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    prefix = "wardrobe/acf0100d-ca11-4fce-815e-c516af11e710/"
    objects = client.list_objects_v2(
        Bucket=settings.cloudflare_r2_bucket, Prefix=prefix
    ).get("Contents", [])

    if not objects:
        print("FAIL: нет кропов в R2")
        return False

    sizes = []
    for obj in objects[:10]:
        data = client.get_object(
            Bucket=settings.cloudflare_r2_bucket, Key=obj["Key"]
        )["Body"].read()
        img = Image.open(io.BytesIO(data))
        sizes.append(img.size)
        print(f"  {obj['Key'].split('/')[-1][:20]}: {img.size}")

    unique_sizes = len(set(sizes))
    if unique_sizes < 2:
        print(f"FAIL: все кропы одного размера {sizes[0]} — bbox не работает")
        return False

    oversized = [s for s in sizes if s[0] > 1200 or s[1] > 1200]
    if oversized:
        print(f"FAIL: {len(oversized)} кропов слишком большие: {oversized}")
        return False

    print(f"PASS: {len(objects)} кропов, {unique_sizes} уникальных размеров")
    return True

if __name__ == "__main__":
    result = test_bbox()
    sys.exit(0 if result else 1)
