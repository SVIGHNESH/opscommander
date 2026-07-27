variable "aws_region" {
  type        = string
  default     = "ap-south-1"
  description = "Region for all resources."
}

variable "aws_profile" {
  type        = string
  default     = null
  description = <<-EOT
    Named AWS profile for the provider. null uses the default credential chain.

    Needed when credentials come from a source the provider's SDK cannot read
    directly (e.g. an `aws login` session), bridged via a profile whose
    credential_process shells out to the CLI.
  EOT
}

variable "name_prefix" {
  type        = string
  default     = "opscommander"
  description = "Prefix for resource names."
}

variable "lambda_package" {
  type        = string
  default     = "../dist/lambda.zip"
  description = <<-EOT
    Deployment package for both functions, built by scripts/build_lambda.sh.

    Both the API and the worker run the same artefact and differ only in
    handler, so there is one zip and no chance of the two drifting apart.
  EOT
}

variable "lambda_runtime" {
  type        = string
  default     = "python3.13"
  description = "Must match the interpreter the package's wheels were built for."
}

variable "lambda_architecture" {
  type        = string
  default     = "arm64"
  description = <<-EOT
    arm64 (Graviton) is around 20% cheaper per GB-second than x86_64.

    Must match the wheels in the package: build with ARCH=arm64, which is the
    default in scripts/build_lambda.sh.
  EOT
}

variable "api_memory_mb" {
  type        = number
  default     = 512
  description = "The API function only verifies, persists, and enqueues."
}

variable "worker_memory_mb" {
  type        = number
  default     = 1024
  description = <<-EOT
    Memory for the pipeline function.

    On Lambda, CPU scales with memory, so this is also the latency dial - and
    since billing is GB-seconds, a larger size that finishes proportionally
    faster costs about the same.
  EOT
}

variable "worker_timeout_seconds" {
  type        = number
  default     = 300
  description = <<-EOT
    Ceiling for one full pipeline run, including the Bedrock call.

    The queue's visibility timeout is set from this; if it were lower, SQS
    would hand the same incident to a second worker while the first was still
    running it.
  EOT
}

variable "worker_max_concurrency" {
  type        = number
  default     = 4
  description = <<-EOT
    Ceiling on concurrent pipeline runs - the reserved-concurrency equivalent
    of OPSCOMMANDER_INGEST_MAX_WORKERS.

    This is what stops an alarm storm from fanning out into as many concurrent
    Bedrock calls as the account will allow. Excess work waits in the queue.
  EOT
}

variable "api_throttle_burst" {
  type        = number
  default     = 20
  description = "Burst cap on the public webhook route."
}

variable "api_throttle_rate" {
  type        = number
  default     = 10
  description = "Steady-state requests/second cap on the public webhook route."
}

variable "auto_approve_severity" {
  type        = string
  default     = "High"
  description = "Safe actions at or below this severity are auto-approved."
}

variable "ingest_suppress_seconds" {
  type        = number
  default     = 1800
  description = <<-EOT
    Ignore a re-firing alarm that already has an open incident younger than
    this. 0 disables suppression.

    This is the main cost control in the stack. An alarm oscillating around its
    threshold emits an ALARM transition every time it crosses, and without
    suppression each one opens a separate incident and pays for its own Bedrock
    call - so one underlying problem can bill as hundreds. It is also the
    correct behaviour on its own terms: a flapping alarm is one incident, not
    hundreds.

    Suppression is checked before the incident is persisted, so a suppressed
    alarm costs a DynamoDB scan and nothing else.
  EOT
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "log_retention_days" {
  type        = number
  default     = 30
  description = "Set explicitly so logs do not accumulate forever by default."
}

variable "bedrock_model_id" {
  type        = string
  default     = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
  description = <<-EOT
    Inference profile the Recommendation Agent invokes.

    ap-south-1 offers Anthropic models through inference profiles only, so this
    must be a profile id, not a bare foundation-model id. A "global." profile
    may route the request to any region; use an "apac." profile if inference
    has to stay in-region, noting those exist only for older models.
  EOT
}

variable "enable_remediation" {
  type        = bool
  default     = false
  description = <<-EOT
    Attach the remediation policy, letting approved actions actually execute.

    Defaults to false so a first deployment observes and recommends without
    being able to change anything. Turn it on once you have watched what the
    approval gate lets through.
  EOT
}

variable "remediation_target_arns" {
  type        = list(string)
  default     = []
  description = "Lambda/ECS resources the Remediation Agent may modify."
}

variable "autoscaling_group_arns" {
  type        = list(string)
  default     = []
  description = "ASGs the Remediation Agent may scale."
}

variable "tags" {
  type    = map(string)
  default = { Application = "opscommander" }
}
