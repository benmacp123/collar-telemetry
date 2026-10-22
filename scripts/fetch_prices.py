"""Fetch a dated snapshot of the AWS list prices the cost report uses.

Optional: the snapshot is committed (``data/prices/aws-eu-west-2.json``),
so ``make cloud-cost`` never needs the network. Reads AWS's public Price
List files (no account or credentials) for each service the stack uses,
keeps only the usage types the stack is billed for, and records each
price with its offer file and publication date.

Each price is the lowest tier with a non-zero rate: what a small workload
pays once any allowance written into the price list (SNS's first 1,000
emails, DynamoDB's first 25 GB) is used up. Those allowances, and the
free tier the price list does not hold (Lambda, SQS, CloudWatch Logs),
are recorded under ``free_tier``.
"""

import argparse
import json
from datetime import date
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices" / "aws-eu-west-2.json"
HOST = "https://pricing.us-east-1.amazonaws.com"
REGION = "eu-west-2"

# Name in the snapshot: (Price List service code, usage type).
WANTED = {
    "lambda_request": ("AWSLambda", "EUW2-Request"),
    "lambda_gb_second": ("AWSLambda", "EUW2-Lambda-GB-Second"),
    "sqs_fifo_request": ("AWSQueueService", "EUW2-Requests-FIFO-Tier1"),
    "dynamodb_write_request_unit": ("AmazonDynamoDB", "EUW2-WriteRequestUnits"),
    "dynamodb_read_request_unit": ("AmazonDynamoDB", "EUW2-ReadRequestUnits"),
    "dynamodb_storage_gb_month": ("AmazonDynamoDB", "EUW2-TimedStorage-ByteHrs"),
    "sns_request": ("AmazonSNS", "EUW2-Requests-Tier1"),
    "sns_email": ("AmazonSNS", "EUW2-DeliveryAttempts-SMTP"),
    "logs_ingested_gb": ("AmazonCloudWatch", "EUW2-DataProcessing-Bytes"),
    "logs_stored_gb_month": ("AmazonCloudWatch", "EUW2-TimedStorage-ByteHrs"),
}

# Allowances the Price List does not hold, from each service's pricing
# page. They apply per account per month across regions.
PAGE_FREE_TIER = {
    "lambda_request": {
        "free_per_month": 1_000_000,
        "source": "https://aws.amazon.com/lambda/pricing/",
    },
    "lambda_gb_second": {
        "free_per_month": 400_000,
        "source": "https://aws.amazon.com/lambda/pricing/",
    },
    "sqs_fifo_request": {
        "free_per_month": 1_000_000,
        "source": "https://aws.amazon.com/sqs/pricing/",
        "note": "shared by standard and FIFO requests",
    },
    "logs_ingested_gb": {
        "free_per_month": 5,
        "source": "https://aws.amazon.com/cloudwatch/pricing/",
        "note": "5 GB shared by ingestion, storage and Logs Insights scans",
    },
}


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``out``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT)
    return parser.parse_args()


def get_json(path: str) -> dict:
    """Fetch one Price List file.

    Args:
        path: Path on the Price List host.

    Returns:
        dict: The parsed file.
    """
    with urlopen(HOST + path, timeout=120) as response:
        return json.load(response)


def pick(offer: dict, usage_type: str) -> tuple[dict, int | None]:
    """The lowest non-zero tier of a usage type, and any free allowance
    written into the price list as a zero-priced tier.

    Args:
        offer: One service's regional offer file.
        usage_type: The usage type, such as ``EUW2-Request``.

    Returns:
        tuple[dict, int | None]: The price entry, and the free quantity
        per month, or None if the price list has no free tier for it.

    Raises:
        LookupError: If the usage type is missing or has no on-demand
            price.
    """
    skus = [
        sku
        for sku, product in offer["products"].items()
        if product["attributes"].get("usagetype") == usage_type
    ]
    if len(skus) != 1:
        raise LookupError(f"{usage_type}: {len(skus)} products")
    dimensions = [
        dimension
        for term in offer["terms"]["OnDemand"][skus[0]].values()
        for dimension in term["priceDimensions"].values()
    ]
    dimensions.sort(key=lambda d: float(d["beginRange"]))
    free = [d for d in dimensions if float(d["pricePerUnit"]["USD"]) == 0]
    paid = [d for d in dimensions if float(d["pricePerUnit"]["USD"]) > 0]
    if not paid:
        raise LookupError(f"{usage_type}: no paid tier")
    entry = {
        "sku": skus[0],
        "usage_type": usage_type,
        "unit": paid[0]["unit"],
        "usd": float(paid[0]["pricePerUnit"]["USD"]),
        "description": paid[0]["description"],
    }
    return entry, int(float(free[0]["endRange"])) if free else None


def main():
    """Fetch each service's eu-west-2 offer file and write the snapshot."""
    args = parse_args()
    services = get_json("/offers/v1.0/aws/index.json")["offers"]
    offers = {}
    for code in sorted({code for code, _ in WANTED.values()}):
        regions = get_json(services[code]["currentRegionIndexUrl"])["regions"]
        path = regions[REGION]["currentVersionUrl"]
        offers[code] = (path, get_json(path))
    prices, free_tier = {}, {}
    for name, (code, usage_type) in WANTED.items():
        path, offer = offers[code]
        entry, free = pick(offer, usage_type)
        prices[name] = {
            "service": code,
            **entry,
            "offer": HOST + path,
            "published": offer["publicationDate"],
        }
        if free is not None:
            free_tier[name] = {"free_per_month": free, "source": HOST + path}
    free_tier |= PAGE_FREE_TIER
    snapshot = {
        "region": REGION,
        "currency": "USD",
        "retrieved": date.today().isoformat(),
        "prices": prices,
        "free_tier": dict(sorted(free_tier.items())),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    for name, entry in prices.items():
        print(f"{name}: {entry['usd']} USD per {entry['unit']}")


if __name__ == "__main__":
    main()
