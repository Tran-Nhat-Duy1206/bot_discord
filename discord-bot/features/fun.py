import json
import random
import asyncio
import html
import urllib.request

import discord
from discord import app_commands
from discord.ext import commands


def _embed(title: str, desc: str, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color)


def _get_json(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def setup(bot: commands.Bot, guilds: list = None):
    guilds = guilds or []
    @bot.tree.command(name="coinflip", description="Tung đồng xu")
    async def coinflip(interaction: discord.Interaction):
        result = random.choice(["Ngửa", "Sấp"])
        await interaction.response.send_message(embed=_embed("🪙 Coinflip", f"Kết quả: **{result}**"))

    @bot.tree.command(name="dice", description="Đổ xúc xắc")
    @app_commands.describe(sides="Số mặt xúc xắc", count="Số lần đổ")
    async def dice(interaction: discord.Interaction, sides: int = 6, count: int = 1):
        if sides < 2 or sides > 1000:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "`sides` phải từ 2 đến 1000."), ephemeral=True)
        if count < 1 or count > 20:
            return await interaction.response.send_message(embed=_embed("❌ Không hợp lệ", "`count` phải từ 1 đến 20."), ephemeral=True)

        rolls = [random.randint(1, sides) for _ in range(count)]
        text = ", ".join(str(x) for x in rolls)
        e = _embed("🎲 Dice", text)
        e.add_field(name="Total", value=str(sum(rolls)), inline=True)
        e.add_field(name="Sides", value=str(sides), inline=True)
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="8ball", description="Hỏi quả cầu tiên tri")
    @app_commands.describe(question="Câu hỏi yes/no")
    async def eightball(interaction: discord.Interaction, question: str):
        answers = [
            "Có, chắc chắn rồi.",
            "Không đâu.",
            "Khả năng cao là có.",
            "Mơ đi 😄",
            "Hỏi lại sau nhé.",
            "Tín hiệu đang mờ...",
            "Câu trả lời là: không rõ.",
            "Đúng, cứ làm đi.",
            "Không nên lúc này.",
            "Nghe có vẻ ổn đấy.",
        ]
        ans = random.choice(answers)
        e = _embed("🎱 8Ball", f"**Q:** {question}\n**A:** {ans}")
        await interaction.response.send_message(embed=e)

    @bot.tree.command(name="meme", description="Lấy meme ngẫu nhiên")
    async def meme(interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await asyncio.to_thread(_get_json, "https://meme-api.com/gimme")
            title = str(data.get("title") or "Meme")
            post_url = str(data.get("postLink") or "")
            img = str(data.get("url") or "")
            nsfw = bool(data.get("nsfw", False))

            if not img:
                return await interaction.followup.send(embed=_embed("❌ Meme", "Không lấy được meme, thử lại sau."), ephemeral=True)

            e = _embed("😂 Meme", title)
            if post_url:
                e.url = post_url
            e.set_image(url=img)
            e.set_footer(text=f"NSFW: {'Yes' if nsfw else 'No'}")
            await interaction.followup.send(embed=e)
        except Exception as e:
            await interaction.followup.send(embed=_embed("❌ Meme", str(e), discord.Color.red()), ephemeral=True)

    @bot.tree.command(name="trivia", description="Câu hỏi trivia ngẫu nhiên")
    async def trivia(interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            url = "https://opentdb.com/api.php?amount=1&type=multiple"
            data = await asyncio.to_thread(_get_json, url)
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list) or not results:
                return await interaction.followup.send(embed=_embed("❌ Trivia", "Không lấy được câu hỏi."), ephemeral=True)

            row = results[0] if isinstance(results[0], dict) else {}
            q = html.unescape(str(row.get("question") or ""))
            correct = html.unescape(str(row.get("correct_answer") or ""))
            wrong = [html.unescape(str(x)) for x in (row.get("incorrect_answers") or []) if isinstance(x, str)]

            options = wrong + [correct]
            random.shuffle(options)
            letters = ["A", "B", "C", "D"]
            lines = []
            answer_key = "?"
            for i, op in enumerate(options[:4]):
                key = letters[i]
                lines.append(f"`{key}.` {op}")
                if op == correct:
                    answer_key = key

            e = _embed("🧠 Trivia", f"{q}\n\n" + "\n".join(lines))
            e.add_field(name="Đáp án", value=f"||{answer_key}||", inline=False)
            await interaction.followup.send(embed=e)
        except Exception as e:
            await interaction.followup.send(embed=_embed("❌ Trivia", str(e), discord.Color.red()), ephemeral=True)
