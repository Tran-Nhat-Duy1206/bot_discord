# Team RPG Game Logic (New Direction)

## 1. Product Direction

Game da chuyen tu **solo RPG** sang **team-based character RPG** theo roadmap trong `TODO.md`.

Muc tieu:
- Tang retention bang collection + gacha.
- Giu Discord UX don gian (uu tien passive, han che active spam).
- Khong pha economy va combat core cua he thong cu.

Core loop moi:
1. Build team (main character + heroes).
2. Hunt/Boss/Dungeon bang team.
3. Nhan gold/xp/material.
4. Roll gacha de mo rong bo suu tap va toi uu team.

---

## 2. Design Rules (Bat buoc)

- Character **khong duoc thiet ke theo huong creep power**; khac nhau chu yeu o role/passive.
- Team size nho, de doc tren Discord: **toi da 5 character**.
- Passive > Active (giam thao tac va tranh chat spam).
- Gacha khong pay-to-win; duplicate co co che chuyen doi.
- Khong rewrite toan bo he thong cu, chi them layer team/character.

---

## 3. Character Layer

### 3.1 Character model

Moi player gom:
- 1 `main_character` (bat buoc).
- Danh sach heroes so huu qua gacha.

Bang du lieu chinh:
- `characters`: dinh nghia nhan vat, role, rarity, stat base.
- `player_characters`: nhan vat ma user so huu + tien trinh rieng.

### 3.2 Role system

4 role chinh:
- DPS
- Tank
- Healer
- Support

Nguyen tac role:
- Khong role nao vuot troi toan dien.
- Moi role dong gop khac nhau vao damage/sustain/utility.

---

## 4. Team System

### 4.1 Cau truc team

- Team size: **5** (1 main + 4 hero).
- Team phai duoc validate truoc combat.
- Team duoc luu DB de tai su dung cho cac mode (hunt/boss/dungeon).

### 4.2 Team Power

Team power duoc dung de scale PvE:

```python
team_power = sum(char.atk + char.def + char.hp * 0.2)
```

Rules:
- Scale monster theo `team_power`.
- **Khong** scale theo so luong character de tranh exploit.

---

## 5. Combat Refactor (Team Combat)

### 5.1 Combat flow moi

```text
1) Kiem tra team hop le
2) Apply passive tu tat ca character
3) Team attack (tong contribution)
4) Monster attack (phan bo len team theo logic hien tai)
5) Tick heal/reduction/passive theo turn
6) Lap lai den khi ket thuc tran
```

### 5.2 Damage model

Van giu cong thuc damage co ban cua he thong cu, nhung dau vao la tong dong gop team:

```python
base_damage = team_atk * (100 / (100 + monster_def)) + random(-2, 4)
final_damage = max(1, base_damage)
```

Trong do `team_atk` la tong contribution sau passive/role buff.

### 5.3 Passive-first combat

- Khong uu tien active skill spam.
- Passive la trung tam cho role identity:
  - DPS: tang crit/damage on-hit.
  - Tank: giam damage team nhan.
  - Healer: hoi phuc nhe moi turn.
  - Support: buff toc do/tang hieu qua dong doi.

Ghi chu: he thong passive detail dang o phase tiep theo, can giu stack cap de tranh power creep.

---

## 6. Gacha System (Core Retention)

### 6.1 Trigger

Command chinh: `/gacha`.

### 6.2 Rarity pool

- Common
- Rare
- Epic
- Legendary

### 6.3 Pity + duplicate handling

- Co soft pity de tranh unlucky streak qua dai.
- Duplicate khong vo nghia: convert thanh shard/gold (tuy phase).

Muc tieu:
- Moi lan roll deu co gia tri.
- Khong lam met nguoi choi bang duplicate vo dung.

---

## 7. Economy & Progression (Compatibility)

He thong sau tiep tuc duoc giu va tai su dung:
- Gold economy (reward, sink, transfer limit).
- Equipment/crafting/shop.
- Quest/dungeon/party season.

Dieu chinh huong team:
- Reward tinh theo team combat output.
- Quest mo rong objective theo character/role (phase sau).
- Dungeon uu tien synergy role hon la stat thuan.

---

## 8. Implementation Status Theo Roadmap

### 8.1 Da xong (moc quan trong)

- Character system (main + heroes, bang du lieu lien quan).
- Role system (DPS/Tank/Healer/Support).
- Team system (size 5, validate, save DB).
- Combat refactor Player -> Team.
- Team power scaling.
- Gacha core + pity + anti-duplicate.

### 8.2 Dang mo rong (phase tiep theo)

- Passive skill day du cho tung character.
- Team synergy bonus theo role mix.
- Character progression rieng (exp/level).
- Banner, gem, shard economy day du.
- Team-based dungeon/party/quest integration.

---

## 9. Formula Snapshot (Current + Team Context)

```python
# Team power
team_power = sum(char.atk + char.def + char.hp * 0.2)

# Team damage vs monster
damage = team_atk * (100 / (100 + monster_def)) + random(-2, 4)
damage = max(1, damage)

# Crit / reduction cap (giu tu he thong cu, neu dang duoc su dung)
crit_cap = 0.85
damage_reduction_cap = 0.65

# Lifesteal cap (neu co nguon lifesteal)
lifesteal_heal_cap = 0.25 * max_hp
```

Luu y: cac gia tri chi tiet (cooldown, cost, rate) tiep tuc duoc dieu chinh trong code va env, tai lieu nay tap trung vao huong logic moi.

---

## 10. Migration Notes

- Tu duy he thong: `player stats` -> `team aggregate stats`.
- Cac mode combat cu khong bi loai bo, chi doi dau vao thanh team.
- Du lieu cu (gold, inventory, equipment) duoc giu de tranh reset trai nghiem nguoi choi.
- Uu tien backward-compatible, rollout theo phase thay vi rewrite lon.

---

## 11. Priority Order (Current)

1. Character system
2. Team system
3. Combat refactor
4. Gacha
5. Passive skill expansion

Trang thai: 1-4 da co nen tang, buoc tiep theo la mo rong passive/synergy/progression de tao chieu sau gameplay.
