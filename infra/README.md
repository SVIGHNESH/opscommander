# OpsCommander infrastructure

Provisions the whole running system in **ap-south-1 (Mumbai)**:

```
CloudWatch Alarm ─▶ SNS ─▶ API Gateway ─▶ api Lambda ─▶ SQS ─▶ worker Lambda
                                              │                     │
                                       (verify, persist,      (the 7 agents)
                                        enqueue, 200)               │
                                                          DynamoDB + S3 + SNS
```

## What is here

| File | Contents |
|---|---|
| `main.tf` | Ingest + notification SNS topics, HTTPS subscription, delivery DLQ, example alarm |
| `compute.tf` | API Gateway, both Lambda functions, the incident queue and its DLQ, log groups |
| `iam.tf` | Single execution role; remediation permissions kept in a separate, opt-in policy |
| `storage.tf` | DynamoDB incident table, S3 report bucket, generated secrets |
| `variables.tf` / `outputs.tf` | Inputs and wiring values |

Unlike the earlier ECS sketch, **no domain and no ACM certificate are needed**.
SNS will only confirm an HTTPS subscription to an endpoint with a publicly trusted certificate, and API Gateway's own hostname already has one.

## Why two functions

Lambda freezes the execution environment the moment a handler returns.
A pipeline started on a background thread inside the request that answers SNS would be suspended mid-Bedrock-call and either resumed much later inside an unrelated invocation or discarded when the environment is reclaimed - with nothing raised either way.

So the API function does only the bounded work (verify the signature, check the topic allowlist, persist, enqueue) and answers in milliseconds, which also keeps it inside the ~15 seconds SNS allows before it retries.
The worker function exists solely to run the seven agents, and gets the long timeout.

`OPSCOMMANDER_INGEST_QUEUE_URL` is what selects this behaviour in the application; unset, it falls back to the in-process thread pool that suits a long-lived server.

## Prerequisites

1. **Submit the Anthropic use case details form, once per account.**
   Serverless models no longer need to be enabled per-region, and the Model access page has been retired - but Anthropic models still gate first-time use on this form. Until it is submitted every invocation fails with `Model use case details have not been submitted for this account`.

   Bedrock console → **Model catalog** → Claude Haiku 4.5 → *Open in playground*, which prompts for the form. Allow ~15 minutes for it to take effect.

   There is also an API (`aws bedrock put-use-case-for-model-access --form-data <blob>`, readable back with `get-use-case-for-model-access`), but `--form-data` is an opaque blob with no published schema, so the console is the practical route for a first submission.
2. **Authenticate.** Terraform's AWS provider cannot read an `aws login` session from `~/.aws/config`. Either export static credentials, or bridge the session:
   ```bash
   eval "$(aws configure export-credentials --format env)"
   ```

## Deploying

```bash
./scripts/build_lambda.sh          # -> dist/lambda.zip (arm64 / python3.13)

cd infra
terraform init
terraform apply
```

The package must be built first: both functions read `dist/lambda.zip`, and `terraform plan` fails on the missing file rather than deploying something stale.
Rebuild and re-apply to ship code changes - `source_code_hash` picks them up.

Every value the application needs is wired into the functions' environment by `compute.tf`, so there is nothing to copy by hand after an apply.

## Only the webhook is public

`compute.tf` routes exactly one path, `POST /webhook/sns`. There is deliberately no `$default` route, because:

- `GET /incidents` and `GET /report/{id}` return root causes, sampled log lines, metrics, and infrastructure health.
- `POST /approve` executes infrastructure changes.

To reach those, run the API or the Streamlit dashboard against the same DynamoDB table from inside your network.
`OPSCOMMANDER_APPROVAL_TOKEN` is generated and injected anyway, as a backstop rather than a substitute for not routing the endpoint.

## Verifying

```bash
# Force an alarm and watch an incident appear.
aws cloudwatch set-alarm-state \
  --alarm-name opscommander-orders-api-errors \
  --state-value ALARM \
  --state-reason "smoke test" \
  --region ap-south-1

aws logs tail "$(terraform output -raw worker_log_group)" --follow --region ap-south-1
```

If nothing arrives, check in this order:

1. `aws sns list-subscriptions-by-topic --topic-arn <ingest_topic_arn>` - confirmed, or still `PendingConfirmation`?
2. The API function's log group - a rejected message always logs why (signature, topic allowlist, staleness).
3. `incident_queue_url` depth - if messages sit there, the worker is not being triggered; check the event source mapping and the queue permissions on the role.
4. `incident_dlq_url` - pipelines that failed every retry.
5. `ingest_dlq_url` - SNS deliveries that never reached API Gateway at all.

## Remediation is off by default

`enable_remediation = false` means approved actions cannot actually execute: the role has no permission to change anything.
Run it that way first and watch what the approval gate lets through.
Turn it on, with an explicit `remediation_target_arns`, once you trust the classifications.

## Cost

Everything here is serverless and scales to zero; with no alarms firing the standing cost is essentially the DynamoDB table, the S3 objects, and log retention.
The per-incident cost is dominated by the Bedrock call, which is why `bedrock_model_id` defaults to Haiku 4.5, and `worker_max_concurrency` bounds how many of those can run at once during a storm.
