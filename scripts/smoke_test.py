import requests
import json
import sys

# Configuration
NODE_URL = "http://localhost:3001"
BRIDGE_URL = "http://localhost:9379"
MODEL_ID = "gemma4-e4b"

# 2x2 opaque white PNG
TINY_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAASSURBVChTY/z//z8DDAA5EAMA6mQD/0mFmBwAAAAASUVORK5CYII="

def print_result(name, success, message=""):
    status = "[PASS]" if success else "[FAIL]"
    print(f"{status} {name}")
    if message:
        print(f"       {message}")

def test_node_health():
    """Checks if the Node.js proxy is up and reports the bridge as online."""
    try:
        url = f"{NODE_URL}/api/backend/status"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            try:
                data = resp.json()
                if data.get("online"):
                    print_result("Node.js Heartbeat", True)
                    return True
                else:
                    print_result("Node.js Heartbeat", False, "Node reports bridge is offline")
            except json.JSONDecodeError:
                print_result("Node.js Heartbeat", False, "Invalid JSON from health check")
        else:
            print_result("Node.js Heartbeat", False, f"HTTP {resp.status_code}")
    except Exception as e:
        print_result("Node.js Heartbeat", False, str(e))
    return False

def test_bridge_models():
    """Checks if the Python Bridge is reachable and lists models."""
    try:
        url = f"{BRIDGE_URL}/v1/models"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            try:
                models = resp.json().get("data", [])
                model_ids = [m.get("id") for m in models]
                print_result("Python Bridge model list", True, f"Available: {', '.join(model_ids)}")
                return True
            except json.JSONDecodeError:
                print_result("Python Bridge model list", False, "Invalid JSON from bridge")
        else:
            print_result("Python Bridge model list", False, f"HTTP {resp.status_code}")
    except Exception as e:
        print_result("Python Bridge model list", False, str(e))
    return False

def test_text_roundtrip():
    """Tests a standard text chat request through the Node.js proxy."""
    try:
        # Primary endpoint is /api/chat as exported by server.js
        url = f"{NODE_URL}/api/chat"
        payload = {
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": "Ping"}],
            "stream": False
        }
        
        resp = requests.post(url, json=payload, timeout=30)
        
        # Fallback to /v1/chat/completions if needed, though /api/chat is preferred
        if resp.status_code == 404:
            url = f"{NODE_URL}/v1/chat/completions"
            resp = requests.post(url, json=payload, timeout=30)
            
        if resp.ok:
            try:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    print_result("Text Roundtrip", True, f"Response: {content[:50]}...")
                    return True
                else:
                    print_result("Text Roundtrip", False, "Empty response content")
            except json.JSONDecodeError:
                print_result("Text Roundtrip", False, "Failed to decode JSON response")
        else:
            print_result("Text Roundtrip", False, f"HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Text Roundtrip", False, str(e))
    return False

def test_vision_roundtrip():
    """Tests a vision chat request through the Node.js proxy."""
    try:
        url = f"{NODE_URL}/api/chat"
        payload = {
            "model": MODEL_ID,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is in this image?"},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG_B64}"}}
                    ]
                }
            ],
            "stream": False
        }
        
        resp = requests.post(url, json=payload, timeout=30)
        
        if resp.status_code == 404:
            url = f"{NODE_URL}/v1/chat/completions"
            resp = requests.post(url, json=payload, timeout=30)

        if resp.ok:
            try:
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    print_result("Vision Roundtrip", True, f"Response: {content[:50]}...")
                    return True
                else:
                    print_result("Vision Roundtrip", False, "Empty response content")
            except json.JSONDecodeError:
                print_result("Vision Roundtrip", False, "Failed to decode JSON response")
        else:
            print_result("Vision Roundtrip", False, f"HTTP {resp.status_code}: {resp.text}")
    except Exception as e:
        print_result("Vision Roundtrip", False, str(e))
    return False

def main():
    print("--- Gemma 4 Connectivity Smoke Test ---")
    
    # Infrastructure checks
    node_ok = test_node_health()
    bridge_ok = test_bridge_models()
    
    all_passed = node_ok and bridge_ok
    
    # Functional checks (dependency: node_ok must be True)
    if node_ok:
        t1 = test_text_roundtrip()
        t2 = test_vision_roundtrip()
        all_passed = all_passed and t1 and t2
    else:
        print("\n[SKIP] Functional tests skipped because Node.js health check failed.")
        all_passed = False

    print("----------------------------------------")
    if all_passed:
        print("RESULT: All connectivity tests PASSED.")
        sys.exit(0)
    else:
        print("RESULT: One or more connectivity tests FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    main()
