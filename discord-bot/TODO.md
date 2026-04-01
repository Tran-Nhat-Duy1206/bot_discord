# Discord Bot TODO

## Ưu tiên cao

### Moderation

* [x] ban command
* [x] kick command
* [x] mute / timeout / untimeout
* [x] clear messages
* [x] warn system (persistent + history)
* [x] auto role
* [x] moderation log channel

---

### Leveling

* [x] XP khi chat
* [x] level up message
* [x] /rank command
* [x] leaderboard
* [x] lưu database
* [x] anti-spam cooldown cho XP
* [x] admin config XP (multiplier, cooldown, channel ignore)

---

## Ưu tiên trung bình

### Economy mở rộng

* [x] daily reward
* [x] work command
* [x] shop
* [x] inventory
* [x] transfer money
* [x] balance command

---

### Music Bot

* [x] join voice
* [x] /play
* [x] /playnext
* [x] /skip
* [x] /queue
* [x] /shuffle
* [x] /pause
* [x] /resume
* [x] /stop
* [x] /leave
* [x] /loop
* [x] auto disconnect
* [x] embed response full cho toàn bộ music command
* [x] Spotify track support
* [x] Spotify playlist/album support (batch queue)
* [x] Fast-start playlist: phát bài đầu trước, nạp phần còn lại nền
* [x] Spotify API fallback để tránh DRM extractor path
* [x] Giảm spam warning yt-dlp trong log
* [x] lyrics command
* [x] volume control
* [x] queue pagination (nhiều hơn 10 bài)
* [x] Queue pagination bằng button (prev/next)
* [x] DJ role permission

### Music Scale-up (kế hoạch)

* [x] Migrate audio engine sang Lavalink (bỏ local ffmpeg path)
* [x] Dùng `wavelink` làm client Lavalink cho discord.py
* [x] Thiết kế multi-node Lavalink + failover strategy
* [x] Redis cache cho track resolve (yt/spotify)
* [x] Redis cache cho Spotify playlist mapping + TTL
* [x] Cache invalidation policy + cache warmup cho playlist hot
* [x] Persist queue state theo guild (Redis) để recover khi restart
* [x] Metrics: queue wait time, resolve latency, node health
* [x] Healthcheck + auto-reconnect Lavalink node
* [x] Rate-limit layer cho music commands (guild/user)
* [x] Autoplay YouTube related khi queue rỗng
* [x] Toggle autoplay theo guild config

---

## Ưu tiên thấp

### AI

* [x] chat AI
* [x] summarize
* [x] translate
* [x] explain code
* [x] image generation
* [x] conversation memory per channel

---

### Fun Commands

* [x] meme
* [x] coinflip
* [x] dice
* [x] 8ball
* [x] trivia

---

### Utility

* [x] ping
* [x] avatar
* [x] userinfo
* [x] serverinfo
* [x] remind

---

# Đã hoàn thành

* [x] deadlines system
* [x] TFT team/item system
* [x] blackjack
* [x] moderation system (core)
* [x] leveling v1
* [x] economy mở rộng v1
* [x] RPG core modular package (`features/rpg/*`)

---

# Chức năng tiếp theo

## Roadmap cập nhật (gần nhất)

* [x] Hoàn tất Music Scale-up (multi-node, metrics, rate-limit, Redis cache, queue recover)
* [x] Hoàn tất AI phase 2 (`/ai_image`, memory theo channel, `/ai_memory_clear`)
* [x] Hoàn tất Fun commands v1 (`/meme`, `/coinflip`, `/dice`, `/8ball`, `/trivia`)
* [x] Deadline Google multi-account rollout (per-user account linking)
* [ ] Deadline module refactor: tách `features/deadlines.py` thành package nhiều file
* [ ] Roadmap kế tiếp ưu tiên: RPG phase 6 + RPG quality/balance
* [ ] Sau RPG: Core bot cải thiện chung (test coverage, config, error policy)

## Deadline Google multi-account

* [x] DB schema cho 1 user nhiều Google account (`user_google_accounts`)
* [x] DB schema lưu OAuth state tạm (`user_google_oauth_states`)
* [x] Command `/deadline_google_login` để tạo link OAuth
* [x] Command `/deadline_google_verify` để hoàn tất liên kết
* [x] Command `/deadline_google_accounts` liệt kê account đã liên kết
* [x] Command `/deadline_google_set_default` chọn account mặc định
* [x] Command `/deadline_google_unlink` gỡ liên kết từng account
* [x] Command `/deadline_google_import_global` để migrate token global nhanh
* [x] Command `/deadline_google_use_account` chọn account theo từng deadline
* [x] Tạo Sheet/Docs ưu tiên dùng account mặc định của owner deadline
* [x] Migrate dữ liệu cũ từ token global sang account user (nếu cần)
* [x] Bổ sung chọn account khi tạo tài liệu (phase 2)
* [x] Mã hóa token_json trong DB (encryption at rest)

## Deadline module refactor

* [x] Tạo package `features/deadlines/`
* [x] Di chuyển code cũ sang `features/deadlines/legacy.py`
* [x] Tạo entrypoint `features/deadlines/__init__.py`
* [x] Tách module `commands.py`, `google.py`, `oauth.py`, `storage.py`
* [ ] Tiếp tục bóc tách logic từ `legacy.py` sang module chuyên biệt (db, views, scheduler, export)

## RPG phase 2

* [x] Tách thêm `battle.py`, `loot.py` khỏi `commands.py`
* [x] Quest reset theo ngày/tuần + quest mới
* [x] Equipment slots: weapon/armor/accessory
* [x] Boss command + cooldown riêng
* [x] Cân bằng lại tỉ lệ drop và công thức damage
* [x] Asset hook (`assets.py`) + fallback text khi chưa có ảnh
* [x] Combat log web (best effort publish link)

## RPG phase 3

* [x] Loot rarity table + command `/rpg_loot`
* [x] Slime jackpot tracking + command `/rpg_jackpot`
* [x] Hunt reward tuning (drop/rate/damage) bằng env config
* [x] Boss combat log publish + fallback embed

## RPG phase 4

* [x] Lootbox command `/open` + daily open limit
* [x] Quest chain cơ bản với `prereq_quest_id`
* [x] Quest objective mới: `open_lootboxes`, `boss_wins`
* [x] Item rarity cải tiến + hiển thị loot detail trong hunt

## RPG phase 5

* [x] Asset local file mode từ folder `assets/rpg` + attach embed file
* [x] Boss variants theo level bracket
* [x] Crafting system: `/craft_list`, `/craft`
* [x] Epic/Legendary craftable equipment items

## RPG phase 6 (đề xuất)

* [x] Passive effects cho equipment (lifesteal, crit bonus, damage reduction)
* [x] Set bonus khi mặc đúng combo item
* [x] Skill system cơ bản (active/passive) cho player
* [x] Boss mechanics theo phase (rage mode, shield turn, summon)
* [x] Dungeon mode nhiều tầng với reward scaling
* [x] Party/co-op hunt (2-4 người)
* [x] PvE event theo tuần (double drop, boss rush)

## RPG chất lượng & cân bằng

* [x] Telemetry combat: lưu tỉ lệ win/lose theo level bracket
* [x] Dashboard cân bằng: damage trung bình, TTK, drop rate thực tế
* [x] Anti-abuse: rate limit command RPG theo user/guild
* [x] Anti-alt exploit cho trade/pay trong RPG
* [x] Rà soát economy inflation (nguồn gold vs sink gold)
* [x] Soft reset theo season + phần thưởng season

## RPG dữ liệu & vận hành

* [ ] Version schema DB + migration script rõ ràng
* [ ] Backup/restore dữ liệu RPG định kỳ
* [ ] Command admin: sửa stats/player rollback
* [ ] Command admin: grant/revoke item an toàn (audit log)
* [ ] Audit log cho mọi thao tác economy/RPG nhạy cảm
* [ ] Validate assets startup (file thiếu/corrupt -> cảnh báo)

## RPG UX/UI

* [ ] Embed theme thống nhất cho toàn bộ RPG
* [ ] Pagination cho inventory/shop/quest dài
* [ ] Nút tương tác cho hunt/boss result (replay/log/inventory)
* [ ] Localized text (vi/en) theo guild config
* [ ] Tối ưu thông báo lỗi thân thiện, có gợi ý command kế tiếp

## Core bot cải thiện chung

* [ ] Test coverage tối thiểu cho modules trọng yếu (rpg/economy/mod)
* [ ] Smoke test command sau khi startup
* [ ] Central config object thay vì đọc env rải rác
* [ ] Chuẩn hoá error handling + retry policy
* [ ] Giảm duplicate logic DB transaction giữa modules
* [ ] Healthcheck command cho bot status/dependency

## Backlog tính năng khác (đề xuất)

* [ ] Economy market/auction house
* [ ] Gacha banner theo season
* [ ] Achievement system + title/badge
* [ ] Pet companion system
* [ ] Web dashboard quản trị RPG/economy

## Security

* [ ] Rate limit global (anti spam toàn bot)
* [ ] Permission check decorator thống nhất
* [ ] Validate input command (anti injection / crash)
* [ ] Anti abuse economy (spam farm, macro)
* [ ] Sensitive data protection (token/API key)
* [ ] Command cooldown per user + per guild
* [ ] Audit log cho admin command (ban/kick/give item)

## Architecture

* [ ] Service layer (business logic tách khỏi command)
* [ ] Repository layer (DB access riêng)
* [ ] DTO / schema validation (pydantic hoặc custom)
* [ ] Dependency injection (inject service vào command)
* [ ] Event system (emit event: on_battle_win, on_level_up)

## Database

* [ ] Index tối ưu query (user_id, guild_id)
* [ ] Connection pool
* [ ] Transaction wrapper chung
* [ ] Data consistency check (fix lệch data)
* [ ] Soft delete / recovery data

## Observability

* [ ] Structured logging (JSON log)
* [ ] Trace command execution time
* [ ] Error tracking (Sentry hoặc custom)
* [ ] Metrics toàn bot (command usage, error rate)
* [ ] Alert khi bot crash hoặc node chết

## Testing

* [ ] Unit test cho service layer
* [ ] Integration test cho DB
* [ ] Mock Discord API
* [ ] Load test (spam command simulation)

## DevOps

* [ ] Dockerize bot
* [ ] Docker Compose (bot + Redis + Lavalink)
* [ ] CI/CD (GitHub Actions)
* [ ] Auto restart khi crash
* [ ] Env config theo môi trường (dev/prod)

## RPG nâng cao (đáng thêm)

* [ ] Status effect (poison, burn, stun, freeze)
* [ ] Turn order (speed stat)
* [ ] Damage type (physical/magic/true damage)
* [ ] Enemy AI pattern (smart AI, không random)
* [ ] World map / region (farm theo khu vực)
* [ ] Daily login reward RPG riêng
* [ ] Guild/clan system

## Economy balance

* [ ] Tax khi trade
* [ ] Item degradation (đồ bị hỏng)
* [ ] Repair system
* [ ] Random event mất tiền (risk factor)
* [ ] Limited shop rotation (FOMO)

## AI nâng cao

* [ ] Context-aware AI (biết user là ai)
* [ ] AI moderation (detect toxic)
* [ ] AI auto-reply theo channel topic
* [ ] AI NPC trong RPG (chat + quest)

## Developer Experience

* [ ] CLI tool để chạy riêng từng module
* [ ] Debug mode (verbose log)
* [ ] Hot reload khi dev
* [ ] Seed data generator

---

# Ý tưởng tương lai

* [ ] web dashboard
* [ ] slash command only
* [ ] multi server support
* [ ] permission system
* [ ] plugin system

---

# Ghi chú

* Mỗi tính năng = 1 file trong features/
* Không để code trong main.py
* Dùng async/await
* Log lỗi vào logs/bot.log
