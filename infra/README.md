# Infrastructure

The serverless deployment (phase 3): Terraform in `terraform/`, the
deploy package built by `make lambda-zip`, and a local run of the same
handlers that needs no AWS account. Nothing here has been applied to AWS
yet.

## Pipeline

```text
publisher -> SQS FIFO -> processor Lambda -> DynamoDB (state, incidents)
             (group =                         |
              collar)                         stream -> notifier Lambda -> SNS email
                                                                           (likely_death only)
```

- **Messages** (`src/cloud/messages.py`): one collar's slice of simulated
  time (its arrivals in a day, plus "run the clock to the end of the
  day"), with the run, a sequence number, the taxon, the upload plan and
  the boundary name. Messages carry everything the processor needs, so
  no configuration table is required.
- **Idempotency:** each state item records the last sequence number
  applied. The processor writes state and changed incidents in one
  `TransactWriteItems`, conditional on that number, so a redelivered
  message is skipped and a missing one stops its collar instead of being
  stepped over.
- **Outbox:** the notifier reads the incidents table's stream, publishes,
  then marks the incident `notified_at`. A crash before publishing retries
  the send; a crash after publishing and before marking sends a
  duplicate. Notifications go out at least once and are never lost.
  `NOTIFY_ENABLED=true` turns it on, so bulk replays can run silent.

## Local runs

- `lambda/Dockerfile`: one image for both handlers, holding the
  detection core, `src/cloud` and the bundled boundaries.
- `local/compose.yaml`: `motoserver/moto` (SQS, DynamoDB with Streams,
  SNS) plus each handler under the Lambda runtime interface emulator. moto
  does not run the queue and stream triggers, so `src/cloud/local.py`
  polls them from the host and calls the handlers. Batch size, retries
  and dead-lettering are therefore only proven by a real deploy.

```sh
make cloud-local   # build the image, run jackals + 1 vulture, tear down
make cloud-moto    # every study, in-process moto, no Docker
```

Both stop with an error unless every stored incident equals the replay
runner's and each `likely_death` incident sent exactly one notification.

## Deploy package

`make lambda-zip` builds `build/lambda.zip` (git-ignored, about 37 MB)
inside the pinned `python:3.14-slim` image: `requirements-lambda.txt` as
manylinux wheels for Lambda's `python3.14` runtime on x86_64 (Amazon
Linux 2023), plus the core, `src/cloud` and the boundaries. The build is
reproducible (same inputs, same bytes) and ends by importing both
handlers from the unpacked zip alone. A zip rather than a container image
means no ECR repository and no image push. The local image below is for
emulation only.

## Terraform

`terraform/` holds the stack above in eu-west-2, every resource tagged
`Project = collar-telemetry`:

- `queue.tf`: the FIFO slices queue (visibility six times the processor
  timeout, five receives, then a FIFO dead-letter queue) and a queue for
  stream batches the notifier gives up on.
- `tables.tf`: on-demand state and incidents tables, with a
  `NEW_AND_OLD_IMAGES` stream on incidents.
- `functions.tf`: both Lambdas from the one zip, their log groups (7-day
  retention, so `destroy` removes them) and the two triggers, both with
  `ReportBatchItemFailures`. The queue trigger is capped at
  `processor_concurrency` instances. The stream trigger passes only
  `likely_death` items.
- `iam.tf`: one role per handler, allowed only the calls its code makes.
- `alerts.tf`: the SNS topic, an email subscription filtered to
  `likely_death`, and an account-wide AWS Budgets alarm (default $5).

State is local and git-ignored, as are `terraform.tfvars` and plan files.
Copy `terraform.tfvars.example` to `terraform.tfvars` and set
`alert_email`. `notify_enabled` defaults to false, so bulk replays send no
email. The provider lock file is committed.

Terraform runs in the pinned `hashicorp/terraform` image, so nothing is
installed on the host:

```sh
make tf-fmt     # format
make tf-check   # fmt -check, init -backend=false, validate (CI runs the same)
make tf-plan    # builds the zip, then plans against your account (credentials in ~/.aws)
```

`tests/cloud/test_terraform.py` checks what `validate` cannot. Resource
names must match the local run's, the runtime must match the zip's
wheels, each handler setting must name a real function, and the
environment variables must be the ones the handlers read.

Not yet proven: the trigger settings (batch sizes, retries,
dead-lettering, the stream filter), the IAM policies and the email
subscription. Session 4's deploy is the first real test of each.

## Local emulation image

The image's base defaults to the Docker Hub copy of the AWS Lambda Python
image (3.13): `public.ecr.aws` was unreachable from the build machine, and
Docker Hub has no 3.14 tag. That copy dates from January 2025. It is fine
for emulation. The deploy uses the zip above, so the stale base never
reaches AWS.
