import os
import sys
import socket
import subprocess
import time
from pathlib import Path

# Set up paths so app and ml modules are always found regardless of cwd
project_root = Path(__file__).parent.resolve()
backend_dir = project_root / "backend"

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# Change current working directory to backend so relative .env and configs resolve correctly
os.chdir(str(backend_dir))

def is_port_in_use(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def ensure_database():
    if is_port_in_use("127.0.0.1", 5432):
        print("[OK] PostgreSQL is running on 127.0.0.1:5432")
        return

    # Check for scoop postgresql
    user_profile = os.environ.get("USERPROFILE", "")
    pg_bin = Path(user_profile) / "scoop" / "apps" / "postgresql" / "current" / "bin"
    pg_data = Path(user_profile) / "scoop" / "apps" / "postgresql" / "current" / "data"
    pg_log = Path(user_profile) / "pg.log"
    pg_ctl = pg_bin / "pg_ctl.exe"

    if pg_ctl.exists() and pg_data.exists():
        print("Starting PostgreSQL database...")
        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
        try:
            subprocess.run(
                [
                    str(pg_ctl), "start",
                    "-D", str(pg_data),
                    "-o", "-p 5432 -h 127.0.0.1",
                    "-l", str(pg_log),
                    "-w", "-t", "15"
                ],
                creationflags=flags,
                check=False
            )
            time.sleep(1)
        except Exception as e:
            print(f"Warning: Failed to auto-start PostgreSQL via pg_ctl: {e}")

    # Verify if started
    if is_port_in_use("127.0.0.1", 5432):
        print("[OK] PostgreSQL started successfully on 127.0.0.1:5432")
    else:
        print("Warning: PostgreSQL does not seem to be running on port 5432.")
        print("  If needed, run: powershell -ExecutionPolicy Bypass -File .\\start_db.ps1")

def ensure_ollama():
    import threading

    def _warmup():
        try:
            import requests
            time.sleep(2)
            requests.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": "qwen3:8b", "prompt": "hi", "stream": False},
                timeout=45,
            )
            print("[OK] Ollama qwen3:8b loaded into memory and ready for AI Chat")
        except Exception:
            pass

    if is_port_in_use("127.0.0.1", 11434):
        print("[OK] Ollama LLM service is running on 127.0.0.1:11434")
        t = threading.Thread(target=_warmup, daemon=True)
        t.start()
        return

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    ollama_exe = Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"

    if ollama_exe.exists():
        print("Starting Ollama LLM service in background...")
        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        flags = (CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP) if sys.platform == "win32" else 0
        try:
            subprocess.Popen(
                [str(ollama_exe), "serve"],
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)
            if is_port_in_use("127.0.0.1", 11434):
                print("[OK] Ollama LLM service started on 127.0.0.1:11434")
                t = threading.Thread(target=_warmup, daemon=True)
                t.start()
        except Exception as e:
            print(f"Note: Ollama auto-start: {e}")

if __name__ == "__main__":
    ensure_database()
    ensure_ollama()
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(backend_dir)],
    )
