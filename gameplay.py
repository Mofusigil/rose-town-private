"""Local baby care and pot-smelting protocols from the shipped client.

Wire shapes: PetManager/PetData/PetHouseMap, SmeltPotView/SmeltPotCtrl and
FairyPotRefineCtrl/FairyPotAttributeCtrl.
Material experience, gold fees, feed effects and baby identity/lifetime come
from the mirror. Smelting level thresholds were remote: LOCAL_SMELT_RULE is
an explicit local rule (100 experience per attribute level), not recovered
production balance. Attribute caps match the shipped client. Fairy-pot material
fees and progress use explicit local rules; its percentage tables and total
attribute limits are read from refineConfig.xml. Rotation is deterministic.
"""
import copy
import functools
from pathlib import Path
import re
import time

DAY = 86400
LOCAL_SMELT_RULE = "local_smelt_100_exp_per_level_v1"
SMELT_EXP_PER_LEVEL = 100
SMELT_ATTRIBUTES = ("speed", "addon", "charm", "exp")
SMELT_CAPS = (10, 15, 20, 20)
STONE_ID = 161209006
LOCAL_FAIRY_RULE = "local_fairy_costs_and_rotation_v1"
FAIRY_ATTRIBUTES = ("speed", "increase", "charm", "exp")
# FlowerPotProps.isThisaDrangonPotID; aliases carry separate ownership.
DRAGON_POT_IDS = frozenset((120705048, 120705049, 120705058, 120705059,
                          120705067, 120705068, 120705102))


class InvalidOrder(ValueError):
    pass


def number(params, key, default=None, minimum=1, maximum=99999):
    value = params.get(key, default)
    if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value)):
        raise InvalidOrder("%s必须是整数" % key)
    value = int(value)
    if not minimum <= value <= maximum:
        raise InvalidOrder("%s必须在%d到%d之间" % (key, minimum, maximum))
    return value


@functools.lru_cache(maxsize=1)
def baby_catalog():
    # This resource is GBK JavaScript object data. Parse its literal records,
    # never execute the mirrored script on the server.
    source = (Path(__file__).parent / "site/h5/meigui/lib/pet_config.js").read_text(encoding="gb18030")
    return {int(identifier): dict(re.findall(r'(\w+):"([^"\n]*)"', fields))
            for identifier, fields in re.findall(r'pet_(\d+):\{([^{}]*)\}', source)}


def new_pet(seq, kind, now, **extra):
    return {"tp": kind, "seq": seq, "lv": 0, "ph": 100, "dex": 0,
            "evo": 0, "avatarid": 0, "birthday": now, "nick": "", "show": 0,
            "skill": 0, "ca": 0, "cd": 0, "dt": 0, "du": 0, "renewal": 0, **extra}


def grant_baby(state, identifier, count, now):
    """Turn a real AT_BAOBAO award into a usable traditional baby instance."""
    config = baby_catalog().get(identifier)
    if config is None:
        raise InvalidOrder("宝宝奖励缺少本地配置")
    pets = state["pets"]
    pet = next((p for p in pets.values() if p.get("tp") == 0 and p.get("avatarid") == identifier), None)
    if pet is None:
        seq = max([0, *pets]) + 1
        pet = new_pet(seq, 0, now, avatarid=identifier,
                      lv=int(config["lvl"]), dex=int(config["dex"]))
        pets[seq] = pet
    # A repeated award extends its configured lifetime; every baby remains in
    # the inventory. The newest awarded one occupies the ordinary baby's bed.
    for other in pets.values():
        if other.get("tp") == 0:
            other["show"] = 0
    pet["show"] = 1
    state["activities"].setdefault("baby_care", {})["carried_seq"] = pet["seq"]
    pet["expires_at"] = max(now, pet.get("expires_at", 0)) + int(config["life"]) * count
    pet["efday"] = max(0, (pet["expires_at"] - now + DAY - 1) // DAY)
    return pet


def migrate_babies(state, timestamp):
    """Recover old recorded awards once, using a stable save-file timestamp.

    Old saves recorded counters without instances or award times. Their file
    timestamp anchors that one-time local migration so merely reloading never
    renews a baby's lifetime. Existing reward counters remain readable.
    """
    store = state["activities"].get("giftcard", {})
    recorded = store.get("baobao", {})
    if not recorded:
        return
    applied = store.setdefault("baobao_applied", {})
    for identifier, count in recorded.items():
        missing = int(count) - int(applied.get(identifier, 0))
        if missing > 0 and int(identifier) in baby_catalog():
            grant_baby(state, int(identifier), missing, timestamp)
            applied[identifier] = int(count)


def pet_payload(pet, now):
    result = new_pet(pet["seq"], pet["tp"], pet.get("birthday", now), **{
        key: value for key, value in pet.items() if key not in ("seq", "tp", "birthday")})
    if "expires_at" in result:
        result["efday"] = max(0, (result["expires_at"] - now + DAY - 1) // DAY)
    if isinstance(result["birthday"], (int, float)):
        result["birthday"] = time.strftime("%Y-%m-%d", time.gmtime(result["birthday"] + 8 * 3600))
    return result


def pets_payload(state, now=None):
    now = int(time.time()) if now is None else now
    pets = [pet_payload(pet, now) for pet in state["pets"].values()]
    result = {"pets": pets}
    for kind in range(7):
        choices = [pet for pet in pets if pet.get("tp") == kind]
        if choices:
            # PetManager reads these named fields, not the optional pets array.
            pet = _choose_pet(state, choices, kind)
            result["TakeonPetInfo" if kind == 0 else "TPetInfo%d" % (kind - 1)] = pet
    return result


def _choose_pet(state, choices, kind):
    carried = state["activities"].get("baby_care", {}).get("carried_seq") if kind == 0 else None
    return next((pet for pet in choices if pet["seq"] == carried), None) or max(
        choices, key=lambda p: (int(p.get("show", 0)), int(p["seq"])))


def _find_pet(state, params, *, sequence=False):
    if sequence:
        seq = number(params, "petseq", maximum=2147483647)
        pet = state["pets"].get(seq)
    else:
        kind = number(params, "pt", minimum=0, maximum=6)
        choices = [p for p in state["pets"].values() if p.get("tp") == kind]
        pet = _choose_pet(state, choices, kind) if choices else None
    if pet is None:
        raise InvalidOrder("宝宝不存在，请先领取或获得宝宝")
    return pet


def _care(cmd, params, state, now):
    if cmd == "rosary_set_pet_neck":
        pet = _find_pet(state, params, sequence=True)
        nick = params.get("nick", "")
        if not isinstance(nick, str) or not 1 <= len(nick.strip()) <= 20 or any(ord(c) < 32 for c in nick):
            raise InvalidOrder("宝宝昵称必须是1到20个可见字符")
        pet["nick"] = nick.strip()
        return {"strPetNick": pet["nick"], "petseq": pet["seq"]}
    pet = _find_pet(state, params)
    if cmd == "rosary_set_pet_status":
        status = number(params, "st", minimum=0, maximum=1)
        pet["show"] = status
        return {"pt": pet["tp"], "st": status}
    material = number(params, "mi", maximum=2147483647)
    material = 4 if material == 115 else material
    if material not in (4, 320, 321):
        raise InvalidOrder("该道具不是已支持的宝宝食物")
    count = number(params, "count")
    owned = state["props"].get(material, 0)
    if owned < count:
        raise InvalidOrder("宝宝食物不足")
    evadd, phadd, lfadd = (count if material == 320 else 0,
                         100 * count if material == 4 else 0,
                         count if material == 321 else 0)
    pet["evo"] = pet.get("evo", 0) + evadd
    pet["ph"] = pet.get("ph", 0) + phadd
    if lfadd:
        old_end = pet.get("expires_at", now + pet.get("efday", 0) * DAY)
        pet["expires_at"] = max(now, old_end) + lfadd * DAY
        pet["efday"] = (pet["expires_at"] - now + DAY - 1) // DAY
    state["props"][material] = owned - count
    return {"nm": owned - count, "evadd": evadd, "phadd": phadd,
            "lfadd": lfadd, **pet_payload(pet, now)}


def _available(state, identifier, now):
    expiry = state["decorations"].get(identifier)
    return expiry is not None and (expiry == 0 or expiry > now)


def dragon_pot(state, identifier):
    points = state["activities"].get("smelt_pots", {}).get(str(identifier), {})
    result = {"id": identifier}
    for attribute, cap in zip(SMELT_ATTRIBUTES, SMELT_CAPS):
        total = min(max(0, int(points.get(attribute, 0))), cap * SMELT_EXP_PER_LEVEL)
        level = total // SMELT_EXP_PER_LEVEL
        result[attribute] = [level, total, level * SMELT_EXP_PER_LEVEL,
                             (level + 1) * SMELT_EXP_PER_LEVEL if level < cap else 0]
    return result


def dragon_payload(state):
    # Initialize every catalog pot so a newly awarded one can open its smelting
    # panel immediately. Ownership still comes from the decoration inventory.
    return {"dragonPotList": [dragon_pot(state, identifier)
            for identifier in sorted(DRAGON_POT_IDS)],
            "local_smelt_rule": LOCAL_SMELT_RULE}


def pot_bonuses(state, pot_type, now, pot=None):
    identifier = state["active_decorations"].get("pot%d" % pot_type, 0)
    result = dict.fromkeys(SMELT_ATTRIBUTES, 0)
    if identifier in DRAGON_POT_IDS and _available(state, identifier, now):
        result.update({key: value[0] for key, value in dragon_pot(state, identifier).items() if key != "id"})
    if pot and pot_type == 2:
        attributes = pot.get("hpattribute", {})
        for key, wire_key in zip(SMELT_ATTRIBUTES, FAIRY_ATTRIBUTES):
            result[key] += attributes.get(wire_key, 0) / 10
    result["speed"] = min(90, result["speed"])
    return result


def fairy_payload(state, identifier, pot):
    level = pot["potlevel"]
    index = sum(p["SoilType"] == 2 for n, p in state["pots"].items() if n <= identifier)
    jade = 31020 + min(2, max(0, level - 1))
    attributes = {key: pot.get("hpattribute", {}).get(key, 0) for key in FAIRY_ATTRIBUTES}
    return {"soilno": identifier, "hanglevel": level, "hangpercent": pot.get("hangpercent", 0),
            "hpattribute": attributes, "local_fairy_rule": LOCAL_FAIRY_RULE,
            "need": {"stone": 1, "material": [{"type": 6, "id": 1001, "count": (level + 1) * 1000}]},
            "attrneed": {"stone": 1, "material": [{"type": 0, "id": jade, "count": 1}]},
            "local_fairy_index": index}


def _fairy(params, state, catalog):
    identifier = number(params, "soilno", maximum=99)
    pot = state["pots"].get(identifier)
    if pot is None or pot["SoilType"] != 2:
        raise InvalidOrder("请先解锁仙藤花盆")
    operation = number(params, "actionop", minimum=3, maximum=7)
    current = fairy_payload(state, identifier, pot)
    attributes = current["hpattribute"]
    level, progress, index = pot["potlevel"], current["hangpercent"], current["local_fairy_index"]
    limits = {int(item.get("level")): int(item.get("sum")) * 10 for item in catalog("refineConfig.xml").findall("Limit")}
    maximum_level = max(limits)
    if level not in limits:
        raise InvalidOrder("仙藤花盆等级不在本地配置中")
    if operation in (3, 4):
        if "pending_hpattribute" in pot:
            raise InvalidOrder("请先保存或放弃待选属性")
        stone = number(params, "stoneid", minimum=31005, maximum=31009)
        if state["props"].get(stone, 0) < 1:
            raise InvalidOrder("炼盆灵石不足")
        if operation == 3:
            if level >= maximum_level:
                raise InvalidOrder("仙藤花盆已满级")
            fee = (level + 1) * 1000
            if state["rosemoney"] < fee:
                raise InvalidOrder("炼盆金币不足")
            candidates = catalog("refineConfig.xml").findall("levelConfig/item")
            row = next((r for r in candidates if int(r.get("potindex")) == index and
                        int(r.get("level")) == level + 1 and
                        int(r.get("percent_min")) <= progress <= int(r.get("percent_max"))), None)
        else:
            if sum(attributes.values()) >= limits[level]:
                raise InvalidOrder("请先提升仙藤花盆等级，再炼制属性")
            jade = current["attrneed"]["material"][0]["id"]
            if state["props"].get(jade, 0) < 1:
                raise InvalidOrder("炼盆灵玉不足")
            candidates = catalog("refineConfig.xml").findall("attrConfig/item")
            total = sum(attributes.values())
            row = next((r for r in candidates if int(r.get("potindex")) == index and
                        int(r.get("attrsum_min")) <= total <= int(r.get("attrsum_max"))), None)
        if row is None:
            raise InvalidOrder("本地配置没有该仙藤花盆的炼制规则")
        # Reproducible local rotation against the shipped success percentages;
        # it does not reproduce the original server's random-number generator.
        attempt = pot.get("refine_attempts", 0)
        succeeded = int((attempt * 37) % 100 < int(row.get("prob%d" % (stone - 31004))))
        state["props"][stone] -= 1
        pot["refine_attempts"] = attempt + 1
        if operation == 3:
            state["rosemoney"] -= fee
            if succeeded:
                progress += 1
                if progress >= 100:
                    pot["potlevel"], progress = level + 1, 0
                pot["hangpercent"] = progress
            response = {"change": {"stone": -1, "material": [{"type": 6, "id": 1001, "count": -fee}]}}
        else:
            state["props"][jade] -= 1
            if succeeded:
                key = FAIRY_ATTRIBUTES[pot.get("attribute_successes", 0) % 4]
                attributes[key] += min(10, limits[level] - sum(attributes.values()))
                pot["hpattribute"] = attributes
                pot["attribute_successes"] = pot.get("attribute_successes", 0) + 1
            response = {"useprop": {"stone": -1, "material": [{"type": 0, "id": jade, "count": -1}]}}
        return {**fairy_payload(state, identifier, pot), **response, "stoneid": stone, "refsucc": succeeded}
    if operation == 5:
        if not sum(attributes.values()):
            raise InvalidOrder("请先炼制属性，再进行属性重置")
        candidate = dict(attributes)
        turn = pot.get("attribute_previews", 0)
        start = turn % 4
        source = next((FAIRY_ATTRIBUTES[(start + i) % 4] for i in range(4)
                       if candidate[FAIRY_ATTRIBUTES[(start + i) % 4]] > 0), None)
        destination = FAIRY_ATTRIBUTES[(FAIRY_ATTRIBUTES.index(source) + 1) % 4]
        amount = min(10, candidate[source])
        candidate[source] -= amount
        candidate[destination] += amount
        pot["pending_hpattribute"] = candidate
        pot["attribute_previews"] = turn + 1
        return {**current, "hpattribute": candidate}
    if "pending_hpattribute" not in pot:
        raise InvalidOrder("没有待保存的属性")
    candidate = pot.pop("pending_hpattribute")
    if operation == 6:
        pot["hpattribute"] = candidate
    return fairy_payload(state, identifier, pot)


def _smelt(params, state, catalog, now):
    request = number(params, "request", maximum=2)
    if request == 1:
        count = number(params, "count")
        state["props"][STONE_ID] = state["props"].get(STONE_ID, 0) + count
        return {"now": now, "count": state["props"][STONE_ID]}
    identifier = number(params, "potID", maximum=2147483647)
    if identifier not in DRAGON_POT_IDS or not _available(state, identifier, now):
        raise InvalidOrder("请先获得有效的聚灵花盆装饰")
    attribute_index = number(params, "attrType", maximum=4) - 1
    attribute = SMELT_ATTRIBUTES[attribute_index]
    auto = number(params, "auto", 0, minimum=0, maximum=1)
    count = number(params, "count", maximum=100)
    number(params, "soilno", 0, minimum=0, maximum=99)
    current = dragon_pot(state, identifier)[attribute]
    if current[3] == 0:
        raise InvalidOrder("该属性已满级")
    definitions = {int(item.get("id")): item for item in catalog("SmeltPotConfig.xml").findall("list/item")}
    costs, gain, gold = [], 0, 0
    seen = set()
    for index in range(1, count + 1):
        material = number(params, "id%d" % index, maximum=2147483647)
        quantity = number(params, "count%d" % index)
        config = definitions.get(material)
        if config is None or material in seen or material == identifier:
            raise InvalidOrder("炼盆材料无效或重复")
        seen.add(material)
        if material in state["decorations"]:
            # The current save format owns decorations once, not by count.
            inventory, owned = "decorations", int(_available(state, material, now))
            if material in state["active_decorations"].values():
                raise InvalidOrder("请先卸下作为材料的装饰")
        elif material in state["pergolas"]:
            inventory, owned = "pergolas", state["pergolas"][material]
        else:
            inventory, owned = "props", state["props"].get(material, 0)
        if owned < quantity:
            raise InvalidOrder("炼盆材料不足")
        costs.append((inventory, material, quantity))
        gain += int(config.get("value")) * quantity
        gold += int(config.get("cost")) * quantity
    if state["rosemoney"] < gold:
        raise InvalidOrder("炼盆金币不足")
    need_level = int(catalog("SmeltPotConfig.xml").find("setting/%s/item" % attribute).get("need"))
    # Charge only experience at/above the stone threshold, including a single
    # large order that crosses several levels; ignore experience beyond the cap.
    next_total = min(current[1] + gain, SMELT_CAPS[attribute_index] * SMELT_EXP_PER_LEVEL)
    stone = max(0, next_total - max(current[1], need_level * SMELT_EXP_PER_LEVEL))
    owned_stone = state["props"].get(STONE_ID, 0)
    deficit = max(0, stone - owned_stone)
    if deficit and (not auto or deficit > 2000):
        raise InvalidOrder("聚灵石不足（自动购买单次最多2000个）")
    for inventory, material, quantity in costs:
        if inventory == "decorations":
            del state[inventory][material]
        else:
            state[inventory][material] -= quantity
    state["rosemoney"] -= gold
    state["props"][STONE_ID] = max(0, owned_stone - stone)
    points = state["activities"].setdefault("smelt_pots", {}).setdefault(str(identifier), {})
    points[attribute] = min(current[1] + gain, SMELT_CAPS[attribute_index] * SMELT_EXP_PER_LEVEL)
    return {"now": now, "potInfo": dragon_pot(state, identifier),
            "coin": state["rosemoney"], "prop": state["props"][STONE_ID],
            "local_smelt_rule": LOCAL_SMELT_RULE, "local_auto_bought_stones": deficit}


def handle(cmd, params, *, state, lock, catalog, persist):
    smelt = cmd == "rosary_activity_oper" and str(params.get("cmd")) == "192"
    fairy = cmd == "rosary0904_expand" and str(params.get("action")) == "6" and str(params.get("actionop")) not in ("1", "2")
    if not smelt and not fairy and cmd not in ("rosary_set_pet_neck", "rosary_set_pet_status", "rosary_talent_pet_feed"):
        return None
    with lock:
        previous = copy.deepcopy(state)
        now = int(time.time())
        try:
            if smelt:
                response = _smelt(params, state, catalog, now)
            elif fairy:
                response = _fairy(params, state, catalog)
            else:
                response = _care(cmd, params, state, now)
        except InvalidOrder as error:
            state.clear()
            state.update(previous)
            return {"result": 1, "resultstr": str(error)}
        if state != previous:
            persist(previous)
        return response
