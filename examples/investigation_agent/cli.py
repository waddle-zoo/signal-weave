from __future__ import annotations

import argparse
import asyncio
import json
import os

from .agent import CatalogContextCollector, InvestigationAgent, OpenAICompatiblePlanner
from .context_tools import load_json_tools
from .delivery import SlackDeliveryAdapter, SlackRoute, SlackWebApi, StdoutDeliveryAdapter
from .mcp_gateway import McpSignalWeaveGateway


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an optional caller-owned multi-step SignalWeave investigation agent"
    )
    parser.add_argument("--card-id", required=True, help="Approved SignalWeave insight card id")
    parser.add_argument(
        "--signalweave-mcp-url",
        default=os.getenv("SIGNALWEAVE_MCP_URL", "http://127.0.0.1:8000/mcp"),
    )
    parser.add_argument("--signalweave-token", default=os.getenv("SIGNALWEAVE_API_TOKEN"))
    parser.add_argument(
        "--evidence-file",
        help="JSON file containing caller-owned evidence tools and ContextFacts",
    )
    parser.add_argument("--llm-base-url", default=os.getenv("OPENAI_BASE_URL"))
    parser.add_argument("--llm-api-key", default=os.getenv("OPENAI_API_KEY"))
    parser.add_argument("--llm-model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--slack-token", default=os.getenv("SLACK_BOT_TOKEN"))
    parser.add_argument("--slack-channel", help="Stable channel name to create or reuse")
    parser.add_argument(
        "--slack-member-id",
        action="append",
        default=[],
        help="Slack user id to invite; repeat for multiple users",
    )
    parser.add_argument(
        "--allow-channel-create",
        action="store_true",
        help="Permit the example agent to create a missing Slack channel",
    )
    parser.add_argument(
        "--allow-slack-invites",
        action="store_true",
        help="Permit the example agent to invite configured Slack user ids",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    gateway = McpSignalWeaveGateway(
        args.signalweave_mcp_url,
        bearer_token=args.signalweave_token,
    )

    collector = None
    if args.evidence_file:
        tools = load_json_tools(args.evidence_file)
        planner = None
        if args.llm_base_url and args.llm_api_key:
            planner = OpenAICompatiblePlanner(
                base_url=args.llm_base_url,
                api_key=args.llm_api_key,
                model=args.llm_model,
            )
        collector = CatalogContextCollector(tools, planner=planner)

    if args.slack_token:
        route = (
            SlackRoute(args.slack_channel, tuple(args.slack_member_id))
            if args.slack_channel
            else None
        )
        delivery = SlackDeliveryAdapter(
            SlackWebApi(args.slack_token),
            route=route,
            allow_channel_create=args.allow_channel_create,
            allow_invites=args.allow_slack_invites,
        )
    else:
        delivery = StdoutDeliveryAdapter()

    result = await InvestigationAgent(
        gateway,
        collector=collector,
        delivery=delivery,
        max_steps=args.max_steps,
    ).run(args.card_id)
    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0 if result.status in {"suppressed", "delivered", "ready_for_delivery"} else 2


def main() -> None:
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))


if __name__ == "__main__":
    main()
