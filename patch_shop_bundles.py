#!/usr/bin/env python3
"""Reapply the small shop fixes after refreshing the mirrored CDN bundles.

The unminified shared value rules live in lib/shop-fixes.js. Replacements are
checked before any file is written so a different upstream build fails clearly.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "site/h5/meigui"
PATCHES = {
    "assets/main/index.57d00.js": [
        (
            't.flowers=new Map,t._flowerSeed=new Map,t.variationFlowers=new Map',
            't.flowers=new Map,t.priceChangeFlower=new Map,t._flowerSeed=new Map,t.variationFlowers=new Map',
        ),
        (
            't.prototype.setSpecialCharm=function(e){if(e){var t=e.valentinesDay2020rcvCharm,o=e.valentinesDay2020sndCharm;if(t)for(var r=0;r<4;r++)this.recvCharms.set(Rose.Models.CharmFlowerArr[r],Number(t[r]));if(o)for(r=0;r<4;r++)this.sendCharms.set(Rose.Models.CharmFlowerArr[r],Number(o[r]))}}',
            't.prototype.setSpecialCharm=function(e){if(e){RoseShopFixes.setCharmValues(this.recvCharms,Rose.Models.CharmFlowerArr,e.valentinesDay2020rcvCharm);RoseShopFixes.setCharmValues(this.sendCharms,Rose.Models.CharmFlowerArr,e.valentinesDay2020sndCharm)}}',
        ),
        (
            'n=e.charm?e.charm:o.getRecvCharm(e.id),a=e.givercharm?e.givercharm:o.getSendCharm(e.id)',
            'n=RoseShopFixes.resolveCharm(e.charm,o.getRecvCharm(e.id)),a=RoseShopFixes.resolveCharm(e.givercharm,o.getSendCharm(e.id))',
        ),
        (
            r'\u9b45\u529b[color=#cc0000] +"+a+"[color]"',
            r'\u9b45\u529b[color=#cc0000] "+RoseShopFixes.formatCharm(a)+"[color]"',
        ),
        (
            r'\u9b45\u529b[color=#cc0000] +"+n+"[color]"',
            r'\u9b45\u529b[color=#cc0000] "+RoseShopFixes.formatCharm(n)+"[color]"',
        ),
    ],
    "assets/Shop/index.b24c8.js": [
        (
            'if(o&&this._flowerManager.priceChangeFlower){var i={totalGold:this.getModel(Rose.Models.UserData).roseMoney,priceChange:this._flowerManager.priceChangeFlower.get(t)}',
            'if(o){var i={totalGold:this.getModel(Rose.Models.UserData).roseMoney,priceChange:this._flowerManager.priceChangeFlower?this._flowerManager.priceChangeFlower.get(t):0}',
        ),
        (
            'u=p.charm?p.charm:c.getRecvCharm(p.id),y=p.givercharm?p.givercharm:c.getSendCharm(p.id)',
            'u=RoseShopFixes.resolveCharm(p.charm,c.getRecvCharm(p.id)),y=RoseShopFixes.resolveCharm(p.givercharm,c.getSendCharm(p.id))',
        ),
        (
            r'\u9b45\u529b +"+this.otherData.sendCharm+"\n"',
            r'\u9b45\u529b "+RoseShopFixes.formatCharm(this.otherData.sendCharm)+"\n"',
        ),
        (
            r'\u9b45\u529b +"+this.otherData.recvCharm+"\n"',
            r'\u9b45\u529b "+RoseShopFixes.formatCharm(this.otherData.recvCharm)+"\n"',
        ),
        (
            'if(h&&(this._userData.roseMoney=h),c){var u=l.seedPriceQPoint*r;u*=c?.8:1,this._userData.balance-=u,this._mainModel.shopData.diamond=this._userData.balance}',
            'if(o.rosemoneyleft!=null&&isFinite(h)&&(this._userData.roseMoney=h),o.balance!=null&&isFinite(Number(o.balance)))this._userData.balance=Number(o.balance),this._mainModel.shopData.diamond=this._userData.balance;else if(c){var u=l.seedPriceQPoint*r;u*=c?.8:1,this._userData.balance-=u,this._mainModel.shopData.diamond=this._userData.balance}',
        ),
    ],
}


def main():
    updated = {}
    for name, patches in PATCHES.items():
        path = ROOT / name
        source = path.read_text()
        for before, after in patches:
            if after in source:
                continue
            if source.count(before) != 1:
                raise ValueError("Unexpected bundle content in %s: %s" % (name, before[:80]))
            source = source.replace(before, after, 1)
        updated[path] = source
    for path, source in updated.items():
        path.write_text(source)
        print("Patched %s" % path.relative_to(ROOT))


if __name__ == "__main__":
    main()
