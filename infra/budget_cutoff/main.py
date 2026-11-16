"""Cloud Run function (2nd gen), triggered by the budget's Pub/Sub topic.

When the month's spend reaches the budget it removes `allUsers` from the demo service's invoker role,
so the public URL answers 403. Nothing is deleted: re-open with
`gcloud run services update <svc> --region <region> --allow-unauthenticated`.
"""
import os

import functions_framework
from cutoff import handle
from google.cloud import run_v2

PROJECT = os.environ["GCP_PROJECT"]
REGION = os.environ.get("REGION", "asia-northeast3")
SERVICE = os.environ.get("SERVICE", "shorts-studio-demo")


def close_service() -> None:
    client = run_v2.ServicesClient()
    name = f"projects/{PROJECT}/locations/{REGION}/services/{SERVICE}"
    policy = client.get_iam_policy(request={"resource": name})
    for binding in policy.bindings:
        if binding.role == "roles/run.invoker" and "allUsers" in binding.members:
            binding.members.remove("allUsers")
    client.set_iam_policy(request={"resource": name, "policy": policy})


@functions_framework.cloud_event
def budget_cutoff(event):
    handle(event.data, close_service)
