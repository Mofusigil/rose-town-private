#!/usr/bin/env python3
"""Reapply client initialization fixes to the verified mirrored bundle."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "site/h5/meigui"
PATCHES = {
    "assets/main/index.57d00.js": [
        (
            'return 0==t||161437001==t?(r=Rose.Settings.AssetBundleName.UI',
            'return (null==t||!Number.isInteger(Number(t))||Number(t)<0)&&(t=0),0==t||161437001==t?(r=Rose.Settings.AssetBundleName.UI',
        ),
        (
            'if(-1==t.indexOf("special_pots")&&t.indexOf("pot")>-1){var o=parseInt(t.split("pot")[1])',
            'if(/^pot\\d+$/.test(t)){var o=parseInt(t.slice(3),10)',
        ),
        (
            'this._growupTimes=o.multiSeason:this._growupTimes=o.times,this.flowerInfo.flowerID=o.id',
            'this._growupTimes=o.multiSeason:this._growupTimes=o.times,this.flowerInfo.flowerID=o.id,e.local_grow_speed>0&&(this._growupTimes=this._growupTimes.map(function(t){return t*(100-Math.min(90,Number(e.local_grow_speed)))/100}))',
        ),
        (
            'this.physicalStrength<=0?"pet_"+e+"_enervated":this.avatarId.toString()',
            'this.physicalStrength<=0?"pet_"+e+"_enervated":this.avatarId?this.avatarId.toString():"pet_"+e+"_normal"',
        ),
        (
            'return 0==this.id||6==this.id?"Main":this.effectiveDay<=0?"Main_1_1":this.physicalStrength<=0?"Main_1_1":"Main"',
            'return 0==this.id||6==this.id&&this.avatarId?"Main":this.effectiveDay<=0?"Main_1_1":this.physicalStrength<=0?"Main_1_1":this.avatarId?"Main":"Main_1_1"',
        ),
        (
            't.prototype.getPetUrl=function(){if(0==this.id||6==this.id)return""+this.avatarId;',
            't.prototype.getPetUrl=function(){if(0==this.id||6==this.id&&this.avatarId)return""+this.avatarId;',
        ),
        (
            't.prototype.getPetUrl2=function(){if(0==this.id||6==this.id)return""+this.avatarId;',
            't.prototype.getPetUrl2=function(){if(0==this.id||6==this.id&&this.avatarId)return""+this.avatarId;',
        ),
        (
            'return 0==this.id||6==this.id?"Main":"Main_1_1"',
            'return 0==this.id||6==this.id&&this.avatarId?"Main":"Main_1_1"',
        ),
    ],
    "assets/SmeltPot/index.82579.js": [
        (
            'e.prototype.getNeedStoneCount=function(){var t=this.smeltValue,e=this.curAddonData.level,o=this.curAddonData.expNext-this.curAddonData.exp,i=this.getModel(r.SmeltPotCfgManager).costMinLvelArr[this.curTab];return o<t?e>=i?this.isNearMax(e,this.curTab)?o:t:e+1==i?t-o:0:e>=i?t:0}',
            'e.prototype.getNeedStoneCount=function(){var t=this.curAddonData,e=this.getModel(r.SmeltPotCfgManager).costMinLvelArr[this.curTab],o=[10,15,20,20][this.curTab]*100;return Math.max(0,Math.min(o,t.exp+this.smeltValue)-Math.max(t.exp,100*e))}',
        ),
    ],
    "assets/FlowerOrder/index.0b031.js": [
        (
            't.resultstr&&t.result&&r.cmd&&"FlowerOrder"==r.cmd&&this.showMessaage(t.resultstr)',
            't.resultstr&&t.result&&r.cmd&&"FlowerOrder"==r.cmd&&(!t.local_unsupported||!1!==r.showCanvas)&&this.showMessaage(t.resultstr)',
        ),
    ],
    "assets/Warehouse/index.cd9c5.js": [
        (
            'case"smeltPot":var v=this.getModel(Rose.Models.PropsManager).decorateProps.get(Number(l));this.cast(Rose.SmeltPot.Name,Rose.SmeltPot.Message.showSmeltPot,v);break;',
            'case"smeltPot":var v=this.getModel(Rose.Models.PropsManager).decorateProps.get(Number(l)),roseSmeltView=this;Rose.Start("SmeltPot").then(function(){roseSmeltView.cast(Rose.SmeltPot.Name,Rose.SmeltPot.Message.showSmeltPot,v)});break;',
        ),
    ],
}
PATCHES["act/main/assets/main/index.951ed.js"] = PATCHES["assets/main/index.57d00.js"]


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
