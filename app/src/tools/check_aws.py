"""Health-check tool: verify the task role can reach AWS."""
from __future__ import annotations

from ..settings import get_client
from . import tool


@tool(
    name="check_aws_connection",
    description=(
        "Verify the agent's AWS task role is reachable. Returns the assumed identity "
        "(account, role ARN) and region. Call this when the user asks about connectivity, "
        "credentials, or which account/region the agent is running against."
    ),
    input_schema={"type": "object", "properties": {}, "required": []},
)
def check_aws_connection() -> str:
    sts = get_client("sts")
    me = sts.get_caller_identity()
    from ..settings import get_settings
    s = get_settings()
    return (
        f"OK\n"
        f"  account: {me['Account']}\n"
        f"  arn:     {me['Arn']}\n"
        f"  region:  {s.aws_region}\n"
        f"  model:   {s.bedrock_model_id}"
    )
