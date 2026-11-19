#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
玫瑰小镇 本地私服 (Rose Town local private server)
--------------------------------------------------
一个 HTTP 服务，同时：
  1. 托管本地镜像的 H5 客户端静态资源（来自 site/h5/meigui/）
  2. 作为游戏后端 API 网关，响应 POST /cgi-bin/<rosary*命令>

网关协议（还原自客户端 main.index.57d00.js / ServerHttpSettings）：
  POST http://<host>/cgi-bin/<cmd>?gprand=<rand>
  Content-Type: application/x-www-form-urlencoded
  body: k1=v1&k2=v2  (含 openid/token/openkey/appid/session_type/benew0908/ossType/cgiVersion)
  响应: JSON {"result": <int>, "resultstr": "...", ...payload}
        result==0 表示成功
"""
import http.server
import base64
import copy
import json
import functools
import os
from pathlib import Path
import re
import ssl
import time
import threading
import tempfile
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
import zipfile
import premium_activities
import gameplay

_SSL_CTX = ssl.create_default_context()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "site", "h5", "meigui")
PORT = int(os.environ.get("ROSE_PORT", "8088"))
HOST = os.environ.get("ROSE_HOST", "127.0.0.1")
LOG = os.path.join(HERE, "private_server.log")

# ---------------------------------------------------------------- mock 数据
# 单用户固定身份（本地私服）
USER = {
    "openid": "AADAD8430DD37E40107C2D2D944712AF",
    "uin": "448984620",
    "nick": "本地玩家",
}

# Use the same configuration archive loaded by the client, rather than copying
# prices into the mock gateway. Purchases are retained across server restarts.
CONFIG_ARCHIVE = os.path.join(
    ROOT, "assets", "Config", "native", "f3",
    "f3c0b147-64ea-4fc3-b2ca-716cfeaf4e1f.8261e.bin")
PLAYER_LOCK = threading.RLock()
STATE_FILE = os.environ.get("ROSE_STATE_FILE", os.path.join(HERE, "local_player_state.json"))

# This gateway is a local game simulation. Premium operations grant their
# contents directly; the saved point balance is never a prerequisite or a fee.
FREE_PAYMENTS = True


def _starter_pots():
    layout = _catalog("plantPotConfig.xml").find("plantFieldLayout")
    free = [item for item in layout.findall("item")
            if int(item.get("cost") or 0) == 0
            and int(item.get("unlocklevel") or 0) == 0]
    return {number: {"SoilType": int(item.get("type") or 0), "potlevel": 0,
                     "soilstate": 51, "planted_at": 0}
            for number, item in enumerate(free, 1)}


def _load_player_state():
    if not os.path.isfile(STATE_FILE):
        saved = {"rosemoney": 1000, "balance": 0}
    else:
        with open(STATE_FILE, encoding="utf-8") as state_file:
            saved = json.load(state_file)
    state = {key: int(saved[key]) for key in ("rosemoney", "balance")}
    state["seeds"] = {int(seed): int(count)
                      for seed, count in saved.get("seeds", {}).items()}
    state["flowers"] = {int(flower): int(count)
                        for flower, count in saved.get("flowers", {}).items()}
    state["pots"] = {int(number): dict(pot)
                     for number, pot in saved.get("pots", {}).items()} or _starter_pots()
    state["experience"] = int(saved.get("experience", 0))
    state["charm"] = int(saved.get("charm", 0))
    for key in ("props", "rose_seeds", "decorations", "pergolas"):
        state[key] = {int(item): int(count)
                      for item, count in saved.get(key, {}).items()}
    state["active_decorations"] = dict(saved.get("active_decorations", {}))
    state["vip"] = dict(saved.get("vip", {}))
    state["sunshine"] = dict(saved.get("sunshine", {}))
    state["pets"] = {int(seq): dict(pet)
                     for seq, pet in saved.get("pets", {}).items()}
    state["premium_actions"] = dict(saved.get("premium_actions", {}))
    state["activities"] = dict(saved.get("activities", {}))
    if (state["rosemoney"] < 0 or state["balance"] < 0 or
            any(seed <= 0 or count < 0 for seed, count in state["seeds"].items())):
        raise ValueError("Invalid local player state in " + STATE_FILE)
    gameplay.migrate_babies(state, int(os.path.getmtime(STATE_FILE)) if os.path.isfile(STATE_FILE) else int(time.time()))
    return state


def _save_player_state():
    _atomic_write(STATE_FILE, json.dumps(PLAYER_STATE, ensure_ascii=False).encode("utf-8"))


def _atomic_write(destination, data):
    """Publish complete files only, and remove temporary files on failure."""
    destination = Path(destination)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as output:
            temporary = output.name
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def _save_or_restore(previous):
    try:
        _save_player_state()
    except OSError:
        PLAYER_STATE.clear()
        PLAYER_STATE.update(previous)
        raise


@functools.lru_cache(maxsize=None)
def _catalog(name):
    with zipfile.ZipFile(CONFIG_ARCHIVE) as archive:
        if name in archive.namelist():
            return ET.fromstring(archive.read(name))
    embedded = {
        "rollPlateConfig.xml": "2a/2a85fc1e-2869-4b9e-8796-95613039a9f3.d1e86.json",
        "DxFavorInfo.xml": "3b/3b2e79b4-0cd9-4f7c-82cc-0cb0605e2e9c.5837a.json",
        "SmeltPotConfig.xml": "6f/6fafa34d-21f2-482a-ab2c-c487b8a579fc.defc0.json",
    }
    if name not in embedded:
        raise KeyError("Missing local catalog: " + name)
    with open(os.path.join(ROOT, "assets/Config/import", embedded[name]), encoding="utf-8") as resource:
        return ET.fromstring(json.load(resource)[5][0][2])


@functools.lru_cache(maxsize=1)
def _seeds():
    return {int(item.get("seedID")): dict(item.attrib)
            for item in _catalog("flowerConfig.xml").findall("flower/item")
            if item.get("seedID")}


@functools.lru_cache(maxsize=1)
def _flowers():
    return {int(seed["id"]): seed for seed in _seeds().values()}


@functools.lru_cache(maxsize=1)
def _props():
    root = _catalog("propConfig.xml")
    return {int(item.get("id")): dict(item.attrib)
            for section in (root.find("propConfig"), root.find("meterial/others"),
                            _catalog("charmLevelsConfig.xml").find("charmflower"))
            for item in section.findall("item")}


@functools.lru_cache(maxsize=1)
def _rose_seed_config():
    return {int(item.get("id")): dict(item.attrib)
            for item in _catalog("propConfig.xml").findall("meterial/seeds/item")}


@functools.lru_cache(maxsize=1)
def _decoration_config():
    return {int(item.get("id")): {**item.attrib, "group": group.get("type")}
            for group in _catalog("propConfig.xml").find("decrateConfig")
            for item in group.findall("item")}


PLAYER_STATE = _load_player_state()


def _server_date(timestamp=None):
    return time.strftime("%Y-%m-%d-%H-%M-%S", time.gmtime(
        (time.time() if timestamp is None else timestamp) + 8 * 3600))


def _pot_payload(number, pot):
    flower = _flowers().get(pot["soilstate"])
    bonuses = gameplay.pot_bonuses(PLAYER_STATE, pot["SoilType"], int(time.time()), pot)
    stage = 0
    if flower:
        stage = 1
        elapsed = time.time() - pot["planted_at"]
        times = flower.get("multiSeason") if pot.get("season", 1) > 1 else flower["times"]
        stage += sum(elapsed >= 60 * float(minutes) * (100 - bonuses["speed"]) / 100
                     for minutes in times.split(","))
    result = {
        "soilno": number, "SoilType": pot["SoilType"],
        "soilsate": pot["soilstate"], "soilstate": pot["soilstate"],
        "potlevel": pot["potlevel"], "level": pot["potlevel"], "potexp": 0,
        "decorpot": _active_decoration("pot%d" % pot["SoilType"]),
        "local_grow_speed": bonuses["speed"],
        "rosestate": stage, "rosebegintime": (
            _server_date(pot["planted_at"]) if flower else ""),
        "isnofood": 0, "isnoshine": 0, "isclutter": 0,
        "gaincount": 0, "leftcount": int(int(flower["maxOutput"]) * (100 + bonuses["addon"]) / 100) if flower else 0,
        "hangpercent": 0, "cultureType": 0, "usespade": 0,
        "season": pot.get("season", 1) if flower else 0,
    }
    if pot["SoilType"] == 2:
        result.update(gameplay.fairy_payload(PLAYER_STATE, number, pot))
    return result


def _plantation_payload():
    with PLAYER_LOCK:
        return {"soilcount": len(PLAYER_STATE["pots"]),
                "servertime": _server_date(), "selforfriend": 0,
                **{"soil%d" % number: [_pot_payload(number, pot)]
                   for number, pot in PLAYER_STATE["pots"].items()}}


def _inventory():
    with PLAYER_LOCK:
        props = PLAYER_STATE["props"]
        result = {**{"vegetableseed%d" % seed: count
                   for seed, count in PLAYER_STATE["seeds"].items()},
                **{"vegetablefruit%d" % flower: count
                   for flower, count in PLAYER_STATE["flowers"].items()},
                **{"prop%d" % item: count for item, count in props.items()},
                **{"shelfdec%d" % item: count
                   for item, count in PLAYER_STATE["pergolas"].items()},
                **{"roseseed%d" % int(_rose_seed_config().get(item, {}).get("seedID", item)): count
                   for item, count in PLAYER_STATE["rose_seeds"].items()}}
        # Older objects use named fields instead of prop<ID>.
        for item, alias in {1: "commonferti", 2: "quickferti", 3: "moreferti",
                            7: "cureferti", 4: "rosejinghua", 328: "memorycrystal",
                            336: "godtear", 1310030032: "foolWater",
                            161240016: "accMagicAgingFerCnt"}.items():
            result[alias] = props.get(item, 0)
        for item in (10, 11, 12, 13, 14):
            result["rose%d" % item] = [props.get(item, 0), 0]
            result["meterial%d" % item] = props.get(item, 0)
        return result


def _plant_flower(params):
    try:
        number = int(params.get("soilno", ""))
        flower_id = int(params.get("rosetype", ""))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "花盆或种子编号无效"}
    flower = _flowers().get(flower_id)
    if flower is None:
        return {"result": 1, "resultstr": "种子不存在"}
    seed_id = int(flower["seedID"])
    flower_type = int(flower.get("type") or 0)
    needed_pot = 1 if flower_type == 1 else 2 if flower_type == 3 else 0
    with PLAYER_LOCK:
        pot = PLAYER_STATE["pots"].get(number)
        if pot is None:
            return {"result": 1, "resultstr": "花盆尚未解锁"}
        if pot["soilstate"] != 51:
            return {"result": 1, "resultstr": "请先清理花盆再播种"}
        if pot["SoilType"] != needed_pot:
            return {"result": 1, "resultstr": "这种鲜花不能种在此类花盆中"}
        if int(flower.get("potLevel") or 0) > pot["potlevel"]:
            return {"result": 1, "resultstr": "花盆等级不足"}
        owned = PLAYER_STATE["seeds"].get(seed_id, 0)
        if owned < 1:
            return {"result": 1, "resultstr": "种子不足"}
        previous = copy.deepcopy(PLAYER_STATE)
        PLAYER_STATE["seeds"][seed_id] = owned - 1
        pot.update(soilstate=flower_id, planted_at=int(time.time()), season=1)
        _save_or_restore(previous)
        return _base(**_pot_payload(number, pot),
                     **{"vegetableseed%d" % seed_id: owned - 1})


def _hoe_flower(params):
    try:
        number = int(params.get("soilno", ""))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "花盆编号无效"}
    with PLAYER_LOCK:
        pot = PLAYER_STATE["pots"].get(number)
        if pot is None:
            return {"result": 1, "resultstr": "花盆尚未解锁"}
        previous = copy.deepcopy(PLAYER_STATE)
        pot.update(soilstate=51, planted_at=0, season=0)
        _save_or_restore(previous)
        return _base(**_pot_payload(number, pot))


def _gain_flower(params):
    try:
        number = int(params.get("soilno", ""))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "花盆编号无效"}
    with PLAYER_LOCK:
        pot = PLAYER_STATE["pots"].get(number)
        if pot is None:
            return {"result": 1, "resultstr": "花盆尚未解锁"}
        flower = _flowers().get(pot["soilstate"])
        if flower is None or _pot_payload(number, pot)["rosestate"] != 5:
            return {"result": 1, "resultstr": "鲜花尚未成熟"}
        previous = copy.deepcopy(PLAYER_STATE)
        flower_id = int(flower["id"])
        bonuses = gameplay.pot_bonuses(PLAYER_STATE, pot["SoilType"], int(time.time()), pot)
        count = int(int(flower["maxOutput"]) * (100 + bonuses["addon"]) / 100)
        total = PLAYER_STATE["flowers"].get(flower_id, 0) + count
        PLAYER_STATE["flowers"][flower_id] = total
        experience = int(int(flower.get("exp") or 0) * (100 + bonuses["exp"]) / 100)
        charm = int(int(flower.get("charm") or 0) * (100 + bonuses["charm"]) / 100)
        PLAYER_STATE["experience"] += experience
        PLAYER_STATE["charm"] += charm
        if pot.get("season", 1) < int(flower.get("season") or 1):
            pot.update(planted_at=int(time.time()), season=pot.get("season", 1) + 1)
        else:
            pot.update(soilstate=50, planted_at=0, season=0)
        _save_or_restore(previous)
        return _base(**_pot_payload(number, pot), igainrosetype=flower_id,
                     igainrosecount=count, addexperice=experience, addcharm=charm,
                     **{"vegetablefruit%d" % flower_id: total})


def _level(total, filename, tag, key, minimum=0):
    return max([minimum] + [int(item.get(key))
                           for item in _catalog(filename).find(tag).findall("item")
                           if total >= int(item.get("value"))])


def _buy_seed(cmd, params):
    try:
        count = int(params.get("count", ""))
        seed_id = int(params.get(
            "seedtype" if cmd == "rosary_qb_buy_seed" else "type", ""))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "种子编号或购买数量无效"}
    if not 1 <= count <= 99:
        return {"result": 1, "resultstr": "购买数量必须在1到99之间"}
    seed = _seeds().get(seed_id)
    if seed is None:
        return {"result": 1, "resultstr": "种子不存在"}
    points = cmd == "rosary_qb_buy_seed"
    price = int(seed.get("seedPriceQPoint" if points else "seedPrice") or 0)
    if price <= 0:
        return {"result": 1, "resultstr": "该种子不支持此购买方式"}
    if (not points and int(seed.get("limittime") or 0)
            and int(seed["limittime"]) <= time.time()):
        return {"result": 1, "resultstr": "该种子已结束出售"}
    currency = "balance" if points else "rosemoney"
    cost = 0 if points and FREE_PAYMENTS else price * count
    with PLAYER_LOCK:
        if PLAYER_STATE[currency] < cost:
            return {"result": 1, "resultstr": "点券不足" if points else "金币不足"}
        before = PLAYER_STATE[currency]
        previous_count = PLAYER_STATE["seeds"].get(seed_id)
        PLAYER_STATE[currency] -= cost
        owned = PLAYER_STATE["seeds"].get(seed_id, 0) + count
        PLAYER_STATE["seeds"][seed_id] = owned
        try:
            _save_player_state()
        except OSError:
            PLAYER_STATE[currency] = before
            if previous_count is None:
                del PLAYER_STATE["seeds"][seed_id]
            else:
                PLAYER_STATE["seeds"][seed_id] = previous_count
            raise
        return _base(type=seed_id, count=count, discount=0,
                     rosemoneyuse=0 if points else cost,
                     rosemoneyleft=PLAYER_STATE["rosemoney"],
                     balance=PLAYER_STATE["balance"],
                     **{"vegetableseed%d" % seed_id: owned})


def _jpeg_ok(resp):
    resp["result"] = 0
    return resp


# 装饰/特殊道具默认值 —— 键名 "prop<startID>"，取自 main.index 的 DecorateCommon 常量，
# 缺省时客户端 parseSpecilProp 会拿到 undefined 并在 updateMaginTreeIdAndTips 崩溃。
DECOR_PROPS = {
    "prop161192000": 161192001,   # MagicTree_startID -> default
    "prop161202000": 161202001,   # SceneDecoration
    "prop161121001": 161121002,   # BaobaoDecoration
    "prop161181001": 161181002,   # BaobaoBGDecoration
    "prop161273000": 161273001,   # EffectDecoration
    "prop161134001": 161134002,   # WaterFlowerRack
    "prop161233000": 161233001,   # Dingding
    "prop161092000": 161092001,   # Dingxiang
    "prop161141001": 161141002,   # FloorDecoration
    "prop161190003": 0,           # Wing
}


def _base(**extra):
    d = {"result": 0, "resultstr": "ok", "svrtime": int(time.time()),
         "local_free_pay": FREE_PAYMENTS, "balance": PLAYER_STATE["balance"]}
    d.update(DECOR_PROPS)
    d.update(extra)
    return d


def _positive(params, key, default=None, maximum=99999):
    # JSON quantities must be integers too: int(1.5) silently grants one item.
    value = int(str(params.get(key, default)))
    if not 1 <= value <= maximum:
        raise ValueError("%s必须在1到%d之间" % (key, maximum))
    return value


def _paid_result(**extra):
    return _base(**{"cost": 0, "paycount": 0, "pay_count": 0, "discount": 0,
                   "rosemoneyleft": PLAYER_STATE["rosemoney"], **extra})


def _buy_props(cmd, params):
    direct = cmd == "rosary_buy_game_props"
    try:
        item = _positive(params, "buyid" if direct else "buytype", maximum=2147483647)
        count = _positive(params, "count" if direct else "buycount")
        paytype = int(params.get("paytype", 1))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "道具编号或购买数量无效"}
    # The client opens this chest immediately and expects the contained item in
    # id/num. Its local reward is one configured ordinary spirit jade per chest.
    if direct and item == 60006:
        with PLAYER_LOCK:
            previous = copy.deepcopy(PLAYER_STATE)
            PLAYER_STATE["props"][31020] = PLAYER_STATE["props"].get(31020, 0) + count
            _save_or_restore(previous)
            return _paid_result(id=31020, num=count, type=0, count=count,
                                buytype=item, buycount=count, **_inventory())
    config = _props().get(item) or _rose_seed_config().get(item)
    if config is None:
        return {"result": 1, "resultstr": "道具不存在"}
    with PLAYER_LOCK:
        previous = copy.deepcopy(PLAYER_STATE)
        gold_cost = int(config.get("price") or 0) * count if paytype == 6 else 0
        if PLAYER_STATE["rosemoney"] < gold_cost:
            return {"result": 1, "resultstr": "金币不足"}
        PLAYER_STATE["rosemoney"] -= gold_cost
        inventory = "rose_seeds" if item in _rose_seed_config() else "props"
        grants = {item: count}
        if inventory == "props":
            grants = ({10: 2 * count, 2: count, 3: count, 13: count} if item == 9
                      else {7: 11 * count} if item == 8
                      else {4: 12 * count} if item == 111
                      else {item: count * (18000 if item == 31004 else 5 if item == 33000 else 1)})
        for identifier, amount in grants.items():
            owned = PLAYER_STATE[inventory].get(identifier, 0)
            PLAYER_STATE[inventory][identifier] = owned + amount
        owned = PLAYER_STATE[inventory].get(4 if item == 111 else item, 0)
        _save_or_restore(previous)
        return _paid_result(id=item, num=count, count=count, buytype=item,
                            buycount=count, nowcount=owned, afterbuytotalcount=owned,
                            rosemoneyuse=gold_cost, **_inventory())


def _decoration_days(identifier):
    expiration = PLAYER_STATE["decorations"][identifier]
    return max(0, (expiration - int(time.time()) + 86399) // 86400) if expiration else 0


def _decoration_available(identifier):
    expiry = PLAYER_STATE["decorations"].get(identifier)
    return expiry is not None and (expiry == 0 or expiry > time.time())


def _active_decoration(slot):
    identifier = PLAYER_STATE["active_decorations"].get(slot, 0)
    return identifier if _decoration_available(identifier) else 0


def _decoration_inventory():
    with PLAYER_LOCK:
        result, timed_pots = {}, {}
        for identifier in PLAYER_STATE["decorations"]:
            config = _decoration_config()[identifier]
            slot = ("pot%d" % {2: 1, 4: 1, 5: 2}.get(int(config.get("flowerPotType") or 0), 0)
                    if config["group"] == "4" else "group" + config["group"])
            used = int(_active_decoration(slot) == identifier)
            days = _decoration_days(identifier)
            expired = int(bool(PLAYER_STATE["decorations"][identifier]) and days == 0)
            result["decorate%d" % identifier] = [{"decoratetype": identifier,
                "effecttime": days, "isuse": used, "isoverdue": expired}]
            if config["group"] == "4":
                result["pot%d" % identifier] = [int(not expired), used]
                if int(config.get("period") or 0):
                    timed_pots["pot%d" % identifier] = [{"type": identifier, "eday": days}]
                if used:
                    # The client treats every fpot key containing "pot" as a
                    # per-item array. Equipped-slot values must use other keys.
                    timed_pots[{"pot0": "soil", "pot1": "water", "pot2": "fairy"}[slot]] = identifier
        result["fpot"] = [timed_pots] if timed_pots else []
        return result


def _buy_decoration(params):
    try:
        identifier = _positive(params, "buytype", maximum=2147483647)
        paytype = int(params.get("paytype", 1))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "装饰编号无效"}
    config = _decoration_config().get(identifier)
    if config is None:
        return {"result": 1, "resultstr": "装饰不存在"}
    with PLAYER_LOCK:
        previous = copy.deepcopy(PLAYER_STATE)
        days = int(config.get("period") or 0)
        old = PLAYER_STATE["decorations"].get(identifier)
        PLAYER_STATE["decorations"][identifier] = (
            max(int(time.time()), old or 0) + days * 86400 if days and old != 0 else 0)
        _save_or_restore(previous)
        return _paid_result(buytype=identifier, effecttime=_decoration_days(identifier),
                            isuse=0, paytype=paytype,
                            **_decoration_inventory())


def _use_decoration(params):
    try:
        identifier = _positive(params, "usetype", maximum=2147483647)
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "装饰编号无效"}
    config = _decoration_config().get(identifier)
    with PLAYER_LOCK:
        if config is None or identifier not in PLAYER_STATE["decorations"]:
            return {"result": 1, "resultstr": "请先购买装饰"}
        if not _decoration_available(identifier):
            return {"result": 1, "resultstr": "装饰已到期，请先续期"}
        previous = copy.deepcopy(PLAYER_STATE)
        slot = ("pot%d" % {2: 1, 4: 1, 5: 2}.get(int(config.get("flowerPotType") or 0), 0)
                if config["group"] == "4" else "group" + config["group"])
        PLAYER_STATE["active_decorations"][slot] = identifier
        _save_or_restore(previous)
        return _base(usetype=identifier, isuse=1, **_decoration_inventory())


def _vip_payload():
    vip = PLAYER_STATE["vip"]
    thresholds = [280, 1880, 3880, 8880, 66880, 168880, 328880, 888880, 2888880]
    experience = vip.get("exp", 0)
    level = max([0] + [number for number, value in enumerate(thresholds, 1)
                       if experience >= value])
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))
    return {"exp": experience, "gift": int(vip.get("daily_gift") == day), "isFirst": int(not experience),
            "level": level, "levelNow": thresholds[level - 1] if level else 0,
            "levelNext": thresholds[min(level, 8)], "timeEnd": vip.get("timeEnd", 0),
            "vipGift": vip.get("vipGift", 0)}


# Growth gifts from the shipped GameVIPManager, in client award units.
VIP_GROWTH_GIFTS = [
    [(10, 120705046, 1), (10, 120705047, 1), (0, 22022, 2)],
    [(10, 120705144, 1), (0, 30012, 1), (0, 22022, 5)],
    [(0, 31004, 18000), (0, 131006019, 1), (0, 22022, 10)],
    [(0, 161157010, 1), (10, 120705050, 1), (16, 141039008, 1)],
    [(10, 120705068, 1), (10, 120705060, 1), (0, 120705066, 1)],
    [(10, 120705067, 1), (10, 120705063, 1), (16, 141039007, 1)],
    [(0, 161190011, 1), (10, 120705062, 1), (0, 30056, 1)],
    [(10, 132002018, 1), (10, 132002518, 1), (0, 30036, 1)],
    [(10, 120705102, 1), (0, 161141019, 1), (0, 30057, 1)],
]


def _grant_awards(awards):
    """Apply client award records while the caller holds PLAYER_LOCK."""
    rose_seeds = _rose_seed_config()
    for award in awards:
        identifier, amount = int(award["id"]), int(award["count"])
        category = int(award.get("type", 0))
        if category == 6:
            PLAYER_STATE["rosemoney"] += amount
            continue
        if category == 4:
            PLAYER_STATE["experience"] += amount
            continue
        if category == 5:
            PLAYER_STATE["charm"] += amount
            continue
        if category == 10 and identifier in _decoration_config():
            if PLAYER_STATE["decorations"].get(identifier) == 0:
                continue
            period = int(_decoration_config()[identifier].get("period") or 0)
            old = PLAYER_STATE["decorations"].get(identifier, 0)
            PLAYER_STATE["decorations"][identifier] = max(int(time.time()), old) + period * amount * 86400 if period else 0
            continue
        if category == 16:
            inventory = PLAYER_STATE["pergolas"]
        elif identifier in _seeds():
            inventory = PLAYER_STATE["seeds"]
        else:
            local_seed = next((local_id for local_id, item in rose_seeds.items()
                               if identifier in (int(item.get("seedID") or 0),
                                                 int(item.get("svrID") or 0))), None)
            if local_seed is not None:
                identifier, inventory = local_seed, PLAYER_STATE["rose_seeds"]
            else:
                inventory = PLAYER_STATE["props"]
        inventory[identifier] = inventory.get(identifier, 0) + amount


def _game_vip(params):
    try:
        request = int(params.get("request", 1))
        months = _positive(params, "index", 1, 999) if request == 2 else 0
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "VIP购买月份无效"}
    with PLAYER_LOCK:
        awards = []
        if request == 2:
            previous = copy.deepcopy(PLAYER_STATE)
            vip = PLAYER_STATE["vip"]
            vip["timeEnd"] = max(int(time.time()), vip.get("timeEnd", 0)) + months * 30 * 86400
            vip["exp"] = vip.get("exp", 0) + 280 * months
            _save_or_restore(previous)
        elif request == 3:
            try:
                level = _positive(params, "index", maximum=9)
            except (ValueError, TypeError):
                return {"result": 1, "resultstr": "VIP礼包等级无效"}
            vip = PLAYER_STATE["vip"]
            if level > _vip_payload()["level"]:
                return {"result": 1, "resultstr": "VIP等级尚未达到礼包要求"}
            flag = 1 << (level - 1)
            if not vip.get("vipGift", 0) & flag:
                previous = copy.deepcopy(PLAYER_STATE)
                awards = [{"type": category, "id": item, "count": count}
                          for category, item, count in VIP_GROWTH_GIFTS[level - 1]]
                _grant_awards(awards)
                vip["vipGift"] = vip.get("vipGift", 0) | flag
                _save_or_restore(previous)
        return _paid_result(roseLifeVIP=_vip_payload(), award=awards,
                            pourcounttodayleft=10, freerosecounttodayleft=10)


def _vip_daily_gift():
    with PLAYER_LOCK:
        vip = PLAYER_STATE["vip"]
        day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 8 * 3600))
        gift = {}
        if vip.get("daily_gift") != day:
            previous = copy.deepcopy(PLAYER_STATE)
            level = _vip_payload()["level"] if vip.get("timeEnd", 0) > time.time() else 0
            quantities = [(1, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (2, 0, 1),
                          (2, 1, 1), (2, 2, 2), (3, 3, 2), (3, 3, 3), (3, 3, 3)][level]
            for identifier, quantity in zip((506, 507, 508), quantities):
                if quantity:
                    PLAYER_STATE["props"][identifier] = PLAYER_STATE["props"].get(identifier, 0) + quantity
                    gift["addprop%d" % identifier] = quantity
            vip["daily_gift"] = day
            _save_or_restore(previous)
        return _base(gift=[gift])


def _sunshine(params):
    try:
        request = int(params.get("request", 1))
        index = _positive(params, "index", 1, 3) if request == 2 else 0
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "阳光卡类型无效"}
    with PLAYER_LOCK:
        sun = PLAYER_STATE["sunshine"]
        if request == 2:
            previous = copy.deepcopy(PLAYER_STATE)
            sun["time"] = max(int(time.time()), sun.get("time", 0)) + (30, 90, 360)[index - 1] * 86400
            if index > 1 and not sun.get("bought%d" % index):
                sun["value"] = sun.get("value", 0) + (300 if index == 2 else 600)
            sun["bought%d" % index] = True
            PLAYER_STATE["props"][131031002] = sun.get("value", 0)
            for identifier in (1019, 2019, 3019):
                PLAYER_STATE["decorations"][identifier] = sun["time"]
            _save_or_restore(previous)
        return _paid_result(lv=1, time=sun.get("time", 0), value=sun.get("value", 0),
                            lvneed=0, nextneed=300, isgot=0, hastips=0, prize=[],
                            **{"decorate%d" % identifier: [{"decoratetype": identifier,
                                "effecttime": sun.get("time", 0)}]
                               for identifier in (1019, 2019, 3019)})


def _buy_charm_flower(params):
    try:
        identifier = _positive(params, "id", maximum=2147483647)
        count = _positive(params, "count", 1)
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "花束编号或数量无效"}
    if identifier not in _props():
        return {"result": 1, "resultstr": "花束不存在"}
    return _buy_props("rosary_buy_game_props", {"buyid": identifier, "count": count, "paytype": 1})


def _send_charm_flower(params):
    try:
        identifier = _positive(params, "buytype", maximum=2147483647)
        count = _positive(params, "buycount", 1)
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "花束编号或数量无效"}
    config = _props().get(identifier)
    if config is None:
        return {"result": 1, "resultstr": "花束不存在"}
    # The four newer bouquets have no local charm table. Keep their unknown
    # bonus at zero instead of deriving a number from the displayed price.
    added = int(config.get("givercharm") or 0) * count
    friend_added = int(config.get("charm") or 0) * count
    with PLAYER_LOCK:
        previous = copy.deepcopy(PLAYER_STATE)
        PLAYER_STATE["charm"] += added
        _save_or_restore(previous)
        return _paid_result(buytype=identifier, buycount=count, addcharm=added,
                            friendaddcharm=friend_added,
                            frienduinnic=base64.b64encode("本地好友".encode()).decode())


def _expand_pot(params):
    try:
        number = _positive(params, "soilno", maximum=99)
        action = int(params.get("action", 0))
        pot_type = 2 if action == 6 else int(params.get("SoilType", 0))
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "花盆编号无效"}
    with PLAYER_LOCK:
        pots = PLAYER_STATE["pots"]
        if action not in (0, 1, 6):
            return _premium_fallback("rosary0904_expand", params)
        if action == 6 and str(params.get("actionop")) not in ("1", "2"):
            return _premium_fallback("rosary0904_expand", params)
        previous = copy.deepcopy(PLAYER_STATE)
        if action == 1:
            if number not in pots:
                return {"result": 1, "resultstr": "花盆尚未解锁"}
            if pots[number]["SoilType"] == 2:
                return {"result": 1, "resultstr": "仙藤花盆请使用炼盆提升等级"}
            pots[number]["potlevel"] = min(6, pots[number]["potlevel"] + 1)
        elif number == len(pots) + 1 and pot_type in (0, 1, 2):
            pots[number] = {"SoilType": pot_type, "potlevel": 0,
                            "soilstate": 51, "planted_at": 0}
        elif number not in pots:
            return {"result": 1, "resultstr": "请按顺序解锁花盆"}
        freestone = []
        if action == 6 and params.get("actionop") in (2, "2") and not pots[number].get("starter_gift"):
            pots[number]["starter_gift"] = True
            PLAYER_STATE["props"][31005] = PLAYER_STATE["props"].get(31005, 0) + 100
            freestone = [{"id": 31005, "count": 100, "type": 0}]
        _save_or_restore(previous)
        return _paid_result(**_pot_payload(number, pots[number]), freestone=freestone)


def _renew_pet(params):
    try:
        seq = _positive(params, "petseq", maximum=2147483647)
        pet_type = gameplay.number(params, "pt", minimum=0, maximum=6)
        months = _positive(params, "month", 1, 999)
        renewal = gameplay.number(params, "auto_renewal", 0, minimum=0, maximum=1)
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "宠物或续费月份无效"}
    with PLAYER_LOCK:
        existing = PLAYER_STATE["pets"].get(seq)
        if (existing is not None and existing["tp"] != pet_type) or (pet_type == 0 and existing is None):
            return {"result": 1, "resultstr": "宝宝序号与类型不匹配"}
        previous = copy.deepcopy(PLAYER_STATE)
        pet = PLAYER_STATE["pets"].setdefault(seq, gameplay.new_pet(seq, pet_type, int(time.time())))
        end = max(int(time.time()), pet.get("expires_at", 0)) + months * 30 * 86400
        pet.update(expires_at=end, efday=(end - int(time.time()) + 86399) // 86400,
                   renewal=renewal)
        _save_or_restore(previous)
        return _paid_result(**pet, effectday=pet["efday"], expired=_server_date(end),
                            req_feed=months, real_feed=months, award_type=0)


def _premium_fallback(cmd, params):
    """Unsupported gameplay must never acknowledge or persist a fake purchase."""
    return {"result": 2, "resultstr": "该玩法尚未实现本地协议，本次操作未执行",
            "local_unsupported": True}


def local_payment(params):
    if params.get("action") != "recharge":
        return {"result": 1, "resultstr": "未知的本地支付操作"}
    try:
        count = _positive(params, "count", 100, 1000000)
    except (ValueError, TypeError):
        return {"result": 1, "resultstr": "充值数量无效"}
    with PLAYER_LOCK:
        previous = copy.deepcopy(PLAYER_STATE)
        PLAYER_STATE["balance"] += count
        _save_or_restore(previous)
        return _paid_result(count=count)


def handle_cmd(cmd, params):
    # Keep initialization snapshots consistent with concurrent purchases.
    with PLAYER_LOCK:
        return _handle_cmd(cmd, params)


def _handle_cmd(cmd, params):
    """Return implemented protocol responses; reject unsupported operations."""
    # ---- 登录 / 进入花园初始化 ----
    if cmd == "rosary0908_get_user_info":
        return _base(
            uin=USER["uin"],
            nick=USER["nick"],
            usernic=base64.b64encode(USER["nick"].encode("utf-8")).decode(),
            userGender=1,
            gameviplevel=0,
            hasphoto=0,
            is_gamevip=0,
            supervip=0,
            annualvip=0,
            exclusivecard=0,
            balance=PLAYER_STATE["balance"],
            iplocationswitch=0,
            iplocation="",
            bluevipgift2024_flg=0,
            hallaward2020_npc=0,
        )
    if cmd == "rosary0909_get_init_first_self":
        giftcard = PLAYER_STATE["activities"].get("giftcard", {})
        charm_end = int(giftcard.get("charm_addon_end", 0))
        return _base(
            charmlevel=_level(PLAYER_STATE["charm"], "charmLevelsConfig.xml", "charm", "level"),
            charmtotal=PLAYER_STATE["charm"], charmneed=100,
            charmaddon=giftcard.get("charm_addon", 0) if charm_end > time.time() else 0,
            charmaddonendtime=charm_end, charmtoday=0,
            experice=PLAYER_STATE["experience"],
            expericelevel=_level(PLAYER_STATE["experience"], "ruleConfig.xml", "expLevel", "id", 1),
            expericetoday=0,
            expaddon=0, expaddonendtime=0,
            logindays=1, logingift=[],
            paylevel=0, paylevelname="",
            rosemoney=PLAYER_STATE["rosemoney"], popularitytotal=0, rosetoptotal=0,
            rostfreetotal=0, firstmakerose=0, tincount=0,
            sunshine={"value": PLAYER_STATE["sunshine"].get("value", 0), "lv": 1,
                      "time": PLAYER_STATE["sunshine"].get("time", 0),
                      "lvneed": 0, "nextneed": 300, "isgot": 0},
            story=0, flag121127030=0, giftcard=0, monthcard=0,
            bluevipgift2024_flg=0, hallaward2020_npc=0,
            illustrations_gift="",
            specialProp=[], position=[], hpdecorate=[],
            sendable={"pot": []},
            roseLifeVIP=_vip_payload(),
            **_inventory(),
            **_decoration_inventory(),
        )
    if cmd == "rosary0907_get_init_second":
        return _base(
            special_pots=[],
            usePersonalTheme=_active_decoration("group9") or 0,
            etime=int(time.time()),
            PAInfo0={"tips": "本地鲜花行情：按基础收购价", "fp": {
                "vegetablefruit%s" % seed["id"]: int(seed.get("flowerPrice") or 0)
                for seed in _seeds().values()}},
            **_inventory(),
            **_decoration_inventory(),
            **gameplay.dragon_payload(PLAYER_STATE),
        )
    if cmd in ("rosary0908_get_plant_info_self",):
        return _base(**_plantation_payload())
    if cmd == "rosary0904_soil_plant_rose":
        return _plant_flower(params)
    if cmd == "rosary0904_hoe":
        return _hoe_flower(params)
    if cmd == "rosary0904_gain":
        return _gain_flower(params)
    if cmd == "rosary_diamond":
        return _base(balance=PLAYER_STATE["balance"])
    if cmd in ("rosary0908_rosemoney_buy_seed", "rosary_qb_buy_seed"):
        return _buy_seed(cmd, params)
    gameplay_result = gameplay.handle(cmd, params, state=PLAYER_STATE,
        lock=PLAYER_LOCK, catalog=_catalog, persist=_save_or_restore)
    if gameplay_result is not None:
        return _paid_result(**gameplay_result)
    activity_result = premium_activities.handle(cmd, params, state=PLAYER_STATE,
        lock=PLAYER_LOCK, catalog=_catalog, persist=_save_or_restore)
    if activity_result is not None:
        return _paid_result(**activity_result)
    if cmd in ("rosary_buy_game_props", "rosary0906_buy_fertilizer", "rosary0903_sale"):
        # rosary0903_sale also handles direct purchases sent to friends.
        if params.get("frienduin") not in (None, "", 0, "0"):
            return _send_charm_flower(params)
        return _buy_props(cmd, params)
    if cmd == "rosary0906_buy_decorate":
        return _buy_decoration(params)
    if cmd == "rosary0906_use_decorate":
        return _use_decoration(params)
    if cmd == "rosary0904_expand":
        return _expand_pot(params)
    if cmd == "rosary_pets_feed":
        return _renew_pet(params)
    if cmd == "rosary0912_gamevip_gifts":
        return _vip_daily_gift()
    if cmd == "rosary0903_get_takeon_pets":
        return _base(**gameplay.pets_payload(PLAYER_STATE))
    if cmd == "rosary_activity_oper":
        activity = str(params.get("cmd", ""))
        request = str(params.get("request", ""))
        if activity == "211":
            return _game_vip(params)
        if activity == "55":
            return _sunshine(params)
        if activity == "236" and request == "2":
            return _buy_charm_flower(params)
        if activity == "38" and request == "5":
            response = _buy_props("rosary_buy_game_props", {
                "buyid": 1310030032, "count": params.get("count", 1), "paytype": 1})
            if not response["result"]:
                response["trickyWater"] = PLAYER_STATE["props"][1310030032]
            return response
    if cmd == "rosary_get_action_flowerinfo" and params.get("history") == "1":
        try:
            flower_id = int(params.get("fid", ""))
        except (ValueError, TypeError):
            return {"result": 1, "resultstr": "鲜花编号无效"}
        seed = next((seed for seed in _seeds().values()
                     if int(seed["id"]) == flower_id), None)
        if seed is None:
            return {"result": 1, "resultstr": "鲜花不存在"}
        price = int(seed.get("flowerPrice") or 0)
        return _base(fid=flower_id, pmin=price, pmax=price)
    if (str(params.get("__local_paid", "")) == "1" or
            str(params.get("paytype", "")) == "1" or
            str(params.get("payway", "")) == "1"):
        return _premium_fallback(cmd, params)
    # Passive telemetry has no game-state side effects.
    if cmd == "rosary_buried_point":
        return _base()
    return _premium_fallback(cmd, params)


class Handler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    MAX_BODY = 1024 * 1024
    TEXT_EXTENSIONS = (".js", ".html", ".htm", ".css", ".json", ".txt", ".xml")
    CDN_EXTENSIONS = TEXT_EXTENSIONS + (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp3", ".ogg", ".wav", ".m4a",
        ".bin", ".bytes", ".py", ".plist", ".fnt", ".ttf", ".woff")

    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _allow_gateway(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        allowed = origin is None or origin in ("http://" + host, "https://" + host)
        if not allowed or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.close_connection = True
            self._send_json({"result": 1, "resultstr": "仅允许同源页面访问本地存档"}, 403)
            return False
        return True

    def _read_body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if (self.headers.get("Transfer-Encoding") is not None or len(lengths) > 1
                or (lengths and not re.fullmatch(r"[0-9]+", lengths[0]))):
            raise ValueError("无效的请求长度或传输编码")
        length = int(lengths[0]) if lengths else 0
        if length > self.MAX_BODY:
            self.close_connection = True
            self._send_json({"result": 1, "resultstr": "请求体不能超过1 MiB"}, 413)
            return None
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("请求体不完整")
        return raw

    # ---- POST: 网关 ----
    def do_POST(self):
        if not self._allow_gateway():
            return
        try:
            raw = self._read_body()
            if raw is None:
                return
            text = raw.decode("utf-8")
            if self.headers.get_content_type() == "application/json":
                params = json.loads(text)
                if not isinstance(params, dict):
                    raise ValueError("请求参数必须为对象")
            else:
                params = dict(urllib.parse.parse_qsl(text, keep_blank_values=True,
                                                    max_num_fields=1000))
        except (ValueError, TimeoutError) as error:
            self.close_connection = True
            self._send_json({"result": 1, "resultstr": str(error)}, 400)
            return
        path = self.path.split("?", 1)[0]
        if path == "/local_payments":
            try:
                response = local_payment(params)
            except (ValueError, TypeError, OSError) as error:
                response = {"result": 1, "resultstr": str(error)}
            self._send_json(response)
            return
        m = re.fullmatch(r"/cgi-bin/([A-Za-z0-9_]+)", path)
        if not m:
            self._send_json({"result": 1, "resultstr": "接口不存在"}, 404)
            return
        cmd = m.group(1)
        # 灰度后缀 _go -> 归一化
        base_cmd = cmd[:-3] if cmd.endswith("_go") else cmd
        self._log("POST", cmd, params)
        try:
            body = handle_cmd(base_cmd, params)
        except Exception as e:
            body = {"result": 1, "resultstr": "mock-error: %s" % e}
        self._send_json(body)

    def do_OPTIONS(self):
        if not self._allow_gateway():
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_GET(self):
        self._serve_get()

    def do_HEAD(self):
        self._serve_get(head_only=True)

    def _serve_get(self, head_only=False):
        # 静态资源 + 伪装的 CGI GET（部分命令走 GET）
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json({"result": 0, "service": "rose-town-local", "status": "ok"})
            return
        if path.startswith("/announcement") and path.endswith("announcement.js"):
            self._send_text("window.__rose_announcement = {};", "application/javascript")
            return
        if path.startswith("/cgi-bin/"):
            if head_only:
                self.send_error(405, "HEAD cannot invoke game commands")
                return
            if not self._allow_gateway():
                return
            m = re.fullmatch(r"/cgi-bin/([A-Za-z0-9_]+)", path)
            if not m:
                self._send_json({"result": 1, "resultstr": "接口不存在"}, 404)
                return
            cmd = m.group(1)
            base_cmd = cmd[:-3] if cmd.endswith("_go") else cmd
            try:
                params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query,
                                                     keep_blank_values=True, max_num_fields=1000))
                self._log("GET cgi", cmd, params)
                self._send_json(handle_cmd(base_cmd, params))
            except Exception as error:
                self._send_json({"result": 1, "resultstr": "mock-error: %s" % error})
            return
        if path in ("/", "/index.html"):
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query,
                                                 keep_blank_values=True))
            login = {"open": "portal", "PingPong": USER["uin"], "openid": USER["openid"],
                     "token": "localtoken", "openkey": "localtoken", "appid": "102072120",
                     "session_type": "openkey"}
            if any(not params.get(key) for key in login):
                params.update({key: value for key, value in login.items() if not params.get(key)})
                self.send_response(302)
                self.send_header("Location", "/index.html?" + urllib.parse.urlencode(params))
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            path = "/index.html"
        try:
            fs_path = self._static_path(path)
        except (ValueError, OSError, RuntimeError):
            self.send_error(400, "Invalid resource path")
            return
        if fs_path.is_dir():
            # Preserve nested activity entry points without exposing listings.
            for index in ("index.html", "index.htm"):
                candidate = path.rstrip("/") + "/" + index
                try:
                    index_path = self._static_path(candidate)
                except (ValueError, OSError, RuntimeError):
                    self.send_error(400, "Invalid resource path")
                    return
                if index_path.is_file():
                    if not path.endswith("/"):
                        query = urllib.parse.urlsplit(self.path).query
                        self.send_response(301)
                        self.send_header("Location", path + "/" + ("?" + query if query else ""))
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    path, fs_path = candidate, index_path
                    break
            else:
                self.send_error(404, "Resource not found")
                return
        resource_path = urllib.parse.unquote(path)
        if fs_path.is_file() and resource_path.lower().endswith(self.TEXT_EXTENSIONS):
            try:
                data = fs_path.read_bytes()
            except OSError:
                self.send_error(404, "Resource not found")
                return
            self._send_resource(resource_path, data, self.guess_type(str(fs_path)))
            return
        if not fs_path.is_file() and resource_path.lower().endswith(self.CDN_EXTENSIONS):
            if self._proxy_cdn(path, fs_path):
                return
        if head_only:
            super().do_HEAD()
        else:
            super().do_GET()

    def _static_path(self, path):
        decoded = urllib.parse.unquote(path, errors="strict")
        if (not decoded.startswith("/") or "\\" in decoded
                or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
                or ".." in decoded.split("/")):
            raise ValueError("Invalid resource path")
        root = Path(ROOT).resolve()
        destination = (root / decoded.lstrip("/")).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("Resource is outside the mirror")
        return destination

    def _send_resource(self, path, data, ctype):
        # 文本资源：服务时把硬编码的腾讯域名改写到本地（对镜像里被后台爬虫
        # 重写回去的 index.js 也始终生效，保证私服路由稳定）
        is_text = path.lower().endswith(self.TEXT_EXTENSIONS)
        if is_text:
            local_cdn = ("http://%s/" % self.headers.get("Host", "localhost:%d" % PORT)).encode()
            local_cgi = local_cdn + b"cgi-bin/"
            for remote in (b"https://cgi.meigui.qq.com/cgi-bin/",
                           b"http://cgi.meigui.qq.com/cgi-bin/", b"//cgi.meigui.qq.com/cgi-bin/"):
                data = data.replace(remote, local_cgi)
            for remote in (b"https://baobaocdn.qq.com/cdn/h5/meigui",
                           b"http://baobaocdn.qq.com/cdn/h5/meigui", b"//baobaocdn.qq.com/cdn/h5/meigui"):
                data = data.replace(remote, local_cdn.rstrip(b"/"))
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if is_text:
            self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _proxy_cdn(self, path, destination):
        base = "https://baobaocdn.qq.com/cdn/h5/meigui"
        urls = [base + path]
        if path.startswith("/assets/"):
            urls.append(base + "/act/main" + path)
        data = None
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as r:
                    data = r.read()
                    ctype = r.headers.get("Content-Type", "application/octet-stream")
                break
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    continue
                self._log("PROXY-FAIL", path, str(error).encode())
                return False
            except Exception as error:
                self._log("PROXY-FAIL", path, str(error).encode())
                return False
        if data is None:
            self._log("PROXY-FAIL", path, b"404 on configured CDN paths")
            return False
        # Atomic replacement prevents concurrent readers from seeing partial files.
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(destination, data)
        except OSError:
            pass
        self._send_resource(urllib.parse.unquote(path), data, ctype)
        return True

    # ---- helpers ----
    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_text(self, text, ctype):
        data = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin in ("http://" + self.headers.get("Host", ""),
                      "https://" + self.headers.get("Host", "")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")

    def _log(self, kind, cmd, raw):
        try:
            if isinstance(raw, dict):
                private = {"openid", "token", "openkey", "access_token", "authorization", "cookie", "pingpong"}
                message = urllib.parse.urlencode({key: "[redacted]" if key.lower() in private else value
                                                  for key, value in raw.items()})
            else:
                message = (raw or b"").decode("utf-8", "replace")
            with open(LOG, "a", encoding="utf-8") as f:
                f.write("%s %s cmd=%s body=%s\n" % (
                    time.strftime("%H:%M:%S"), kind, cmd,
                    message[:400]))
        except Exception:
            pass

    def log_message(self, fmt, *args):
        # The request target may contain login tokens in its query string.
        if args and isinstance(args[0], str) and "?" in args[0]:
            args = (re.sub(r"\?\S*", "?[redacted]", args[0]), *args[1:])
        super().log_message(fmt, *args)


def main():
    with http.server.ThreadingHTTPServer((HOST, PORT), Handler) as httpd:
        print("[*] Rose private server on http://%s:%d  (root=%s)" % (HOST, PORT, ROOT), flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
