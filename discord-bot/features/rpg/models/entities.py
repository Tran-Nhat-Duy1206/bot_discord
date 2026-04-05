from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Player:
    guild_id: int
    user_id: int
    level: int = 1
    xp: int = 0
    hp: int = 100
    max_hp: int = 100
    attack: int = 12
    defense: int = 6
    gold: int = 150
    created_at: int = 0


@dataclass
class PlayerStats:
    level: int
    xp: int
    hp: int
    max_hp: int
    attack: int
    defense: int
    gold: int


@dataclass
class EquipmentProfile:
    attack: int = 0
    defense: int = 0
    hp: int = 0
    lifesteal: float = 0.0
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0
    equipped: dict = field(default_factory=dict)
    set_bonus: Optional[dict] = None


@dataclass
class SkillProfile:
    attack: int = 0
    defense: int = 0
    hp: int = 0
    lifesteal: float = 0.0
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0
    passives: list = field(default_factory=list)
    unlocked: set = field(default_factory=set)


@dataclass
class CombatEffects:
    lifesteal: float = 0.0
    crit_bonus: float = 0.0
    damage_reduction: float = 0.0


@dataclass
class CombatResult:
    ok: bool = False
    pack: int = 0
    kills: int = 0
    slime_kills: int = 0
    gold: int = 0
    xp: int = 0
    leveled_up: bool = False
    level: int = 1
    xp_remain: int = 0
    hp: int = 0
    effective_hp: int = 0
    drops: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    encounters: dict = field(default_factory=dict)
    drop_rarity: dict = field(default_factory=dict)
    jackpot_hits: int = 0
    jackpot_gold: int = 0
    combat_effects: CombatEffects = field(default_factory=CombatEffects)
    set_bonus: str = ""
    passive_skills: list = field(default_factory=list)
    lifesteal_heal: int = 0
    damage_blocked: int = 0
    weekly_event: dict = field(default_factory=dict)


@dataclass
class BossResult:
    ok: bool = False
    win: bool = False
    boss_id: str = ""
    boss: str = ""
    gold: int = 0
    xp: int = 0
    drops: dict = field(default_factory=dict)
    base_hp: int = 0
    leveled_up: bool = False
    level: int = 1
    xp_remain: int = 0
    logs: list = field(default_factory=list)
    combat_effects: CombatEffects = field(default_factory=CombatEffects)
    set_bonus: str = ""
    passive_skills: list = field(default_factory=list)
    lifesteal_heal: int = 0
    damage_blocked: int = 0
    phase_events: list = field(default_factory=list)
    rage_triggered: bool = False
    shield_turns: int = 0
    summon_count: int = 0
    weekly_event: dict = field(default_factory=dict)


@dataclass
class DungeonResult:
    ok: bool = False
    cleared: bool = False
    floors_cleared: int = 0
    total_floors: int = 0
    gold: int = 0
    xp: int = 0
    drops: dict = field(default_factory=dict)
    hp: int = 0
    level: int = 1
    xp_remain: int = 0
    leveled_up: bool = False
    logs: list = field(default_factory=list)
    combat_effects: CombatEffects = field(default_factory=CombatEffects)
    set_bonus: str = ""
    passive_skills: list = field(default_factory=list)
    lifesteal_heal: int = 0
    damage_blocked: int = 0
    weekly_event: dict = field(default_factory=dict)


@dataclass
class PartyHuntResult:
    ok: bool = False
    pack: int = 0
    kills: int = 0
    gold: int = 0
    xp: int = 0
    drops: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)
    members: list = field(default_factory=list)
    weekly_event: dict = field(default_factory=dict)


@dataclass
class Quest:
    quest_id: str
    objective: str
    target: int
    progress: int
    reward_gold: int
    reward_xp: int
    period: str = "none"
    reset_after: int = 0
    prereq_quest_id: str = ""
    claimed: bool = False

    @property
    def is_complete(self) -> bool:
        return self.progress >= self.target and not self.claimed

    @property
    def is_locked(self, claimed_map: dict[str, bool]) -> bool:
        if not self.prereq_quest_id:
            return False
        return not claimed_map.get(self.prereq_quest_id, False)


@dataclass
class CraftResult:
    ok: bool = False
    message: str = ""
    recipe_id: str = ""
    amount: int = 0


@dataclass
class LootboxResult:
    ok: bool = False
    total_gold: int = 0
    bonus_items: list = field(default_factory=list)
    remaining_opens: int = 0
    message: str = ""
