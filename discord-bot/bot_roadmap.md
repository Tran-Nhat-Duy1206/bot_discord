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
