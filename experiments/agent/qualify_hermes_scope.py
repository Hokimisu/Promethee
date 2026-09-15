"""Construct real Hermes without calling inference; never validates model access.

Run with the installed Hermes Python. The new output folder is a technical
profile excluded from personal memory. No existing profile is imported.
"""

import argparse
import json
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--mcp-python", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--turn-id", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    profile = output / "profile"
    profile.mkdir()
    (profile / "vault").mkdir()
    config = {
        "tools": {"tool_search": {"enabled": "off"}},
        "mcp_servers": {
            "promethee": {
                "command": str(args.mcp_python.resolve()),
                "args": [
                    "-m",
                    "promethee.mcp_server",
                    "--data-dir",
                    str(args.data_dir.resolve()),
                    "--turn-id",
                    args.turn_id,
                ],
                "timeout": 10,
                "tools": {
                    "include": [
                        "read_world",
                        "list_capabilities",
                        "submit_action",
                        "read_execution",
                        "cancel_action",
                    ],
                    "resources": False,
                    "prompts": False,
                },
            }
        },
    }
    (profile / "config.yaml").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (output / "purpose.json").write_text(
        json.dumps({"purpose": "developer qualification; exclude from personal memory"})
    )
    hermes_root = args.hermes_root.resolve()
    os.environ["HERMES_HOME"] = str(profile)
    os.chdir(profile)
    sys.path[:0] = [str(hermes_root), str(root / "src/promethee")]
    from hermes_adapter import create_agent
    from tools.mcp_tool import shutdown_mcp_servers

    try:
        agent = create_agent(
            model="gpt-6-astra",
            api_key="diagnostic-placeholder",
            base_url="https://api.openai.com/v1",
            api_mode="chat_completions",
            session_id="promethee-scope-qualification",
        )
        report = {
            "tools": sorted(agent.valid_tool_names),
            "inference_called": False,
            "provider_access_validated": False,
            "context_files_disabled": agent.skip_context_files,
            "fallback_chain_empty": not agent._fallback_chain,
        }
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        shutdown_mcp_servers()


if __name__ == "__main__":
    main()
