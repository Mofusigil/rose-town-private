# -*- coding: utf-8 -*-
from pathlib import Path

vp = Path(
    r"D:/project/rose/rose_h5_client_proj/h5-proj/assets/Script/RoseAct"
    r"/2609ShuangHuiYingChangAn/Processors/ShuangHuiYingChangAnView.ts"
)
t = vp.read_text(encoding="utf-8")
imp = 'import { ShuangHuiYingChangAnAllTaskPanel } from "../Canvas/ShuangHuiYingChangAnAllTaskPanel";'
imp2 = (
    imp
    + '\nimport { ShuangHuiYingChangAnBigAwardPanel } from "../Canvas/ShuangHuiYingChangAnBigAwardPanel";'
)
if "ShuangHuiYingChangAnBigAwardPanel" not in t:
    t = t.replace(imp, imp2, 1)

old_fin = """        const extra = data?.drawResult?.extraAward;
        if (extra && extra.length > 0) {
            this._showAwardPanel({ award: extra }, ShuangHuiYingChangAnConstants.TIP_CONGRATULATIONS_MULTIPLE);
        }"""
new_fin = """        const award = data?.drawResult?.award || [];
        const extra = data?.drawResult?.extraAward || [];
        if ((award && award.length > 0) || (extra && extra.length > 0)) {
            this._showBigAwardPanel(award, extra, ShuangHuiYingChangAnConstants.TIP_CONGRATULATIONS_MULTIPLE);
        }"""
if old_fin not in t:
    raise SystemExit("finish block not found")
t = t.replace(old_fin, new_fin, 1)

old_show = """    /**
     * 结果/大奖弹窗（复用 ActivityAwardPanel · E7）
     * awardData 形状：{ award: Item[] } 或排行 { rank, award }
     */
    private _showAwardPanel(awardData: any, describe: string): void {
        const awardPanel = new Rose.RoseAct.ActivityAwardPanel(
            ShuangHuiYingChangAnMainCanvas.BundleStr,
            ShuangHuiYingChangAnMainCanvas.PanelPathStr
        );
        const awardVM = new Rose.RoseAct.ActivityAwardViewModel();
        awardVM.json = { describe };
        const temporaryModel = new ShuangHuiYingChangAnModel();
        temporaryModel.json = awardData;
        awardVM.watch(temporaryModel);
        awardPanel.show(awardVM);
        awardPanel.on(Rose.RoseAct.ActivityAwardPanel.Close, () => {
            awardPanel.close();
        });
        LOG.i(`_showAwardPanel. awardLen=${awardData?.award?.length || 0}`);
    }"""

new_show = """    /**
     * 结果/大奖弹窗（AwardPanel · 10/50 上翻页 + 下额外大奖；E7）
     * awardData 形状：{ award: Item[] } 或排行 { rank, award }
     */
    private _showAwardPanel(awardData: any, describe: string): void {
        const awards = awardData?.award || [];
        this._showBigAwardPanel(awards, [], describe);
    }

    /** 请玺汇总 / 通用恭喜获得：上区普通奖 + 下区额外大奖（1～5，四色标签） */
    private _showBigAwardPanel(awards: any[], extraAwards: any[], describe: string): void {
        const panel = new ShuangHuiYingChangAnBigAwardPanel(
            ShuangHuiYingChangAnMainCanvas.BundleStr,
            ShuangHuiYingChangAnMainCanvas.PanelPathStr
        );
        const upper = ShuangHuiYingChangAnUtils.itemsToPropAwardModels(awards);
        const extra = ShuangHuiYingChangAnUtils.itemsToPropAwardModels(extraAwards);
        const tags = ShuangHuiYingChangAnUtils.buildExtraPrizeTags(extraAwards);
        panel.setAwardData(upper, extra, describe, tags);
        panel.on(ShuangHuiYingChangAnBigAwardPanel.Close, () => {
            panel.close();
        });
        panel.show();
        LOG.i(`_showBigAwardPanel. award=${upper.length} extra=${extra.length}`);
    }"""

if old_show not in t:
    raise SystemExit("showAward block not found")
t = t.replace(old_show, new_show, 1)
vp.write_text(t, encoding="utf-8")
print("View wired")

up = Path(
    r"D:/project/rose/rose_h5_client_proj/h5-proj/assets/Script/RoseAct"
    r"/2609ShuangHuiYingChangAn/Utils/ShuangHuiYingChangAnUtils.ts"
)
u = up.read_text(encoding="utf-8")
if "itemsToPropAwardModels" not in u:
    add = """
    /** 协议道具行 → PropAwardModel */
    public static itemsToPropAwardModels(
        rows: Array<{ type?: number; id?: number; count?: number } | Rose.Canvas.PropAwardModel> | null | undefined
    ): Rose.Canvas.PropAwardModel[] {
        const out: Rose.Canvas.PropAwardModel[] = [];
        if (!Array.isArray(rows)) return out;
        for (let i = 0; i < rows.length; i++) {
            const raw = rows[i];
            if (!raw) continue;
            if (raw instanceof Rose.Canvas.PropAwardModel) {
                out.push(raw);
                continue;
            }
            const prop = new Rose.Canvas.PropAwardModel();
            Rose.RoseAct.ActivityModel.setPropAwardModel(prop, raw as any);
            out.push(prop);
        }
        return out;
    }

    /**
     * 额外大奖四色标签（图5）：优先读 quality/color/level（0~3 → 绿蓝黄红）；
     * 缺省按序循环绿→蓝→黄→红。
     */
    public static buildExtraPrizeTags(rows: Array<{ quality?: number; color?: number; level?: number }> | null | undefined): number[] {
        const C = ShuangHuiYingChangAnConstants;
        const tags: number[] = [];
        if (!Array.isArray(rows)) return tags;
        const cycle = [C.PRIZE_TAG_GREEN, C.PRIZE_TAG_BLUE, C.PRIZE_TAG_YELLOW, C.PRIZE_TAG_RED];
        for (let i = 0; i < rows.length; i++) {
            const r = rows[i] || {};
            let q = Number(r.quality ?? r.color ?? r.level);
            if (!Number.isFinite(q) || q < 0) {
                tags.push(cycle[i % cycle.length]);
                continue;
            }
            if (q >= 0 && q <= 3) tags.push(q + 1);
            else if (q >= 1 && q <= 4) tags.push(q);
            else tags.push(cycle[i % cycle.length]);
        }
        return tags;
    }
"""
    idx = u.rfind("\n}")
    u = u[:idx] + add + u[idx:]
    up.write_text(u, encoding="utf-8")
    print("Utils added")

mp = Path(
    r"D:/project/rose/rose_h5_client_proj/h5-proj/assets/Script/RoseAct"
    r"/2609ShuangHuiYingChangAn/Tests/ActivityModuleMockBackend.2609ShuangHuiYingChangAn.ts"
)
m = mp.read_text(encoding="utf-8")
oldm = """        const award = [{ type: 18, id: 10001, count: drawCount }];
        const extraAward = drawCount >= 10 ? [{ type: 18, id: 10009, count: 1 }] : [];"""
newm = """        const award = [{ type: 18, id: 10001, count: drawCount }];
        let extraAward: any[] = [];
        if (drawCount >= 50) {
            extraAward = [
                { type: 18, id: 10009, count: 1, level: 0 },
                { type: 18, id: 10008, count: 1, level: 1 },
                { type: 18, id: 10007, count: 1, level: 2 },
                { type: 18, id: 10006, count: 1, level: 3 },
                { type: 18, id: 10005, count: 1, level: 0 },
            ];
        } else if (drawCount >= 10) {
            extraAward = [{ type: 18, id: 10009, count: 1, level: 0 }];
        }"""
if oldm not in m:
    raise SystemExit("mock block missing")
mp.write_text(m.replace(oldm, newm, 1), encoding="utf-8")
print("mock ok")

# soften test assert ActivityAwardPanel
tp = Path(
    r"D:/project/rose/rose_h5_client_proj/h5-proj/assets/Script/RoseAct"
    r"/2609ShuangHuiYingChangAn/Tests/ActivityModuleTestRunner.2609ShuangHuiYingChangAn.ts"
)
tt = tp.read_text(encoding="utf-8")
tt2 = tt.replace(
    'assert(/_showAwardPanel/.test(src) && /ActivityAwardPanel/.test(src), "结果/大奖须 ActivityAwardPanel");',
    'assert(/_showBigAwardPanel/.test(src) && /ShuangHuiYingChangAnBigAwardPanel/.test(src), "结果/大奖须 BigAwardPanel");',
)
tt2 = tt2.replace(
    'assert(/_finishTreasureDraw[\\s\\S]{0,400}_showAwardPanel/.test(src), "玺藏 extraAward 须走奖窗");',
    'assert(/_finishTreasureDraw[\\s\\S]{0,500}_showBigAwardPanel/.test(src), "玺藏 award+extraAward 须走 BigAward 奖窗");',
)
if tt2 != tt:
    tp.write_text(tt2, encoding="utf-8")
    print("tests updated")
else:
    print("tests no change (patterns maybe different)")
