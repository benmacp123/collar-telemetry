# Infrastructure

The serverless deployment (phase 3): Terraform in `terraform/`, the
deploy package built by `make lambda-zip`, and a local run of the same
handlers that needs no AWS account. Deployed to eu-west-2 on 2026-10-22,
and again on 2026-10-23 after the state write cut and the live clock were
added; each time run against every study and destroyed the same day.
Every run's stored incidents matched the replay runner's exactly
(`results/cloud/aws-*.json`). The figures below are from the second
deploy, with the first's where the change matters.

## Pipeline

```text
publisher -> SQS FIFO -> processor Lambda -> DynamoDB (state, incidents)
             (group =                         |
              collar)                         stream -> notifier Lambda -> SNS email
                ^                                                          (potential_death only)
                |
EventBridge Scheduler -> clock Lambda (live mode only; deployed disabled)
```

- **Messages** (`src/cloud/messages.py`): one collar's slice of simulated
  time (its arrivals in a day, plus "run the clock to the end of the
  day"), with the run, a sequence number, the taxon, the upload plan and
  the boundary name. Messages carry everything the processor needs, so
  no configuration table is required.
- **Idempotency:** each state item records the last sequence number
  applied, and every state write is conditional on it, so a redelivered
  message is skipped and a missing one stops its collar instead of being
  stepped over. A message that changes incidents writes state and
  incidents in one `TransactWriteItems`; the rest (94% in the full run)
  use a plain conditional `PutItem`, since a transaction bills every
  write twice. The state is stored zlib-compressed (about a third of its
  JSON size), as writes are billed per started kilobyte.
- **Live clock** (`src/cloud/clock.py`): replay slices carry their own
  "run the clock to" time, but a live collar that falls silent sends
  nothing, so nothing would raise its gap alert. An EventBridge Scheduler
  rule (`clock_rate`, default hourly; `clock_enabled`, default false)
  invokes the clock handler with the scheduled time; it lists the live
  run's collars from the state table and sends each a tick (a message
  with no sequence number) in the collar's own message group. The core
  is split-invariant (running the clock to T1 then T2 equals running it
  to T2), so a tick that changes no incident is not saved at all, and
  one that does is saved under the stored sequence number. Tests replace
  a silent collar's clock-only slices with ticks through the queue and
  get the replay's incidents exactly; on AWS, one invocation sent all 22
  jackal collars a tick that drained through the processor in 44 s with
  no dead letter (`results/cloud/aws-clock.json`). Cost is an estimate,
  not metered (the schedule stayed disabled): hourly ticks add roughly
  $0.4-2.6 per 1,000 animal-months (SQS FIFO requests, Lambda
  invocations and one state read per tick; writes only when an incident
  changes), two to twenty times the rest of live mode. A slower rate
  costs proportionally less and delays a gap alert by up to one interval
  on top of its 36 h or longer allowance.
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
runner's and each `potential_death` incident sent exactly one notification.

## Deploy package

`make lambda-zip` builds `build/lambda.zip` (git-ignored, about 37 MB)
inside the pinned `python:3.14-slim` image: the `lambda` dependency
group, exported from `uv.lock` with hashes, as manylinux wheels for Lambda's `python3.14` runtime on x86_64 (Amazon
Linux 2023), plus the core, `src/cloud` and the boundaries. The build is
reproducible (same inputs, same bytes) and ends by importing every
handler from the unpacked zip alone. A zip rather than a container image
means no ECR repository and no image push. The local image below is for
emulation only.

## Terraform

`terraform/` holds the stack above in eu-west-2, every resource tagged
`Project = collar-telemetry`:

- `package.tf`: a private S3 bucket holding the deploy zip, from which
  every function is created. Uploading it inline sends 36 MB per function
  in one signed request, which Lambda refuses if it takes over 5 minutes
  to arrive; on a slow uplink with three functions it did.
- `queue.tf`: the FIFO slices queue (visibility six times the processor
  timeout, five receives, then a FIFO dead-letter queue) and a queue for
  stream batches the notifier gives up on.
- `tables.tf`: on-demand state and incidents tables, with a
  `NEW_AND_OLD_IMAGES` stream on incidents.
- `functions.tf`: both Lambdas from the one zip, their log groups (7-day
  retention, so `destroy` removes them) and the two triggers, both with
  `ReportBatchItemFailures`. The queue trigger is capped at
  `processor_concurrency` instances. The stream trigger passes only
  `potential_death` items.
- `clock.tf`: the clock Lambda, its role (scan state, send to the
  queue), the scheduler's role (invoke the clock only) and the schedule,
  disabled unless `clock_enabled = true`. Schedules take no tags, so
  `cloud-leftovers` checks for it by name.
- `iam.tf`: one role per handler, allowed only the calls its code makes.
- `alerts.tf`: the SNS topic, an email subscription filtered to
  `potential_death`, and an account-wide AWS Budgets alarm (default $5).

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

The deploys proved what the local runs could not: the trigger settings
(batch sizes, the stream filter, `ReportBatchItemFailures`), the IAM
policies (the clock's included), the 60 s timeout on the heaviest slices
(over 100 KB) and the email subscription. No message reached either
failure queue. The second deploy's first `apply` failed: three functions
uploading the 36 MB zip inline over a slow uplink, one arriving after
the 5-minute signature window; `package.tf` (the zip via S3) fixed it.

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
5. The clock test: `make cloud-clock` invokes the clock handler once for
   `jackals-satellite_daily`, with a time before every collar's clock,
   and checks each collar's tick drains through the processor with no
   dead letter (`results/cloud/aws-clock.json`). No stored incident
   changes.
6. `make tf-destroy`, then `make cloud-leftovers`. The tagging API lists
   deleted resources for a while after `destroy`, so confirm a hit with
   the service's own get call before treating it as real.
7. Within 15 days (CloudWatch's one-minute retention), `make cloud-usage`
   to save the metered usage, then `make cloud-cost` (offline).

Each `cloud-aws` run writes `results/cloud/aws-<label>.json` and exits
non-zero on any difference from the replay, dead letter or missing
notification. A message in the FIFO dead-letter queue stops its collar,
since later sequence numbers fail the processor's check, so the fix is to
rerun that collar.

## Latency

Wall-clock time from publishing a slice to storing the first write of
each incident, full run: jackals and elephants median 0.9-1.5 s, p95
2.7-4.7 s; vultures median 1.3-4.2 s, p95 5.4-14.9 s (first deploy:
5.8-6.3 s and 18.7-20.1 s; the smaller state writes are the likely
reason). Everything is published up front, so these include time queued
behind the rest of the run (vultures' heavy slices, at a processor
concurrency of 5). The jackal figures are the smoke run's: the full run
reuses its run ID, so the processor skipped those slices as already
applied. Stored to notified: median 0.3 s, p95 2.6 s (three
notifications).

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

- **The full run cost $0.23** (first deploy: $0.82): 105,684 slices over
  3,466 animal-months, so **$0.07 per 1,000 animal-months** ($0.24). No
  processor errors; metered sends equal the messages published.
- **The state write cut worked as modelled.** State table writes fell
  from 972,912 to 203,847 units (21%), about 2 write units a slice
  instead of 9: most slices (94%) now use a plain conditional put rather
  than a transaction, and the state is stored compressed. The offline
  model in `make cloud-sizing` predicted 20.5%; it reads about 15% high
  on both layouts (cause unknown), so it is a cross-check, not the
  figure. Reads fell too (173,968 to 106,953 units), as smaller items
  need fewer 4 KB read units.
- **DynamoDB writes are still the largest line, 69% of the run**; Lambda
  is 11%, SQS 9%, reads 7%, logs 5%.
- **Live mode, projected: $0.11-0.20 per 1,000 animal-months** (first
  deploy: $0.28-0.37). The replay averaged 9.8 slices per invocation
  (255 ms per invocation, 26 ms per slice); live, each slice gets its
  own, which mostly adds Lambda time and log lines. The live clock, if
  enabled hourly, would add an estimated $0.4-2.6 (see Live clock).
- **Idle: $0.33 a month.** The queue trigger made a median 15 empty
  receives a minute in 13 quiet minutes, 657,000 requests a month, the
  same as the first deploy (36 quiet minutes). Minutes before the
  trigger existed (the failed first `apply` left the queue up for 18
  minutes without it) are excluded: nothing polled, so they read zero.
  That is the live cost of roughly 1,700 to 2,900 animals, so for a
  small project the fixed cost of an idle trigger outweighs the
  per-animal cost.
- **Free tier:** idle polling uses about two thirds of SQS's 1M free
  requests, and the rest covers about 3,700 animals; Lambda's allowances
  would cover far more. DynamoDB request units have no free tier, so a
  100-collar project would pay about half a cent a month for them.

## Local emulation image

The image's base defaults to the Docker Hub copy of the AWS Lambda Python
image (3.13): `public.ecr.aws` was unreachable from the build machine, and
Docker Hub has no 3.14 tag. That copy dates from January 2025. It is fine
for emulation. The deploy uses the zip above, so the stale base never
reaches AWS.
