"""Local premium activity protocols, backed by the mirrored client catalog.

The gateway supplies the player state and its atomic persistence callback.
Handlers return business fields only; the gateway adds the free-payment envelope.

GiftCard's annual rewards and the material wheel use the shipped XML tables.
The monthly card table, HappyEgg odds, and PetPK gift/augury rewards were served
remotely and are absent from the mirror. Their explicitly local rules below use
real catalog entries; deterministic rotations make the local game reproducible.
"""

import copy
import datetime as dt
import functools
import re
import time
import gameplay


DAY = 86400
LOCAL_TIMEZONE = dt.timezone(dt.timedelta(hours=8))
# MonthlyCardKey's order is significant: its UI assigns IDs by array position.
MONTHLY_REWARDS = (
    (0, 2, 1),                 # 每日化肥卡: 急速化肥
    (6, 1001, 10000),          # 每日金币卡
    (0, 31005, 1),             # 每日灵石卡
    (0, 120601006, 1),         # 每日琼脂卡
    (0, 26071, 1),             # 夜来香月卡: 夜来香种子
    (0, 31024, 1),             # 营养液月卡: 水培营养液
    (10, 132002022, 1),        # 蝶恋花月卡: 蝶恋花墙纸
)
EGG_REWARDS = ((0, 2, 1), (0, 31005, 1), (0, 120601006, 1),
               (0, 31024, 1), (0, 101, 1))
EGG_BIG_REWARD = (0, 161391001, 1)
PET_GIFT_REWARDS = ((0, 37105, 1), (0, 37106, 1), (0, 37107, 1))
LOCAL_RULE = "local_catalog_rewards_v1"


class InvalidOrder(ValueError):
    """A malformed or unavailable activity order; never a storage error."""


def _number(params, key, default=None, *, minimum=1, maximum=99999):
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError, OverflowError):
        raise InvalidOrder("%s无效" % key) from None
    if not minimum <= value <= maximum:
        raise InvalidOrder("%s必须在%d到%d之间" % (key, minimum, maximum))
    return value


def _date(now):
    return dt.datetime.fromtimestamp(now, LOCAL_TIMEZONE).date()


def _month(now):
    date = _date(now)
    return date.year * 12 + date.month - 1


def _award(category, identifier, count, **extra):
    return {"type": category, "id": identifier, "count": count, **extra}


@functools.lru_cache(maxsize=4)
def _item_index(catalog):
    """Separate wire/server IDs from the player's canonical inventory keys."""
    root = catalog("propConfig.xml")
    props = {int(item.get("id")): dict(item.attrib)
             for path in ("propConfig/item", "meterial/others/item")
             for item in root.findall(path)}
    for section in ("tokenConfig", "runesConfig"):
        for item in catalog("petPKConfig.xml").findall(section + "/item"):
            props[int(item.get("id"))] = dict(item.attrib)
    roses = {int(item.get("id")): dict(item.attrib)
             for item in root.findall("meterial/seeds/item")}
    rose_aliases = {alias: identifier for identifier, item in roses.items()
                    for alias in (identifier, int(item["svrID"]))}
    rose_seed_ids = {int(item["seedID"]): identifier
                     for identifier, item in roses.items()}
    seeds = {int(item.get("seedID")): dict(item.attrib)
             for item in catalog("flowerConfig.xml").findall("flower/item")
             if item.get("seedID")}
    decorations = {int(item.get("id")): dict(item.attrib)
                   for group in root.find("decrateConfig")
                   for item in group.findall("item")}
    server_props = {int(item["svrID"]): identifier
                    for identifier, item in props.items() if item.get("svrID")}
    return props, roses, rose_aliases, rose_seed_ids, seeds, decorations, server_props


def _grant(state, catalog, awards, now):
    """Apply rewards while the transaction lock is held, in catalog units."""
    props, roses, rose_aliases, rose_ids, seeds, decorations, server_props = _item_index(catalog)
    for award in awards:
        category, amount = int(award["type"]), int(award["count"])
        if amount <= 0:
            raise InvalidOrder("奖励数量无效")
        if category == 6:
            state["rosemoney"] += amount
            continue
        if category in (4, 5):
            key = "experience" if category == 4 else "charm"
            state[key] = state.get(key, 0) + amount
            continue
        if category == 3:
            giftcard = state["activities"].setdefault("giftcard", {})
            giftcard["charm_addon"] = int(award.get("charmaddon", 300))
            giftcard["charm_addon_end"] = max(now, giftcard.get("charm_addon_end", 0)) + amount * 60
            continue
        identifier = int(award["id"])
        if category == 1:
            giftcard = state["activities"].setdefault("giftcard", {})
            baobao = giftcard.setdefault("baobao", {})
            key = str(identifier)
            try:
                gameplay.grant_baby(state, identifier, amount, now)
            except gameplay.InvalidOrder as error:
                raise InvalidOrder(str(error)) from None
            baobao[key] = baobao.get(key, 0) + amount
            giftcard.setdefault("baobao_applied", {})[key] = baobao[key]
            continue
        if category == 10:
            if identifier not in decorations:
                raise InvalidOrder("装饰奖励不存在")
            days = int(decorations[identifier].get("period") or 0)
            inventory = state["decorations"]
            if identifier in inventory and inventory[identifier] == 0:
                continue  # An existing permanent decoration stays permanent.
            inventory[identifier] = max(now, inventory.get(identifier, 0)) + days * amount * DAY if days else 0
            continue
        if category == 16:
            inventory = state.setdefault("pergolas", {})
        elif category == 18 and "种子" in award.get("name", "") and identifier in rose_ids:
            identifier, inventory = rose_ids[identifier], state["rose_seeds"]
        elif identifier in rose_aliases:
            identifier, inventory = rose_aliases[identifier], state["rose_seeds"]
        elif identifier in seeds:
            inventory = state["seeds"]
        elif identifier in server_props:
            identifier, inventory = server_props[identifier], state["props"]
        elif identifier in props:
            inventory = state["props"]
        else:
            raise InvalidOrder("奖励道具不存在")
        inventory[identifier] = inventory.get(identifier, 0) + amount


def _monthly_payload(store, now):
    cards = []
    today = _date(now)
    for identifier, reward in enumerate(MONTHLY_REWARDS, 1):
        card = store.get(str(identifier), {})
        bought = card.get("bought_at", 0)
        expiry = card.get("expires_at", 0)
        claimed = set(card.get("claimed_days", []))
        days = []
        if bought:
            # The old client displays a 31-day window even when renewals stack.
            first_day = _date(bought)
            cycles = max(0, (today - first_day).days // 31)
            start = first_day + dt.timedelta(days=31 * cycles)
            bought = int(dt.datetime.combine(start, dt.time(), LOCAL_TIMEZONE).timestamp())
            for offset in range(31):
                date = start + dt.timedelta(days=offset)
                days.append(3 if date.isoformat() in claimed else
                            4 if date < today or expiry <= now else
                            2 if date == today else 1)
        cards.append({"buytime": bought, "endtime": expiry, "paytype": 0,
                      "value": 0, "price": 0, "discount": 0, "days": days,
                      "giftList": [_award(*reward)]})
    return {"now": now, "cards": cards, "local_reward_rule": LOCAL_RULE}


def _giftcard(params, state, catalog, now, annual):
    action = _number(params, "action", 1, maximum=3)
    identifier = _number(params, "gifttype", maximum=7) if action != 1 else None
    giftcard = state["activities"].setdefault("giftcard", {})
    store = giftcard.setdefault("annual" if annual else "monthly", {})
    if not annual:
        if action == 2:
            card = store.setdefault(str(identifier), {})
            if card.get("expires_at", 0) <= now:
                card["bought_at"] = now
            card["expires_at"] = max(now, card.get("expires_at", 0)) + 31 * DAY
        elif action == 3:
            card = store.get(str(identifier), {})
            today = _date(now).isoformat()
            if card.get("expires_at", 0) <= now:
                raise InvalidOrder("请先领取免费月卡")
            if today in card.get("claimed_days", []):
                raise InvalidOrder("今日月卡奖励已领取")
            _grant(state, catalog, [_award(*MONTHLY_REWARDS[identifier - 1])], now)
            card.setdefault("claimed_days", []).append(today)
        return _monthly_payload(store, now)

    configs = {int(card.get("gifttype")): card for card in catalog("GiftCardConfig.xml").findall("card")}
    if identifier is not None and identifier not in configs:
        raise InvalidOrder("年卡不存在")
    month = _month(now)
    awards = []
    if action == 2:
        card = store.setdefault(str(identifier), {})
        if card.get("expires_month", 0) <= month:
            card["bought_month"] = month
        card["expires_month"] = max(month, card.get("expires_month", month)) + 12
    elif action == 3:
        card = store.get(str(identifier), {})
        if card.get("expires_month", 0) <= month:
            raise InvalidOrder("请先领取免费年卡")
        if month in card.get("claimed_months", []):
            raise InvalidOrder("本月年卡奖励已领取")
        reward_month = configs[identifier].find("month[@index='%d']" % (_date(now).month,))
        for item in reward_month.findall("award"):
            raw = dict(item.attrib)
            raw.update(type=int(raw["type"]), count=int(raw["count"]))
            if raw["type"] != 3:
                raw["id"] = int(raw["id"])
            awards.append(raw)
        _grant(state, catalog, awards, now)
        card.setdefault("claimed_months", []).append(month)
    response = {"now": now, "giftmonth": _date(now).month,
                "gifttype": identifier or 0, "discount": [{"discount": 0} for _ in range(7)],
                "award": awards}
    for index in configs:
        card = store.get(str(index), {})
        bought = card.get("bought_month")
        items = []
        if bought is not None:
            for offset in range(12):
                reward_month = month - (month - bought) % 12 + offset
                status = (3 if reward_month in card.get("claimed_months", []) else
                          4 if reward_month < month or reward_month >= card["expires_month"] else
                          2 if reward_month == month else 1)
                items.append({"m": reward_month % 12 + 1, "s": status})
        response["gift%d" % index] = {"gifttype": index, "bm": bought % 12 + 1 if bought is not None else 0,
                                     "item": items}
    return response


def _draw(pool, start, count):
    """Aggregate a catalog rotation without making an entry for every draw."""
    awards = []
    for index, (category, identifier, amount) in enumerate(pool):
        offset = (index - start) % len(pool)
        quantity = (count + len(pool) - 1 - offset) // len(pool)
        if quantity:
            awards.append(_award(category, identifier, amount * quantity))
    return awards


def _egg_data(identifier, store, now):
    draws = store.get("draws", {}).get(str(identifier), 0)
    return {"uniqID": identifier, "name": "本地金币蛋" if identifier == 1 else "本地幸运蛋",
            "type": identifier, "totlLuck": 10, "curLuck": draws % 10,
            "previousTimes": 1, "luck": 1, "total": 99999, "left": 99999,
            "beginT": now - DAY, "endT": now + 365 * DAY, "now": now,
            "cost1": 0 if identifier == 1 else 1,
            "cost2": 5, "cost3": 10, "dailyCntForAward": 1,
            "firstAward": _award(*EGG_BIG_REWARD), "coolEndT": 0}


def _happy_egg(params, state, catalog, now):
    request = _number(params, "request", 1, maximum=4)
    identifier = _number(params, "index", 2, maximum=2) if request in (3, 4) else None
    count = _number(params, "count", 1) if request in (2, 3) else 0
    store = state["activities"].setdefault("happy_egg", {})
    if request == 1:
        return {"now": now, "prop": store.get("hammers", 0),
                "subActivity": [_egg_data(index, store, now) for index in (1, 2)],
                "local_reward_rule": LOCAL_RULE}
    if request == 2:
        store["hammers"] = store.get("hammers", 0) + count
        return {"now": now, "prop": store["hammers"], "count": count}
    if request == 4:
        return {"now": now, "bigItem": [_award(*EGG_BIG_REWARD)],
                "item": [_award(*item) for item in EGG_REWARDS], "local_reward_rule": LOCAL_RULE}
    draws = store.setdefault("draws", {})
    previous = draws.get(str(identifier), 0)
    awards = _draw(EGG_REWARDS, previous, count)
    specials = [_award(EGG_BIG_REWARD[0], EGG_BIG_REWARD[1], (previous + count) // 10 - previous // 10)]
    specials = [award for award in specials if award["count"]]
    _grant(state, catalog, awards + specials, now)
    draws[str(identifier)] = previous + count
    if identifier == 2:
        # Free automatic purchase fills any missing hammers for this draw.
        store["hammers"] = max(0, store.get("hammers", 0) - count)
    return {**_egg_data(identifier, store, now), "prop": store.get("hammers", 0),
            "addLuck": count, "specAward": specials, "award": awards,
            "local_reward_rule": LOCAL_RULE}


def _discounts(catalog, store):
    bought = store.get("discount_bought", {})
    rows = []
    for item in catalog("petPKConfig.xml").findall("discountProp/item"):
        match = re.fullmatch(r"Prop(\d+)", item.get("icon", ""))
        if not match:
            raise InvalidOrder("折扣店道具配置无效")
        rows.append({"id": int(match.group(1)), "left": max(1, 99999 - bought.get(item.get("id"), 0)),
                     "price": 0})
    return rows


def _petpk(params, state, catalog, now):
    operation = _number(params, "type", maximum=26)
    store = state["activities"].setdefault("petpk", {})
    if operation == 3:
        return {"honour": store.get("honour", 0)}
    if operation == 12:
        identifier = _number(params, "id", maximum=2147483647)
        count = _number(params, "num", 1)
        config = catalog("petPKConfig.xml").find("shopProp/item[@id='%d']" % identifier)
        if config is None:
            raise InvalidOrder("竞技商店道具不存在")
        # The two lottery bags open immediately; their contents use local rules.
        if identifier == 60013:
            awards = [_award(0, 37000, count)]
        elif identifier == 60014:
            awards = [_award(0, 30022, count)]
        else:
            category = 6 if identifier == 1001 else 5 if identifier == 1000 else 0
            awards = [_award(category, identifier, int(config.get("num") or 1) * count)]
        _grant(state, catalog, awards, now)
        return {"addprop": awards, "honour": store.get("honour", 0),
                "local_reward_rule": LOCAL_RULE}
    if operation == 22:
        request = _number(params, "request", 1, maximum=2)
        rows = _discounts(catalog, store)
        response = {"rushbuy": rows, "now": now}
        if request == 2:
            index = _number(params, "index", maximum=len(rows))
            count = _number(params, "count", 1)
            award = _award(0, rows[index - 1]["id"], count)
            _grant(state, catalog, [award], now)
            bought = store.setdefault("discount_bought", {})
            key = str(index)
            bought[key] = bought.get(key, 0) + count
            response.update(award=award, rushbuy=_discounts(catalog, store))
        return response
    if operation == 24:
        kind = _number(params, "augury", 2, maximum=2)
        key = "free" if kind == 1 else "pay"
        augury = store.setdefault("augury", {name: [0, 0, 0] for name in ("free1", "free2", "pay1", "pay2")})
        # Array slots match the view's [expiry, bonus, attribute] consumption.
        augury[key + "1"] = [now + DAY, 5, 1]
        augury[key + "2"] = [now + DAY, 5, 2]
        awards = [_award(0, 37106 if kind == 2 else 37105, 1)]
        _grant(state, catalog, awards, now)
        store[key + "_auguries"] = store.get(key + "_auguries", 0) + 1
        return {"augury": copy.deepcopy(augury), "prize": awards, "free": 0,
                "local_reward_rule": LOCAL_RULE}
    awards = [_award(*item) for item in PET_GIFT_REWARDS]
    _grant(state, catalog, awards, now)
    store["gifts"] = store.get("gifts", 0) + 1
    return {"prize": awards, "local_reward_rule": LOCAL_RULE}


def _dingxiang_payload(store, catalog, now):
    config = catalog("DxFavorInfo.xml")
    first = config.find("favor_lv/level")
    return {"lv": 1, "energy": store.get("energy", 0),
            "effect_day": max(0, (store.get("expires_at", 0) - now + DAY - 1) // DAY),
            "cur_haogan": store.get("favor", 0), "have_gift": 0,
            "send_count_limit": int(config.find("send_rose").get("daily")),
            "recover_energy": int(first.get("recover_energy")),
            "skills": [{"id": identifier, "lv": 0, "level": 0, "exp": 0,
                        "need_flower": [], "need_rose": [], "award": []}
                       for identifier in range(1, 6)],
            "award": [], "count": 0}


def _dingxiang(params, state, catalog, now, operation):
    store = state["activities"].setdefault("dingxiang", {})
    if operation == 1012:
        months = _number(params, "pay_month", 1, maximum=999)
        store["expires_at"] = max(now, store.get("expires_at", 0)) + 30 * months * DAY
    elif operation == 1010:
        count = _number(params, "count", 1)
        paid = _number(params, "is_pay", 1, minimum=0, maximum=1)
        if not paid:
            owned = state["props"].get(120601006, 0)
            if owned < count:
                raise InvalidOrder("琼脂不足")
            state["props"][120601006] = owned - count
        config = catalog("DxFavorInfo.xml").find("qiongzhi")
        store["energy"] = store.get("energy", 0) + int(config.get("add_energy")) * count
        return {**_dingxiang_payload(store, catalog, now), "count": count}
    return _dingxiang_payload(store, catalog, now)


def _material_machine(cmd, params, state, catalog, now):
    store = state["activities"].setdefault("material_machine", {})
    if cmd == "rosary_get_props_info":
        return {"LFNInfo": {}, "totalstep": store.get("totalstep", 0),
                "currentstep": store.get("currentstep", 0), "now": now}
    if cmd == "rosary0903_begin_play":
        kind = _number(params, "kind", 1, maximum=5)
        if kind not in (1, 5):
            raise InvalidOrder("本地转盘类型无效")
        wheel = _number(params, "type", 1, maximum=5)
        store.update(wheel=wheel, currentstep=0)
    else:
        wheel = store.get("wheel", 0)
        if not wheel or store.get("currentstep", 0) >= store.get("totalstep", 0):
            raise InvalidOrder("请先开始免费转盘")
    config = catalog("rollPlateConfig.xml").find("rollInfo/plate[@type='%d']" % wheel)
    if config is None or not config.get("totalstep"):
        raise InvalidOrder("转盘配置不存在")
    props, roses, rose_aliases, rose_ids, seeds, decorations, server_props = _item_index(catalog)
    known_ids = props.keys() | rose_aliases.keys() | rose_ids.keys() | seeds.keys() | server_props.keys()
    # The mirrored wheel also references the old 4000 lucky bag, whose item
    # definition is absent. Only select entries the client can resolve to loot.
    items = [item for item in config.findall("item")
             if int(item.get("id")) in known_ids
             and not (int(item.get("id")) in rose_ids and "种子" not in item.get("name", ""))]
    if not items:
        raise InvalidOrder("转盘奖励配置为空")
    draws = store.get("draws", 0)
    item = items[draws % len(items)]
    award = _award(int(item.get("type")), int(item.get("id")), 1, name=item.get("name"))
    _grant(state, catalog, [award], now)
    store["draws"] = draws + 1
    store["totalstep"] = int(config.get("totalstep"))
    store["currentstep"] = store.get("currentstep", 0) + 1
    return {"currentaward": award["id"], "currentawardcount": 1,
            "currentawardname": award["name"], "currentawardtype": award["type"],
            "totalstep": store["totalstep"], "currentstep": store["currentstep"],
            "award": [], "svrData": {"materialAward": None, "nationalAward": [], "gatherprop": []},
            "lucky_star": 0, "morestep": 0, "fraward": 0, "now": now,
            "local_reward_rule": "local_rotation_from_rollPlateConfig"}


def handle(cmd, params, *, state, lock, catalog, persist):
    """Return activity fields, or None when another gateway handler owns it."""
    activity = str(params.get("cmd", ""))
    if cmd == "rosary_activity_oper":
        if activity not in ("43", "12", "198", "1001", "1010", "1012", "192"):
            return None
        if activity == "192" and str(params.get("request", "")) != "1":
            return None  # The separate pot-refining protocol owns potInfo.
    elif cmd == "rosary_talentpk_oper":
        if str(params.get("type", "")) not in ("3", "12", "22", "24", "26"):
            return None
    elif cmd not in ("rosary0903_begin_play", "rosary0903_play", "rosary_get_props_info"):
        return None
    with lock:
        previous = copy.deepcopy(state)
        now = int(time.time())
        try:
            if cmd == "rosary_talentpk_oper":
                response = _petpk(params, state, catalog, now)
            elif cmd != "rosary_activity_oper":
                response = _material_machine(cmd, params, state, catalog, now)
            elif activity in ("43", "12"):
                response = _giftcard(params, state, catalog, now, activity == "12")
            elif activity == "198":
                response = _happy_egg(params, state, catalog, now)
            elif activity == "192":
                count = _number(params, "count", 1)
                _grant(state, catalog, [_award(0, 161209006, count)], now)
                response = {"now": now, "count": state["props"][161209006]}
            else:
                response = _dingxiang(params, state, catalog, now, int(activity))
        except InvalidOrder as error:
            state.clear()
            state.update(previous)
            return {"result": 1, "resultstr": str(error)}
        if state != previous:
            persist(previous)
        return response
