#!/usr/bin/env python3
"""Test script for thinking feature."""
import requests
import json

# Test with thinking enabled
url = "http://localhost:8000/v1/messages"
headers = {
    "Content-Type": "application/json",
    "x-api-key": "test-key"  # Replace with your API key if needed
}

# Test 1: With thinking enabled
print("=== Test 1: With thinking enabled ===")
data = {
    "model": "claude-sonnet-4.5",
    "max_tokens": 2048,
    "thinking": {
        "type": "enabled",
        "budget_tokens": 1000
    },
    "messages": [
        {
            "role": "user",
            "content": "What is 25 * 47? Show your reasoning step by step."
        }
    ],
    "stream": True
}

try:
    response = requests.post(url, headers=headers, json=data, stream=True)
    print(f"Status: {response.status_code}")

    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                try:
                    event_data = json.loads(line_str[6:])
                    print(json.dumps(event_data, indent=2, ensure_ascii=False))
                except:
                    pass
except Exception as e:
    print(f"Error: {e}")

print("\n=== Test 2: Without thinking ===")
data["thinking"] = None

try:
    response = requests.post(url, headers=headers, json=data, stream=True)
    print(f"Status: {response.status_code}")

    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                try:
                    event_data = json.loads(line_str[6:])
                    if event_data.get("type") in ["content_block_start", "content_block_delta"]:
                        print(json.dumps(event_data, indent=2, ensure_ascii=False))
                except:
                    pass
except Exception as e:
    print(f"Error: {e}")
