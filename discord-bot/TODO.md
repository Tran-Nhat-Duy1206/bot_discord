# 🚀 Discord Bot TODO (TEAM RPG VERSION)

---

# ✅ ĐÃ HOÀN THÀNH (TỪ VERSION TRƯỚC)

## 🎮 Core RPG

* [x] Player system (level, xp, hp, atk, def, gold)
* [x] `/hunt` - combat với monster
* [x] `/boss` - boss battle với cooldown
* [x] `/daily` - daily reward
* [x] `/work` - earn gold
* [x] `/shop` - mua item
* [x] `/inventory` - xem items
* [x] `/balance` - xem gold
* [x] `/transfer` - chuyển gold
* [x] Equipment system (weapon, armor, accessory)
* [x] Lootbox system (`/open`, daily limit)
* [x] Quest system (daily/weekly, prereq)
* [x] Crafting system (`/craft_list`, `/craft`)
* [x] Passive effects cho equipment
* [x] Set bonus
* [x] Boss variants theo level
* [x] Dungeon mode
* [x] Party/co-op hunt
* [x] PvE event (double drop)
* [x] Season system + soft reset
* [x] Telemetry (win/lose, damage, gold, xp)

## 💰 Economy & Safety

* [x] User lock (per-user locking)
* [x] Transaction wrapper
* [x] Anti double-spend
* [x] Anti-abuse (rate limit, trade exploit)
* [x] Gold ledger / audit log
* [x] Transfer limit (daily, pair limit)
* [x] Telemetry combat

## 🎵 Music Bot

* [x] Lavalink integration (wavelink)
* [x] Multi-node + failover
* [x] Spotify support
* [x] Queue management + pagination
* [x] Autoplay YouTube
* [x] DJ role permission
* [x] Lyrics command

## ⚙️ Moderation

* [x] ban/kick command
* [x] mute/timeout
* [x] clear messages
* [x] warn system (persistent)
* [x] auto role
* [x] log channel

## 📈 Leveling

* [x] XP khi chat
* [x] /rank command
* [x] leaderboard
* [x] admin config (multiplier, cooldown, ignore channel)

## 🎉 Fun & Utility

* [x] meme, coinflip, dice, 8ball, trivia
* [x] ping, avatar, userinfo, serverinfo, remind

---

# ❌ ĐÃ BỎ (KHÔNG LÀM)

* [x] Web dashboard
* [x] Plugin system
* [x] Active skill spam (giữ passive thay active)
* [x] Element system (fire/water/light)
* [x] 5+ team slots
* [x] Guild/clan system
* [x] World map/region

---

# 🎯 Mục tiêu chính

* RPG chuyển sang **Team-based + Character system**
* Tăng retention bằng gacha + collection
* Không phá balance hiện tại
* Vẫn lightweight cho Discord UX

---

# 🥇 PHASE 1 — CORE REFACTOR (BẮT BUỘC)

## 🔁 Character System (CRITICAL)

* [x] Thêm **Main Character**
  * chọn giới tính (male/female)
  * stat base giống player hiện tại
* [x] Thêm bảng `characters`
* [x] Thêm bảng `player_characters`
* [x] Mỗi player có:
  * main_character (bắt buộc)
  * danh sách heroes

---

## 🎭 Role System (BẮT BUỘC)

* [x] Define role:
  * DPS
  * Tank
  * Healer
  * Support
* [x] Mỗi character có:
  * role
  * base stats riêng
* [x] Không tạo character "mạnh hơn", chỉ khác role

---

## 🎲 Gacha System (CORE LOOP)

* [x] Command `/gacha`
* [x] Drop rate:
  * Common / Rare / Epic / Legendary
* [x] Thêm pity system (soft pity)
* [x] Anti-duplicate:
  * convert duplicate → shard / gold
* [ ] Animation text đơn giản (Discord friendly)

---

## 🧱 Team System

* [x] Command `/team`
* [x] Team size: **5 characters**
  * Main (fixed)
  * +4 heroes
* [x] Validate team trước combat
* [x] Lưu team vào DB

---

## ⚔️ Combat Refactor (QUAN TRỌNG NHẤT)

* [x] Convert:
  * Player → Team
* [x] Combat flow mới:
  * apply passive
  * team attack
  * monster attack
* [x] Không dùng active skill spam (Discord UX kém)
* [x] Damage = tổng contribution của team

---

## ⚖️ Balance Layer

* [x] Team power system:
```python
team_power = sum(char.atk + char.def + char.hp * 0.2)
```
* [x] Monster scale theo team power
* [x] Không scale theo số lượng character

---

# 🥈 PHASE 2 — GAMEPLAY DEPTH

## 🧠 Passive Skill System

* [ ] Mỗi character có 1–2 passive
* [ ] Ví dụ:
  * DPS → +crit
  * Tank → giảm damage team
  * Healer → heal mỗi turn
* [ ] Stack có giới hạn

---

## 🔗 Team Synergy

* [ ] Bonus khi mix role:
  * Tank + Healer → +def
  * DPS + Support → +damage
* [ ] Không làm quá phức tạp

---

## 🧬 Character Progression

* [ ] Level riêng cho character
* [ ] EXP chia từ combat
* [ ] Ascend (optional, phase sau)

---

# 🥉 PHASE 3 — GACHA EXPANSION

## 🎟️ Banner System

* [ ] Rate-up character
* [ ] Rotation theo tuần
* [ ] Limited character (optional)

---

## 💠 Currency

* [ ] Thêm `gem`
* [ ] Gacha dùng gem
* [ ] Earn free gem (daily / quest)

---

## 🔁 Duplicate Handling

* [ ] Convert → shard
* [ ] Shard dùng để:
  * nâng cấp character
  * unlock passive

---

# 🏅 PHASE 4 — INTEGRATION

## ⚔️ Dungeon

* [ ] Team-based dungeon
* [ ] Synergy quan trọng hơn stat

---

## 👥 Party

* [ ] Party = nhiều team
* [ ] Scale monster theo số người

---

## 🧾 Quest

* [ ] Quest liên quan character:
  * summon X lần
  * dùng healer X trận

---

# 🏆 PHASE 5 — RETENTION

## 🎯 Collection System

* [ ] Character index
* [ ] % completion

---

## 🎨 Cosmetic

* [ ] Skin character
* [ ] Title riêng theo character

---

## 🏅 Leaderboard

* [ ] Top team power
* [ ] Top collection

---

# ❄️ KHÔNG LÀM NGAY (TRÁNH OVERDESIGN)

* [ ] PvP real-time
* [ ] Skill tree phức tạp
* [ ] Element system (fire/water/light)

---

# 🧠 DESIGN RULES

* Character ≠ mạnh hơn → chỉ khác role
* Team size nhỏ (max 5)
* Passive > Active
* Gacha không pay-to-win
* Discord UX phải đơn giản

---

# 🔥 PRIORITY (RẤT QUAN TRỌNG)

1. Character system
2. Team system
3. Combat refactor
4. Gacha
5. Passive skill

---

# 💬 NOTE

* Đây là bước chuyển từ:
  * Solo RPG → Team RPG
* Không rewrite toàn bộ → chỉ thêm layer
* Giữ hệ thống cũ (equipment, gold, combat)

---
