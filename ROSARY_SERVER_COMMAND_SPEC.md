# 玫瑰小镇 H5 私服 服务端命令完整规格 (Rosary Server Command Spec)

> 由 intent 102 静态逆向补全。数据来源：`/home/asriel/Projects/rose_town/site/h5/meigui/_src_readable/main.index.beautified.js`
> （框架/HttpSettings/命令表）与 `assets/<Feature>/index.*.js` 各玩法 bundle（64 个 bundle 的
> `RosarySeverUrl.*` 引用、`.send()/.request()` 调用点、`@RosarySeverResponse` 响应处理函数）。
> 与本文件配套的机器可读提取物在 `/home/asriel/Projects/ARTEX/data/tasks/4/i102/`
> （`all_sends.txt`、`activity_oper.txt`、`appendix.md`、`handlers2.json`、`spec_raw.json`）。

---

## 1. 传输协议总览

| 项 | 值 |
|---|---|
| 网关基址 | `https://cgi.meigui.qq.com/cgi-bin/` （`RosarySeverHost`） |
| 方法 | **POST** |
| Content-Type | `application/x-www-form-urlencoded` |
| 附加头 | `pragma: no-cache`；`XMLHttpRequest.withCredentials = true`（带 cookie） |
| URL 形式 | `https://cgi.meigui.qq.com/cgi-bin/<command>?gprand=<Math.random()>` |
| 请求体 | 参数对象直接拼成 `k1=v1&k2=v2...`（**不做 urlencode**，见 PostLoader.setRequest） |
| 响应体 | 文本 → 先 `\xNN` 反转义 → `JSON.parse` → 对象 `response` |
| 回调对象 | `{ url, response, userParams }`（响应处理函数参数 `e.response` / `e.userParams`） |

### 1.1 每个请求自动注入的参数（`HttpSettings.pretreatmentRequest`）

客户端对**除 `rosary0908_get_user_info` 以外的所有命令**注入登录态与公共参数，然后拼 `?gprand=`：

- 登录态（来自 URL query / localStorage / cookie，任一）：
  - `PingPong` — 会话票据（来自 URL `?PingPong=` 或 `window.__ROSE_PINGPONG__`）。**无 PingPong 则跳过整个注入。**
  - `openid` — 若无 cookie，则按 PingPong 查硬编码表取默认值（见下表）
  - `token` 与 `openkey` = 同一个 token 值（两者都发）
  - `appid` = `102072120`（默认）
  - `session_type` = `openkey`（默认）
- 公共参数（若请求体未自带则填默认值）：
  - `benew0908 = 5`（若未指定）
  - `ossType = 3`（若未指定）
  - `cgiVersion = 43`（若未指定）

> ⚠️ `rosary0908_get_user_info` 是**唯一例外**：只注入登录态、不加 gprand/benew0908/ossType/cgiVersion。

### 1.2 FakeLogin 硬编码 openid 表（无 cookie 时的回退）

```
448984620  -> AADAD8430DD37E40107C2D2D944712AF
1130360251 -> 506C35083A6D6294B1A706C6F6906769
803700022  -> 9AA608845B935D3F37FA55C4100B300F
```

### 1.3 灰度路由（gray routing）

- `grayCgiList`（来自 `rosary0909_get_init_first_self` 响应）中的命令名 → URL 追加 `_go` 后缀。
- `actCmdList`（同上）命中且命令为 `rosary_activity_oper` 时：若请求体 `cmd` 数字 ∈ `actCmdList`
  → URL 变为 `rosary_activity_oper_go`。
- **私服建议**：init 响应里返回 `grayCgiList: []` 与 `actCmdList: []` 即可让所有命令走原始 URL，避免实现 `_go` 变体。

### 1.4 响应信封与 result 码

统一 JSON 信封：`{ "result": <int>, "resultstr": "<msg>", ...命令专属字段 }`

| 字段 | 语义 |
|---|---|
| `result` | **0 = 成功**；非 0 = 失败。客户端普遍 `if (resp.result) 弹 resultstr` / `if (0==resp.result) 成功`。 |
| `resultstr` | 失败提示文案（成功时通常为空或省略）。 |
| `errno` | 部分命令（如 `rosary0907_sale_vegetable`）额外返回的错误码。 |
| `1000013` | **全局特殊码**：表示「服务器维护中」，在响应总处理 `pretreatmentResponse` 里拦截（`1000013 == t.result`）。 |

> 客户端**不比对具体数值结果码**（除 1000013）；一律以 `result` 真值判断成功/失败，具体原因用 `resultstr`。
> 因此私服实现只需保证：成功返回 `result:0` + 正确 payload；失败返回 `result:非0` + `resultstr`。

---

## 2. 命令表（105 个 SeverUrl 键 → 60 个真实后端命令）

同一命令被多个功能复用（尤其 `rosary0904_expand`、`rosary_activity_oper`、
`rosary0903_send`、`rosary0907_sale_vegetable`、`rosary_get_props_info`、
`rosary0904_get_freeseed`、`rosary0903_sale`）。

### 2.1 启动/基础（intent 101 已覆盖，此处备查）
| 键 | 命令 | 说明 |
|---|---|---|
| GetUserBaseInfo | `rosary0908_get_user_info` | 拉用户基础信息（不注入公共参数） |
| GetPlayerInfo | `rosary0909_get_init_first_self` | 初始化自身；响应含 `grayCgiList/actCmdList/svrtime/GameSettings` |
| GetFriendInfo | `rosary0909_get_init_first_friend` | 初始化好友 |
| InitSecond | `rosary0907_get_init_second` | 二次初始化（`{common:"1",selforfriend:0}`） |
| GetPlantationInfo | `rosary0908_get_plant_info_self` | 拉自家庭院/花盆 |
| GetFriendPlantationInfo | `rosary0908_get_plant_info_friend` | 拉好友庭院 |
| GetDiamond | `rosary_diamond` | 点券信息 |
| GetTask | `rosary_task` | 任务 |
| LimitSaleInfo | `rosary_get_props_info` | 限时售卖 |
| GetPets | `rosary0903_get_takeon_pets` | 拉宠物 |

### 2.2 种植/收获/庭院（核心玩法）
| 键 | 命令 | 用途 |
|---|---|---|
| PlantationFlower | `rosary0904_soil_plant_rose` | 种花 |
| PlantationGain | `rosary0904_gain` | 收获/偷花/抓蝴蝶 |
| PlantationHoe | `rosary0904_hoe` | 铲除 |
| PlantationAction | `rosary0904_plant_action` | 植株动作（如施肥动作/催熟 etc.） |
| PlantationSpade | `rosary0904_plant_use_spade` | 使用小铲 |
| PlantationFertilizer | `rosary0906_use_fertilizer` | 施肥 |
| StealFriendFlower | `rosary0904_steal` | 偷好友花 |
| FlowerGraft | `rosary1003_plant_graft` | 嫁接 |
| PotExpand / FlowerPotUplevel / FlowerPotUplevelByQB / FlowerPotRefineLevel / UnlockFlowerPot / UnlockFairyFlowerPot / PotGemAction / PotAttributeAction | `rosary0904_expand` | 花盆扩容/升级/解锁/宝石/属性（同命令靠 `actionop`/`action` 区分） |
| UseTrickyWater | `rosary_activity_oper` | 使用神水（活动命令族，见 §3.4） |
| PlantationOper | `rosary_activity_oper` | 庭院活动操作 |

### 2.3 玫瑰制作/材料（GetRoseMaterial 玩法机）
| 键 | 命令 | 用途 |
|---|---|---|
| GetRoseMaterial / LimitSaleInfo | `rosary_get_props_info` | 材料机基础数据 |
| GetRoseMaterial_begin_play | `rosary0903_begin_play` | 转盘开始（免费/付费） |
| rosary0903_play | `rosary0903_play` | 单步转盘 |
| rosary_converter | `rosary_converter` | 材料合成/回收 |
| rollPlate_award | `rosary_activity_oper` | 领取转盘奖励 |
| MakeRose | `rosary0903_make_rose` | 制作玫瑰 |
| MakeWing | `rosary_activity_oper` | 制作翅膀 |
| Makekey | `rosary_make_key` | 制作钥匙 |
| Use_Goddess | `rosary_god_tear` | 使用女神之泪 |
| BuyGmaePropsOther | `rosary0903_sale` | 杂项购买（含转盘购买） |

### 2.4 商店/背包/赠礼/出售
| 键 | 命令 | 用途 |
|---|---|---|
| BuySeedWithGold | `rosary0908_rosemoney_buy_seed` | 玫瑰币买种子 |
| BuySeedWithQB | `rosary_qb_buy_seed` | Q币买种子 |
| BuyGameProps | `rosary_buy_game_props` | 通用道具购买 |
| BuyFertilizer | `rosary0906_buy_fertilizer` | 买肥料 |
| BuyPotDecorate | `rosary0906_buy_decorate` | 买花盆装饰 |
| UsePotDecorate / DecorateByDecorateProps | `rosary0906_use_decorate` | 使用/更换装饰 |
| BuyCharmFlower | `rosary_activity_oper` | 买魅力花/送花 |
| SellFlower / SellProps | `rosary0907_sale_vegetable` | 卖花/卖道具（同命令靠 `type`+`cmd` 区分） |
| PickRose | `rosary0903_gather` | 采摘玫瑰 |
| OpenGift | `rosary0903_open_chip` | 开碎片/礼包 |
| ExchangeRoseSeed | `rosary0903_exchange_crowry` | 兑换玫瑰种子 |
| FriendGiftSend / FriendGardenPour | `rosary0903_send` | 好友赠礼/浇花 |
| ComposeLingshiProps / ComposeFlowerPot / UpgradePearl / HangingOrnament | `rosary_activity_oper` | 灵犀/花盆合成、珍珠升级、挂饰 |

### 2.5 好友/宠物
| 键 | 命令 | 用途 |
|---|---|---|
| FriendInfo | `rosary_get_friends_info` | 好友列表 |
| FriendList_Operation_Request | `rosary_get_friend_flowerstatus` | 好友花状态/操作 |
| InvitFriendSendGift | `rosary0912_send_newyearsgift` | 邀请好友送礼 |
| GetFriendPetHouseInfo | `rosary0903_get_takeon_pets` | 好友宠物房 |
| SetPetNickName | `rosary_set_pet_neck` | 宠物改名 |
| SetPetStatus | `rosary_set_pet_status` | 宠物上/下场 |
| PetRenew | `rosary_pets_feed` | 宠物续费 |
| PetFeed | `rosary_talent_pet_feed` | 天赋宠喂养 |
| PetScout | `rosary_detect_user` | 探宝/嗅探 |
| PetExplore | `talent_pet_adventure` | 宠物探险 |
| PetPK | `rosary_talentpk_oper` | 宠物 PK（见 §3.3） |

### 2.6 活动族（全部 `rosary_activity_oper`）
AchieveMent/成就、IllustratedBooks/图鉴(`rosary_get_achievement`)、GetFreeGift/免费领种(`rosary0904_get_freeseed`)、
DingXiang/丁香、GameVip/GameDailyGift(`rosary0912_gamevip_gifts`)、TownDaily/小镇日常、FlowerRace/花赛、
FlowerGod/花神、RoseSignIn/签到、FlowerOrder/花坊订单、DailyTask/日常任务、HappyEgg/彩蛋、
ButteryflyFlower/蝴蝶花、GiftCard/礼卡、Recycle/回收、Perfume/香水、SmeltPotOP/熔炉、
GameSettingOper/游戏设置、UpgradeRoseSeed/升种子、RankListButteryfly/榜单等。

### 2.7 其它
| 键 | 命令 |
|---|---|
| ChangeTitle | `rosary_set_title` |
| NormalGameSetting | `rosary0907_maskorunmask` |
| MessageInfo | `rosary0904_get_message` |
| GetRewardCharmPrivilege | `rosary0903_get_salary` |
| RankListBigAward | `rosary0903_big_award` |
| RankListExpAndCharm | `rosary_get_word_rank` |
| HistoryPrice | `rosary_get_action_flowerinfo` |
| IllustratedBooks | `rosary_get_achievement` |
| NotFound | `rosary_buried_point`（埋点上报） |
| PutFlower | `rosary0912_put` |
| GourdInfo | `rosary_gourd_oper`（葫芦玩法） |

---

## 3. 核心玩法命令详表（请求参数 / 响应字段 / userParams.cmd）

> 记法：请求体列出发出的业务参数（§1.1 的登录态/公共参数省略）；
> `cmd=` 指传给客户端监听器的 `userParams.cmd`（同 URL 下区分处理分支，
> **服务端不必回显，但语义上同一命令可能对应多个操作**）；响应列出客户端读取的字段。

### 3.1 种植 / 收获 / 庭院（bundle: Plantation, PlantationMap）

- **`rosary0904_soil_plant_rose`** — 种花（PlantationFlower）
  - 请求：`{ soilno:<花盆序号>, rosetype:<玫瑰类型id> }`
  - 响应：`result`，并回填花盆 `{ soilno, dx_award, award{count}, butterflyID, soilsate, level,
    potAttributeData*.speed, vegetableseed<N> }`（客户端把响应 json 合并进对应花盆对象）
- **`rosary0904_gain`** — 收获（PlantationGain），三种分支同一命令：
  - 自己收：`{ soilno, rosetype }` cmd=`PlantationGain`
  - 偷好友：`{ soilno, needEncrypt:1, frienduin:<加密QQ> }` cmd=`PlantationGain`（frienduin 需加密）
  - 抓蝴蝶：`{ soilno, catch:1, catchFrienduin:<加密QQ> }` cmd=`catchButterfly`
  - 响应：`{ result, soilno, season, soilsate, rosestate, rosebegintime }`
    （`season>1` 回填 `{soilsate,rosestate,rosebegintime,season}`，否则 `soilsate=50`）
- **`rosary0904_hoe`** — 铲除（PlantationHoe）：`{ soilno, rosetype }` → 响应 `{ result, soilno }`
- **`rosary0904_plant_action`** — 植株动作（PlantationAction）：`{ soilno, ... }` → `{ result, soilno }`
- **`rosary0906_use_fertilizer`** — 施肥（PlantationFertilizer）：`{ soilno, ... }` → `{ result, soilno }`
- **`rosary0904_expand`** — 花盆扩容/升级/解锁（同一命令多用途，靠 `actionop`/`action` 区分）：
  - 解锁普通盆 `{ soilno, SoilType, ... }` cmd=`UnlockFlowerPot`
  - 升级普盆 `{ paytype:6|1, soilno, SoilType, action:1 }` cmd=`FlowerPotUplevel` / `FlowerPotUplevelByQB`
  - 解锁仙盆 `{ benew0908:3, actionop:1, action:6, paytype:1|6, soilno }` cmd=`UnlockFairyFlowerPot`
  - 仙盆首解 `{ benew0908:3, actionop:2, action:6, paytype, soilno }` cmd=`UnlockFairyFlowerPotFirst`
  - 扩展花盆（PotExpand）`{ soilno, ... }`
  - 响应：`{ result, ... } + 花盆更新`
- **`rosary1003_plant_graft`** — 嫁接（FlowerGraft）
- **`rosary0904_steal`** — 偷好友花（StealFriendFlower）

### 3.2 制作玫瑰 / 材料机（bundle: GetRoseMaterial，命令集 `rosary0903_*`）

- **`rosary_get_props_info`** — 材料机基础数据
  - 请求：`{ benew0908:1 }` cmd=`ShowGetRoseMaterial`
  - 响应：`{ result, resultstr, LFNInfo, huapan, huapan_discount }`
- **`rosary0903_play`** — 单步转盘
  - 请求：`{ benew0908:1 }` cmd=`freePlay`
  - 响应：`{ result, currentaward, currentawardtype, currentawardcount, currentawardname, totalstep, currentstep }`
- **`rosary0903_begin_play`** — 开始转盘/免费玩
  - 免费玩：`{ benew0908:3, type:5, play_free:0, kind:5 }` cmd=`freePlay`
  - 主流程开始：`{ benew0908:3, kind:1, type, play_free:0 }` cmd=`primaryStart`（userParams 带 `type`）
  - 响应：`{ result, lucky_star, award[], totalstep, currentstep, currentaward, currentawardcount,
    currentawardname, morestep, fraward, frname, svrData{materialAward,nationalAward,gatherprop} }`
- **`rosary0903_sale`** — 购买转盘次数/道具（BuyGmaePropsOther）
  - 请求：`{ benew0908:1, paytype:1, buytype:<买号>, gameviplevel, buycount:<数量>, frienduin:0 }`
    cmd=`buy`（userParams 另带 `price`）
  - 响应：`{ result, buycount, discount }`
- **`rosary_converter`** — 材料合成/回收
  - 请求：`{ num, type, id, kind, benew0908 }` cmd=`startRecycle`（userParams 带 `id,num`）
  - 响应：`{ result, gift[], isGratis, tips }`
- **`rosary0903_make_rose`** — 制作玫瑰（MakeRose，bundle: Combine）
  - 请求：`o`（合成配方 `{ id/材料..., }`），cmd=`MakeRose@CombineCtrl`
- **`rosary_activity_oper`** — 领转盘奖励（rollPlate_award）
  - 请求：`{ cmd:20, request:8, kind, benew0908:1 }` cmd=`getAward`
  - 响应：`{ result, award, huapan, gametype }`

### 3.3 宠物 PK（bundle: PetPK*，命令 `rosary_talentpk_oper`）

所有子功能共用 `rosary_talentpk_oper`，靠请求体 `type` + `userParams.cmd` 区分：

| 功能 | 请求体 | userParams.cmd |
|---|---|---|
| 初始化 | `{ type:1, cgiVersion:43, benew0908:1 }` | `InitInfo@PetPKMsgCtrl` |
| 排行榜翻页 | `{ page, type:8, benew0908:1 }` | `ChangeRankPage` |
| 领排行奖励 | `{ type:11, benew0908:1 }` | `GetRankAward` |
| 免费占卜 | `{ type:24, augury:1, cgiVersion:43, benew0908:1, platform:1 }` | `FreeAugury@PetPKAuguryCtrl` |
| 付费占卜 | `{ type:24, augury:2, paytype:1, ... }` | `PayAugury@PetPKAuguryCtrl` |
| 买礼包 | `{ type:26, paytype:1, platform:1, ... }` | `BuyGift@PetPKBuyGiftCtrl` |
| 折扣店初始化 | `{ type:22, request:1, ... }` | `Init@PetPKDisCountCtrl` |
| 折扣店购买 | `n`(cost) | `Buy@PetPKDisCountCtrl` |
| 商店初始化/购买 | `{ type:3, ... }` / `{ num,id,paytype,cost }` | `Init/Buy@PetPKShopCtrl` |
| 队伍初始化 | `{ type:3, ... }` | `InitInfo@PetPKTeamCtrl` |
| 符文/令牌 使用|升级|装卸 | `t` | `UseRunes/SaveMatrix/UpgradeToken/UnloadToken/EquippingToken@PetPKTeamCtrl` |
| 战旗 | `{ type:25, action:1|3, ... }` | `InitFlag/UseSpoils@PetPKTeamCtrl` |
| 训练 | `{ op,id,... }` | `Training@PetPKTrainingCtrl` |
| 合同/天赋升级 | `{ type:23,request:1,... }` / `{ id,count,contUg,upgrade }` | `ContractOpen/ContractUp@PetPKTrainingCtrl` |

- 初始化响应字段：`{ result, resultstr, matrix, selfaward, award }`

### 3.4 日常任务 / 活动（`rosary_activity_oper` 命令族）

命令体统一为 `{ cmd:<数字>, request:<数字>, ...业务参数 }`；不同活动用不同 `cmd` 号段。
**服务端按 `cmd` 号 + `request` 号分派即可，`userParams.cmd` 只是客户端路由用（无需回显）。**

| 活动 | 命令体（cmd/request） | 关键业务参数 |
|---|---|---|
| 每日任务 DailyTask | `{cmd:222,request:1}` init；领奖带 `index` | — |
| 小镇日常 TownDaily | 领阳光奖 / 提示 / 初始化 / 购买阳光（cmd 分支） | `coin,selectindex` |
| 签到 RoseSignIn | `{cmd:146,request:1}` init；签到/领奖带 `index` | — |
| 花神 FlowerGod | `{cmd:213,request:1}` init；`request:10` 历史；`request:5` 刷新兑换 | `flowerId,count,taskType,index,type` |
| 花赛 FlowerRace | `{cmd:48,request:7}` 领奖；`request:14` 猜奖；`request:6` 排名；初始化带 page | `index,type` |
| 花坊订单 FlowerOrder | `{cmd:60,request:1}` 列表；`request:8` 刷新兑换 | `paytype` |
| 丁香 DingXiang | `{cmd:1001}` 信息；1002 换技能；1003~1013 各种操作 | `count,position,paytype,id,skill_id,exchange_value,pay_month` |
| 彩蛋 HappyEgg | `{cmd:198,request:1}` | — |
| 蝴蝶花 ButterflyFlower | `{cmd:231,request:1}` 展示；`request:6` 兑换数据；`request:8` 升级属性 | — |
| 游戏VIP GameVip | 初始化/买VIP（`count`）/成长礼包 | `count` |
| 回收 Recycle | 分步：查询(参数 `e`)/开始(`o,t`)/领取(`s,u/a`)/确认(`c,l`) | — |
| 香水 Perfume | `{cmd:252,request:1}` init | — |
| 熔炉 SmeltPotOP | `{request:20,cmd:20,benew0908:1,paytype:1}` 付费 | — |
| 礼卡 GiftCard_Http | `{cmd:43,benew0908:1,cgiVersion:43,action:1}` / `{cmd:12,...}` | — |
| 升种子 UpgradeRoseSeed | `{autopay,seed_id,cmd:1}` | — |
| 图鉴 IllustratedBooks | 读 `{benew0908:1}`；激活/加速/领榜/领奖（`opType,cost`） | — |
| 游戏设置 GameSettingOper | `{cmd:20,request:21,flag}`（简设/锁娜/协议开关）；`{cmd:181,request:1..6,pwd,newPwd}` 密码操作 | `flag,pwd,newPwd` |
| 榜单蝴蝶 RankListButteryfly | （领奖等） | — |

### 3.5 商店（bundle: Shop）

- **`rosary0908_rosemoney_buy_seed`**（BuySeedWithGold）：`{ count, type, etime }` cmd（userParams 带 `reportTime`）
- **`rosary_qb_buy_seed`**（BuySeedWithQB）：`{ count, seedtype, gameviplevel, paytype }`
- **`rosary_buy_game_props`**（BuyGameProps）：`{ count, buyid, gameviplevel, paytype }`
  （不同玩法复用：玫瑰种子升级买灵石 `buyid=RoseSeedUpgradeSettings.StoneId`）
- **`rosary0906_buy_fertilizer`**（BuyFertilizer）：`{ buytype, buycount, paytype, frienduin:0, gameviplevel, benew0908:1 }`
  cmd=`buyShopProps`
- **`rosary0906_buy_decorate`**（BuyPotDecorate）：`{ buytype, qqgamevipflag, paytype }` cmd=`ShowBuyPotDecorate`
- **`rosary_activity_oper`**（BuyCharmFlower）：
  - 送魅力花 `{ buycount:1, frienduin:<加密>, gameviplevel:0, buytype:41, needEncrypt:1, paytype:1 }` cmd=`SendCharmFlower`
  - 购买 `{ request:2, id, cmd:236, count }`
  - 响应：`{ result, resultstr, cost, frienduinnic, buycount, addcharm, friendaddcharm, discount }`
- **`rosary0906_use_decorate`**（UsePotDecorate / DecorateByDecorateProps）：`{ usetype, dotype }` cmd=`UsePotDecorate`/`DecorateCtrl`

### 3.6 背包 / 出售（bundle: Warehouse）

- **`rosary0903_gather`** — 采摘玫瑰（PickRose），三分支：
  - 单收/批收：`{ type:0, rosetype, position }` cmd=`PickRose` / `PickRoseBatch`
  - 一键收：`{ type:1, rosetype, position }` cmd=`PickRoseSecond`
  - 响应：`{ result, resultstr, award, awardname, awrdtype, gatherrosetye, gathertyperoseleft[],
    getrosejinghua, petchip, tiggerchip, extra_bonus }`
- **`rosary0907_sale_vegetable`** — 卖花/卖道具（SellFlower/SellProps），靠 cmd+参数区分：
  - 卖花 `{ type, etime, position:0, addon:0|1, count }` cmd=`SellFlower`
  - 全部卖出 `s`（参数含 `position,etime,sale_type,fid_count,sale_fid`）cmd=`sellAllFlowers`
  - 卖道具 `{ type, count }` cmd=`SellProps`
  - 响应：`{ result, resultstr, errno, rosemoneyleft, rosemoneyadd, gamebeanadd, addon, position,
    donnerAdded, extramoney, addvegetablefruit<N>, addprop<N> }`
- **`rosary0903_open_chip`** — 开碎片/礼包（OpenGift）：`{ chiptype }` cmd=`OpenGift`
  → `{ result, chipgrade, chipnumberleft, currentaward, currentawardcount }`
- **`rosary0903_exchange_crowry`** — 兑换玫瑰种子（ExchangeRoseSeed）：`{ materialtype, materialCnt }`
  cmd=`ExchangeRoseSeed` → `{ result, resultstr }`

### 3.7 好友赠礼（bundle: FriendGift，命令 `rosary0903_send`）

- 送花盆（Huapen）：`{ frienduin:<加密QQ>, rosetype, sendcount, needEncrypt:1 }` cmd=`FriendGiftSendHuapen`
- 送玫瑰（Rose）：`{ frienduin:<加密QQ>, rosetype, sendcount, position, needEncrypt:1 }` cmd=`FriendGiftSendRose`
- 送羽毛（Yumao，走 `rosary_activity_oper`）：`{ cmd:176, request:2, friendUin, count, featherid }`
  cmd=`FriendGiftSendYumao`
- **响应**：`{ result, resultstr, useprop{id,count}, sendprop{id,count}, sendcount, sendRoseType,
  getrosejinghua, actiontime, freerosecounttodayleft, charmAddon }`
- 浇花 FriendGardenPour（`rosary0903_send`）：cmd=`FriendGardenPour`

### 3.8 任务（bundle: Task，命令 `rosary_task`）

- 初始化：`{ cgiVersion:43, tasktype:0, index:-1 }`
- 领任务/交任务：`t` cmd=`onTaskGet`（userParams 带 `tp`）
- 响应：`{ result, resultstr, info, user_task, ... }`

### 3.9 其它要点命令

- **`rosary_set_pet_status`**（SetPetStatus）：`{ pt:<宠物id>, st:0|1 }`（下场/上场）
- **`rosary_set_pet_neck`**（SetPetNickName）：`{ nick, petseq }`（userParams `petid`）
- **`rosary_talent_pet_feed`**（PetFeed）：`{ pt, count, mi, benew0908:2, cgiVersion:43 }`
- **`rosary_pets_feed`**（PetRenew）：`{ payway:1, pt, auto_renewal:0|1, month, petseq, carry:0 }`
- **`rosary_detect_user`**（PetScout）：`t` cmd=`SendDogdrivingbell`（探宝/驱铃）
- **`talent_pet_adventure`**（PetExplore）：宠物探险（多分支 cmd）
- **`rosary0903_get_takeon_pets`**（GetPets/GetFriendPetHouseInfo）：
  `{ needEncrypt:1, frienduin, GetPetType:2|3|4, benew0908:3, cgiVersion:43 }`
- **`rosary0912_put`**（PutFlower）：`t` cmd=`putFlower`（userParams `putData`）
- **`rosary_set_title`**（ChangeTitle）：改称号/主题（`titleIndex` / `useTheme`）
- **`rosary0907_maskorunmask`**（NormalGameSetting）：`{ refusetips, maskstranger, maskfriend }`
- **`rosary0912_send_newyearsgift`**（InvitFriendSendGift）：邀请好友送礼
- **`rosary_get_friends_info`**（FriendInfo）：`{ cmd:1, seq:0, bFlash:1, type, needEncrypt:1 }`
- **`rosary0904_get_freeseed`**（GetFreeGift）：`{ gifttype:29?|.. , cgiVersion:43, benew0908:1, platform:1 }`
- **`rosary_activity_oper`**（GetDingXiangInfo 入口）：`{ cmd:1001 }`

---

## 4. 私服实现建议（最小可玩）

1. **静态托管**：把 `site/h5/meigui/` 与 baobaocdn 资源本地化托管；客户端 `RosarySeverHost` 指向 localhost。
2. **登录注入**：URL 带上 `?PingPong=<任意非空>&openid=<...>&token=<...>&appid=102072120&session_type=openkey`，
   即可让客户端为所有命令注入登录态（否则请求体缺 openid/token）。
3. **init 响应**：`rosary0909_get_init_first_self` 必须返回 `grayCgiList:[]`、`actCmdList:[]`
   （避免灰度 `_go` 路由），并带 `svrtime` 与客户端需要的 `GameSettings`。
4. **响应信封**：所有命令返回 `{"result":0, "resultstr":"", ...}`；`result:0` 即成功。
5. **命令分派**：按 §2 表把 URL → 功能；同一 URL 多用途（`rosary0904_expand`/`rosary_activity_oper`/
   `rosary0907_sale_vegetable`/`rosary0903_send`）按请求体的 `cmd`/`request`/`type`/`action`/`actionop` 分支。
6. **好友 QQ 加密**：`frienduin`/`catchFrienduin` 需按客户端 `needEncrypt` 逻辑加密（客户端加密，
   服务端解密；私服可直接返回自己发出的原值做映射）。

---

## 5. 遗留 / 待办（交规划者）

- `frienduin` 的加密算法（客户端 `needEncrypt` 路径）未逆向，影响偷花/赠礼/好友庭院——需要单独一条意图。
- `rosary0904_expand`、`rosary_activity_oper` 的**完整 cmd 号段枚举**（尤其活动 `cmd` 号）跨多 bundle，
  本表已覆盖主要项；剩余零星分支在 `appendix.md` / `activity_oper.txt` 中列出。
- `svrData / GameSettings / potAttributeData` 等大结构字段的**精确 schema** 仍依赖 init 响应，
  建议在私服联调时从真实响应补齐。
- `PetExplore = talent_pet_adventure` 在提取时未取到其 key（bundle 内直接内联字符串 URL），
  可留意 `PetExploreMap` bundle。
