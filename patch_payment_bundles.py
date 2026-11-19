#!/usr/bin/env python3
"""Reapply checked private-payment hooks to the mirrored Cocos bundles.

The shared behavior is readable in lib/local-payments.js. Each replacement is
checked before writing; unexpected upstream changes stop the entire operation.
Run patch_shop_bundles.py before this script after refreshing upstream files.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent / "site/h5/meigui"
MAIN = ["assets/main/index.57d00.js", "act/main/assets/main/index.951ed.js"]
COMMON = [
    ("t.onComplete=function(r){if(t.onComplete=o,t.onComplete&&t.onComplete(r),e.settings.pretreatmentResponse){var i=e.settings.pretreatmentResponse(r.url,r.response),n=i[0],a=i[1];n&&e._dispatcher.notify(a,r)}else e._dispatcher.notify(r.url,r);var s=(new Date).getTime()-e._timestamp,l=e.settings.interval-s;l>0?setTimeout(function(){e.requestLoop()},l):e.requestLoop()}",
     "t.onComplete=function(r){try{if(t.onComplete=o,t.onComplete&&t.onComplete(r),e.settings.pretreatmentResponse){var i=e.settings.pretreatmentResponse(r.url,r.response),n=i[0],a=i[1];n&&e._dispatcher.notify(a,r)}else e._dispatcher.notify(r.url,r)}finally{var s=(new Date).getTime()-e._timestamp,l=e.settings.interval-s;l>0?setTimeout(function(){e.requestLoop()},l):e.requestLoop()}}"),
    ("var o=JSON.parse(t);return new s(this.url,o)",
     "var o=JSON.parse(t);RoseLocalPayments.observeResponse(o,this.url);return new s(this.url,o)"),
    ("e.CheckBalance=function(e){return Kernel.System.GetSystem(Framework.ModelSystem).get(p).balance>=e}",
     "e.CheckBalance=function(e){return RoseLocalPayments.canAfford(Kernel.System.GetSystem(Framework.ModelSystem).get(p).balance,e)}"),
    ('o.GoToRecharge=function(){Milkytea.Log("GoToRecharge====>"),parent.postMessage({action:"GoToRecharge"},"*")}',
     'o.GoToRecharge=function(){return RoseLocalPayments.recharge()}'),
    ('t.prototype.payCoin=function(e){var t=p.pay_url;t+="&count="+(e=Math.max(1,Math.floor(e/10))),cc.sys.openURL(t)}',
     't.prototype.payCoin=function(e){return RoseLocalPayments.recharge(e)}'),
    ("t.prototype.request=function(e){var t,o,r;this.settings.pretreatmentRequest",
     "t.prototype.request=function(e){RoseLocalPayments.tagRequest(e);var t,o,r;this.settings.pretreatmentRequest"),
    ("(t=this._module).notify.apply(t,s([e],o))",
     "RoseLocalPayments.notify(this._module,e,s([e],o))"),
]
EXACT = {name: COMMON for name in MAIN}
EXACT.update({
    "assets/Roseary/index.7c46f.js": [
        ("t.roseLifeVIP&&(o.roseLifeVIP=t.roseLifeVIP.level,o.roseLifeVIPTimeEnd=t.roseLifeVIP.timeEnd)",
         "t.roseLifeVIP&&(o.roseLifeVIP=t.roseLifeVIP.level,o.roseLifeVIPTimeEnd=t.roseLifeVIP.timeEnd,o.roseLifeGift=t.roseLifeVIP.gift)"),
    ],
    "assets/Alert/index.11790.js": [
        ("s.ShowMessage=function(t,e,n,i,r){void 0===r&&(r=null),Milkytea.CastModule",
         "s.ShowMessage=function(t,e,n,i,r){if(RoseLocalPayments.confirmPayment(e,i,r))return;void 0===r&&(r=null),Milkytea.CastModule"),
    ],
    "assets/GameVip/index.20d97.js": [
        ("t<0?this.getModel(Rose.Models.GameVIPManager).payCoin(t):this.notify(r.GameVipMessage.BuyVip_Request",
         "!RoseLocalPayments.canAfford(0,-t)?this.getModel(Rose.Models.GameVIPManager).payCoin(t):this.notify(r.GameVipMessage.BuyVip_Request"),
    ],
    "assets/GiftCard/index.89047.js": [
        ("this.userData.roseMoney=this.userData.roseMoney-Number(i.price)*s",
         "this.userData.roseMoney=RoseLocalPayments.afterSpend(this.userData.roseMoney,Number(i.price)*s)"),
    ],
    "assets/FairyPotRefine/index.67530.js": [
        ("n.balance-=50", "n.balance=RoseLocalPayments.afterSpend(n.balance,50)"),
        ("n.balance-=10*a.count", "n.balance=RoseLocalPayments.afterSpend(n.balance,10*a.count)"),
        ("n.balance-=20*a.count", "n.balance=RoseLocalPayments.afterSpend(n.balance,20*a.count)"),
        ("n.balance-=30*a.count", "n.balance=RoseLocalPayments.afterSpend(n.balance,30*a.count)"),
    ],
    "assets/Shop/index.b24c8.js": [
        ("e.seedPriceQPoint*o>this.getModel(Rose.Models.UserData).balance",
         "!RoseLocalPayments.canAfford(this.getModel(Rose.Models.UserData).balance,e.seedPriceQPoint*o)"),
        ("else if(e.seedPrice>0&&e.seedPrice*o>this.getModel(Rose.Models.UserData).roseMoney)",
         "else if(!e.seedPriceQPoint&&e.seedPrice>0&&e.seedPrice*o>this.getModel(Rose.Models.UserData).roseMoney)"),
        ("(this.payType==p.PayType.gold?this.m_data.price:this.discountPrice)>(this.payType==p.PayType.gold?this.totalGold:this.totalDiamod)",
         "(this.payType==p.PayType.gold?this.m_data.price>this.totalGold:!RoseLocalPayments.canAfford(this.totalDiamod,this.discountPrice))"),
        ("this.needDiamod>this.totalDiamod",
         "!RoseLocalPayments.canAfford(this.totalDiamod,this.needDiamod)", 2),
    ],
    "assets/PetHouseMap/index.c997b.js": [
        ("var n=this.getModel(Rose.Models.UserData).balance-o.pay_count/10",
         "var n=RoseLocalPayments.afterSpend(this.getModel(Rose.Models.UserData).balance,o.pay_count/10)"),
    ],
    "assets/FlowerGod/index.1fe7a.js": [
        ("i*o>this.getModel(Rose.Models.UserData).balance",
         "!RoseLocalPayments.canAfford(this.getModel(Rose.Models.UserData).balance,i*o)"),
    ],
})

# Only the shipped user-balance comparisons are transformed. Server-response
# validation (response.balance >= 0) and every gold-money comparison stay intact.
USER = r"(?:this\.(?:_userData|userData)|(?:this|[a-z])\.getModel\(Rose\.Models\.UserData\))"
COMPARE = re.compile(r"(?P<balance>" + USER + r"\.balance)<(?P<price>[a-z]|\d+)(?![\w.])")
SPEND = re.compile(r"(?P<user>" + USER + r")\.balance-=|(?P<same>" + USER + r")\.balance=(?P=same)\.balance-")


def expression_end(source, offset):
    """Read the small arithmetic RHS without swallowing outer JS delimiters."""
    depth = 0
    ternary = 0
    quote = None
    escaped = False
    for index in range(offset, len(source)):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            if depth == 0:
                return index
            depth -= 1
        elif depth == 0 and char == "?":
            ternary += 1
        elif depth == 0 and char == ":":
            if ternary == 0:
                return index
            ternary -= 1
        elif depth == 0 and char in ",;}":
            return index
    raise ValueError("Unterminated balance arithmetic")


def patch_arithmetic(source, name):
    source, checks = COMPARE.subn(
        lambda m: "!RoseLocalPayments.canAfford(%s,%s)" % (m["balance"], m["price"]), source)
    matches = list(SPEND.finditer(source))
    spends = 0
    for match in reversed(matches):
        # This legacy shop fallback is already protected by the explicit server
        # balance field. Keep its text so the older shop patch stays repeatable.
        if name == "assets/Shop/index.b24c8.js" and source[match.end():match.end() + 2] == "u,":
            continue
        end = expression_end(source, match.end())
        user = match["user"] or match["same"]
        replacement = "%s.balance=RoseLocalPayments.afterSpend(%s.balance,%s)" % (
            user, user, source[match.end():end])
        source = source[:match.start()] + replacement + source[end:]
        spends += 1
    return source, checks, spends


# Filled from the current build; distinct upstream builds need a new review.
COUNTS = {
    "assets/main/index.57d00.js": (1, 0),
    "assets/Act_2202HitBalloon/index.8cc45.js": (2, 0),
    "assets/Act_2203ShoppingEveryDay/index.a11de.js": (1, 0),
    "assets/Act_2412IllustratedBooks/index.e82e4.js": (1, 1),
    "assets/Combine/index.bf9b7.js": (1, 2),
    "assets/ButterflyFlower/index.bf66e.js": (0, 1),
    "assets/BeanVine/index.07196.js": (0, 2),
    "assets/DingXiang/index.791b5.js": (0, 5),
    "assets/DecorateGarden/index.deda8.js": (0, 5),
    "assets/FairyPotRefine/index.67530.js": (0, 8),
    "assets/Dream/index.0b3be.js": (0, 1),
    "assets/FlowerGod/index.1fe7a.js": (3, 0),
    "assets/FlowerOrder/index.0b031.js": (0, 2),
    "assets/FlowerRace/index.a1b93.js": (1, 1),
    "assets/GameVip/index.20d97.js": (1, 0),
    "assets/GetRoseMaterial/index.34454.js": (0, 3),
    "assets/GiftCard/index.89047.js": (0, 4),
    "assets/GourdUI/index.9ca3f.js": (0, 3),
    "assets/PetHouseMap/index.c997b.js": (0, 1),
    "assets/PetPKDisCount/index.53526.js": (1, 1),
    "assets/PetPKAugury/index.ac3e8.js": (0, 1),
    "assets/PetPKCRank/index.cf4fd.js": (0, 2),
    "assets/PetPKBuyGift/index.c3514.js": (0, 1),
    "assets/PetPKShop/index.4d8e4.js": (1, 1),
    "assets/PetPKTeam/index.ce0f6.js": (0, 2),
    "assets/PlantationMap/index.77c1e.js": (0, 2),
    "assets/PotAttribute/index.8ed14.js": (0, 2),
    "assets/PetPKTraining/index.8eef7.js": (0, 7),
    "assets/PotGem/index.99df7.js": (0, 3),
    "assets/RoseSeedUpgrade/index.d29e9.js": (0, 1),
    "assets/Shop/index.b24c8.js": (4, 6),
    "assets/Warehouse/index.cd9c5.js": (0, 1),
    "assets/SoilPergolas/index.f1848.js": (0, 2),
    "assets/TownDaily/index.0155a.js": (1, 1),
    "act/main/assets/main/index.951ed.js": (1, 0),
}


def build_updates(root=ROOT):
    updates = {}
    for name, replacements in EXACT.items():
        source = (root / name).read_text()
        for replacement in replacements:
            before, after = replacement[:2]
            expected = replacement[2] if len(replacement) > 2 else 1
            already = source.count(after)
            pending = source.count(before)
            if already + pending != expected:
                raise ValueError("Unexpected bundle fragment in %s: %s" % (name, before[:80]))
            source = source.replace(before, after)
        updates[name] = source
    candidates = list((root / "assets").rglob("*.js")) + [root / MAIN[1]]
    for path in candidates:
        name = str(path.relative_to(root))
        original = updates.get(name, path.read_text())
        patched, checks, spends = patch_arithmetic(original, name)
        if checks or spends or name in COUNTS:
            expected = COUNTS.get(name)
            actual = (patched.count("RoseLocalPayments.canAfford("),
                      patched.count("RoseLocalPayments.afterSpend("))
            if expected != actual:
                raise ValueError("Unexpected payment hook counts in %s: %s, expected %s" % (name, actual, expected))
            updates[name] = patched
    for name, script in [("index.html", "lib/local-payments.js"),
                         ("act/main/index.html", "../../lib/local-payments.js")]:
        source = (root / name).read_text()
        if 'src="%s"' % script not in source:
            marker = "  <script>"
            if marker not in source:
                raise ValueError("Missing entrypage script marker: " + name)
            source = source.replace(marker, '  <script src="%s"></script>\n%s' % (script, marker), 1)
        updates[name] = source
    return updates


def main():
    updates = build_updates()
    for name, source in updates.items():
        path = ROOT / name
        if path.read_text() != source:
            path.write_text(source)
            print("Patched %s" % name)


if __name__ == "__main__":
    main()
