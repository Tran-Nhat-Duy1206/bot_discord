# 📅 Discord Bot Roadmap (TEAM RPG)

---

## 🗓️ Timeline Overview

| Phase | Name | Est. Time | Status |
|-------|------|-----------|--------|
| 1 | Core Refactor | 2-3 weeks | ⬜ Not Started |
| 2 | Gameplay Depth | 2 weeks | ⬜ Not Started |
| 3 | Gacha Expansion | 1-2 weeks | ⬜ Not Started |
| 4 | Integration | 2 weeks | ⬜ Not Started |
| 5 | Retention | 1 week | ⬜ Not Started |

---

## 🚀 Phase 1 — Core Refactor (Weeks 1-3)

### Week 1: Database & Models
- [ ] Create `characters` table
- [ ] Create `player_characters` table
- [ ] Implement Main Character creation (gender selection)
- [ ] Migrate existing player stats to main character

### Week 2: Role & Gacha
- [ ] Define roles: DPS, Tank, Healer, Support
- [ ] Assign base stats per role
- [ ] Implement `/gacha` command
- [ ] Set up drop rates (Common/Rare/Epic/Legendary)
- [ ] Add pity system (soft pity)
- [ ] Handle duplicates → shard conversion

### Week 3: Team System & Combat
- [ ] Implement `/team` command
- [ ] Team validation (3 characters max)
- [ ] Refactor combat: Player → Team
- [ ] Apply passive skills in combat
- [ ] Team damage calculation
- [ ] Balance: monster scale by team power

**Milestone:** Core team-based RPG playable

---

## 🎮 Phase 2 — Gameplay Depth (Weeks 4-5)

### Week 4: Passive Skills & Synergy
- [ ] Add 1-2 passive skills per character
- [ ] Implement role synergy bonuses
- [ ] Cap passive stacks

### Week 5: Character Progression
- [ ] Individual character leveling
- [ ] EXP distribution from combat
- [ ] Plan for Ascend system (future)

**Milestone:** Characters have progression and synergy

---

## 🎲 Phase 3 — Gacha Expansion (Weeks 6-7)

### Week 6: Banner & Currency
- [ ] Implement banner system (rate-up)
- [ ] Weekly rotation
- [ ] Add `gem` currency
- [ ] Free gem earning (daily/quest)

### Week 7: Duplicate Handling
- [ ] Shard system
- [ ] Character upgrade via shards
- [ ] Passive unlock via shards

**Milestone:** Gacha is fully functional with economy

---

## ⚔️ Phase 4 — Integration (Weeks 8-9)

### Week 8: Dungeons & Party
- [ ] Team-based dungeon
- [ ] Party system (multiple teams)
- [ ] Monster scaling by party size

### Week 9: Quest System
- [ ] Character-specific quests
- [ ] Quest: summon X times
- Quest: use healer X battles

**Milestone:** Multiplayer features working

---

## 🏆 Phase 5 — Retention (Week 10)

### Week 10: Collection & Cosmetics
- [ ] Character index (collection tracker)
- [ ] Completion percentage
- [ ] Character skins
- [ ] Titles per character
- [ ] Leaderboards (team power, collection)

**Milestone:** Retention features complete

---

## 🔄 Release Cadence

| Release | Features | Target |
|---------|----------|--------|
| v2.0 (Beta) | Phase 1 | Week 3 |
| v2.1 | Phase 2 | Week 5 |
| v2.2 | Phase 3 | Week 7 |
| v2.3 | Phase 4 | Week 9 |
| v2.4 (Stable) | Phase 5 | Week 10 |

---

## 🎯 Success Metrics

- Daily Active Users (DAU) growth
- Retention rate (Day 1, Day 7, Day 30)
- Gacha pull rate
- Team composition diversity
- Average session time

---

## ⚠️ Risks & Mitigation

| Risk | Mitigation |
|------|-------------|
| Combat balance broken | Telemetry + hotfix capability |
| Gacha feel unfair | Pity system + duplicate value |
| Too complex | Passive > Active design |
| Database load | Proper indexing + caching |

---

## 🛠️ Technical Requirements

- PostgreSQL (existing)
- Redis for caching (existing)
- Lavalink for music (existing)
- No new infrastructure needed

---

*Last Updated: 2026-04-06*
