# The deploy zip goes to S3 once and every function is created from it.
# Sent inline, each CreateFunction carries the whole 36 MB in one signed
# request, and Lambda refuses a request that arrives more than 5 minutes
# after signing: on a slow uplink, three uploads at once ran past that
# (2026-10-23). force_destroy so `destroy` empties and removes the bucket.
resource "aws_s3_bucket" "lambda" {
  bucket_prefix = "${var.name_prefix}-lambda-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "lambda" {
  bucket                  = aws_s3_bucket.lambda.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "lambda" {
  bucket      = aws_s3_bucket.lambda.id
  key         = "lambda.zip"
  source      = var.lambda_zip
  source_hash = filemd5(var.lambda_zip)
}
