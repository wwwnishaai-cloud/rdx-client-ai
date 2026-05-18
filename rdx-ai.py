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
import random

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
# NOTE: do_model() during setup is removed. Model is now controlled by:
# 1. /model command (fetches live models from server, saves to both local config + server DB)
# 2. Admin dashboard default_model setting (used when user has no explicit preference)

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
            # Only send model override if user explicitly chose one via /model command.
            # If not set, the server will use admin's global default_model from ai_settings.
            if config.get("model") and config["model"] != "__server_default__":
                payload["model"] = config["model"]

            # Determine active model to display
            active_model = config.get("model") or "default"
            print(f"\n{C.PURPLE}[RDX AI]{C.RESET} {C.DIM}({active_model}){C.RESET} ", end="", flush=True)

            # Start background spinner animation
            spinner_active = True
            async def spinner_animation():
                spinners = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
                ascii_spinners = ["|", "/", "-", "\\"]
                phrases = [
                    "Thinking...",
                    "Analyzing context...",
                    "Reasoning...",
                    "Solving...",
                    "Formulating response...",
                    "Structuring answer...",
                    "Retrieving intelligence..."
                ]
                i = 0
                use_ascii = False
                while spinner_active:
                    phrase = phrases[(i // 15) % len(phrases)]
                    spinner_char = ascii_spinners[i % len(ascii_spinners)] if use_ascii else spinners[i % len(spinners)]
                    text = f"{C.CYAN}{spinner_char}{C.RESET} {C.DIM}{phrase}{C.RESET}"
                    try:
                        sys.stdout.write(text)
                        sys.stdout.flush()
                    except UnicodeEncodeError:
                        use_ascii = True
                        spinner_char = ascii_spinners[i % len(ascii_spinners)]
                        text = f"{C.CYAN}{spinner_char}{C.RESET} {C.DIM}{phrase}{C.RESET}"
                        try:
                            sys.stdout.write(text)
                            sys.stdout.flush()
                        except Exception:
                            pass
                    
                    # Organic random delay between 50ms and 150ms like Claude Code CLI!
                    await asyncio.sleep(random.uniform(0.05, 0.15))
                    
                    # Erase exactly the printed characters
                    erase_len = 2 + len(phrase)
                    try:
                        sys.stdout.write("\b" * erase_len + " " * erase_len + "\b" * erase_len)
                        sys.stdout.flush()
                    except Exception:
                        pass
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
                        except asyncio.CancelledError:
                            pass
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
                    except asyncio.CancelledError:
                        pass
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
    parts = cmd.split()
    command = parts[0].lower()
    args = parts[1:]

    def get_headers():
        return {"Authorization": f"Bearer {config.get('jwt_token', '')}"}

    if command == '/help':
        print(f"""
{C.BOLD}Base Commands:{C.RESET}
  {C.CYAN}/help{C.RESET}          — Show this help
  {C.CYAN}/api <key>{C.RESET}     — Set/change API key
  {C.CYAN}/models{C.RESET}        — List available models
  {C.CYAN}/model <name>{C.RESET}  — Switch model
  {C.CYAN}/history{C.RESET}       — Show chat history
  {C.CYAN}/clear{C.RESET}         — Clear session
  {C.CYAN}/account{C.RESET}       — Account info
  {C.CYAN}/logout{C.RESET}        — Logout
  {C.CYAN}exit{C.RESET}           — Exit

{C.BOLD}Dashboard & Analytics:{C.RESET}
  {C.CYAN}/stats{C.RESET}         — View dashboard stats
  {C.CYAN}/analytics{C.RESET}     — View analytics charts
  {C.CYAN}/logs{C.RESET}          — View activity logs
  {C.CYAN}/profile{C.RESET}       — View your profile
  {C.CYAN}/messages{C.RESET}      — View unread messages

{C.BOLD}App Management:{C.RESET}
  {C.CYAN}/apps{C.RESET}          — List all apps
  {C.CYAN}/app-create <n>{C.RESET}— Create app
  {C.CYAN}/app-delete <id>{C.RESET}— Delete app by ID

{C.BOLD}License Management:{C.RESET}
  {C.CYAN}/licenses{C.RESET}      — List licenses
  {C.CYAN}/keygen <app_id> <days>{C.RESET} — Generate key
  {C.CYAN}/bulk-keygen <id> <days> <amt>{C.RESET} — Bulk gen
  {C.CYAN}/key-delete <id>{C.RESET} — Delete license
  
{C.BOLD}Member Management:{C.RESET}
  {C.CYAN}/members{C.RESET}       — List members
  {C.CYAN}/member-create <user> <pass> <app_id>{C.RESET}
  {C.CYAN}/member-delete <id>{C.RESET} — Delete user
  {C.CYAN}/member-ban <id> <reason>{C.RESET} — Ban user
  {C.CYAN}/extend-sub <id> <days>{C.RESET} — Extend sub

{C.BOLD}Discord Integration:{C.RESET}
  {C.CYAN}/discord-link <id>{C.RESET} — Link Discord ID
  {C.CYAN}/discord-send <tgt> <msg>{C.RESET} — Send Discord msg
""")

    elif command == '/api':
        if args:
            config["api_key"] = args[0]
            save_config(config)
            ok("API key updated!")
        else:
            key = config.get("api_key")
            if key:
                info(f"API key: {key[:8] + '...' + key[-4:]}")
            else:
                info("No API key set.")

    elif command == '/models':
        info("Fetching available models from OpenCode...")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{AI_SERVER}/models", headers=get_headers())
                data = resp.json()
                models = data.get("models", [])
                if not models:
                    info("No models returned.")
                else:
                    print(f"\n{C.BOLD}{C.CYAN}Available Models:{C.RESET}")
                    for idx, model in enumerate(models, 1):
                        is_current = " (Active)" if config.get("model") == model else ""
                        print(f"  {C.BOLD}{idx}{C.RESET}. {model}{C.GREEN}{is_current}{C.RESET}")
            except Exception as e:
                err(f"Failed to fetch models: {e}")

    elif command == '/model':
        if args:
            config["model"] = args[0]
            save_config(config)
            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    await client.post(f"{AI_SERVER}/model/switch", json={"model": args[0]}, headers=get_headers())
                except: pass
            ok(f"Model switched to: {args[0]}")
        else:
            info("Use /model <name> to switch.")

    elif command == '/history':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{AI_SERVER}/history", headers=get_headers())
                data = resp.json()
                messages = data.get("messages", [])
                for msg in messages[-10:]:
                    role = "You" if msg.get("role") == "user" else "RDX AI"
                    print(f"  {C.DIM}{msg.get('created_at', '')}{C.RESET} [{role}] {msg.get('content', '')[:100]}")
            except Exception as e:
                err(str(e))

    elif command == '/clear':
        ok("Session cleared.")

    elif command == '/account':
        info(f"Username: {config.get('username')}")
        info(f"User ID: {config.get('user_id')}")

    elif command == '/logout':
        confirm = ask("Are you sure? (y/n): ")
        if confirm.lower() == 'y':
            if os.path.exists(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            ok("Logged out. Restart to re-authenticate.")

    # --- Dashboard Commands ---
    elif command == '/stats':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/stats", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/analytics':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/analytics", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/logs':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/logs", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/profile':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/auth/me", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))
            
    elif command == '/messages':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/messages", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    # --- App Management ---
    elif command == '/apps':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/apps", headers=get_headers())
                data = resp.json()
                if data.get('success'):
                    apps = data.get('data', [])
                    print(f"\n{C.BOLD}{C.CYAN}Your Apps:{C.RESET}")
                    for app in apps:
                        print(f"  {C.BOLD}ID:{C.RESET} {app['id']} | {C.BOLD}Name:{C.RESET} {app['name']} | {C.BOLD}Key:{C.RESET} {app['owner_key']}")
                else:
                    err(data.get('message', 'Failed to fetch apps'))
            except Exception as e: err(str(e))

    elif command == '/app-create':
        if not args:
            err("Usage: /app-create <name>")
            return
        name = " ".join(args)
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/apps", json={"name": name}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/app-delete':
        if not args: return err("Usage: /app-delete <id>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.delete(f"{MAIN_SERVER}/rdx/api/apps/{args[0]}", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    # --- License Management ---
    elif command == '/licenses':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/licenses", headers=get_headers())
                data = resp.json()
                if data.get('success'):
                    lics = data.get('data', [])
                    print(f"\n{C.BOLD}{C.CYAN}Your Licenses:{C.RESET}")
                    for lic in lics[:20]: # Show top 20
                        print(f"  {C.BOLD}ID:{C.RESET} {lic['id']} | {C.BOLD}Key:{C.RESET} {lic['license_key']} | {C.BOLD}Status:{C.RESET} {lic['status']}")
                else:
                    err(data.get('message', 'Failed'))
            except Exception as e: err(str(e))

    elif command == '/keygen':
        if len(args) < 2: return err("Usage: /keygen <app_id> <days>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/licenses/create", json={"app_id": args[0], "duration_days": int(args[1])}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/bulk-keygen':
        if len(args) < 3: return err("Usage: /bulk-keygen <app_id> <days> <amount>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/licenses/bulk", json={"app_id": args[0], "duration_days": int(args[1]), "amount": int(args[2])}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/key-delete':
        if not args: return err("Usage: /key-delete <id>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.delete(f"{MAIN_SERVER}/rdx/api/licenses/{args[0]}", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    # --- Member Management ---
    elif command == '/members':
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{MAIN_SERVER}/rdx/api/users", headers=get_headers())
                data = resp.json()
                if data.get('success'):
                    users = data.get('data', [])
                    print(f"\n{C.BOLD}{C.CYAN}Your Members:{C.RESET}")
                    for u in users[:20]:
                        print(f"  {C.BOLD}ID:{C.RESET} {u['id']} | {C.BOLD}User:{C.RESET} {u['username']} | {C.BOLD}Status:{C.RESET} {u['status']}")
                else:
                    err(data.get('message', 'Failed'))
            except Exception as e: err(str(e))

    elif command == '/member-create':
        if len(args) < 3: return err("Usage: /member-create <username> <password> <app_id>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/users", json={"username": args[0], "password": args[1], "app_id": args[2], "duration": 30}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))
            
    elif command == '/member-delete':
        if not args: return err("Usage: /member-delete <id>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.delete(f"{MAIN_SERVER}/rdx/api/users/{args[0]}", headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/member-ban':
        if len(args) < 2: return err("Usage: /member-ban <user_id> <reason>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/users/ban", json={"user_id": args[0], "reason": " ".join(args[1:])}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/extend-sub':
        if len(args) < 2: return err("Usage: /extend-sub <user_id> <days>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/users/extend", json={"user_id": args[0], "days": int(args[1])}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    # --- Discord Integration ---
    elif command == '/discord-link':
        if not args: return err("Usage: /discord-link <your_discord_id>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/auth/ai/discord-link", json={"discord_id": args[0]}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    elif command == '/discord-send':
        if len(args) < 2: return err("Usage: /discord-send <channel_id> <message>")
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{MAIN_SERVER}/rdx/api/auth/ai/discord/send", json={"target": args[0], "message": " ".join(args[1:])}, headers=get_headers())
                print(json.dumps(resp.json(), indent=2))
            except Exception as e: err(str(e))

    else:
        err(f"Unknown command: {command}. Type /help")

# ── Main ────────────────────────────────────────────────
async def main():
    config = load_config()

    if config:
        # One-time migration: clear stale model saved from old fake hardcoded list.
        # These models were saved by the old setup flow and bypass the admin global default.
        stale_defaults = {'llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'mixtral-8x7b-32768', 'gemma2-9b-it'}
        if config.get('model') in stale_defaults:
            config['model'] = None
            save_config(config)
            info("Model preference cleared — now using admin's global default. Use /model to pick a model.")

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
