# Infrastructure

The serverless deployment (phase 3): Terraform in `terraform/`, the
deploy package built by `make lambda-zip`, and a local run of the same
handlers that needs no AWS account. Deployed to eu-west-2 on 2026-10-22,
run against every study, and destroyed the same day. Every run's stored
incidents matched the replay runner's exactly (`results/cloud/aws-*.json`).

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

The deploy proved what the local runs could not: the trigger settings
(batch sizes, the stream filter, `ReportBatchItemFailures`), the IAM
policies, the 60 s timeout on the heaviest slices (over 100 KB) and the
email subscription. No message reached either failure queue.

## Deploy, run and destroy

Every step needs AWS credentials (`AWS_PROFILE`) and costs a little money;
`terraform.tfvars` must hold `alert_email`.

1. `make tf-plan`, then `make tf-apply` (notifications off), which also
   saves the outputs to the git-ignored `build/terraform-outputs.json`.
   Confirm the subscription from the email SNS sends: until then SNS drops
   every alert without an error.
2. A smoke run, with resends, which the queue or the processor should
   drop:
   `make cloud-aws ARGS="--label smoke --study jackals --resend-every 50"`.
3. Optional, the email test: `make tf-apply NOTIFY=true`, then one
   vulture with `--expect-notify`, then `make tf-apply` to switch it off.
4. The full run: `make cloud-aws ARGS="--label full"` (about an hour,
   most of it the workstation publishing at about 33 messages a second).
   Rerunning a run and collar sends nothing new: the processor skips
   slices it has applied, and notified incidents keep `notified_at`.
5. `make tf-destroy`, then `make cloud-leftovers`. The tagging API lists
   deleted resources for a while after `destroy`, so confirm a hit with
   the service's own get call before treating it as real.
6. Within 15 days (CloudWatch's one-minute retention), `make cloud-usage`
   to save the metered usage, then `make cloud-cost` (offline).

Each `cloud-aws` run writes `results/cloud/aws-<label>.json` and exits
non-zero on any difference from the replay, dead letter or missing
notification. A message in the FIFO dead-letter queue stops its collar,
since later sequence numbers fail the processor's check, so the fix is to
rerun that collar.

## Latency

Wall-clock time from publishing a slice to storing the first write of
each incident, full run: jackals and elephants median 1.2-2.2 s, p95
3.7-6.1 s; vultures median 5.8-6.3 s, p95 18.7-20.1 s. Everything is
published up front, so these include time queued behind the rest of the
run (vultures' heavy slices, at a processor concurrency of 5). Stored to
notified: 2.9 s (two notifications).

## Cost

`make cloud-cost` prices the full run from metered usage, without an
account: CloudWatch's per-minute sums for the run's window
(`results/cloud/usage-aws.json`, fetched once by `make cloud-usage`) at
the committed list prices (`data/prices/aws-eu-west-2.json`, dated, from
AWS's public Price List). Results in `results/cloud/COST.md`:

- **As billed:** each line's quantity, with how it was found. Lambda time
  and calls, DynamoDB request units (including transactions' double
  writes), log bytes and empty receives are metered. SQS sends are
  counted from the run's own messages. Receives and deletes are not
  metered per call, so they are taken as one each per processor
  invocation (assumed).
- **Per animal-month:** divided by the animal-months the run covered,
  from each deployment's first arrival to its end of watch.
- **Live mode (provisional):** the replay hands the processor batches of
  up to ten slices; live, each collar's daily slice arrives alone. The
  projection gives a range: per-invocation costs (run time, Lambda's log
  lines) spread over slices (low), or charged in full to every slice
  (high).
- **Idle:** the queue trigger keeps long-polling an empty queue, and each
  empty receive is a billed request. Measured in the quiet minutes
  outside the runs.
- **Free tier:** list prices throughout, with how many animals the
  always-free allowances would cover. DynamoDB on-demand request units
  have none.

Cost Explorer, about 48 hours after the session, checks the total.

Results (list prices of 2026-10-22, USD, before free tier):

- **The full run cost $0.79**: 105,684 slices over 3,466 animal-months,
  so **$0.23 per 1,000 animal-months**. No processor errors; metered sends
  equal the messages published.
- **DynamoDB writes are 89% of it.** Each slice rewrites the collar's
  whole state item (median about 4 KB, at most 62 KB) inside a
  transaction, which bills every write twice: about 9 write units a
  slice, 99% of them on the state table. Smaller state, or a plain
  conditional write when a slice raises no incident, would be the place
  to save. Lambda time is 3%, SQS 3%.
- **Live mode, projected: $0.27-0.36 per 1,000 animal-months.** The
  replay averaged 9.8 slices per invocation (260 ms per invocation,
  27 ms per slice); live, each slice gets its own, which mostly adds
  Lambda time and log lines. DynamoDB writes still dominate.
- **Idle: $0.33 a month.** The queue trigger made a median 15 empty
  receives a minute in 36 quiet minutes, 657,000 requests a month. That
  is the live cost of 900 to 1,200 animals, so for a small
  project the fixed cost of an idle trigger outweighs the per-animal
  cost.
- **Free tier:** idle polling uses about two thirds of SQS's 1M free
  requests, and the rest covers about 3,700 animals; Lambda's allowances
  would cover over 30,000. DynamoDB request units have no free tier, so a
  100-collar project would pay about $0.02 a month, all of it DynamoDB.

## Local emulation image

The image's base defaults to the Docker Hub copy of the AWS Lambda Python
image (3.13): `public.ecr.aws` was unreachable from the build machine, and
Docker Hub has no 3.14 tag. That copy dates from January 2025. It is fine
for emulation. The deploy uses the zip above, so the stale base never
reaches AWS.
