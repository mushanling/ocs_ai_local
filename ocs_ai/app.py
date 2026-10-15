import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import secrets
import time

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .quiz import Question, SYSTEM_PROMPT, image_urls, messages, parse_answer
from .store import Store


def create_app(settings: Settings | None = None, transport=None):
    settings = settings or Settings.load()
    store = Store(settings.db_path)
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=transport, timeout=settings.timeout, follow_redirects=False) as client:
            app.state.client = client
            yield

    app = FastAPI(title="OCS AI Local", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_api(request: Request, call_next):
        # CORS is needed only for the OCS search endpoint; model credentials stay server-side.
        cors = request.url.path == "/api/search"
        if request.method == "OPTIONS" and cors:
            response = JSONResponse({"ok": True})
        else:
            response = await call_next(request)
        if cors:
            response.headers.update({
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Private-Network": "true",
            })
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    def authorized(request):
        return secrets.compare_digest(request.headers.get("Authorization", ""), f"Bearer {settings.token}")

    def denied():
        return JSONResponse({"code": 1, "msg": "本地访问 Token 不正确"}, status_code=401)

    @app.get("/")
    async def home():
        return FileResponse(ROOT / "ocs_ai/static/index.html")

    @app.get("/app.js")
    async def script():
        return FileResponse(ROOT / "ocs_ai/static/app.js", media_type="text/javascript")

    @app.get("/style.css")
    async def stylesheet():
        return FileResponse(ROOT / "ocs_ai/static/style.css", media_type="text/css")

    @app.get("/api/health")
    async def health():
        return {"ok": True, "configured": bool(settings.api_key), "model": settings.model,
                "thinking": settings.thinking, "effort": settings.effort, "vision": settings.vision}

    @app.get("/ocs-config.json")
    async def config():
        origin = f"http://127.0.0.1:{settings.port}"
        # Use a fixed loopback URL; never trust an incoming Host to generate the configuration.
        return [{"name": "本地 AI 题库", "homepage": origin, "url": origin + "/api/search",
                 "method": "post", "contentType": "json", "type": "GM_xmlhttpRequest",
                 "headers": {"Content-Type": "application/json", "Authorization": f"Bearer {settings.token}"},
                 "data": {"title": "${title}", "options": "${options}", "type": "${type}"},
                 "handler": "return (res)=> res.code === 0 ? [res.data.question, res.data.answers.join('#'), { ai: true, tags: res.data.tags }] : [res.msg, undefined]"}]

    @app.get("/api/logs")
    async def logs(request: Request):
        return {"code": 0, "data": store.logs()} if authorized(request) else denied()

    @app.delete("/api/cache")
    async def clear(request: Request):
        if not authorized(request):
            return denied()
        store.clear()
        return {"code": 0, "msg": "缓存已清空"}

    @app.post("/api/search")
    async def search(request: Request):
        if not authorized(request):
            return denied()
        started = time.monotonic()
        question = None
        try:
            # Bound incoming body before parsing (including data URL images).
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ValueError("请求超过 8 MiB 上限")
                chunks.append(chunk)
            question = Question.model_validate_json(b"".join(chunks))
            if not question.title.strip():
                raise ValueError("题目不能为空")
            images = image_urls(question)
            if images and not settings.vision:
                raise ValueError("本题含图片，请启用 VISION_ENABLED；不会跳过图片猜答案")
            fingerprint = {"question": question.model_dump(), "base": settings.base_url, "model": settings.model,
                           "thinking": settings.thinking, "effort": settings.effort, "prompt": SYSTEM_PROMPT,
                           "vision": settings.vision, "max_tokens": settings.max_tokens}
            key = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            # A shared total deadline bounds queueing and upstream time; identical requests reuse cache.
            async with asyncio.timeout(settings.timeout):
                async with lock:
                    cached = store.get(key, settings.cache_ttl) if settings.cache else None
                    if cached:
                        result = {**cached, "cached": True, "usage": {}}
                    else:
                        if not settings.api_key:
                            raise ValueError("请先在 .env 填写 LLM_API_KEY 并重启服务")
                        body = {"model": settings.model, "messages": messages(question, images),
                                "response_format": {"type": "json_object"}, "max_tokens": settings.max_tokens,
                                "stream": False}
                        if settings.thinking != "omit":
                            body["thinking"] = {"type": settings.thinking}
                        if settings.thinking != "disabled" and settings.effort:
                            body["reasoning_effort"] = settings.effort
                        response = await app.state.client.post(settings.base_url.rstrip("/") + "/chat/completions",
                            headers={"Authorization": f"Bearer {settings.api_key}"}, json=body)
                        if response.status_code != 200:
                            # Do not echo provider response bodies: they may contain credentials or prompt data.
                            raise ValueError(f"模型接口返回 HTTP {response.status_code}，请检查配置、额度或服务状态")
                        payload = response.json()
                        choice = payload["choices"][0]
                        if choice.get("finish_reason") != "stop":
                            raise ValueError("模型答案未完整生成或被拦截，请检查 LLM_MAX_TOKENS")
                        answers, reason = parse_answer(choice["message"]["content"], question)
                        usage = payload.get("usage") or {}
                        result = {"question": question.title, "answers": answers, "reason": reason,
                                  "model": settings.model, "cached": False,
                                  "usage": {k: v for k, v in usage.items() if k in {"prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens"}},
                                  "tags": [settings.model, settings.thinking, settings.effort]}
                        if settings.cache:
                            store.put(key, result)
            result["latency_ms"] = round((time.monotonic() - started) * 1000)
            store.log({"status": "ok", "type": question.type, "options": question.options, **result})
            return {"code": 0, "data": result}
        except ValidationError:
            message = "题目格式无效：仅允许 title、options、type、images，type 使用 OCS 英文题型"
        except (TimeoutError, httpx.TimeoutException):
            message = "搜题超时，请降低并发、调整总超时或稍后重试"
        except httpx.RequestError:
            message = "无法连接模型接口，请检查 LLM_BASE_URL 和网络"
        except ValueError as exc:
            message = str(exc)
        except (KeyError, IndexError, TypeError):
            message = "模型接口响应结构无效"
        # Never log raw provider content or API configuration supplied by the client.
        message = message.replace(settings.api_key, "[redacted]") if settings.api_key else message
        store.log({"status": "error", "question": question.title if question else "", "msg": message,
                   "latency_ms": round((time.monotonic() - started) * 1000)})
        return {"code": 1, "msg": message}

    return app
