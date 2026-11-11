"""The Microsoft account the player signs in with, and its Minecraft session.

Microsoft's device-code sign-in, then Xbox Live, XSTS and the Minecraft services, as the official launcher
and Horizon's do. Honoka starts the game only for an account that owns Minecraft: Java Edition (Horizon's
owner gate, docs/api/launch-guide.md step 0): it never starts it without one.

account.json keeps the profile and the tokens. The tokens are protected with Windows' DPAPI (readable only
by this Windows user) and, elsewhere, kept in a file only this user can read.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Callable

from . import config, net, paths

MICROSOFT = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
XBOX_USER = "https://user.auth.xboxlive.com/user/authenticate"
XSTS = "https://xsts.auth.xboxlive.com/xsts/authorize"
MINECRAFT = "https://api.minecraftservices.com"
SCOPE = "XboxLive.signin offline_access"
# A Minecraft token is renewed when it has less than this left.
MARGIN = 10 * 60


class AuthError(Exception):
    pass


class NotOwner(AuthError):
    pass


@dataclass
class DeviceCode:
    user_code: str
    verification_uri: str
    device_code: str
    interval: int
    expires_at: float


@dataclass
class Session:
    name: str
    uuid: str
    access_token: str
    xuid: str | None

    def game_json(self) -> str:
        """The session JSON horizon-client reads on standard input (Launch API)."""
        body = {"name": self.name, "uuid": self.uuid, "access_token": self.access_token, "user_type": "msa"}
        if self.xuid:
            body["xuid"] = self.xuid
        return json.dumps(body)


# --- Protecting the tokens on disk ------------------------------------------------------------------------

def _protect(data: bytes) -> str:
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(data, protect=True)).decode()
    return "plain:" + base64.b64encode(data).decode()


def _unprotect(text: str) -> bytes:
    kind, _, body = text.partition(":")
    raw = base64.b64decode(body)
    if kind == "dpapi":
        return _dpapi(raw, protect=False)
    if kind == "plain":
        return raw
    raise ValueError("unknown protection")


def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # UI_FORBIDDEN
    if not ok:
        raise OSError("Windows could not protect the account's tokens")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _write_private(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# --- The stored account -----------------------------------------------------------------------------------

def load() -> dict | None:
    try:
        stored = json.loads(paths.account_file().read_text(encoding="utf-8"))
        stored["secrets"] = json.loads(_unprotect(stored["secrets"]))
        return stored
    except (OSError, ValueError, KeyError):
        return None


def _save(profile: dict, secrets: dict) -> None:
    body = {**profile, "secrets": _protect(json.dumps(secrets).encode())}
    _write_private(paths.account_file(), json.dumps(body, indent=2, ensure_ascii=False))


def sign_out() -> None:
    try:
        paths.account_file().unlink()
    except FileNotFoundError:
        pass


def signed_in() -> dict | None:
    """The account's profile (name, uuid, owns), without secrets; None when nobody is signed in."""
    stored = load()
    if not stored:
        return None
    return {k: stored[k] for k in ("name", "uuid", "owns") if k in stored}


# --- Microsoft -------------------------------------------------------------------------------------------

def _client_id() -> str:
    client_id = config.msa_client_id()
    if not client_id:
        raise AuthError(
            "В этой сборке Honoka не настроен вход Microsoft (нет client ID приложения Azure). См. README, «Вход»."
        )
    return client_id


def start_device_code() -> DeviceCode:
    status, body = net.request_json(f"{MICROSOFT}/devicecode", form={"client_id": _client_id(), "scope": SCOPE})
    if status != 200 or not body:
        raise AuthError(f"Microsoft не начал вход ({status}).")
    return DeviceCode(
        user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        device_code=body["device_code"],
        interval=int(body.get("interval", 5)),
        expires_at=time.time() + int(body.get("expires_in", 900)),
    )


def finish_device_code(code: DeviceCode, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Waits until the player signed in on Microsoft's page, then completes the sign-in. Returns the profile."""
    interval = code.interval
    while True:
        if cancelled():
            raise AuthError("Вход отменён.")
        if time.time() > code.expires_at:
            raise AuthError("Код входа устарел. Попробуйте ещё раз.")
        time.sleep(interval)
        status, body = net.request_json(
            f"{MICROSOFT}/token",
            form={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": _client_id(),
                "device_code": code.device_code,
            },
        )
        error = (body or {}).get("error")
        if status == 200 and body and body.get("access_token"):
            return _complete(body)
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "authorization_declined":
            raise AuthError("Вход отклонён на странице Microsoft.")
        if error == "expired_token":
            raise AuthError("Код входа устарел. Попробуйте ещё раз.")
        raise AuthError(f"Microsoft отказал во входе ({error or status}).")


def _refresh_microsoft(refresh_token: str) -> dict:
    status, body = net.request_json(
        f"{MICROSOFT}/token",
        form={
            "grant_type": "refresh_token",
            "client_id": _client_id(),
            "refresh_token": refresh_token,
            "scope": SCOPE,
        },
    )
    if status != 200 or not body or not body.get("access_token"):
        raise AuthError("Вход устарел: войдите в аккаунт Microsoft снова.")
    # Microsoft may or may not hand out a new refresh token: keep the old one when it doesn't.
    if not body.get("refresh_token"):
        body["refresh_token"] = refresh_token
    return body


# --- Xbox Live and the Minecraft services ------------------------------------------------------------------

XSTS_ERRORS = {
    2148916233: "У этого аккаунта Microsoft нет профиля Xbox. Создайте его на xbox.com и войдите снова.",
    2148916235: "Xbox Live недоступен в стране этого аккаунта.",
    2148916236: "Аккаунту нужна проверка возраста на xbox.com.",
    2148916237: "Аккаунту нужна проверка возраста на xbox.com.",
    2148916238: "Это детский аккаунт: взрослый должен добавить его в семью Microsoft.",
}


def _minecraft_login(ms_access: str) -> tuple[str, float, str | None]:
    """(Minecraft token, when it expires, xuid) from a Microsoft access token."""
    status, xbl = net.request_json(
        XBOX_USER,
        json_body={
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com", "RpsTicket": f"d={ms_access}"},
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
        },
    )
    if status != 200 or not xbl or not xbl.get("Token"):
        raise AuthError("Xbox Live отказал во входе.")
    status, xsts = net.request_json(
        XSTS,
        json_body={
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
            "RelyingParty": "rp://api.minecraftservices.com/",
            "TokenType": "JWT",
        },
    )
    if xsts and xsts.get("XErr"):
        raise AuthError(XSTS_ERRORS.get(xsts["XErr"], f"Xbox Live отказал во входе ({xsts['XErr']})."))
    try:
        claims = xsts["DisplayClaims"]["xui"][0]
        uhs, token = claims["uhs"], xsts["Token"]
    except (TypeError, KeyError, IndexError):
        raise AuthError("Xbox Live отказал во входе.") from None
    if status != 200:
        raise AuthError("Xbox Live отказал во входе.")
    xtoken = f"XBL3.0 x={uhs};{token}"
    # launcher/login first: login_with_xbox gives a new account a token without its profile.
    status, mc = net.request_json(f"{MINECRAFT}/launcher/login", json_body={"xtoken": xtoken, "platform": "PC_LAUNCHER"})
    if status != 200 or not mc or not mc.get("access_token"):
        status, mc = net.request_json(f"{MINECRAFT}/authentication/login_with_xbox", json_body={"identityToken": xtoken})
    if status == 403:
        raise AuthError("Сервисы Minecraft не пускают этот лаунчер: его приложение ещё не одобрено Mojang.")
    if status == 429:
        raise AuthError("Слишком много входов подряд. Подождите минуту.")
    if status != 200 or not mc or not mc.get("access_token"):
        raise AuthError("Сервисы Minecraft отказали во входе.")
    return mc["access_token"], time.time() + int(mc.get("expires_in", 86400)), claims.get("xid")


def _owns_game(token: str) -> bool:
    status, body = net.request_json(f"{MINECRAFT}/entitlements/mcstore", headers={"Authorization": f"Bearer {token}"})
    if status != 200 or body is None:
        raise AuthError("Не удалось проверить, какие игры есть у аккаунта.")
    return any(i.get("name") in ("game_minecraft", "product_minecraft") for i in body.get("items", []))


def _profile(token: str) -> dict | None:
    status, body = net.request_json(f"{MINECRAFT}/minecraft/profile", headers={"Authorization": f"Bearer {token}"})
    if status == 404:
        return None
    if status != 200 or not body or "id" not in body:
        raise AuthError("Не удалось прочитать профиль Minecraft.")
    return {"uuid": body["id"].replace("-", "").lower(), "name": body["name"]}


def _complete(ms: dict) -> dict:
    mc_token, expires_at, xuid = _minecraft_login(ms["access_token"])
    owns = _owns_game(mc_token)
    profile = _profile(mc_token) if owns else None
    if profile is None:
        owns = False
        profile = {"uuid": "", "name": ""}
    profile["owns"] = owns
    _save(
        profile,
        {
            "refresh_token": ms.get("refresh_token", ""),
            "minecraft_token": mc_token,
            "minecraft_expires_at": expires_at,
            "xuid": xuid,
        },
    )
    if not owns:
        raise NotOwner("На этом аккаунте Microsoft нет Minecraft: Java Edition. Honoka играет только с купленной игрой.")
    return profile


def session() -> Session:
    """The signed-in owner's Minecraft session, renewed when it is about to expire."""
    stored = load()
    if not stored:
        raise AuthError("Войдите в аккаунт Microsoft.")
    secrets = stored["secrets"]
    if not stored.get("owns") or secrets.get("minecraft_expires_at", 0) - MARGIN < time.time():
        if not secrets.get("refresh_token"):
            raise AuthError("Вход устарел: войдите в аккаунт Microsoft снова.")
        _complete(_refresh_microsoft(secrets["refresh_token"]))
        stored = load()
        secrets = stored["secrets"]
    if not stored.get("owns"):
        raise NotOwner("На этом аккаунте Microsoft нет Minecraft: Java Edition. Honoka играет только с купленной игрой.")
    return Session(stored["name"], stored["uuid"], secrets["minecraft_token"], secrets.get("xuid"))
