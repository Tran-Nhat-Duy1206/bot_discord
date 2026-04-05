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

# 🚀 Discord Bot TODO (Refactored - Production Focus)

---

# 🎯 Mục tiêu chính

* Xây bot RPG có thể scale 100–500 user
* Giữ user lâu (retention)
* Kiếm tiền (monetization)
* Code maintainable + ít bug

---

# 🥇 PHASE 1 — STABILITY & SCALE (BẮT BUỘC)

## 🔒 Concurrency & Data Safety (CRITICAL)

* [x] User lock theo `user_id`
* [x] Transaction wrapper chung cho DB (BEGIN / COMMIT / ROLLBACK)
* [x] Đảm bảo mọi command RPG chạy trong transaction
* [x] Anti double-spend (gold, item, reward)

---

## ⚙️ Architecture (CLEAN CODE)

* [x] Tách Service Layer:

  * `combat_service.py`
  * `economy_service.py`
  * `quest_service.py`
  * `player_service.py`
* [x] Không để logic trong command
* [x] Chuẩn hóa flow: load → process → save
* [x] Repository Layer cho DB access
* [x] Concurrent user lock (per-user locking)
* [x] Transaction wrapper với user-level locks
* [x] Tổ chức folder rõ ràng:
  * `combat/` - battle, loot, equipment, skills
  * `data/` - game configuration
  * `db/` - database layer
  * `models/` - data classes
  * `repositories/` - DB access
  * `services/` - business logic
  * `utils/` - helpers

---

## ⚡ Performance

* [ ] Cache player (RAM cache)
* [ ] Cache inventory
* [ ] Giảm số lần query DB trong 1 command
* [ ] Batch DB write (ghi 1 lần thay vì nhiều lần)

---

## 🧾 Logging & Debug

* [ ] Structured logging (JSON log)
* [ ] Log command usage
* [ ] Log error rõ ràng

---

---

# 🥈 PHASE 2 — GAMEPLAY & RETENTION

## 🔁 Core Gameplay Loop

* [ ] Daily reward
* [ ] Daily streak system
* [ ] Hunt → mạnh → boss → loot → repeat
* [ ] Cooldown system chuẩn

---

## 🎮 Content giữ user

* [ ] Boss rotation theo giờ
* [ ] Dungeon scaling
* [ ] Quest daily / weekly
* [ ] Event system:

  * double drop
  * boss rush

---

## 🏆 Progression

* [ ] Balance lại damage / drop rate
* [ ] Improve loot rarity system
* [ ] Leaderboard meaningful

---

---

# 🥉 PHASE 3 — MONETIZATION (KIẾM TIỀN)

## 💎 Premium Currency

* [ ] Thêm `gem` vào player
* [ ] Shop mua gem (manual hoặc tích hợp payment sau)
* [ ] Dùng gem để:

  * mở boss đặc biệt
  * reset cooldown
  * mua lootbox premium

---

## 👑 VIP System

* [ ] Thêm `vip_expire`
* [ ] Buff nhẹ:

  * +XP
  * +gold
  * giảm cooldown
* [ ] Không pay-to-win

---

## 🎟️ Battle Pass

* [ ] Mission system
* [ ] Tier reward (free + premium)
* [ ] Reset theo season

---

## 🎨 Cosmetic

* [ ] Title
* [ ] Skin weapon
* [ ] Effect combat

---

---

# 🏅 PHASE 4 — SCALE & OPTIMIZATION

## 📊 Observability

* [ ] Track command execution time
* [ ] Metrics:

  * số user active
  * tỉ lệ win/lose
* [ ] Error tracking (Sentry hoặc custom)

---

## 🧾 Economy Safety

* [ ] Audit log:

  * gold flow
  * item change
* [ ] Detect abuse:

  * spam command
  * trade exploit

---

## ⚙️ DB Optimization

* [ ] Index tối ưu query
* [ ] Data consistency check
* [ ] Cleanup data định kỳ

---

---

# 🧱 PHASE 5 — DATA & ADMIN

* [ ] DB schema versioning
* [ ] Migration script
* [ ] Backup / restore
* [ ] Admin command:

  * sửa stats
  * rollback player
* [ ] Grant/revoke item (có audit log)

---

---

# 🚀 PHASE 6 — ADVANCED RPG (OPTIONAL)

* [ ] Status effect (poison, burn, stun)
* [ ] Turn order (speed stat)
* [ ] Damage type (physical/magic)
* [ ] Enemy AI pattern
* [ ] World map / region
* [ ] Guild / clan system

---

---

# ❄️ TẠM HOÃN (KHÔNG LÀM NGAY)

## ⛔ Không ưu tiên lúc này

* [ ] Web dashboard
* [ ] Plugin system
* [ ] Multi-node phức tạp (trừ khi >1000 user)
* [ ] Load test nặng
* [ ] Full CI/CD pipeline
* [ ] Music scale-up thêm (đã đủ rồi)

---

---

# 🧪 TESTING (LÀM SAU KHI ỔN ĐỊNH)

* [ ] Unit test cho service layer
* [ ] Integration test DB
* [ ] Mock Discord API
* [ ] Spam test command (simulate user)

---

---

# 🛠️ DEVOPS (TỐI THIỂU)

* [ ] Auto restart bot khi crash
* [ ] Healthcheck command
* [ ] Env config dev/prod

---

---

# 🎯 NGUYÊN TẮC PHÁT TRIỂN

* Không thêm feature khi chưa ổn định
* Mỗi command = 1 flow rõ ràng
* Load 1 lần → xử lý → save 1 lần
* Ưu tiên:

  1. Không bug
  2. Không lag
  3. User quay lại

---

---

# 💬 Ghi chú

* RPG là core product
* Các module khác (music, fun, moderation) chỉ là phụ
* Focus giữ user + kiếm tiền, không phải thêm feature

---

