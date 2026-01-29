# haze_launcher.py
import json
import os
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ssl
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_base_path() -> str:
    if is_frozen():
        return os.path.join(os.path.dirname(sys.executable), "_internal")
    return os.path.dirname(os.path.abspath(__file__))


def get_data_dir() -> str:
    """
    .env, bots_registry.json 등 데이터 파일 경로
    - 개발환경: 프로젝트 루트
    - 배포환경: _internal 폴더
    """
    if is_frozen():
        return os.path.join(os.path.dirname(sys.executable), "_internal")
    return os.path.dirname(os.path.abspath(__file__))


def find_python_executable() -> str:
    override = os.getenv("HAZE_PYTHON")
    if override and os.path.exists(override):
        return override
    if not is_frozen():
        return sys.executable
    candidate = os.path.join(os.path.dirname(sys.executable), "python.exe")
    if os.path.exists(candidate):
        return candidate
    return "python"


ENV_PATH = os.path.join(get_data_dir(), ".env")
REGISTRY_PATH = os.path.join(get_data_dir(), "bots_registry.json")


def load_env_items(path: str) -> list[dict]:
    items = []
    if not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                items.append({"type": "raw", "raw": raw})
                continue
            if "=" in raw:
                key, value = raw.split("=", 1)
                items.append({"type": "kv", "key": key.strip(), "value": value.strip()})
            else:
                items.append({"type": "raw", "raw": raw})
    return items


def save_env_items(path: str, items: list[dict]) -> None:
    lines = []
    for item in items:
        if item["type"] == "raw":
            lines.append(item["raw"])
        else:
            lines.append(f"{item['key']}={item['value']}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def env_items_to_dict(items: list[dict]) -> dict:
    result = {}
    for item in items:
        if item["type"] == "kv":
            result[item["key"]] = item["value"]
    return result


class BotSpec:
    def __init__(self, bot_id: str, name: str, path: str, fixed: bool, auto_restart: bool = True):
        self.id = bot_id
        self.name = name
        self.path = path
        self.fixed = fixed
        self.auto_restart = auto_restart
        self.desired = False
        self.process: subprocess.Popen | None = None
        self.last_exit: int | None = None
        self.restart_at: float | None = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class BotManager:
    def __init__(self, env_path: str):
        self.env_path = env_path
        self._lock = threading.Lock()
        self._bots: dict[str, BotSpec] = {}
        self._stop_event = threading.Event()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)

    def start(self) -> None:
        self._monitor_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._monitor_thread.join(timeout=2)

    def bots(self) -> list[BotSpec]:
        with self._lock:
            return list(self._bots.values())

    def get_bot(self, bot_id: str) -> BotSpec | None:
        with self._lock:
            return self._bots.get(bot_id)

    def add_bot(self, bot: BotSpec) -> None:
        with self._lock:
            self._bots[bot.id] = bot

    def remove_bot(self, bot_id: str) -> None:
        with self._lock:
            self._bots.pop(bot_id, None)

    def start_bot(self, bot_id: str) -> None:
        bot = self.get_bot(bot_id)
        if bot is None:
            return
        if bot.is_running():
            bot.desired = True
            return

        print(f"[START] {bot.name} 시작 준비 중...")

        env = os.environ.copy()
        env.update(env_items_to_dict(load_env_items(self.env_path)))
        env["SSL_CERT_FILE"] = certifi.where()
        cwd = os.path.dirname(bot.path) or get_data_dir()

        # Windows에서 새 콘솔 창으로 실행
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_CONSOLE

        try:
            if bot.path.endswith(".exe"):
                bot.process = subprocess.Popen(
                    [bot.path],
                    cwd=cwd,
                    env=env,
                    creationflags=creationflags,
                )
            else:
                python_exe = find_python_executable()
                bot.process = subprocess.Popen(
                    [python_exe, "-u", bot.path],  # -u: unbuffered 출력
                    cwd=cwd,
                    env=env,
                    creationflags=creationflags,
                )

            print(f"[START] {bot.name} 시작됨 (PID: {bot.process.pid})")
            bot.desired = True
            bot.last_exit = None
            bot.restart_at = None
        except Exception as e:
            print(f"[START] {bot.name} 시작 실패: {e}")

    def stop_bot(self, bot_id: str) -> None:
        bot = self.get_bot(bot_id)
        if bot is None:
            print(f"[STOP] 봇을 찾을 수 없음: {bot_id}")
            return

        bot.desired = False

        if bot.process is None:
            print(f"[STOP] {bot.name}: 프로세스가 이미 없음")
            return

        pid = bot.process.pid
        print(f"[STOP] {bot.name} 종료 시도... (PID: {pid})")

        try:
            if bot.process.poll() is None:
                # 방법 1: taskkill 사용 (가장 확실)
                if sys.platform == "win32":
                    result = subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    print(f"[STOP] taskkill 결과: {result.stdout.strip()} {result.stderr.strip()}")
                else:
                    os.kill(pid, signal.SIGKILL)

                # 프로세스 종료 대기
                try:
                    bot.process.wait(timeout=3)
                except:
                    pass

            print(f"[STOP] {bot.name} 종료 완료 (PID: {pid})")

        except Exception as e:
            print(f"[STOP] {bot.name} 종료 중 오류: {e}")

        bot.process = None
        bot.last_exit = None
        bot.restart_at = None

    def stop_all(self) -> None:
        for bot in self.bots():
            self.stop_bot(bot.id)

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            to_restart = []
            with self._lock:
                for bot in self._bots.values():
                    if bot.process is not None and bot.process.poll() is not None:
                        exit_code = bot.process.poll()
                        print(f"[EXIT] {bot.name} 종료 감지 (exit code: {exit_code})")
                        bot.last_exit = exit_code
                        bot.process = None
                        if bot.desired and bot.auto_restart:
                            bot.restart_at = now + 2.0
                            print(f"[AUTO-RESTART] {bot.name} 2초 후 재시작 예정")
                        else:
                            bot.desired = False
                    if bot.restart_at is not None and bot.restart_at <= now:
                        to_restart.append(bot)
                        bot.restart_at = None
            for bot in to_restart:
                try:
                    print(f"[AUTO-RESTART] {bot.name} 재시작 중...")
                    self.start_bot(bot.id)
                except Exception as e:
                    print(f"[AUTO-RESTART] {bot.name} 재시작 실패: {e}")
            time.sleep(0.5)


def load_registry(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("bots", [])
    except Exception:
        return []


def save_registry(path: str, bots: list[BotSpec]) -> None:
    data = {
        "bots": [
            {
                "name": bot.name,
                "path": bot.path,
                "auto_restart": bot.auto_restart,
            }
            for bot in bots
            if not bot.fixed
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class EnvEditor(tk.Toplevel):
    def __init__(self, master: tk.Tk, env_path: str):
        super().__init__(master)
        self.title("Env Editor")
        self.geometry("720x480")
        self.env_path = env_path
        self.items = load_env_items(env_path)

        self.tree = ttk.Treeview(self, columns=("key", "value"), show="headings", height=14)
        self.tree.heading("key", text="Key")
        self.tree.heading("value", text="Value")
        self.tree.column("key", width=200, anchor="w")
        self.tree.column("value", width=480, anchor="w")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        form = ttk.Frame(self)
        form.pack(fill=tk.X, padx=10)
        ttk.Label(form, text="Key").grid(row=0, column=0, sticky="w")
        ttk.Label(form, text="Value").grid(row=1, column=0, sticky="w")

        self.key_var = tk.StringVar()
        self.value_var = tk.StringVar()
        self.key_entry = ttk.Entry(form, textvariable=self.key_var)
        self.value_entry = ttk.Entry(form, textvariable=self.value_var)
        self.key_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.value_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        form.columnconfigure(1, weight=1)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(btns, text="Add/Update", command=self.add_or_update).pack(side=tk.LEFT)
        ttk.Button(btns, text="Delete", command=self.delete_item).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Save", command=self.save).pack(side=tk.RIGHT)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.refresh()

    def refresh(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        for idx, item in enumerate(self.items):
            if item["type"] == "kv":
                self.tree.insert("", tk.END, iid=str(idx), values=(item["key"], item["value"]))

    def on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        item = self.items[idx]
        if item["type"] == "kv":
            self.key_var.set(item["key"])
            self.value_var.set(item["value"])

    def add_or_update(self) -> None:
        key = self.key_var.get().strip()
        value = self.value_var.get()
        if not key:
            messagebox.showwarning("Env Editor", "Key is required.")
            return
        for item in self.items:
            if item["type"] == "kv" and item["key"] == key:
                item["value"] = value
                self.refresh()
                return
        self.items.append({"type": "kv", "key": key, "value": value})
        self.refresh()

    def delete_item(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        if self.items[idx]["type"] == "kv":
            self.items.pop(idx)
            self.refresh()

    def save(self) -> None:
        save_env_items(self.env_path, self.items)
        messagebox.showinfo("Env Editor", "Saved.")


class DashboardApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Haze Bot Dashboard")
        self.root.geometry("900x520")

        self.manager = BotManager(ENV_PATH)
        self.manager.start()

        self.tree = ttk.Treeview(
            root,
            columns=("name", "status", "auto_restart", "path"),
            show="headings",
            height=16,
        )
        self.tree.heading("name", text="Bot")
        self.tree.heading("status", text="Status")
        self.tree.heading("auto_restart", text="Auto-Restart")
        self.tree.heading("path", text="Path")
        self.tree.column("name", width=160, anchor="w")
        self.tree.column("status", width=140, anchor="w")
        self.tree.column("auto_restart", width=110, anchor="center")
        self.tree.column("path", width=440, anchor="w")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, padx=12, pady=4)

        ttk.Button(controls, text="Start", command=self.start_selected).pack(side=tk.LEFT)
        ttk.Button(controls, text="Stop", command=self.stop_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text="Add Bot", command=self.add_bot).pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text="Remove Bot", command=self.remove_bot).pack(side=tk.LEFT, padx=6)
        ttk.Button(controls, text="Edit .env", command=self.open_env_editor).pack(side=tk.LEFT, padx=6)

        self.auto_restart_var = tk.BooleanVar(value=True)
        self.auto_restart_chk = ttk.Checkbutton(
            controls,
            text="Auto-Restart",
            variable=self.auto_restart_var,
            command=self.toggle_auto_restart,
        )
        self.auto_restart_chk.pack(side=tk.RIGHT)

        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._load_initial_bots()
        self.refresh_ui()

    def _load_initial_bots(self) -> None:
        base_path = get_base_path()
        
        # 배포 환경에서는 .exe, 개발 환경에서는 .py
        if is_frozen():
            ext = ".exe"
        else:
            ext = ".py"

        fixed_bots = [
            BotSpec("fixed:scheduler", "scheduler", os.path.join(base_path, f"haze_scheduler{ext}"), True, True),
            BotSpec("fixed:scrimer", "scrimer", os.path.join(base_path, f"haze_latte{ext}"), True, True),
        ]
        
        for bot in fixed_bots:
            self.manager.add_bot(bot)

        for entry in load_registry(REGISTRY_PATH):
            path = entry.get("path")
            name = entry.get("name") or os.path.splitext(os.path.basename(path))[0]
            auto_restart = bool(entry.get("auto_restart", True))
            if not path or not os.path.exists(path):
                continue
            bot_id = f"user:{path}"
            self.manager.add_bot(BotSpec(bot_id, name, path, False, auto_restart))

        self._sync_tree()

    def _sync_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for bot in self.manager.bots():
            self.tree.insert(
                "",
                tk.END,
                iid=bot.id,
                values=(bot.name, "Stopped", "On" if bot.auto_restart else "Off", bot.path),
            )

    def _update_registry(self) -> None:
        save_registry(REGISTRY_PATH, self.manager.bots())

    def on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        bot = self.manager.get_bot(selected[0])
        if bot is None:
            return
        self.auto_restart_var.set(bot.auto_restart)

    def refresh_ui(self) -> None:
        for bot in self.manager.bots():
            if bot.is_running():
                status = f"Running (PID {bot.process.pid})"
            elif bot.last_exit is not None:
                status = f"Exited ({bot.last_exit})"
            else:
                status = "Stopped"
            self.tree.item(
                bot.id,
                values=(bot.name, status, "On" if bot.auto_restart else "Off", bot.path),
            )
        self.root.after(500, self.refresh_ui)

    def start_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        for bot_id in selected:
            bot = self.manager.get_bot(bot_id)
            if bot and os.path.exists(bot.path):
                try:
                    self.manager.start_bot(bot_id)
                except Exception as exc:
                    messagebox.showerror("Start Bot", str(exc))
            else:
                messagebox.showwarning("Start Bot", f"Missing file: {bot.path if bot else bot_id}")

    def stop_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        for bot_id in selected:
            self.manager.stop_bot(bot_id)

    def add_bot(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Bot .py",
            filetypes=[("Python Files", "*.py")],
        )
        if not path:
            return
        if os.path.basename(path) in {"haze_scheduler.py", "haze_latte.py"}:
            messagebox.showwarning("Add Bot", "scheduler/scrimer are already fixed bots.")
            return
        bot_id = f"user:{path}"
        if self.manager.get_bot(bot_id):
            messagebox.showinfo("Add Bot", "This bot is already registered.")
            return
        name = self._unique_name(os.path.splitext(os.path.basename(path))[0])
        bot = BotSpec(bot_id, name, path, False, True)
        self.manager.add_bot(bot)
        self.tree.insert(
            "",
            tk.END,
            iid=bot.id,
            values=(bot.name, "Stopped", "On" if bot.auto_restart else "Off", bot.path),
        )
        self._update_registry()

    def remove_bot(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        for bot_id in selected:
            bot = self.manager.get_bot(bot_id)
            if bot is None:
                continue
            if bot.fixed:
                messagebox.showwarning("Remove Bot", f"{bot.name} is fixed and cannot be removed.")
                continue
            if bot.is_running():
                messagebox.showwarning("Remove Bot", f"Stop {bot.name} before removing.")
                continue
            self.manager.remove_bot(bot_id)
            self.tree.delete(bot_id)
        self._update_registry()

    def toggle_auto_restart(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        value = self.auto_restart_var.get()
        for bot_id in selected:
            bot = self.manager.get_bot(bot_id)
            if bot is None:
                continue
            bot.auto_restart = value
            if not value and bot.restart_at is not None:
                bot.restart_at = None
        self._update_registry()

    def open_env_editor(self) -> None:
        EnvEditor(self.root, ENV_PATH)

    def on_close(self) -> None:
        if messagebox.askyesno("Exit", "Stop all bots and exit?"):
            self.manager.stop_all()
            self.manager.stop()
            self.root.destroy()

    def _unique_name(self, base_name: str) -> str:
        existing = {bot.name for bot in self.manager.bots()}
        if base_name not in existing:
            return base_name
        counter = 2
        while f"{base_name}_{counter}" in existing:
            counter += 1
        return f"{base_name}_{counter}"


def main() -> None:
    root = tk.Tk()
    DashboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()