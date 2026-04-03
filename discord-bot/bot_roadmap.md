# Discord Bot Roadmap (Updated)

## Current Snapshot

Bot is now at a strong multi-feature stage (Advanced-Intermediate), with these groups already live:

- Moderation core: kick/ban/timeout/warn/autorole/modlog
- Leveling: XP, rank, leaderboard, anti-spam, admin config
- Economy: blackjack + daily/work/shop/inventory/transfer/balance
- Music (Lavalink + Wavelink): full playback controls, Spotify support, autoplay, healthcheck, metrics, rate-limit, Redis cache/persist
- AI: chat, summarize, translate, explain code, image generation, per-channel memory
- Utility: ping/avatar/userinfo/serverinfo/remind
- Fun: meme/coinflip/dice/8ball/trivia

---

## Completed Milestones

### Foundation

- Deadlines system
- TFT lookup (team/item)
- Core module split into `features/*`

### Music Scale-up

- Migrated to Lavalink engine
- Multi-node + failover strategy
- Queue pagination with buttons
- Healthcheck + auto-reconnect
- Runtime metrics (`/music_metrics`)
- Guild/User rate-limit for music commands
- Redis cache for resolve/Spotify playlist
- Cache warmup/invalidation policy
- Queue persistence and restore by guild (Redis)

### AI Phase 2

- `/ai_image`
- Per-channel memory for `/ai_chat`
- `/ai_memory_clear`

### Fun Commands v1

- `/meme`
- `/coinflip`
- `/dice`
- `/8ball`
- `/trivia`

---

## Next Priority Roadmap

### Sprint 1: RPG Phase 6 (Core Gameplay)

- [x] Passive effects for equipment (lifesteal, crit bonus, damage reduction)
- [x] Set bonus for equipment combinations
- [x] Basic skill system (active/passive)
- [x] Boss phase mechanics (rage, shield turn, summon)
- [x] Dungeon mode with reward scaling
- [x] Party/co-op hunt (2-4 players)
- [x] Weekly PvE events (double drop, boss rush)

### Sprint 2: RPG Quality and Balance

- Combat telemetry by level bracket (win/lose)
- Balance dashboard (avg damage, TTK, real drop rate)
- RPG anti-abuse rate limits (user/guild)
- Anti-alt exploit checks for RPG trade/pay
- Economy inflation audit (gold source vs sink)

### Sprint 3: Data and Operations

- DB schema versioning + migration scripts
- Scheduled backup/restore flow for RPG data
- Admin recovery commands (player stats rollback)
- Safe grant/revoke item commands + audit log
- Startup asset validation for RPG assets

### Sprint 4: Core Improvements

- Minimum test coverage for critical modules (rpg/economy/mod)
- Startup smoke tests for commands
- Centralized config object (reduce scattered env reads)
- Standardized error handling + retry policy
- Reduce duplicate DB transaction logic across modules

---

## Tracking Checklist (High-level)

- [x] Moderation
- [x] Leveling
- [x] Economy (extended)
- [x] Music (scale-up complete)
- [x] AI (phase 2 complete)
- [x] Fun commands v1
- [x] Utility core
- [x] RPG phase 6
- [ ] RPG quality and balance
- [ ] Core bot engineering hardening

---

## Notes

- Keep feature logic inside `features/`, avoid business logic in `main.py`.
- Keep async-first command handlers and I/O.
- Store runtime and persistent data under `data/` and Redis when enabled.
- Keep logs centralized at `logs/bot.log`.

🚀 Discord Bot Roadmap (RPG-Centric Edition)
🎯 Core Vision

Bot định hướng là:

RPG-centric Discord bot với gameplay gây nghiện, social interaction, và progression rõ ràng.

Các module khác (music, AI, utility) đóng vai trò support, không phải core.

📊 Current Snapshot

Bot hiện đang ở mức Advanced-Intermediate (gần production-ready):

✅ Systems đã hoàn thiện
Moderation: ban/kick/timeout/warn/autorole/modlog
Leveling: XP, rank, leaderboard, anti-spam, config
Economy: daily/work/shop/inventory/transfer/balance
Music: Lavalink + Wavelink + multi-node + Redis + metrics
AI: chat/summarize/translate/image + memory theo channel
Utility: ping/avatar/userinfo/serverinfo/remind
Fun: meme/coinflip/dice/8ball/trivia
🧠 Strategic Focus
❗ Quy tắc chính
❌ Không thêm nhiều feature mới ngoài RPG
✅ Tập trung Retention + UX + Gameplay loop
✅ Engineering chỉ làm đủ dùng (practical)
🔥 Phase 1: RPG Core Loop (QUAN TRỌNG NHẤT)
🎯 Mục tiêu

Tạo vòng lặp:

Login → Reward → Hunt/Boss → Loot → Upgrade → Unlock → Repeat
🧩 Features cần hoàn thiện
1. Daily System (Retention core)
 /daily_login
 Streak reward (reset nếu miss)
 Reward scaling theo ngày (day 1 → day 7)
 Rare reward ở mốc cao (lootbox / epic)
2. Quest System (Improved)
 Daily quest (hunt/boss/damage)
 Weekly quest
 Hidden quest
 Quest chain (unlock theo progress)
 Reward đa dạng: gold + item + exp + currency
3. Reward Feedback (UX cực quan trọng)
 Embed loot đẹp (rarity, emoji, highlight)
 Hiển thị crit/miss/damage rõ ràng
 Highlight drop hiếm (JACKPOT)
 EXP gain rõ ràng
4. Next Action Suggestion

Sau mỗi command:

 Gợi ý command tiếp theo
/hunt again
/inventory
/boss
⚔️ Phase 2: Combat & Loot Optimization
🎯 Mục tiêu

Combat phải đã mắt – dễ hiểu – có cảm xúc

Combat improvements
 Crit hit (highlight)
 Miss chance
 Skill effect text
 Lifesteal / shield / effect hiển thị rõ
Loot system
 Rarity tier (common → legendary)
 Jackpot system (ultra rare drop)
 Duplicate → convert shard / upgrade
 Loot animation feel (text-based)
📈 Phase 3: Progression System
🎯 Mục tiêu

Người chơi luôn biết:

“Mình đang mạnh lên như thế nào?”

Features
 /progress command
 Level + % progress
 Power score / gear score
 Unlock preview (skill/dungeon/etc)
👥 Phase 4: Social Layer (Retention mạnh nhất)
🎯 Mục tiêu

Tạo lý do chơi cùng người khác

Features
 Party bonus (EXP/gold boost)
 Party leaderboard
 Weekly ranking
Future (không ưu tiên ngay)
 Guild / Clan system
 Guild boss
 Co-op dungeon leaderboard
🎮 Phase 5: Anti-Boredom System
🎯 Mục tiêu

Giữ gameplay không bị lặp

Features
 Random encounter (boss mini)
 Random event (double gold, bonus EXP)
 Rare spawn khi hunt
 Event theo ngày/tuần
🧠 Phase 6: Meta Progression
🎯 Mục tiêu

Giữ player lâu dài (long-term retention)

Features
 Talent tree
 Passive build diversity
 Prestige system (reset + buff)
 Season system + reward
🎨 Phase 7: UX / UI Overhaul
🎯 Mục tiêu

Tăng usage x2–x3

Features
 Embed theme thống nhất toàn RPG
 Button interaction (hunt again, next, etc.)
 Pagination (inventory/shop/quest)
 Error message thân thiện + gợi ý command
 Command flow mượt
🛠 Phase 8: Core Engineering (Practical)
🎯 Mục tiêu

Ổn định bot, không over-engineering

Features
 Basic test coverage (rpg/economy/mod)
 Central config object
 Standard error handling
 Reduce duplicate DB logic
 Basic logging improvement
💾 Phase 9: Data & Operations
🎯 Mục tiêu

Tránh mất data và dễ maintain

Features
 DB schema versioning
 Migration scripts
 Backup/restore đơn giản
 Admin rollback command
 Audit log cho action quan trọng
🧊 Frozen Modules (Maintenance Mode)
Deadline System
❄️ Không phát triển thêm
❄️ Chỉ maintain bug nếu cần
AI nâng cao
❄️ Không ưu tiên:
Context-aware AI
AI NPC
DevOps nâng cao
❄️ Tạm hoãn:
CI/CD full
Load test phức tạp
Distributed tracing
📦 Suggested Structure
features/
 ├── rpg/
 │   ├── battle.py
 │   ├── loot.py
 │   ├── daily.py
 │   ├── quest.py
 │   ├── progression.py
 │   ├── social.py
 │   ├── rewards.py
 │   └── ui.py
📊 Priority Checklist
🔥 High Priority
 Daily + streak
 Quest improved
 Reward UX
 Next action suggestion
🟡 Medium
 Progress system
 Combat feedback
 Party bonus + leaderboard
🟢 Low
 Guild system
 Talent tree
 Prestige
🧠 Final Notes
RPG = core product
UX = force multiplier
Social = retention engine
Engineering = support (không phải trọng tâm)
✅ Kết luận

Roadmap mới này giúp bạn:

🎯 Tập trung đúng thứ quan trọng (RPG + retention)
🚀 Tăng khả năng giữ user
🧠 Tránh over-engineering
📈 Chuẩn bị scale sau này