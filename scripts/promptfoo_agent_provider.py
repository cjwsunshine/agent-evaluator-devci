#!/usr/bin/env python3
"""
Promptfoo provider for this platform.

Reads a prompt from stdin and calls the Agent configured by PROMPTFOO_AGENT_ID.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.services.agent_service import AgentService


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    agent_id_text = os.environ.get('PROMPTFOO_AGENT_ID')
    if not agent_id_text:
        print('')
        return 1

    try:
        agent_id = int(agent_id_text)
    except ValueError:
        print('')
        return 1

    app = create_app()
    with app.app_context():
        result = AgentService.call_agent(agent_id, prompt)

    if result.get('success'):
        output = result.get('data', '')
        print(str(output))
        return 0

    print(str(result.get('message') or result.get('error') or ''))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
