"""Local-only ChatGPT plan connection verifier. No API-key billing fallback."""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

AUTH = "https://auth.openai.com"
API = "https://api.openai.com/v1"
APP_NAME = "GPT Selection Translator"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


class VerificationError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, *, form=None, payload=None, bearer=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"auth.openai.com", "api.openai.com"} or parsed.port not in (None, 443):
        raise VerificationError("拒绝连接非官方接口。")
    headers = {"Accept": "application/json", "User-Agent": "GPT-Selection-Translator/0.1"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if payload is not None:
        data = json.dumps(payload).encode()
        headers.update({"Content-Type": "application/json", "Accept": "text/event-stream"})
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        return urllib.request.build_opener(NoRedirect()).open(req, timeout=35)
    except urllib.error.HTTPError as e:
        code = ""
        try:
            obj = json.loads(e.read(65536))
            err = obj.get("error", {})
            code = err.get("code", "") if isinstance(err, dict) else err
        except (ValueError, AttributeError):
            pass
        code = code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", code) else ""
        raise VerificationError(f"官方接口返回 HTTP {e.code}" + (f"（{code}）" if code else "") + "。") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise VerificationError("连接官方接口失败或超时，请检查网络后重试。") from None


def get_json(url, **kwargs):
    with request(url, **kwargs) as response:
        return json.loads(response.read(2_000_000))


def b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def b64encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def validate_identity(token, client_id, nonce, jwks):
    """Accept only a signed RS256 ID token for this exact login transaction."""
    try:
        if not isinstance(token, str) or len(token) > 32000:
            raise ValueError()
        header64, claims64, sig64 = token.split(".")
        header = json.loads(b64decode(header64))
        claims = json.loads(b64decode(claims64))
        if header.get("alg") != "RS256" or header.get("crit"):
            raise ValueError()
        key = next(k for k in jwks["keys"] if k.get("kid") == header.get("kid") and k.get("kty") == "RSA" and k.get("use", "sig") == "sig")
        if key.get("alg", "RS256") != "RS256" or "verify" not in key.get("key_ops", ["verify"]):
            raise ValueError()
        public = rsa.RSAPublicNumbers(int.from_bytes(b64decode(key["e"]), "big"), int.from_bytes(b64decode(key["n"]), "big")).public_key()
        public.verify(b64decode(sig64), (header64 + "." + claims64).encode(), padding.PKCS1v15(), hashes.SHA256())
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        now = time.time()
        if claims.get("iss") != AUTH or client_id not in audiences:
            raise ValueError()
        if len(audiences) > 1 and claims.get("azp") != client_id:
            raise ValueError()
        if claims.get("azp", client_id) != client_id:
            raise ValueError()
        if not isinstance(claims.get("exp"), (float, int)) or claims["exp"] <= now:
            raise ValueError()
        if not isinstance(claims.get("iat"), (float, int)) or claims["iat"] > now + 60:
            raise ValueError()
        if claims.get("nbf", 0) > now + 60:
            raise ValueError()
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError()
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
            raise ValueError()
        return claims
    except Exception:
        raise VerificationError("登录身份校验未通过，未保存新凭据。请重新登录。") from None


def dpapi(data: bytes, decrypt=False):
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), "GPT Selection Translator", None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise VerificationError("Windows 凭据加密或解密失败。")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def atomic_write(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def read_stream(response, on_delta=None):
    result = []
    for raw in response:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        event = json.loads(data)
        kind = event.get("type")
        if kind == "response.output_text.delta":
            delta = event.get("delta", "")
            result.append(delta)
            if on_delta:
                on_delta(delta)
        if kind in {"error", "response.failed", "response.incomplete"}:
            code = event.get("code") or (event.get("response", {}).get("error") or {}).get("code", "")
            code = code if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", code) else kind
            raise VerificationError("翻译请求未完成（" + code + "）。")
        if kind == "response.completed":
            completed = event.get("response", {})
            if completed.get("status", "completed") != "completed":
                raise VerificationError("翻译请求没有成功完成。")
            text = "".join(result)
            if not text:
                text = "".join(part.get("text", "") for item in completed.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text")
            if not text.strip():
                raise VerificationError("请求已完成，但没有返回译文。")
            return text
    raise VerificationError("连接中断，尚未收到完成确认。")


class App:
    def __init__(self, state_dir):
        self.directory = Path(state_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        host = self.directory / "host-id.txt"
        if not host.exists():
            atomic_write(host, ("urn:uuid:" + str(uuid.uuid4())).encode())
        self.host_id = host.read_text().strip()
        self.lock = threading.RLock()
        self.csrf = secrets.token_urlsafe(32)
        self.pending = None
        self.account = None
        self.retry_client = None
        self.busy = False
        self.status = {"phase": "ready", "message": "等待你使用 ChatGPT 登录。", "verified": False, "translation": "", "model": ""}
        self.set_status()

    def set_status(self, **changes):
        with self.lock:
            self.status.update(changes)
            atomic_write(self.directory / "status.json", json.dumps(self.status, ensure_ascii=False, indent=2).encode())

    def authorization(self, origin):
        with self.lock:
            if self.busy:
                raise VerificationError("正在验证账号，请等待本次检查完成。")
            verifier = secrets.token_urlsafe(48)
            pending = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32), "verifier": verifier,
                       "redirect_uri": origin + "/auth/callback", "expires": time.time() + 600}
            saved = self.directory / "account.dpapi"
            account = json.loads(dpapi(saved.read_bytes(), decrypt=True)) if saved.exists() else None
            client = account["client_id"] if account else (self.retry_client or "dynamic_agent_client")
            pending.update(client_id=client, subject=account.get("subject") if account else None)
            self.pending = pending
            params = {"client_id": client, "ext_agent_host_id": self.host_id, "response_type": "code",
                      "redirect_uri": pending["redirect_uri"], "scope": SCOPES, "resource": API,
                      "state": pending["state"], "nonce": pending["nonce"], "code_challenge_method": "S256",
                      "code_challenge": b64encode(hashlib.sha256(verifier.encode()).digest())}
            if client == "dynamic_agent_client":
                params["agent_name_hint"] = APP_NAME
            self.set_status(phase="waiting", message="请在 OpenAI 官方页面完成登录和授权。", verified=False, translation="")
            return AUTH + "/api/accounts/authorize?" + urllib.parse.urlencode(params)

    def consume_callback(self, query):
        values = urllib.parse.parse_qs(query, keep_blank_values=True, max_num_fields=20)
        if any(len(v) != 1 for v in values.values()):
            raise VerificationError("登录回调格式无效。")
        value = lambda name: values.get(name, [""])[0]
        with self.lock:
            pending = self.pending
            if not pending or pending["expires"] < time.time() or not hmac.compare_digest(value("state"), pending["state"]):
                raise VerificationError("登录请求不匹配或已过期，请重新登录。")
            self.pending = None
            if value("error"):
                raise VerificationError("登录或套餐授权没有完成；没有发送翻译请求。")
            issued = value("client_id") or pending["client_id"]
            if not issued or issued == "dynamic_agent_client" or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", issued):
                raise VerificationError("官方没有返回有效的应用注册标识。")
            if pending["client_id"] != "dynamic_agent_client" and issued != pending["client_id"]:
                raise VerificationError("返回的应用注册标识不匹配。")
            self.retry_client = issued
            if not value("code"):
                raise VerificationError("登录回调缺少授权码。")
            self.busy = True
            self.set_status(phase="checking", message="正在检查套餐权限并试译固定测试句……")
        threading.Thread(target=self.complete, args=(pending, issued, value("code")), daemon=True).start()

    def complete(self, pending, issued, code):
        try:
            tokens = get_json(AUTH + "/api/accounts/oauth/token", form={"grant_type": "authorization_code", "client_id": issued,
                "code": code, "code_verifier": pending["verifier"], "redirect_uri": pending["redirect_uri"], "resource": API})
            claims = validate_identity(tokens.get("id_token"), issued, pending["nonce"], get_json(AUTH + "/.well-known/jwks.json"))
            if pending["subject"] and claims["sub"] != pending["subject"]:
                raise VerificationError("返回的账号与原来保存的账号不同，未替换凭据。")
            scopes = tokens.get("scope", "").split()
            if "chatgpt.tokens.use.direct" not in scopes:
                raise VerificationError("登录成功，但未获得使用 ChatGPT 套餐的权限。")
            if not tokens.get("access_token") or tokens.get("token_type", "").lower() != "bearer":
                raise VerificationError("官方没有返回有效的访问凭据。")
            account = {**tokens, "client_id": issued, "subject": claims["sub"], "issuer": AUTH, "ext_agent_host_id": self.host_id, "saved_at": time.time()}
            atomic_write(self.directory / "account.dpapi", dpapi(json.dumps(account).encode()))
            self.account = account
            catalog = get_json(API + "/models", bearer=tokens["access_token"])
            models = [m for m in catalog.get("models", []) if m.get("visibility") == "list" and m.get("slug")]
            if not models:
                raise VerificationError("已获得套餐权限，但账号未返回可用模型，尚未验证翻译。")
            model = models[0]
            self.set_status(model=model.get("display_name") or model["slug"], message="已获得套餐权限，正在试译 Hello, world!……")
            payload = {"model": model["slug"], "input": [{"role": "user", "content": "Translate into Simplified Chinese. Return only the translation: Hello, world!"}], "store": False, "stream": True}
            with request(API + "/responses", payload=payload, bearer=tokens["access_token"]) as response:
                translated = read_stream(response)
            self.set_status(phase="success", message="验证成功：ChatGPT 套餐已完成一次翻译请求。", verified=True, translation=translated)
        except VerificationError as e:
            self.set_status(phase="error", message=str(e), verified=False)
        except Exception:
            self.set_status(phase="error", message="验证未完成。没有切换到 API Key，也没有尝试额外计费方式。", verified=False)
        finally:
            with self.lock:
                self.busy = False


PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GPT 划词翻译 · 连接验证</title>
<style nonce="NONCE">*{box-sizing:border-box}body{margin:0;background:#f5f6f4;color:#18312b;font:16px/1.7 'Microsoft YaHei',sans-serif}main{max-width:760px;margin:8vh auto;padding:36px}small{color:#58756b;letter-spacing:.12em}h1{font-size:34px;letter-spacing:-1px;margin:12px 0}p{color:#53695f}section{background:white;border:1px solid #dce5dd;border-radius:22px;padding:30px;margin-top:28px;box-shadow:0 12px 35px #18312b08}button{border:0;border-radius:12px;background:#185a46;color:white;padding:14px 24px;font:inherit;cursor:pointer}button:disabled{background:#83958d;cursor:wait}.label{font-size:13px;font-weight:bold;color:#708479;text-transform:uppercase}#message{font-size:18px;white-space:pre-wrap}#result{font-size:26px;white-space:pre-wrap;background:#f0f6ef;border-radius:12px;padding:20px;display:none}.note{font-size:13px;margin-top:24px}footer{margin-top:24px;color:#76887e;font-size:13px}.pill{display:inline-block;background:#e8eee8;border-radius:30px;padding:4px 12px;font-size:13px}</style>
<main><small>GPT SELECTION TRANSLATOR</small><h1>先连接你的 ChatGPT 套餐</h1><p>确认 Plus 可以用于本地翻译，然后再接上划词与译文浮窗。</p><span class="pill">本机连接验证 · 无需 API Key</span>
<section><div class="label">01 / 官方登录与授权</div><p>点击后进入 OpenAI 官方页面。请自行输入密码、验证码，并检查授权内容。若跳转没有完成，可重新点击；这会取消上次未完成的登录。</p><form method="post" action="/login"><input type="hidden" name="csrf" value="CSRF"><button id="login">Continue with ChatGPT</button></form><p class="note">授权后将自动试译固定句子 “Hello, world!”。这会使用少量 ChatGPT 套餐用量。程序没有 API Key 计费后备路径。</p></section>
<section><div class="label">02 / 验证结果</div><p id="message">读取状态中……</p><p id="model"></p><div id="result"></div></section>
<footer>仅监听本机地址。凭据由 Windows 加密保存在本机工作目录，不会显示在页面或日志中。此版本用于连接验证，尚未启用全局划词。</footer></main>
<script nonce="NONCE">async function poll(){try{const r=await fetch('/status',{cache:'no-store'});const s=await r.json();document.getElementById('message').textContent=s.message;document.getElementById('model').textContent=s.model?'测试模型：'+s.model:'';const o=document.getElementById('result');o.textContent=s.translation;o.style.display=s.translation?'block':'none';document.getElementById('login').disabled=s.phase==='checking'}catch(e){}setTimeout(poll,1800)}poll();</script></html>"""


def serve(app, port=0):
    nonce = secrets.token_urlsafe(24)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # OAuth callback queries must never enter access logs.

        def respond(self, code, body=b"", kind="text/html; charset=utf-8", location=None):
            self.send_response(code)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer" if self.path.startswith("/auth/callback") else "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; connect-src 'self'; form-action 'self' https://auth.openai.com; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            return self.headers.get("Host") == urllib.parse.urlsplit(self.server.origin).netloc

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403)
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/":
                return self.respond(200, PAGE.replace("NONCE", nonce).replace("CSRF", app.csrf).encode())
            if url.path == "/status":
                with app.lock:
                    if app.pending and app.pending["expires"] < time.time():
                        app.pending = None
                        app.set_status(phase="error", message="登录等待已超时，请重新点击登录。")
                    body = json.dumps(app.status, ensure_ascii=False).encode()
                return self.respond(200, body, "application/json; charset=utf-8")
            if url.path == "/auth/callback":
                try:
                    app.consume_callback(url.query)
                except VerificationError as e:
                    # Invalid or unsolicited callbacks do not replace an active login.
                    with app.lock:
                        if app.pending is None and not app.busy and app.status["phase"] == "waiting":
                            app.set_status(phase="error", message=str(e))
                    return self.respond(400, ("<meta charset=utf-8><p>" + str(e) + "</p><a href='/'>返回验证页面</a>").encode())
                return self.respond(303, location="/")
            return self.respond(404)

        def do_POST(self):
            if not self.valid_host() or self.path != "/login":
                return self.respond(403)
            if self.headers.get("Origin") != self.server.origin:
                return self.respond(403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 2048:
                    return self.respond(400)
                form = urllib.parse.parse_qs(self.rfile.read(length).decode())
                if not hmac.compare_digest(form.get("csrf", [""])[0], app.csrf):
                    return self.respond(403)
                return self.respond(303, location=app.authorization(self.server.origin))
            except VerificationError as e:
                app.set_status(phase="error", message=str(e))
                return self.respond(303, location="/")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.origin = "http://127.0.0.1:" + str(server.server_port)
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", default=str(Path(__file__).resolve().parent / "data"))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    # A second launch opens the running verifier instead of replacing its state.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    name = "Local\\GPTSelectionTranslator-" + hashlib.sha256(str(Path(args.state_dir).resolve()).lower().encode()).hexdigest()[:24]
    mutex = kernel.CreateMutexW(None, False, name)
    if not mutex:
        raise VerificationError("无法启动本地验证服务。")
    if ctypes.get_last_error() == 183:
        info = json.loads((Path(args.state_dir) / "server.json").read_text())
        url = urllib.parse.urlsplit(info["url"])
        if url.scheme == "http" and url.hostname == "127.0.0.1" and url.port and not url.path and not url.query and not url.fragment:
            webbrowser.open(info["url"])
        kernel.CloseHandle(mutex)
        return
    app = App(args.state_dir)
    server = serve(app, args.port)
    atomic_write(app.directory / "server.json", json.dumps({"url": server.origin, "pid": os.getpid()}).encode())
    print(server.origin, flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(server.origin)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
