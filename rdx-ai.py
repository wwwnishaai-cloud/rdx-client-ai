#!/usr/bin/env python3
"""
RDX AI Terminal Agent
Usage: python rdx-ai.py
Install deps: pip install httpx
"""
import asyncio
import sys
import os
import json
import uuid
import webbrowser
import time

try:
    import httpx
except ImportError:
    print("[ERROR] httpx not installed. Run: pip install httpx")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".rdx-ai")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
MAIN_SERVER = "https://rdxcommunity.qzz.io"
AI_SERVER = "https://rdxcommunity.qzz.io/rdx/api/ai"

# ── Colors ──────────────────────────────────────────────
class C:
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'

# ── UI ──────────────────────────────────────────────────
def banner():
    print(f"""
{C.PURPLE}{C.BOLD}╔══════════════════════════════════════════════════════════╗
║              RDX CLIENT AI v2.0                           ║
║    {C.DIM}Type 'exit' to quit, '/help' for commands{C.RESET}{C.PURPLE}{C.BOLD}             ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
""")

def setup_banner():
    print(f"""
{C.CYAN}{C.BOLD}╔══════════════════════════════════════════════════════════╗
║              RDX CLIENT AI v2.0 — Setup                  ║
╚══════════════════════════════════════════════════════════╝{C.RESET}
""")

def ok(msg, **kwargs): print(f"{C.GREEN}[OK]{C.RESET} {msg}", **kwargs)
def err(msg, **kwargs): print(f"{C.RED}[ERROR]{C.RESET} {msg}", **kwargs)
def info(msg, **kwargs): print(f"{C.CYAN}[INFO]{C.RESET} {msg}", **kwargs)
def ask(msg): return input(f"{C.YELLOW}[?]{C.RESET} {msg}").strip()

# ── Config ──────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# ── Auth Flow ───────────────────────────────────────────
async def do_auth():
    temp_token = uuid.uuid4().hex

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{MAIN_SERVER}/rdx/api/terminal/register",
            json={"temp_token": temp_token})
        data = resp.json()
        auth_url = data.get("auth_url", f"{MAIN_SERVER}/terminal-auth?token={temp_token}")

    info("Opening browser for authentication...")
    print(f"  {C.DIM}{auth_url}{C.RESET}\n")
    webbrowser.open(auth_url)

    info("Waiting for authentication", end="")
    sys.stdout.flush()

    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(300):
            await asyncio.sleep(2)
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/terminal/status",
                    params={"token": temp_token})
                data = resp.json()
            except Exception:
                print(".", end="", flush=True)
                continue

            if data.get("linked"):
                ok(f"Authenticated as: {C.BOLD}{data['username']}{C.RESET}")
                return {
                    "jwt_token": data["jwt_token"],
                    "user_id": data["user_id"],
                    "username": data["username"]
                }
            if data.get("expired"):
                err("Token expired. Try again.")
                return None
            print(".", end="", flush=True)

    err("Timeout. Try again.")
    return None

# ── API Key Setup ───────────────────────────────────────
async def do_api_key():
    print(f"\n{C.CYAN}[API KEY]{C.RESET} Get your free API key at: {C.BOLD}https://opencode.ai{C.RESET}")
    key = ask("Enter your API key: ")
    if not key:
        info("Skipped. Using default key (limited).")
        return None
    ok("API key saved!")
    return key

# ── Model Selection ─────────────────────────────────────
def do_model():
    print(f"\n{C.CYAN}[MODEL]{C.RESET} Select a model:")
    print(f"  {C.BOLD}1{C.RESET}. llama-3.3-70b-versatile (default, fast)")
    print(f"  {C.BOLD}2{C.RESET}. llama-3.1-8b-instant (ultra fast)")
    print(f"  {C.BOLD}3{C.RESET}. mixtral-8x7b-32768 (long context)")
    print(f"  {C.BOLD}4{C.RESET}. gemma2-9b-it (lightweight)")
    choice = ask("> ")
    models = {"1": "llama-3.3-70b-versatile", "2": "llama-3.1-8b-instant",
              "3": "mixtral-8x7b-32768", "4": "gemma2-9b-it"}
    model = models.get(choice, "llama-3.3-70b-versatile")
    ok(f"Model set to: {C.BOLD}{model}{C.RESET}")
    return model

# ── Chat ────────────────────────────────────────────────
async def chat_loop(config):
    session_token = None

    while True:
        try:
            user_input = input(f"\n{C.GREEN}[You]{C.RESET} > ").strip()
            if not user_input:
                continue
            if user_input.lower() == 'exit':
                print(f"{C.DIM}Goodbye! Session saved.{C.RESET}")
                break
            if user_input.startswith('/'):
                await handle_cmd(user_input, config)
                continue

            headers = {"Content-Type": "application/json"}
            if config.get("jwt_token"):
                headers["Authorization"] = f"Bearer {config['jwt_token']}"

            payload = {
                "message": user_input,
                "platform": "terminal",
                "session_token": session_token or uuid.uuid4().hex,
            }
            if config.get("api_key"):
                payload["user_api_key"] = config["api_key"]
            if config.get("model"):
                payload["model"] = config["model"]

            # Determine active model to display
            active_model = config.get("model") or "default"
            print(f"\n{C.PURPLE}[RDX AI]{C.RESET} {C.DIM}({active_model}){C.RESET} ", end="", flush=True)

            # Start background spinner animation
            spinner_active = True
            async def spinner_animation():
                spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                i = 0
                while spinner_active:
                    sys.stdout.write(f"{C.CYAN}{spinners[i % len(spinners)]}{C.RESET}")
                    sys.stdout.flush()
                    await asyncio.sleep(0.1)
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                    i += 1

            spinner_task = asyncio.create_task(spinner_animation())

            async with httpx.AsyncClient(timeout=60.0) as client:
                try:
                    async with client.stream("POST", f"{AI_SERVER}/chat",
                        headers=headers, json=payload) as resp:

                        # Stop spinner once connection is established and response is received
                        spinner_active = False
                        try:
                            spinner_task.cancel()
                            await spinner_task
                        except Exception:
                            pass

                        if resp.status_code != 200:
                            error = await resp.aread()
                            err_text = error.decode(errors='ignore')
                            if resp.status_code in (502, 503) or "<html" in err_text.lower():
                                err("AI Server is waking up from sleep mode. Please wait a few seconds and try again!")
                            else:
                                err(err_text)
                            continue

                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            data = line[6:]
                            try:
                                parsed = json.loads(data)
                                if parsed.get("done"):
                                    session_token = parsed.get("session_token")
                                    continue
                                if parsed.get("error"):
                                    print(f"\n{C.RED}{parsed['error']}{C.RESET}")
                                    break
                                content = parsed.get("content", "")
                                print(content, end="", flush=True)
                            except json.JSONDecodeError:
                                pass
                        print()
                except Exception as e:
                    spinner_active = False
                    try:
                        spinner_task.cancel()
                        await spinner_task
                    except Exception:
                        pass
                    err(str(e))

        except KeyboardInterrupt:
            print(f"\n{C.DIM}Goodbye!{C.RESET}")
            break
        except Exception as e:
            err(str(e))

# ── Commands ────────────────────────────────────────────
async def handle_cmd(cmd, config):
    parts = cmd.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else None

    if command == '/help':
        print(f"""
{C.BOLD}Commands:{C.RESET}
  {C.CYAN}/help{C.RESET}          — Show this help
  {C.CYAN}/api <key>{C.RESET}     — Set/change API key
  {C.CYAN}/api{C.RESET}           — Show current API key
  {C.CYAN}/models{C.RESET}        — List all available models on OpenCode
  {C.CYAN}/model <name>{C.RESET}  — Switch to a specific model
  {C.CYAN}/model{C.RESET}         — Choose available models interactively
  {C.CYAN}/history{C.RESET}       — Show chat history
  {C.CYAN}/clear{C.RESET}         — Clear session
  {C.CYAN}/status{C.RESET}        — Server status
  {C.CYAN}/account{C.RESET}       — Account info
  {C.CYAN}/logout{C.RESET}        — Logout
  {C.CYAN}exit{C.RESET}           — Exit
""")

    elif command == '/api':
        if arg:
            config["api_key"] = arg
            save_config(config)
            ok("API key updated!")
        else:
            key = config.get("api_key")
            if key:
                masked = key[:8] + "..." + key[-4:]
                info(f"API key: {masked}")
            else:
                info("No API key set. Using default.")

    elif command == '/models':
        info("Fetching available models from OpenCode...")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                headers = {"Authorization": f"Bearer {config.get('jwt_token', '')}"}
                resp = await client.get(f"{AI_SERVER}/models", headers=headers)
                if resp.status_code != 200:
                    err(f"Server returned status {resp.status_code}")
                    return
                data = resp.json()
                models = data.get("models", [])
                if not models:
                    info("No models returned from server.")
                else:
                    print(f"\n{C.BOLD}{C.CYAN}Available Models on OpenCode:{C.RESET}")
                    for idx, model in enumerate(models, 1):
                        is_current = " (Active)" if config.get("model") == model else ""
                        print(f"  {C.BOLD}{idx}{C.RESET}. {model}{C.GREEN}{is_current}{C.RESET}")
                    print(f"\n{C.DIM}Type '/model <name>' or run '/model' to switch!{C.RESET}")
            except Exception as e:
                err(f"Failed to fetch models: {e}")

    elif command == '/model':
        if arg:
            config["model"] = arg
            save_config(config)
            ok(f"Model switched to: {arg}")
        else:
            info("Fetching available models...")
            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    headers = {"Authorization": f"Bearer {config.get('jwt_token', '')}"}
                    resp = await client.get(f"{AI_SERVER}/models", headers=headers)
                    if resp.status_code != 200:
                        err(f"Server returned status {resp.status_code}")
                        return
                    data = resp.json()
                    models = data.get("models", [])
                    if not models:
                        info("No models returned from server.")
                        return
                    
                    print(f"\n{C.BOLD}{C.CYAN}Select a Model to Switch:{C.RESET}")
                    active_model = config.get("model")
                    for idx, model in enumerate(models, 1):
                        is_current = " (Current)" if active_model == model or (not active_model and idx == 1) else ""
                        print(f"  {C.BOLD}{idx}{C.RESET}. {model}{C.GREEN}{is_current}{C.RESET}")
                    
                    choice = ask("\nEnter number (or press Enter to keep current): ")
                    if choice.strip():
                        try:
                            choice_idx = int(choice) - 1
                            if 0 <= choice_idx < len(models):
                                new_model = models[choice_idx]
                                config["model"] = new_model
                                save_config(config)
                                ok(f"Model switched to: {new_model}")
                            else:
                                err("Invalid choice.")
                        except ValueError:
                            err("Invalid input. Please enter a number.")
                except Exception as e:
                    err(f"Failed to fetch models: {e}")

    elif command == '/status':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{AI_SERVER}/status")
                data = resp.json()
                info(f"Server: {json.dumps(data, indent=2)}")
            except Exception as e:
                err(f"Cannot reach server: {e}")

    elif command == '/account':
        info(f"Username: {config.get('username', 'Unknown')}")
        info(f"User ID: {config.get('user_id', 'Unknown')}")

    elif command == '/logout':
        confirm = ask("Are you sure? (y/n): ")
        if confirm.lower() == 'y':
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
                ok("Logged out. Restart to re-authenticate.")

    elif command == '/history':
        info("Fetching history...")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{AI_SERVER}/history",
                    headers={"Authorization": f"Bearer {config.get('jwt_token', '')}"})
                if resp.status_code != 200:
                    err_text = resp.text
                    if resp.status_code in (502, 503) or "<html" in err_text.lower():
                        err("AI Server is waking up from sleep mode. Please wait a few seconds and try again!")
                    else:
                        err(f"Server returned status {resp.status_code}")
                    return
                data = resp.json()
                messages = data.get("messages", [])
                if not messages:
                    info("No history found.")
                else:
                    for msg in messages[-10:]:
                        role = "You" if msg.get("role") == "user" else "RDX AI"
                        print(f"  {C.DIM}{msg.get('created_at', '')}{C.RESET} [{role}] {msg.get('content', '')[:100]}")
            except Exception as e:
                err(str(e))

    elif command == '/clear':
        session_token = None
        ok("Session cleared.")

    else:
        err(f"Unknown command: {command}. Type /help")

# ── Main ────────────────────────────────────────────────
async def main():
    config = load_config()

    if config:
        banner()
        print(f"  {C.DIM}Welcome back, {C.BOLD}{config.get('username', 'User')}{C.RESET}{C.DIM}!{C.RESET}")
        await chat_loop(config)
    else:
        setup_banner()
        info("First time setup — connecting to RDX Auth...\n")

        auth_data = await do_auth()
        if not auth_data:
            err("Authentication failed. Please try again.")
            return

        config = {
            "jwt_token": auth_data["jwt_token"],
            "user_id": auth_data["user_id"],
            "username": auth_data["username"],
            "api_key": None,
            "model": None,
            "server_url": AI_SERVER,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_config(config)

        ok("Setup complete! Starting RDX AI...")
        banner()
        await chat_loop(config)

if __name__ == "__main__":
    asyncio.run(main())
