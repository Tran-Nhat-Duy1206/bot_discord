import os
import json
import asyncio
import base64
import io
import urllib.request
import urllib.error
import time
import random
from collections import deque

import discord
from discord import app_commands
from discord.ext import commands


AI_API_URL = os.getenv("AI_API_URL", "https://api.openai.com/v1/chat/completions")
AI_IMAGE_API_URL = os.getenv("AI_IMAGE_API_URL", "https://api.openai.com/v1/images/generations")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini")
AI_IMAGE_MODEL = os.getenv("AI_IMAGE_MODEL", "gpt-image-1")

AI_TIMEOUT_SEC = int(os.getenv("AI_TIMEOUT_SEC", "35"))
AI_MAX_INPUT_CHARS = int(os.getenv("AI_MAX_INPUT_CHARS", "6000"))
AI_MAX_OUTPUT_CHARS = int(os.getenv("AI_MAX_OUTPUT_CHARS", "3500"))
AI_MEMORY_CHANNEL_MESSAGES = int(os.getenv("AI_MEMORY_CHANNEL_MESSAGES", "12"))
AI_IMAGE_SIZE = os.getenv("AI_IMAGE_SIZE", "1024x1024")

AI_SEMAPHORE = asyncio.Semaphore(2)
AI_CHANNEL_MEMORY: dict[int, deque[dict]] = {}


def _trim(text: str, n: int) -> str:
    t = (text or "").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


def _extract_text(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return ""


def _channel_history(channel_id: int) -> deque[dict]:
    if channel_id not in AI_CHANNEL_MEMORY:
        AI_CHANNEL_MEMORY[channel_id] = deque(maxlen=max(2, AI_MEMORY_CHANNEL_MESSAGES))
    return AI_CHANNEL_MEMORY[channel_id]


def _memory_add(channel_id: int, role: str, content: str):
    if channel_id <= 0:
        return
    c = _trim(content, AI_MAX_INPUT_CHARS)
    if not c:
        return
    hist = _channel_history(channel_id)
    hist.append({"role": role, "content": c})


def _chat_messages_sync(messages, temperature=0.4, max_tokens=700):
    if not AI_API_KEY:
        raise RuntimeError("Thiếu AI_API_KEY")

    payload = {
        "model": AI_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }

    req = urllib.request.Request(
        AI_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AI_API_KEY}",
        },
    )

    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SEC) as resp:
                data = json.loads(resp.read().decode())

            out = _extract_text(data)
            if not out:
                raise RuntimeError("AI không trả về nội dung")

            return _trim(out, AI_MAX_OUTPUT_CHARS)

        except urllib.error.HTTPError as e:
            body = ""
            err_code = ""
            err_msg = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
                payload = json.loads(body) if body else {}
                err = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(err, dict):
                    err_code = str(err.get("code") or "")
                    err_msg = str(err.get("message") or "")
            except Exception:
                pass

            # quota hết thì trả lỗi rõ ràng, không retry vô ích
            if err_code == "insufficient_quota":
                raise RuntimeError(
                    "AI đang hết quota/billing. Vui lòng nạp credit hoặc đổi AI_API_KEY khác còn quota."
                )

            # rate limit tạm thời thì retry
            if e.code == 429:
                wait = (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
                if attempt == 4:
                    raise RuntimeError(
                        "AI đang bị rate limit. Thử lại sau ít phút."
                    )
                continue

            if err_msg:
                raise RuntimeError(f"AI API HTTP {e.code}: {err_msg}")
            raise RuntimeError(f"AI API HTTP {e.code}")

        except Exception as e:
            if attempt == 4:
                raise RuntimeError(str(e))
            time.sleep(1)


def _chat_sync(system_prompt, user_prompt, temperature=0.4, max_tokens=700):
    return _chat_messages_sync(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def _chat(system_prompt, user_prompt, temperature=0.4, max_tokens=700):
    user_prompt = _trim(user_prompt, AI_MAX_INPUT_CHARS)

    async with AI_SEMAPHORE:  # 🔥 chống spam
        return await asyncio.to_thread(
            _chat_sync,
            system_prompt,
            user_prompt,
            temperature,
            max_tokens,
        )


async def _chat_with_memory(channel_id: int, system_prompt: str, user_prompt: str, temperature=0.4, max_tokens=700):
    user_prompt = _trim(user_prompt, AI_MAX_INPUT_CHARS)
    hist = list(_channel_history(channel_id))
    msgs = [{"role": "system", "content": system_prompt}] + hist + [{"role": "user", "content": user_prompt}]

    async with AI_SEMAPHORE:
        ans = await asyncio.to_thread(_chat_messages_sync, msgs, temperature, max_tokens)

    _memory_add(channel_id, "user", user_prompt)
    _memory_add(channel_id, "assistant", ans)
    return ans


def _embed(title, content):
    e = discord.Embed(
        title=title,
        description=_trim(content, 3900),
        color=discord.Color.blurple(),
    )
    e.set_footer(text=f"Model: {AI_MODEL}")
    return e


def _image_generate_sync(prompt: str) -> tuple[str, bytes | None]:
    if not AI_API_KEY:
        raise RuntimeError("Thiếu AI_API_KEY")

    payload = {
        "model": AI_IMAGE_MODEL,
        "prompt": _trim(prompt, AI_MAX_INPUT_CHARS),
        "size": AI_IMAGE_SIZE,
    }

    req = urllib.request.Request(
        AI_IMAGE_API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {AI_API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"AI image HTTP {e.code}: {body[:300]}")

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise RuntimeError("AI image không trả dữ liệu")

    first = items[0] if isinstance(items[0], dict) else {}
    url = str(first.get("url") or "").strip()
    b64 = str(first.get("b64_json") or "").strip()
    if b64:
        try:
            return "", base64.b64decode(b64)
        except Exception:
            pass
    if url:
        return url, None
    raise RuntimeError("AI image không có url/b64_json")


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []

    @bot.tree.command(name="ai_chat", description="Chat với AI")
    @app_commands.describe(prompt="Nội dung bạn muốn hỏi")
    @app_commands.checks.cooldown(1, 5)  # 🔥 chống spam user
    async def ai_chat(interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()

        try:
            channel_id = interaction.channel_id or 0
            ans = await _chat_with_memory(
                channel_id,
                "Bạn là trợ lý Discord, trả lời ngắn gọn, rõ ràng, tiếng Việt.",
                prompt,
                0.6,
                600,
            )
            await interaction.followup.send(embed=_embed("🤖 AI Chat", ans))

        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Lỗi AI",
                    description=str(e),
                    color=discord.Color.red(),
                ),
                ephemeral=True,
            )

    @bot.tree.command(name="ai_image", description="Tạo ảnh bằng AI")
    @app_commands.describe(prompt="Mô tả ảnh cần tạo")
    @app_commands.checks.cooldown(1, 8)
    async def ai_image(interaction: discord.Interaction, prompt: str):
        await interaction.response.defer()
        try:
            async with AI_SEMAPHORE:
                url, img_bytes = await asyncio.to_thread(_image_generate_sync, prompt)

            if img_bytes:
                f = discord.File(io.BytesIO(img_bytes), filename="ai-image.png")
                e = discord.Embed(title="🖼️ AI Image", description=_trim(prompt, 1000), color=discord.Color.blurple())
                e.set_image(url="attachment://ai-image.png")
                e.set_footer(text=f"Model: {AI_IMAGE_MODEL}")
                return await interaction.followup.send(embed=e, file=f)

            e = discord.Embed(title="🖼️ AI Image", description=_trim(prompt, 1000), color=discord.Color.blurple())
            e.set_image(url=url)
            e.set_footer(text=f"Model: {AI_IMAGE_MODEL}")
            await interaction.followup.send(embed=e)
        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Lỗi AI Image", description=str(e), color=discord.Color.red()),
                ephemeral=True,
            )

    @bot.tree.command(name="ai_memory_clear", description="Xóa memory AI của channel hiện tại")
    async def ai_memory_clear(interaction: discord.Interaction):
        cid = interaction.channel_id or 0
        AI_CHANNEL_MEMORY.pop(cid, None)
        await interaction.response.send_message("🧹 Đã xóa AI conversation memory của channel này.", ephemeral=True)

    @bot.tree.command(name="ai_summarize", description="Tóm tắt văn bản")
    @app_commands.checks.cooldown(1, 5)
    async def ai_summarize(interaction: discord.Interaction, text: str):
        await interaction.response.defer()

        try:
            ans = await _chat(
                "Tóm tắt nội dung rõ ràng, giữ ý chính.",
                text,
                0.3,
                700,
            )
            await interaction.followup.send(embed=_embed("📝 Summary", ans))

        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Lỗi", description=str(e), color=discord.Color.red()),
                ephemeral=True,
            )

    @bot.tree.command(name="ai_translate", description="Dịch văn bản")
    @app_commands.checks.cooldown(1, 5)
    async def ai_translate(interaction: discord.Interaction, text: str, lang: str = "English"):
        await interaction.response.defer()

        try:
            ans = await _chat(
                "Dịch tự nhiên, đúng ngữ cảnh.",
                f"Dịch sang {lang}:\n{text}",
                0.2,
                700,
            )
            await interaction.followup.send(embed=_embed("🌐 Translate", ans))

        except Exception as e:
            await interaction.followup.send(
                embed=discord.Embed(title="❌ Lỗi", description=str(e), color=discord.Color.red()),
                ephemeral=True,
            )

    @ai_chat.error
    @ai_summarize.error
    @ai_translate.error
    @ai_image.error
    async def on_app_command_error(interaction: discord.Interaction, error):
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ Bình tĩnh 😅 thử lại sau {error.retry_after:.1f}s",
                ephemeral=True,
            )
