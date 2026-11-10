#!/usr/bin/env python3
"""Probe whether magpie's VLM can answer AgentProg's UI-TARS grounding prompt.

Sends the exact prompt AgentProg uses for the Volcengine Ark UI-TARS API
(``get_ui_tars_mobile_prompt_api``) to the local magpie gateway and prints the
raw response.  This is a compatibility probe, not a benchmark run.
"""

from __future__ import annotations

import base64
import io
import os
import sys

import requests
from PIL import Image

BASE_URL = os.environ.get("MAGPIE_BASE_URL", "http://127.0.0.1:3425/v1")
API_KEY = os.environ.get("MAGPIE_API_KEY", "magpie")
MODEL = os.environ.get("PROBE_MODEL", "auto/gpt-6.1-sol")


def prompt(language: str, instruction: str) -> str:
    return f'''
You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.
## Output Format
```
Thought: ...
Action: ...
```
## Action Space

click(point='<point>x1 y1</point>')
long_press(point='<point>x1 y1</point>')
type(content='') #If you want to submit your input, use "\\n" at the end of `content`.
scroll(point='<point>x1 y1</point>', direction='down or up or right or left')
open_app(app_name=\\'\')
drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')
press_home()
press_back()
finished(content='xxx') # Use escape characters \\', \\", and \\n in content part to ensure we can parse the content in normal python string format.


## Note
- Use {language} in `Thought` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `Thought` part.

## User Instruction
{instruction}
'''


def main() -> int:
    shot_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/agentprog_probe.png"
    target = sys.argv[2] if len(sys.argv) > 2 else "the Officework activity button"
    image = Image.open(shot_path).convert("RGB")
    resized = image.resize((round(image.width * 0.5), round(image.height * 0.5)))
    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    payload = {
        "model": MODEL,
        "temperature": 0.2,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt("Chinese", f"Click on {target}.")},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
    }
    resp = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json=payload,
        timeout=300,
    )
    print("status:", resp.status_code)
    if resp.status_code != 200:
        print(resp.text[:2000])
        return 1
    data = resp.json()
    print(data["choices"][0]["message"].get("content", ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
