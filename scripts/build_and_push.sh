#!/usr/bin/env bash
# Builds the agent image via AWS CodeBuild and pushes to ECR.
# Used because no Docker daemon is available in the local dev env.
#
# Usage: scripts/build_and_push.sh [image_tag]
#   image_tag defaults to the short git SHA.
#
# Environment:
#   AWS_PROFILE      (default: cardiac-sense-staging-s3)
#   AWS_REGION       (default: eu-central-1)
#   PROJECT_PREFIX   (default: claude-aws-agent-staging)

set -euo pipefail

AWS_PROFILE="${AWS_PROFILE:-cardiac-sense-staging-s3}"
AWS_REGION="${AWS_REGION:-eu-central-1}"
PREFIX="${PROJECT_PREFIX:-claude-aws-agent-staging}"
TAG="${1:-$(git rev-parse --short=8 HEAD)}"

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

SOURCE_BUCKET="$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  s3api list-buckets --query "Buckets[?starts_with(Name, '${PREFIX}-codebuild-src-')].Name | [0]" \
  --output text)"

if [ -z "$SOURCE_BUCKET" ] || [ "$SOURCE_BUCKET" = "None" ]; then
  echo "ERROR: codebuild source bucket not found. Run 'terraform apply' in infra/envs/staging first." >&2
  exit 1
fi

PROJECT="${PREFIX}-image-build"

echo "==> Packaging source"
ZIP=$(mktemp -t agent-source-XXXXXX.zip)
git archive --format=zip --output="$ZIP" HEAD app ui prompts knowledge skills

echo "==> Uploading to s3://$SOURCE_BUCKET/source.zip"
aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  s3 cp "$ZIP" "s3://$SOURCE_BUCKET/source.zip"

echo "==> Starting CodeBuild project $PROJECT (tag=$TAG)"
BUILD_ID=$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  codebuild start-build --project-name "$PROJECT" \
  --environment-variables-override name=IMAGE_TAG,value="$TAG",type=PLAINTEXT \
  --query 'build.id' --output text)

echo "==> Build started: $BUILD_ID"
echo "==> Polling status…"

while :; do
  STATUS=$(aws --profile "$AWS_PROFILE" --region "$AWS_REGION" \
    codebuild batch-get-builds --ids "$BUILD_ID" \
    --query 'builds[0].buildStatus' --output text)
  case "$STATUS" in
    SUCCEEDED) echo "==> Build SUCCEEDED. Image tag: $TAG"; rm -f "$ZIP"; echo "$TAG"; exit 0 ;;
    FAILED|FAULT|TIMED_OUT|STOPPED) echo "==> Build $STATUS" >&2; rm -f "$ZIP"; exit 1 ;;
    IN_PROGRESS) sleep 10 ;;
    *) echo "==> Status: $STATUS"; sleep 10 ;;
  esac
done
