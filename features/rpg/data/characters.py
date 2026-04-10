import random


CHARACTERS = {
    "rimuru_slime": {
        "name": "Rimuru", "form": "Slime", "rarity": "rare", "role": "support", "species": "slime",
        "form_index": 1, "evolution_line": "rimuru", "gender": "none",
        "hp": 110, "attack": 12, "defense": 10, "speed": 11, "passive_skill": "arcane_mist", "emoji": "💧",
    },
    "rimuru_demon_slime": {
        "name": "Rimuru", "form": "Demon Slime", "rarity": "rare", "role": "support", "species": "slime",
        "form_index": 2, "evolution_line": "rimuru", "gender": "none",
        "hp": 145, "attack": 18, "defense": 14, "speed": 14, "passive_skill": "arcane_mist", "emoji": "💠",
    },
    "rimuru_human_form": {
        "name": "Rimuru", "form": "Human Form", "rarity": "epic", "role": "support", "species": "majin",
        "form_index": 3, "evolution_line": "rimuru", "gender": "none",
        "hp": 190, "attack": 27, "defense": 18, "speed": 19, "passive_skill": "predator_core", "emoji": "✨",
    },
    "rimuru_true_demon_lord": {
        "name": "Rimuru", "form": "Demon Lord", "rarity": "legendary", "role": "support", "species": "demon_lord",
        "form_index": 4, "evolution_line": "rimuru", "gender": "none",
        "hp": 245, "attack": 35, "defense": 25, "speed": 23, "passive_skill": "predator_core", "emoji": "🔷",
    },
    "rimuru_void_god": {
        "name": "Rimuru", "form": "True Demon Lord / Ultimate Skill", "rarity": "mythic", "role": "support", "species": "ultimate",
        "form_index": 5, "evolution_line": "rimuru", "gender": "none",
        "hp": 320, "attack": 48, "defense": 34, "speed": 30, "passive_skill": "void_authority", "emoji": "🌌",
    },

    "benimaru_ogre": {
        "name": "Benimaru", "form": "Ogre", "rarity": "rare", "role": "dps", "species": "ogre",
        "form_index": 1, "evolution_line": "benimaru", "gender": "male",
        "hp": 130, "attack": 20, "defense": 10, "speed": 12, "passive_skill": "flame_slash", "emoji": "🔥",
    },
    "benimaru_kijin_majin": {
        "name": "Benimaru", "form": "Kijin Majin", "rarity": "epic", "role": "dps", "species": "kijin",
        "form_index": 2, "evolution_line": "benimaru", "gender": "male",
        "hp": 170, "attack": 28, "defense": 14, "speed": 16, "passive_skill": "hell_flame", "emoji": "🔥",
    },
    "benimaru_oni_majin": {
        "name": "Benimaru", "form": "Oni Majin", "rarity": "legendary", "role": "dps", "species": "oni",
        "form_index": 3, "evolution_line": "benimaru", "gender": "male",
        "hp": 220, "attack": 36, "defense": 18, "speed": 20, "passive_skill": "inferno_body", "emoji": "🔥",
    },
    "benimaru_divine_oni": {
        "name": "Benimaru", "form": "Divine Oni (Flame Soul Oni)", "rarity": "mythic", "role": "dps", "species": "divine_oni",
        "form_index": 4, "evolution_line": "benimaru", "gender": "male",
        "hp": 300, "attack": 48, "defense": 24, "speed": 26, "passive_skill": "flame_sovereign", "emoji": "☀️",
    },

    "shion_ogress": {
        "name": "Shion", "form": "Ogress", "rarity": "rare", "role": "tank", "species": "ogre",
        "form_index": 1, "evolution_line": "shion", "gender": "female",
        "hp": 160, "attack": 18, "defense": 14, "speed": 11, "passive_skill": "battle_fortitude", "emoji": "🗡️",
    },
    "shion_wicked_oni": {
        "name": "Shion", "form": "Wicked Oni", "rarity": "epic", "role": "tank", "species": "oni",
        "form_index": 2, "evolution_line": "shion", "gender": "female",
        "hp": 210, "attack": 25, "defense": 20, "speed": 14, "passive_skill": "battle_fortitude", "emoji": "🩸",
    },
    "shion_war_goddess": {
        "name": "Shion", "form": "War Goddess", "rarity": "legendary", "role": "tank", "species": "divine_oni",
        "form_index": 3, "evolution_line": "shion", "gender": "female",
        "hp": 270, "attack": 33, "defense": 28, "speed": 18, "passive_skill": "tyrant_guard", "emoji": "⚔️",
    },
    "shion_ruin_empress": {
        "name": "Shion", "form": "Ruin Empress", "rarity": "mythic", "role": "tank", "species": "ultimate",
        "form_index": 4, "evolution_line": "shion", "gender": "female",
        "hp": 350, "attack": 46, "defense": 37, "speed": 24, "passive_skill": "tyrant_guard", "emoji": "🜏",
    },

    "shuna_ogress": {
        "name": "Shuna", "form": "Ogress Shrine Maiden", "rarity": "rare", "role": "healer", "species": "ogre",
        "form_index": 1, "evolution_line": "shuna", "gender": "female",
        "hp": 130, "attack": 12, "defense": 13, "speed": 11, "passive_skill": "spirit_blessing", "emoji": "🌸",
    },
    "shuna_arc_priestess": {
        "name": "Shuna", "form": "Arc Priestess", "rarity": "epic", "role": "healer", "species": "kijin",
        "form_index": 2, "evolution_line": "shuna", "gender": "female",
        "hp": 175, "attack": 18, "defense": 18, "speed": 15, "passive_skill": "spirit_blessing", "emoji": "🕯️",
    },
    "shuna_oracle": {
        "name": "Shuna", "form": "Oracle of Harvest", "rarity": "legendary", "role": "support", "species": "oni",
        "form_index": 3, "evolution_line": "shuna", "gender": "female",
        "hp": 230, "attack": 27, "defense": 24, "speed": 20, "passive_skill": "moon_veil", "emoji": "🌙",
    },
    "shuna_crimson_oracle": {
        "name": "Shuna", "form": "Crimson Oracle", "rarity": "mythic", "role": "support", "species": "ultimate",
        "form_index": 4, "evolution_line": "shuna", "gender": "female",
        "hp": 300, "attack": 38, "defense": 32, "speed": 28, "passive_skill": "moon_veil", "emoji": "🔮",
    },

    "souei_shadow_runner": {
        "name": "Souei", "form": "Shadow Runner", "rarity": "rare", "role": "dps", "species": "kijin",
        "form_index": 1, "evolution_line": "souei", "gender": "male",
        "hp": 110, "attack": 22, "defense": 9, "speed": 19, "passive_skill": "shadow_chain", "emoji": "🕷️",
    },
    "souei_shadow_lord": {
        "name": "Souei", "form": "Shadow Lord", "rarity": "epic", "role": "dps", "species": "oni",
        "form_index": 2, "evolution_line": "souei", "gender": "male",
        "hp": 150, "attack": 31, "defense": 14, "speed": 24, "passive_skill": "shadow_chain", "emoji": "🌑",
    },
    "souei_night_sovereign": {
        "name": "Souei", "form": "Night Sovereign", "rarity": "legendary", "role": "dps", "species": "divine_oni",
        "form_index": 3, "evolution_line": "souei", "gender": "male",
        "hp": 205, "attack": 42, "defense": 20, "speed": 30, "passive_skill": "night_execution", "emoji": "🌘",
    },

    "hakurou_old_swordsman": {
        "name": "Hakurou", "form": "Old Swordsman", "rarity": "rare", "role": "dps", "species": "kijin",
        "form_index": 1, "evolution_line": "hakurou", "gender": "male",
        "hp": 135, "attack": 21, "defense": 12, "speed": 15, "passive_skill": "blade_discipline", "emoji": "⚔️",
    },
    "hakurou_master_sage": {
        "name": "Hakurou", "form": "Master Sage", "rarity": "epic", "role": "support", "species": "oni",
        "form_index": 2, "evolution_line": "hakurou", "gender": "male",
        "hp": 170, "attack": 29, "defense": 17, "speed": 19, "passive_skill": "blade_discipline", "emoji": "🗡️",
    },
    "hakurou_iaido_saint": {
        "name": "Hakurou", "form": "Iaido Saint", "rarity": "legendary", "role": "dps", "species": "saint",
        "form_index": 3, "evolution_line": "hakurou", "gender": "male",
        "hp": 230, "attack": 39, "defense": 24, "speed": 25, "passive_skill": "night_execution", "emoji": "☄️",
    },

    "geld_orc_lord": {
        "name": "Geld", "form": "Orc Lord", "rarity": "rare", "role": "tank", "species": "orc",
        "form_index": 1, "evolution_line": "geld", "gender": "male",
        "hp": 190, "attack": 16, "defense": 20, "speed": 8, "passive_skill": "iron_bastion", "emoji": "🛡️",
    },
    "geld_barrier_lord": {
        "name": "Geld", "form": "Barrier Lord", "rarity": "epic", "role": "tank", "species": "high_orc",
        "form_index": 2, "evolution_line": "geld", "gender": "male",
        "hp": 250, "attack": 23, "defense": 28, "speed": 11, "passive_skill": "iron_bastion", "emoji": "🧱",
    },
    "geld_juggernaut": {
        "name": "Geld", "form": "Juggernaut", "rarity": "legendary", "role": "tank", "species": "disaster",
        "form_index": 3, "evolution_line": "geld", "gender": "male",
        "hp": 320, "attack": 31, "defense": 36, "speed": 15, "passive_skill": "tyrant_guard", "emoji": "🗿",
    },

    "diablo_arch_demon": {
        "name": "Diablo", "form": "Arch Demon", "rarity": "epic", "role": "support", "species": "demon",
        "form_index": 1, "evolution_line": "diablo", "gender": "male",
        "hp": 180, "attack": 29, "defense": 17, "speed": 21, "passive_skill": "demonic_contract", "emoji": "😈",
    },
    "diablo_demon_peer": {
        "name": "Diablo", "form": "Demon Peer", "rarity": "legendary", "role": "support", "species": "primordial",
        "form_index": 2, "evolution_line": "diablo", "gender": "male",
        "hp": 245, "attack": 38, "defense": 25, "speed": 27, "passive_skill": "demonic_contract", "emoji": "🕸️",
    },
    "diablo_hell_king": {
        "name": "Diablo", "form": "Hell King Noir", "rarity": "mythic", "role": "support", "species": "ultimate",
        "form_index": 3, "evolution_line": "diablo", "gender": "male",
        "hp": 315, "attack": 52, "defense": 34, "speed": 33, "passive_skill": "void_authority", "emoji": "♠️",
    },

    "milim_dragonoid": {
        "name": "Milim", "form": "Dragonoid", "rarity": "epic", "role": "dps", "species": "dragonoid",
        "form_index": 1, "evolution_line": "milim", "gender": "female",
        "hp": 170, "attack": 34, "defense": 12, "speed": 24, "passive_skill": "star_dragon", "emoji": "💥",
    },
    "milim_destroyer": {
        "name": "Milim", "form": "Destroyer", "rarity": "legendary", "role": "dps", "species": "demon_lord",
        "form_index": 2, "evolution_line": "milim", "gender": "female",
        "hp": 235, "attack": 45, "defense": 20, "speed": 29, "passive_skill": "star_dragon", "emoji": "🌠",
    },
    "milim_stampede": {
        "name": "Milim", "form": "Stampede Dragon", "rarity": "mythic", "role": "dps", "species": "ultimate",
        "form_index": 3, "evolution_line": "milim", "gender": "female",
        "hp": 305, "attack": 58, "defense": 28, "speed": 34, "passive_skill": "flame_sovereign", "emoji": "🪐",
    },

    "veldora_sealed": {
        "name": "Veldora", "form": "Sealed Storm Dragon", "rarity": "common", "role": "tank", "species": "dragon",
        "form_index": 1, "evolution_line": "veldora", "gender": "male",
        "hp": 180, "attack": 16, "defense": 18, "speed": 9, "passive_skill": "storm_skin", "emoji": "🌀",
    },
    "veldora_unbound": {
        "name": "Veldora", "form": "Unbound Dragon", "rarity": "legendary", "role": "tank", "species": "true_dragon",
        "form_index": 2, "evolution_line": "veldora", "gender": "male",
        "hp": 290, "attack": 40, "defense": 33, "speed": 20, "passive_skill": "storm_skin", "emoji": "🌪️",
    },
    "veldora_chaos_dragon": {
        "name": "Veldora", "form": "Chaos Dragon", "rarity": "mythic", "role": "tank", "species": "ultimate",
        "form_index": 3, "evolution_line": "veldora", "gender": "male",
        "hp": 360, "attack": 54, "defense": 42, "speed": 27, "passive_skill": "void_authority", "emoji": "🐉",
    },

    "gobta_goblin": {
        "name": "Gobta", "form": "Goblin Guard", "rarity": "common", "role": "support", "species": "goblin",
        "form_index": 1, "evolution_line": "gobta", "gender": "male",
        "hp": 95, "attack": 12, "defense": 9, "speed": 13, "passive_skill": "lucky_slacker", "emoji": ":uncommon:",
    },
    "gobta_hobgoblin": {
        "name": "Gobta", "form": "Hobgoblin Scout", "rarity": "rare", "role": "dps", "species": "hobgoblin",
        "form_index": 2, "evolution_line": "gobta", "gender": "male",
        "hp": 130, "attack": 19, "defense": 12, "speed": 17, "passive_skill": "lucky_slacker", "emoji": "🟩",
    },

    "gabiru_lizardman": {
        "name": "Gabiru", "form": "Lizardman", "rarity": "common", "role": "dps", "species": "lizardman",
        "form_index": 1, "evolution_line": "gabiru", "gender": "male",
        "hp": 100, "attack": 15, "defense": 10, "speed": 12, "passive_skill": "dragon_scale", "emoji": "🦎",
    },
    "gabiru_dragonnewt": {
        "name": "Gabiru", "form": "Dragonnewt", "rarity": "rare", "role": "dps", "species": "dragonnewt",
        "form_index": 2, "evolution_line": "gabiru", "gender": "male",
        "hp": 140, "attack": 23, "defense": 15, "speed": 17, "passive_skill": "dragon_scale", "emoji": "🐲",
    },

    "goblin_raider": {
        "name": "Goblin", "form": "Raider", "rarity": "common", "role": "dps", "species": "goblin",
        "form_index": 1, "evolution_line": "goblin_generic", "gender": "none",
        "hp": 82, "attack": 11, "defense": 7, "speed": 10, "passive_skill": "lucky_slacker", "emoji": "👺",
    },
    "goblin_scout": {
        "name": "Goblin", "form": "Scout", "rarity": "common", "role": "support", "species": "goblin",
        "form_index": 2, "evolution_line": "goblin_generic", "gender": "none",
        "hp": 76, "attack": 9, "defense": 8, "speed": 13, "passive_skill": "lucky_slacker", "emoji": ":uncommon:",
    },
    "hobgoblin_vanguard": {
        "name": "Hobgoblin", "form": "Vanguard", "rarity": "rare", "role": "tank", "species": "hobgoblin",
        "form_index": 3, "evolution_line": "goblin_generic", "gender": "none",
        "hp": 128, "attack": 14, "defense": 14, "speed": 11, "passive_skill": "dragon_scale", "emoji": "🪖",
    },

    "ogre_tribe_warrior": {
        "name": "Ogre", "form": "Tribe Warrior", "rarity": "rare", "role": "tank", "species": "ogre",
        "form_index": 1, "evolution_line": "ogre_generic", "gender": "none",
        "hp": 152, "attack": 17, "defense": 16, "speed": 10, "passive_skill": "battle_fortitude", "emoji": "🔺",
    },
    "ogre_flame_hunter": {
        "name": "Ogre", "form": "Flame Hunter", "rarity": "rare", "role": "dps", "species": "ogre",
        "form_index": 2, "evolution_line": "ogre_generic", "gender": "none",
        "hp": 138, "attack": 21, "defense": 12, "speed": 13, "passive_skill": "flame_slash", "emoji": "🥀",
    },

    "human_swordsman": {
        "name": "Human", "form": "Swordsman", "rarity": "common", "role": "dps", "species": "human",
        "form_index": 1, "evolution_line": "human_generic", "gender": "none",
        "hp": 90, "attack": 13, "defense": 9, "speed": 11, "passive_skill": "blade_discipline", "emoji": "🗡",
    },
    "human_mercenary": {
        "name": "Human", "form": "Mercenary", "rarity": "common", "role": "tank", "species": "human",
        "form_index": 2, "evolution_line": "human_generic", "gender": "none",
        "hp": 110, "attack": 12, "defense": 12, "speed": 10, "passive_skill": "iron_bastion", "emoji": "🛡",
    },
    "human_adept_mage": {
        "name": "Human", "form": "Adept Mage", "rarity": "rare", "role": "support", "species": "human",
        "form_index": 3, "evolution_line": "human_generic", "gender": "none",
        "hp": 98, "attack": 15, "defense": 11, "speed": 14, "passive_skill": "arcane_mist", "emoji": "📜",
    },

    "orc_footsoldier": {
        "name": "Orc", "form": "Footsoldier", "rarity": "common", "role": "tank", "species": "orc",
        "form_index": 1, "evolution_line": "orc_generic", "gender": "none",
        "hp": 118, "attack": 12, "defense": 13, "speed": 8, "passive_skill": "iron_bastion", "emoji": "🐗",
    },
    "orc_enforcer": {
        "name": "Orc", "form": "Enforcer", "rarity": "rare", "role": "tank", "species": "orc",
        "form_index": 2, "evolution_line": "orc_generic", "gender": "none",
        "hp": 145, "attack": 16, "defense": 16, "speed": 9, "passive_skill": "battle_fortitude", "emoji": "⛓️",
    },
    "orc_general": {
        "name": "Orc", "form": "General", "rarity": "epic", "role": "tank", "species": "high_orc",
        "form_index": 3, "evolution_line": "orc_generic", "gender": "none",
        "hp": 182, "attack": 22, "defense": 22, "speed": 11, "passive_skill": "iron_bastion", "emoji": "🪓",
    },
    "orc_disaster": {
        "name": "Orc", "form": "Disaster", "rarity": "legendary", "role": "tank", "species": "disaster",
        "form_index": 4, "evolution_line": "orc_generic", "gender": "none",
        "hp": 260, "attack": 32, "defense": 31, "speed": 14, "passive_skill": "tyrant_guard", "emoji": "🩸",
    },

    "high_goblin_elite": {
        "name": "High Goblin", "form": "Elite", "rarity": "epic", "role": "dps", "species": "high_goblin",
        "form_index": 4, "evolution_line": "goblin_generic", "gender": "none",
        "hp": 156, "attack": 26, "defense": 15, "speed": 19, "passive_skill": "shadow_chain", "emoji": "🟦",
    },
    "gobta_high_goblin": {
        "name": "Gobta", "form": "High Goblin Captain", "rarity": "epic", "role": "dps", "species": "high_goblin",
        "form_index": 3, "evolution_line": "gobta", "gender": "male",
        "hp": 170, "attack": 28, "defense": 16, "speed": 20, "passive_skill": "lucky_slacker", "emoji": "🟦",
    },
    "rigur_hobgoblin": {
        "name": "Rigur", "form": "Hobgoblin Chief", "rarity": "rare", "role": "tank", "species": "hobgoblin",
        "form_index": 1, "evolution_line": "rigur", "gender": "male",
        "hp": 138, "attack": 17, "defense": 16, "speed": 12, "passive_skill": "battle_fortitude", "emoji": "🛡",
    },
    "rigur_high_goblin": {
        "name": "Rigur", "form": "High Goblin Commander", "rarity": "epic", "role": "tank", "species": "high_goblin",
        "form_index": 2, "evolution_line": "rigur", "gender": "male",
        "hp": 190, "attack": 24, "defense": 23, "speed": 15, "passive_skill": "iron_bastion", "emoji": "🟪",
    },
    "rigurd_hobgoblin": {
        "name": "Rigurd", "form": "Hobgoblin Regent", "rarity": "rare", "role": "support", "species": "hobgoblin",
        "form_index": 1, "evolution_line": "rigurd", "gender": "male",
        "hp": 146, "attack": 14, "defense": 17, "speed": 11, "passive_skill": "arcane_mist", "emoji": "🏰",
    },
    "rigurd_high_goblin": {
        "name": "Rigurd", "form": "High Goblin King", "rarity": "epic", "role": "support", "species": "high_goblin",
        "form_index": 2, "evolution_line": "rigurd", "gender": "male",
        "hp": 205, "attack": 20, "defense": 25, "speed": 14, "passive_skill": "moon_veil", "emoji": "👑",
    },
    "gobzo_hobgoblin": {
        "name": "Gobzo", "form": "Hobgoblin Lancer", "rarity": "rare", "role": "dps", "species": "hobgoblin",
        "form_index": 1, "evolution_line": "gobzo", "gender": "male",
        "hp": 128, "attack": 20, "defense": 12, "speed": 16, "passive_skill": "blade_discipline", "emoji": "🪄",
    },
    "gobuichi_hobgoblin": {
        "name": "Gobuichi", "form": "Hobgoblin Guard", "rarity": "rare", "role": "tank", "species": "hobgoblin",
        "form_index": 1, "evolution_line": "gobuichi", "gender": "male",
        "hp": 142, "attack": 16, "defense": 18, "speed": 12, "passive_skill": "battle_fortitude", "emoji": "🪖",
    },

    "gabiru_dragon_warrior": {
        "name": "Gabiru", "form": "Dragon Warrior", "rarity": "epic", "role": "dps", "species": "dragonewt",
        "form_index": 3, "evolution_line": "gabiru", "gender": "male",
        "hp": 188, "attack": 31, "defense": 20, "speed": 22, "passive_skill": "dragon_scale", "emoji": "🐉",
    },
    "gabiru_dragon_king": {
        "name": "Gabiru", "form": "Dragon King", "rarity": "legendary", "role": "dps", "species": "dragonnewt",
        "form_index": 4, "evolution_line": "gabiru", "gender": "male",
        "hp": 244, "attack": 40, "defense": 26, "speed": 27, "passive_skill": "night_execution", "emoji": "🐲",
    },
    "abiru_lizard_king": {
        "name": "Abiru", "form": "Lizardman King", "rarity": "epic", "role": "support", "species": "lizardman",
        "form_index": 1, "evolution_line": "abiru", "gender": "male",
        "hp": 196, "attack": 24, "defense": 23, "speed": 19, "passive_skill": "moon_veil", "emoji": "🦎",
    },

    "ranga_direwolf": {
        "name": "Ranga", "form": "Direwolf", "rarity": "rare", "role": "dps", "species": "beast",
        "form_index": 1, "evolution_line": "ranga", "gender": "male",
        "hp": 132, "attack": 23, "defense": 12, "speed": 18, "passive_skill": "shadow_chain", "emoji": "🐺",
    },
    "ranga_tempest_wolf": {
        "name": "Ranga", "form": "Tempest Wolf", "rarity": "epic", "role": "dps", "species": "magic_beast",
        "form_index": 2, "evolution_line": "ranga", "gender": "male",
        "hp": 186, "attack": 33, "defense": 18, "speed": 24, "passive_skill": "storm_skin", "emoji": "🌩️",
    },
    "ranga_star_wolf": {
        "name": "Ranga", "form": "Star Wolf", "rarity": "legendary", "role": "dps", "species": "divine_beast",
        "form_index": 3, "evolution_line": "ranga", "gender": "male",
        "hp": 248, "attack": 43, "defense": 25, "speed": 31, "passive_skill": "star_dragon", "emoji": "⭐",
    },
    "ranga_divine_wolf": {
        "name": "Ranga", "form": "Divine Wolf", "rarity": "mythic", "role": "dps", "species": "ultimate",
        "form_index": 4, "evolution_line": "ranga", "gender": "male",
        "hp": 318, "attack": 56, "defense": 33, "speed": 36, "passive_skill": "void_authority", "emoji": "🌠",
    },

    "testarossa_demon": {
        "name": "Testarossa", "form": "Demon", "rarity": "epic", "role": "support", "species": "demon",
        "form_index": 1, "evolution_line": "testarossa", "gender": "female",
        "hp": 188, "attack": 30, "defense": 18, "speed": 23, "passive_skill": "demonic_contract", "emoji": "🤍",
    },
    "testarossa_primordial": {
        "name": "Testarossa", "form": "Primordial White", "rarity": "legendary", "role": "support", "species": "primordial",
        "form_index": 2, "evolution_line": "testarossa", "gender": "female",
        "hp": 252, "attack": 41, "defense": 26, "speed": 29, "passive_skill": "void_authority", "emoji": ":common:",
    },
    "testarossa_awakened": {
        "name": "Testarossa", "form": "Awakened Primordial", "rarity": "mythic", "role": "support", "species": "ultimate",
        "form_index": 3, "evolution_line": "testarossa", "gender": "female",
        "hp": 326, "attack": 54, "defense": 35, "speed": 35, "passive_skill": "void_authority", "emoji": "🤍",
    },
    "ultima_demon": {
        "name": "Ultima", "form": "Demon", "rarity": "epic", "role": "dps", "species": "demon",
        "form_index": 1, "evolution_line": "ultima", "gender": "female",
        "hp": 176, "attack": 32, "defense": 17, "speed": 25, "passive_skill": "hell_flame", "emoji": ":Epic:",
    },
    "ultima_primordial": {
        "name": "Ultima", "form": "Primordial Violet", "rarity": "legendary", "role": "dps", "species": "primordial",
        "form_index": 2, "evolution_line": "ultima", "gender": "female",
        "hp": 236, "attack": 44, "defense": 23, "speed": 31, "passive_skill": "night_execution", "emoji": "💜",
    },
    "ultima_awakened": {
        "name": "Ultima", "form": "Awakened Primordial", "rarity": "mythic", "role": "dps", "species": "ultimate",
        "form_index": 3, "evolution_line": "ultima", "gender": "female",
        "hp": 304, "attack": 57, "defense": 30, "speed": 36, "passive_skill": "flame_sovereign", "emoji": ":Epic:",
    },
    "carrera_demon": {
        "name": "Carrera", "form": "Demon", "rarity": "epic", "role": "dps", "species": "demon",
        "form_index": 1, "evolution_line": "carrera", "gender": "female",
        "hp": 182, "attack": 33, "defense": 18, "speed": 24, "passive_skill": "hell_flame", "emoji": ":legends:",
    },
    "carrera_primordial": {
        "name": "Carrera", "form": "Primordial Yellow", "rarity": "legendary", "role": "dps", "species": "primordial",
        "form_index": 2, "evolution_line": "carrera", "gender": "female",
        "hp": 242, "attack": 45, "defense": 24, "speed": 30, "passive_skill": "flame_sovereign", "emoji": "💛",
    },
    "carrera_awakened": {
        "name": "Carrera", "form": "Awakened Primordial", "rarity": "mythic", "role": "dps", "species": "ultimate",
        "form_index": 3, "evolution_line": "carrera", "gender": "female",
        "hp": 312, "attack": 58, "defense": 31, "speed": 35, "passive_skill": "void_authority", "emoji": ":legends:",
    },

    "hinata_holy_knight": {
        "name": "Hinata", "form": "Holy Knight", "rarity": "epic", "role": "dps", "species": "human",
        "form_index": 1, "evolution_line": "hinata", "gender": "female",
        "hp": 170, "attack": 34, "defense": 19, "speed": 24, "passive_skill": "blade_discipline", "emoji": "⛪",
    },
    "hinata_saint": {
        "name": "Hinata", "form": "Saint", "rarity": "legendary", "role": "dps", "species": "saint",
        "form_index": 2, "evolution_line": "hinata", "gender": "female",
        "hp": 232, "attack": 44, "defense": 27, "speed": 30, "passive_skill": "night_execution", "emoji": "⚜️",
    },
    "hinata_true_hero": {
        "name": "Hinata", "form": "True Hero Tier", "rarity": "mythic", "role": "dps", "species": "hero",
        "form_index": 3, "evolution_line": "hinata", "gender": "female",
        "hp": 298, "attack": 56, "defense": 34, "speed": 36, "passive_skill": "void_authority", "emoji": "✨",
    },
    "yuuki_mastermind": {
        "name": "Yuuki", "form": "Mastermind", "rarity": "legendary", "role": "support", "species": "human",
        "form_index": 1, "evolution_line": "yuuki", "gender": "male",
        "hp": 222, "attack": 36, "defense": 26, "speed": 28, "passive_skill": "predator_core", "emoji": "♟️",
    },
    "shizu_inferno": {
        "name": "Shizu", "form": "Inferno Hero", "rarity": "legendary", "role": "dps", "species": "human",
        "form_index": 1, "evolution_line": "shizu", "gender": "female",
        "hp": 226, "attack": 41, "defense": 24, "speed": 27, "passive_skill": "flame_slash", "emoji": "🔥",
    },
    "chloe_time_hero": {
        "name": "Chloe", "form": "Time Hero", "rarity": "mythic", "role": "dps", "species": "hero",
        "form_index": 1, "evolution_line": "chloe", "gender": "female",
        "hp": 310, "attack": 57, "defense": 36, "speed": 34, "passive_skill": "void_authority", "emoji": "⏳",
    },

    "kaijin_dwarf_smith": {
        "name": "Kaijin", "form": "Dwarf Smith", "rarity": "rare", "role": "support", "species": "dwarf",
        "form_index": 1, "evolution_line": "kaijin", "gender": "male",
        "hp": 152, "attack": 18, "defense": 19, "speed": 12, "passive_skill": "iron_bastion", "emoji": "🔨",
    },
    "kurobe_master_smith": {
        "name": "Kurobe", "form": "Master Blacksmith", "rarity": "epic", "role": "support", "species": "dwarf",
        "form_index": 1, "evolution_line": "kurobe", "gender": "male",
        "hp": 188, "attack": 26, "defense": 24, "speed": 14, "passive_skill": "blade_discipline", "emoji": "⚒️",
    },
    "myourmiles_steward": {
        "name": "Myourmiles", "form": "Grand Steward", "rarity": "rare", "role": "support", "species": "human",
        "form_index": 1, "evolution_line": "myourmiles", "gender": "male",
        "hp": 134, "attack": 14, "defense": 15, "speed": 15, "passive_skill": "arcane_mist", "emoji": "💰",
    },
    "vesta_researcher": {
        "name": "Vesta", "form": "Arc Researcher", "rarity": "epic", "role": "support", "species": "dwarf",
        "form_index": 1, "evolution_line": "vesta", "gender": "male",
        "hp": 174, "attack": 24, "defense": 18, "speed": 18, "passive_skill": "moon_veil", "emoji": "🧪",
    },
    "gazel_dwargo_king": {
        "name": "Gazel", "form": "King of Dwargon", "rarity": "legendary", "role": "tank", "species": "dwarf",
        "form_index": 1, "evolution_line": "gazel", "gender": "male",
        "hp": 252, "attack": 38, "defense": 33, "speed": 23, "passive_skill": "tyrant_guard", "emoji": "👑",
    },

    "reyheim_priest": {
        "name": "Reyheim", "form": "Church Priest", "rarity": "rare", "role": "healer", "species": "human",
        "form_index": 1, "evolution_line": "reyheim", "gender": "male",
        "hp": 142, "attack": 16, "defense": 16, "speed": 14, "passive_skill": "spirit_blessing", "emoji": "⛪",
    },
    "arnaud_paladin": {
        "name": "Arnaud", "form": "Paladin", "rarity": "epic", "role": "tank", "species": "human",
        "form_index": 1, "evolution_line": "arnaud", "gender": "male",
        "hp": 196, "attack": 25, "defense": 24, "speed": 18, "passive_skill": "battle_fortitude", "emoji": "🛡️",
    },
    "fritz_crusader": {
        "name": "Fritz", "form": "Crusader", "rarity": "epic", "role": "dps", "species": "human",
        "form_index": 1, "evolution_line": "fritz", "gender": "male",
        "hp": 182, "attack": 30, "defense": 19, "speed": 22, "passive_skill": "blade_discipline", "emoji": "⚔️",
    },
    "glenda_attley_sniper": {
        "name": "Glenda", "form": "Attley Sniper", "rarity": "epic", "role": "dps", "species": "human",
        "form_index": 1, "evolution_line": "glenda", "gender": "female",
        "hp": 168, "attack": 31, "defense": 16, "speed": 25, "passive_skill": "night_execution", "emoji": "🎯",
    },

    "king_edmaris": {
        "name": "Edmaris", "form": "King of Farmus", "rarity": "epic", "role": "support", "species": "human",
        "form_index": 1, "evolution_line": "edmaris", "gender": "male",
        "hp": 176, "attack": 22, "defense": 20, "speed": 15, "passive_skill": "arcane_mist", "emoji": "👑",
    },
    "razen_grand_mage": {
        "name": "Razen", "form": "Grand Mage", "rarity": "legendary", "role": "support", "species": "human",
        "form_index": 1, "evolution_line": "razen", "gender": "male",
        "hp": 224, "attack": 39, "defense": 25, "speed": 26, "passive_skill": "predator_core", "emoji": "🔥",
    },
    "folgen_general": {
        "name": "Folgen", "form": "Farmus General", "rarity": "epic", "role": "tank", "species": "human",
        "form_index": 1, "evolution_line": "folgen", "gender": "male",
        "hp": 198, "attack": 27, "defense": 23, "speed": 17, "passive_skill": "battle_fortitude", "emoji": "🪖",
    },

    "yamza_executive": {
        "name": "Yamza", "form": "Clayman Executive", "rarity": "epic", "role": "dps", "species": "majin",
        "form_index": 1, "evolution_line": "yamza", "gender": "male",
        "hp": 182, "attack": 32, "defense": 18, "speed": 23, "passive_skill": "hell_flame", "emoji": "🩹",
    },
    "tear_clown": {
        "name": "Tear", "form": "Moderate Harlequin", "rarity": "legendary", "role": "support", "species": "majin",
        "form_index": 1, "evolution_line": "tear", "gender": "female",
        "hp": 228, "attack": 37, "defense": 24, "speed": 27, "passive_skill": "moon_veil", "emoji": "🎭",
    },
    "footman_clown": {
        "name": "Footman", "form": "Moderate Harlequin", "rarity": "legendary", "role": "tank", "species": "majin",
        "form_index": 1, "evolution_line": "footman", "gender": "male",
        "hp": 248, "attack": 34, "defense": 30, "speed": 20, "passive_skill": "tyrant_guard", "emoji": "🎪",
    },

    "suphia_beast_warrior": {
        "name": "Suphia", "form": "Beast Warrior", "rarity": "epic", "role": "dps", "species": "beastman",
        "form_index": 1, "evolution_line": "suphia", "gender": "female",
        "hp": 184, "attack": 34, "defense": 19, "speed": 25, "passive_skill": "night_execution", "emoji": "🐆",
    },
    "albis_serpent": {
        "name": "Albis", "form": "Serpent Queen", "rarity": "legendary", "role": "support", "species": "beastman",
        "form_index": 1, "evolution_line": "albis", "gender": "female",
        "hp": 230, "attack": 36, "defense": 27, "speed": 28, "passive_skill": "moon_veil", "emoji": "🐍",
    },
    "phobio_lion": {
        "name": "Phobio", "form": "Lion Warrior", "rarity": "epic", "role": "dps", "species": "beastman",
        "form_index": 1, "evolution_line": "phobio", "gender": "male",
        "hp": 192, "attack": 33, "defense": 20, "speed": 24, "passive_skill": "flame_slash", "emoji": "🦁",
    },

    "velgrynd_scorch_dragon": {
        "name": "Velgrynd", "form": "Scorch Dragon", "rarity": "mythic", "role": "dps", "species": "true_dragon",
        "form_index": 1, "evolution_line": "velgrynd", "gender": "female",
        "hp": 330, "attack": 60, "defense": 36, "speed": 34, "passive_skill": "flame_sovereign", "emoji": "🔥",
    },
    "velzard_frost_dragon": {
        "name": "Velzard", "form": "Frost Dragon", "rarity": "mythic", "role": "tank", "species": "true_dragon",
        "form_index": 1, "evolution_line": "velzard", "gender": "female",
        "hp": 348, "attack": 54, "defense": 44, "speed": 30, "passive_skill": "storm_skin", "emoji": "❄️",
    },

    "beretta_demon_doll": {
        "name": "Beretta", "form": "Demon Doll", "rarity": "legendary", "role": "support", "species": "demon",
        "form_index": 1, "evolution_line": "beretta", "gender": "none",
        "hp": 236, "attack": 38, "defense": 28, "speed": 25, "passive_skill": "demonic_contract", "emoji": "🪆",
    },
    "ramiris_fairy_queen": {
        "name": "Ramiris", "form": "Fairy Queen", "rarity": "legendary", "role": "support", "species": "fairy",
        "form_index": 1, "evolution_line": "ramiris", "gender": "female",
        "hp": 220, "attack": 32, "defense": 30, "speed": 30, "passive_skill": "arcane_mist", "emoji": "🧚",
    },
    "zegion_insect_king": {
        "name": "Zegion", "form": "Insect King", "rarity": "mythic", "role": "tank", "species": "insect",
        "form_index": 1, "evolution_line": "zegion", "gender": "male",
        "hp": 336, "attack": 57, "defense": 40, "speed": 31, "passive_skill": "void_authority", "emoji": "🪲",
    },
    "apito_queen_bee": {
        "name": "Apito", "form": "Queen Bee", "rarity": "legendary", "role": "support", "species": "insect",
        "form_index": 1, "evolution_line": "apito", "gender": "female",
        "hp": 244, "attack": 37, "defense": 29, "speed": 29, "passive_skill": "spirit_blessing", "emoji": "🐝",
    },
    "kumara_nine_tail": {
        "name": "Kumara", "form": "Nine-Tail Fox", "rarity": "mythic", "role": "dps", "species": "beast",
        "form_index": 1, "evolution_line": "kumara", "gender": "female",
        "hp": 318, "attack": 59, "defense": 34, "speed": 37, "passive_skill": "void_authority", "emoji": "🦊",
    },
    "dord_minister": {
        "name": "Dord", "form": "Dwarf Minister", "rarity": "rare", "role": "support", "species": "dwarf",
        "form_index": 1, "evolution_line": "dord", "gender": "male",
        "hp": 146, "attack": 16, "defense": 18, "speed": 13, "passive_skill": "arcane_mist", "emoji": "📘",
    },
    "kaido_general": {
        "name": "Kaido", "form": "Dwargon General", "rarity": "epic", "role": "tank", "species": "dwarf",
        "form_index": 1, "evolution_line": "kaido", "gender": "male",
        "hp": 202, "attack": 26, "defense": 25, "speed": 17, "passive_skill": "iron_bastion", "emoji": "🏹",
    },
    "grigori_inquisitor": {
        "name": "Grigori", "form": "Inquisitor", "rarity": "epic", "role": "dps", "species": "human",
        "form_index": 1, "evolution_line": "grigori", "gender": "male",
        "hp": 178, "attack": 31, "defense": 18, "speed": 23, "passive_skill": "night_execution", "emoji": "⚖️",
    },
    "abiru_orc_general": {
        "name": "Abiru", "form": "Orc General", "rarity": "epic", "role": "tank", "species": "high_orc",
        "form_index": 1, "evolution_line": "abiru_orc", "gender": "male",
        "hp": 218, "attack": 28, "defense": 26, "speed": 16, "passive_skill": "battle_fortitude", "emoji": "🐗",
    },
    "masayuki_chosen": {
        "name": "Masayuki", "form": "Chosen Hero", "rarity": "legendary", "role": "support", "species": "human",
        "form_index": 1, "evolution_line": "masayuki", "gender": "male",
        "hp": 240, "attack": 36, "defense": 30, "speed": 28, "passive_skill": "predator_core", "emoji": "🎖️",
    },
    "gadra_ancient_mage": {
        "name": "Gadra", "form": "Ancient Mage", "rarity": "legendary", "role": "support", "species": "human",
        "form_index": 1, "evolution_line": "gadra", "gender": "male",
        "hp": 228, "attack": 40, "defense": 24, "speed": 27, "passive_skill": "moon_veil", "emoji": "📚",
    },
    "adalman_undead_priest": {
        "name": "Adalman", "form": "Undead Priest", "rarity": "legendary", "role": "healer", "species": "undead",
        "form_index": 1, "evolution_line": "adalman", "gender": "male",
        "hp": 246, "attack": 34, "defense": 28, "speed": 21, "passive_skill": "spirit_blessing", "emoji": "💀",
    },
    "albert_undead_knight": {
        "name": "Albert", "form": "Undead Knight", "rarity": "epic", "role": "tank", "species": "undead",
        "form_index": 1, "evolution_line": "albert", "gender": "male",
        "hp": 214, "attack": 28, "defense": 26, "speed": 18, "passive_skill": "tyrant_guard", "emoji": "🦴",
    },
    "treyni_dryad": {
        "name": "Treyni", "form": "Dryad", "rarity": "epic", "role": "support", "species": "dryad",
        "form_index": 1, "evolution_line": "treyni", "gender": "female",
        "hp": 186, "attack": 24, "defense": 22, "speed": 24, "passive_skill": "spirit_blessing", "emoji": "🌿",
    },
    "trya_dryad": {
        "name": "Trya", "form": "Dryad", "rarity": "rare", "role": "healer", "species": "dryad",
        "form_index": 1, "evolution_line": "trya", "gender": "female",
        "hp": 150, "attack": 18, "defense": 16, "speed": 20, "passive_skill": "spirit_blessing", "emoji": "🍃",
    },
    "clayman_demon_lord": {
        "name": "Clayman", "form": "Demon Lord", "rarity": "legendary", "role": "support", "species": "demon_lord",
        "form_index": 1, "evolution_line": "clayman", "gender": "male",
        "hp": 236, "attack": 35, "defense": 27, "speed": 24, "passive_skill": "demonic_contract", "emoji": "🎎",
    },
    "frey_harpy_queen": {
        "name": "Frey", "form": "Harpy Queen", "rarity": "legendary", "role": "dps", "species": "harpy",
        "form_index": 1, "evolution_line": "frey", "gender": "female",
        "hp": 226, "attack": 39, "defense": 23, "speed": 31, "passive_skill": "night_execution", "emoji": "🪽",
    },
    "carrion_beast_king": {
        "name": "Carrion", "form": "Beast King", "rarity": "legendary", "role": "tank", "species": "beastman",
        "form_index": 1, "evolution_line": "carrion", "gender": "male",
        "hp": 268, "attack": 37, "defense": 31, "speed": 24, "passive_skill": "battle_fortitude", "emoji": "🦁",
    },
    "leon_cromwell": {
        "name": "Leon", "form": "Cromwell", "rarity": "mythic", "role": "dps", "species": "demon_lord",
        "form_index": 1, "evolution_line": "leon", "gender": "male",
        "hp": 308, "attack": 56, "defense": 34, "speed": 33, "passive_skill": "flame_sovereign", "emoji": "🌟",
    },
    "luminous_valentine": {
        "name": "Luminous", "form": "Valentine", "rarity": "mythic", "role": "support", "species": "demon_lord",
        "form_index": 1, "evolution_line": "luminous", "gender": "female",
        "hp": 304, "attack": 52, "defense": 36, "speed": 32, "passive_skill": "moon_veil", "emoji": "🌹",
    },
    "guy_crimson": {
        "name": "Guy", "form": "Crimson", "rarity": "mythic", "role": "dps", "species": "primordial",
        "form_index": 1, "evolution_line": "guy", "gender": "male",
        "hp": 322, "attack": 60, "defense": 35, "speed": 35, "passive_skill": "void_authority", "emoji": "🩸",
    },
    "veldanava_star_king": {
        "name": "Veldanava", "form": "Star King Dragon", "rarity": "mythic", "role": "support", "species": "god_dragon",
        "form_index": 1, "evolution_line": "veldanava", "gender": "male",
        "hp": 360, "attack": 65, "defense": 42, "speed": 36, "passive_skill": "void_authority", "emoji": "🌌",
    },
}


DEFAULT_CHARACTER_IMAGE_URL = "IMAGE_URL_HERE"
for _char in CHARACTERS.values():
    if isinstance(_char, dict):
        _char.setdefault("image", DEFAULT_CHARACTER_IMAGE_URL)


CHARACTER_RARITY = {
    "common": {"chance": 0.50, "pity_bonus": 0},
    "rare": {"chance": 0.28, "pity_bonus": 0},
    "epic": {"chance": 0.14, "pity_bonus": 0},
    "legendary": {"chance": 0.08, "pity_bonus": 3},
    "mythic": {"chance": 0.00, "pity_bonus": 0},
}


GACHA_BANNERS = {
    "none": {
        "name": "Standard Rift",
        "rate_up_lines": [],
    },
    "benimaru": {
        "name": "Crimson General Banner",
        "rate_up_lines": ["benimaru"],
    },
    "rimuru": {
        "name": "Azure Sovereign Banner",
        "rate_up_lines": ["rimuru"],
    },
    "tempest": {
        "name": "Tempest Retainers Banner",
        "rate_up_lines": ["benimaru", "shion", "shuna", "souei", "hakurou", "geld", "gobta", "gabiru"],
    },
    "primordial": {
        "name": "Primordial Conclave Banner",
        "rate_up_lines": ["diablo", "testarossa", "ultima", "carrera"],
    },
    "beast": {
        "name": "Eurazania Fang Banner",
        "rate_up_lines": ["ranga", "suphia", "albis", "phobio", "kumara"],
    },
    "demonlords": {
        "name": "Demon Lord Court Banner",
        "rate_up_lines": ["rimuru", "milim", "clayman", "frey", "carrion", "ramiris", "yuuki"],
    },
}


ROLE_SYNERGY = {
    ("tank", "healer"): {"def_bonus": 0.15, "desc": "Tank + Healer: +15% Guard"},
    ("dps", "support"): {"dmg_bonus": 0.15, "desc": "DPS + Support: +15% Might"},
    ("support", "healer"): {"heal_bonus": 0.18, "desc": "Support + Healer: +18% Heal"},
    ("tank", "support"): {"def_bonus": 0.1, "desc": "Tank + Support: +10% Guard"},
    ("dps", "dps"): {"dmg_bonus": 0.1, "desc": "DPS + DPS: +10% Might"},
}


PASSIVE_SKILLS = {
    "arcane_mist": {"name": "Arcane Mist", "stat": "heal", "bonus": 0.12, "desc": "Support healing up"},
    "predator_core": {"name": "Predator Core", "stat": "crit", "bonus": 0.08, "desc": "Critical chance up"},
    "void_authority": {"name": "Void Authority", "stat": "double", "bonus": 0.18, "desc": "Double strike chance up"},
    "flame_slash": {"name": "Flame Slash", "stat": "attack", "bonus": 0.12, "desc": "Might up"},
    "hell_flame": {"name": "Hell Flame", "stat": "crit", "bonus": 0.1, "desc": "Crit up"},
    "inferno_body": {"name": "Inferno Body", "stat": "lifesteal", "bonus": 0.12, "desc": "Lifesteal up"},
    "flame_sovereign": {"name": "Flame Sovereign", "stat": "attack", "bonus": 0.22, "desc": "Massive might up"},
    "battle_fortitude": {"name": "Battle Fortitude", "stat": "reduction", "bonus": 0.12, "desc": "Damage taken down"},
    "tyrant_guard": {"name": "Tyrant Guard", "stat": "defense", "bonus": 0.18, "desc": "Guard up"},
    "spirit_blessing": {"name": "Spirit Blessing", "stat": "heal", "bonus": 0.18, "desc": "Healing up"},
    "moon_veil": {"name": "Moon Veil", "stat": "reduction", "bonus": 0.1, "desc": "Team ward"},
    "shadow_chain": {"name": "Shadow Chain", "stat": "double", "bonus": 0.12, "desc": "Extra strikes"},
    "night_execution": {"name": "Night Execution", "stat": "crit", "bonus": 0.14, "desc": "Assassination crit"},
    "blade_discipline": {"name": "Blade Discipline", "stat": "attack", "bonus": 0.1, "desc": "Sword mastery"},
    "iron_bastion": {"name": "Iron Bastion", "stat": "defense", "bonus": 0.14, "desc": "Shielded body"},
    "demonic_contract": {"name": "Demonic Contract", "stat": "heal", "bonus": 0.1, "desc": "Dark support aura"},
    "star_dragon": {"name": "Star Dragon", "stat": "attack", "bonus": 0.16, "desc": "Burst might"},
    "storm_skin": {"name": "Storm Skin", "stat": "reduction", "bonus": 0.15, "desc": "Storm barrier"},
    "lucky_slacker": {"name": "Lucky Slacker", "stat": "crit", "bonus": 0.05, "desc": "Lucky crit"},
    "dragon_scale": {"name": "Dragon Scale", "stat": "defense", "bonus": 0.1, "desc": "Scale guard"},
}


GACHA_COST = 100
SOFT_PITY = 50
HARD_PITY = 90
DUPLICATE_SHARD_VALUE = 5
MYTHIC_ASCEND_LEGENDARY_SHARDS = 50


def get_characters_by_rarity(rarity: str) -> list[str]:
    r = str(rarity or "").strip().lower()
    return [cid for cid, c in CHARACTERS.items() if str(c.get("rarity", "")).lower() == r]


def _banner_legendary_candidates(banner_id: str) -> list[str]:
    banner = GACHA_BANNERS.get(str(banner_id or "none").lower()) or GACHA_BANNERS["none"]
    lines = {str(x).lower() for x in banner.get("rate_up_lines", [])}
    if not lines:
        return []
    return [
        cid
        for cid, c in CHARACTERS.items()
        if str(c.get("rarity", "")).lower() == "legendary"
        and str(c.get("evolution_line", "")).lower() in lines
    ]


def get_mythic_form_for_line(evolution_line: str) -> str:
    line = str(evolution_line or "").strip().lower()
    for cid, c in CHARACTERS.items():
        if str(c.get("evolution_line", "")).lower() == line and str(c.get("rarity", "")).lower() == "mythic":
            return cid
    return ""


def _weighted_pick(weight_map: dict[str, float]) -> str:
    roll = random.random()
    cumulative = 0.0
    for rarity, w in weight_map.items():
        cumulative += max(0.0, float(w))
        if roll <= cumulative:
            return rarity
    return "common"


def roll_character(pity_count: int = 0, banner_id: str = "none") -> tuple[str, str]:
    effective_pity = max(0, min(int(pity_count), HARD_PITY))

    if effective_pity >= HARD_PITY:
        rarity = "legendary"
        candidates = get_characters_by_rarity(rarity)
        rate_up = _banner_legendary_candidates(banner_id)
        if rate_up and random.random() < 0.5:
            candidates = rate_up
        if candidates:
            return random.choice(candidates), rarity

    rates = {
        "common": float(CHARACTER_RARITY["common"]["chance"]),
        "rare": float(CHARACTER_RARITY["rare"]["chance"]),
        "epic": float(CHARACTER_RARITY["epic"]["chance"]),
        "legendary": float(CHARACTER_RARITY["legendary"]["chance"]),
    }
    if effective_pity >= SOFT_PITY:
        boost = effective_pity - SOFT_PITY + 1
        rates["legendary"] += boost * 0.001 * float(CHARACTER_RARITY["legendary"]["pity_bonus"])
        rates["common"] = max(0.01, rates["common"] - boost * 0.002)
        rates["rare"] = max(0.05, rates["rare"] - boost * 0.001)

    total = sum(max(0.0, x) for x in rates.values())
    normalized = {k: (max(0.0, v) / total if total > 0 else 0.0) for k, v in rates.items()}
    rarity = _weighted_pick(normalized)

    candidates = get_characters_by_rarity(rarity)
    if rarity == "legendary":
        rate_up = _banner_legendary_candidates(banner_id)
        if rate_up and random.random() < 0.5:
            candidates = rate_up
    if not candidates:
        fallback = list(CHARACTERS.keys())
        if not fallback:
            return "", "common"
        cid = random.choice(fallback)
        return cid, str(CHARACTERS.get(cid, {}).get("rarity", "common"))
    return random.choice(candidates), rarity


def character_exp_needed(level: int) -> int:
    return int(100 + (level ** 1.3) * 50)

