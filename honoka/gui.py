"""The window: the account, one Play button, and what is happening."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

from . import __version__, account, config, game, horizon_bridge, play, system

BG = "#16161d"
CARD = "#22222c"
INK = "#f2f2f5"
MUTED = "#9a9aab"
ACCENT = "#f0795a"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.cancel_sign_in = False

        root.title(config.APP_NAME)
        root.geometry("560x380")
        root.minsize(480, 340)
        root.configure(bg=BG)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Play.TButton", font=("Helvetica", 18, "bold"), padding=(40, 14),
                        background=ACCENT, foreground="#ffffff", borderwidth=0)
        style.map("Play.TButton", background=[("disabled", "#5a4a46"), ("active", "#ff8c6e")])
        style.configure("Small.TButton", padding=(10, 4))
        style.configure("Bar.Horizontal.TProgressbar", troughcolor=CARD, background=ACCENT, borderwidth=0)

        tk.Label(root, text=config.APP_NAME, font=("Helvetica", 30, "bold"), fg=INK, bg=BG).pack(pady=(26, 0))
        tk.Label(root, text=f"сервер {config.SERVER_NAME} · {config.SERVER_ADDRESS}", fg=MUTED, bg=BG).pack()

        card = tk.Frame(root, bg=CARD, padx=14, pady=10)
        card.pack(fill="x", padx=24, pady=(18, 0))
        self.account_label = tk.Label(card, text="", fg=INK, bg=CARD, anchor="w", justify="left", wraplength=380)
        self.account_label.pack(side="left", fill="x", expand=True)
        self.account_button = ttk.Button(card, style="Small.TButton", command=self.on_account)
        self.account_button.pack(side="right")

        self.play_button = ttk.Button(root, text="Играть", style="Play.TButton", command=self.on_play)
        self.play_button.pack(pady=(22, 12))

        self.bar = ttk.Progressbar(root, style="Bar.Horizontal.TProgressbar", mode="determinate", maximum=1.0)
        self.bar.pack(fill="x", padx=24)
        self.status = tk.Label(root, text="", fg=MUTED, bg=BG, wraplength=500, justify="center")
        self.status.pack(fill="x", padx=24, pady=(8, 0))
        tk.Label(root, text=f"v{__version__} · игра: Horizon (неофициальный проект)", fg="#55556a", bg=BG,
                 font=("Helvetica", 9)).pack(side="bottom", pady=6)

        warnings = system.warnings()
        if warnings:
            self.set_status(warnings[0])
        self.refresh_account()
        root.after(100, self.pump)

    # --- helpers ---------------------------------------------------------------------------------------

    def set_status(self, text: str, fraction: float | None = None) -> None:
        self.status.configure(text=text)
        if fraction is None:
            if str(self.bar.cget("mode")) != "indeterminate":
                self.bar.configure(mode="indeterminate")
                self.bar.start(12)
        else:
            if str(self.bar.cget("mode")) != "determinate":
                self.bar.stop()
                self.bar.configure(mode="determinate")
            self.bar["value"] = max(0.0, min(1.0, fraction))

    def idle_bar(self) -> None:
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.bar["value"] = 0

    def refresh_account(self) -> None:
        if not config.msa_client_id():
            self.refresh_bridge()
            return
        profile = account.signed_in()
        if profile and profile.get("owns"):
            self.account_label.configure(text=f"Аккаунт: {profile['name']}")
            self.account_button.configure(text="Выйти")
        elif profile:
            self.account_label.configure(text="На аккаунте нет Minecraft: Java Edition")
            self.account_button.configure(text="Выйти")
        else:
            self.account_label.configure(text="Войдите с аккаунтом Microsoft, на котором куплена игра")
            self.account_button.configure(text="Войти")
        self.play_button.state(["!disabled"] if not self.busy else ["disabled"])

    def refresh_bridge(self) -> None:
        """Until Honoka's own Azure app: the account signed in in the Horizon launcher (horizon_bridge)."""
        self.play_button.state(["!disabled"] if not self.busy else ["disabled"])
        if horizon_bridge.find_launcher() is None:
            # Nothing to install by hand: «Войти» downloads it (horizon_bridge.install_launcher).
            self.bridge_owner = None
            self.account_button.configure(text="Войти")
            self.account_label.configure(text="Войдите аккаунтом Microsoft, на котором куплена игра")
            return
        self.account_label.configure(text="Спрашиваю лаунчер Horizon…")

        def ask():
            try:
                owner = horizon_bridge.owner_account()
            except horizon_bridge.BridgeError as e:
                owner, error = None, str(e)
            else:
                error = None

            def show():
                self.bridge_owner = owner
                if owner:
                    self.account_label.configure(text=f"Аккаунт (через лаунчер Horizon): {owner['name']}")
                    self.account_button.configure(text="Обновить")
                else:
                    self.account_label.configure(text=error or "Войдите аккаунтом Microsoft, на котором куплена игра")
                    self.account_button.configure(text="Войти")

            self.events.put(("call", show))

        threading.Thread(target=ask, daemon=True).start()

    def run(self, work, done) -> None:
        """Runs `work(progress)` on a thread; `done(result, error)` back on the window's thread."""
        self.busy = True
        self.play_button.state(["disabled"])
        self.account_button.state(["disabled"])

        def progress(text, fraction=None):
            self.events.put(("progress", text, fraction))

        def target():
            try:
                result, error = work(progress), None
            except Exception as e:  # shown to the player
                result, error = None, e
            self.events.put(("done", done, result, error))

        threading.Thread(target=target, daemon=True).start()

    def pump(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    self.set_status(event[1], event[2])
                elif event[0] == "done":
                    self.busy = False
                    self.account_button.state(["!disabled"])
                    self.idle_bar()
                    event[1](event[2], event[3])
                    self.refresh_account()
                elif event[0] == "call":
                    event[1]()
        except queue.Empty:
            pass
        self.root.after(100, self.pump)

    # --- sign-in ---------------------------------------------------------------------------------------

    def on_account(self) -> None:
        if not config.msa_client_id():
            if getattr(self, "bridge_owner", None):
                self.refresh_bridge()
            else:
                self.bridge_sign_in()
            return
        if account.signed_in():
            account.sign_out()
            self.set_status("Вы вышли из аккаунта.", 0)
            self.idle_bar()
            self.refresh_account()
            return
        self.cancel_sign_in = False

        def work(progress):
            progress("Связываюсь с Microsoft…", None)
            code = account.start_device_code()
            self.events.put(("call", lambda: self.show_code(code)))
            progress("Ждём вход на странице Microsoft…", None)
            return account.finish_device_code(code, cancelled=lambda: self.cancel_sign_in)

        def done(profile, error):
            self.close_code()
            if error:
                self.set_status(str(error), 0)
            else:
                self.set_status(f"Готово, {profile['name']}! Жмите «Играть».", 1.0)

        self.run(work, done)

    def bridge_sign_in(self) -> None:
        """Signs in in the Horizon launcher through its command line (its window needs macOS 12)."""
        self.cancel_sign_in = False

        def work(progress):
            progress("Спрашиваю у лаунчера Horizon код входа…", None)

            def on_code(link, code):
                dc = account.DeviceCode(code, link, "", 0, 0)
                self.events.put(("call", lambda: self.show_code(dc)))
                progress("Ждём вход на странице Microsoft…", None)

            return horizon_bridge.sign_in(on_code, cancelled=lambda: self.cancel_sign_in, progress=progress)

        def done(name, error):
            self.close_code()
            self.set_status(str(error) if error else f"Готово, {name}! Жмите «Играть».", 0 if error else 1.0)

        self.run(work, done)

    def show_code(self, code: account.DeviceCode) -> None:
        win = tk.Toplevel(self.root, bg=BG, padx=24, pady=18)
        win.title("Вход Microsoft")
        win.transient(self.root)
        tk.Label(win, text="Откройте страницу Microsoft и введите код:", fg=INK, bg=BG).pack()
        tk.Label(win, text=code.user_code, font=("Courier", 26, "bold"), fg=ACCENT, bg=BG).pack(pady=10)
        link = tk.Label(win, text=code.verification_uri, fg="#7fb2ff", bg=BG, cursor="hand2")
        link.pack()
        link.bind("<Button-1>", lambda _e: webbrowser.open(code.verification_uri))
        tk.Label(win, text="Код уже скопирован. Окно закроется само после входа.", fg=MUTED, bg=BG).pack(pady=(10, 6))
        ttk.Button(win, text="Отмена", command=self.on_cancel_sign_in).pack()
        win.protocol("WM_DELETE_WINDOW", self.on_cancel_sign_in)
        self.root.clipboard_clear()
        self.root.clipboard_append(code.user_code)
        webbrowser.open(code.verification_uri)
        self.code_window = win

    def on_cancel_sign_in(self) -> None:
        self.cancel_sign_in = True
        self.close_code()

    def close_code(self) -> None:
        win = getattr(self, "code_window", None)
        if win is not None:
            win.destroy()
            self.code_window = None

    # --- play ------------------------------------------------------------------------------------------

    def on_play(self) -> None:
        if config.msa_client_id() and not account.signed_in():
            self.on_account()
            return

        def done(proc, error):
            if error:
                self.set_status(str(error), 0)
                return
            self.set_status("Игра запущена. Приятной игры!", 1.0)
            self.play_button.state(["disabled"])
            self.busy = True
            threading.Thread(target=self.wait_game, args=(proc,), daemon=True).start()

        self.run(play.play, done)

    def wait_game(self, proc) -> None:
        code = proc.wait()

        def finished():
            self.busy = False
            self.refresh_account()
            self.set_status(game.exit_message(code) or "Игра закрыта.", 0)
            self.idle_bar()

        self.events.put(("call", finished))


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
