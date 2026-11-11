"""python -m honoka [gui|login|logout|status|play]"""

from __future__ import annotations

import argparse
import sys

from . import __version__, account, config, game, horizon_bridge, play, system


def _progress(text: str, fraction: float | None = None) -> None:
    pct = f" {fraction * 100:3.0f}%" if fraction is not None else ""
    print(f"\r{text}{pct}".ljust(80), end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="honoka", description="Honoka: лаунчер сервера Hoka на Horizon.")
    parser.add_argument("--version", action="version", version=f"honoka {__version__}")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="окно лаунчера (по умолчанию)")
    sub.add_parser("login", help="войти в аккаунт Microsoft")
    sub.add_parser("logout", help="выйти")
    sub.add_parser("status", help="аккаунт и система")
    sub.add_parser("play", help="подготовить и запустить игру на сервере")
    args = parser.parse_args(argv)

    try:
        if args.cmd in (None, "gui"):
            from . import gui

            gui.main()
        elif args.cmd == "login":
            code = account.start_device_code()
            print(f"Откройте {code.verification_uri} и введите код {code.user_code}")
            profile = account.finish_device_code(code)
            print(f"Готово: {profile['name']}")
        elif args.cmd == "logout":
            account.sign_out()
            print("Вы вышли.")
        elif args.cmd == "status":
            if config.msa_client_id():
                profile = account.signed_in()
                print("Аккаунт:", profile["name"] if profile and profile.get("owns") else "нет")
            else:
                print("Вход: временно через лаунчер Horizon (своего client ID Azure ещё нет)")
                try:
                    owner = horizon_bridge.owner_account()
                    print("Аккаунт:", owner["name"] if owner else "нет аккаунта с купленной игрой")
                except horizon_bridge.BridgeError as e:
                    print("Аккаунт:", e)
            for warning in system.warnings():
                print("Внимание:", warning)
        elif args.cmd == "play":
            proc = play.play(_progress)
            print()
            message = game.exit_message(proc.wait())
            if message:
                print(message, file=sys.stderr)
                return 1
    except account.AuthError as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"\nОшибка: {e}", file=sys.stderr)
        return 1
    return 0
