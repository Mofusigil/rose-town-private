# 项目检查与修复记录

日期：2026-10-23。范围：本地服务、存档边界、资源加载、期限状态、客户端初始化、宝宝与炼盆玩法、镜像完整性和启动脚本。

## 本轮已解决

| 问题 | 修复与验证 |
|---|---|
| 静态文本请求和 CDN 缓存路径可越过镜像目录 | 解码后检查路径，拒绝目录穿越、控制字符与指向镜像外的符号链接；GET、HEAD 和缓存写入均覆盖 |
| 首次补取 CDN 脚本仍包含远程游戏接口 | 首次响应与缓存命中共用改写流程；缓存保留原始内容，写入采用原子替换；写盘失败仍可返回改写结果 |
| 首页必须手动拼接登录 URL | `/` 和 `/index.html` 自动补齐本地登录参数，保留已有查询参数；活动子目录首页继续正常加载 |
| HTTP 异常请求可能断连、阻塞或误调用接口 | 限制请求体大小、校验长度和编码、设置读取超时、精确匹配 CGI 路由；HEAD 不执行业务操作 |
| 任意网页可触发单人存档操作 | 默认仅监听 127.0.0.1；拒绝跨源浏览器网关请求，CORS 仅返回同源许可；日志隐藏登录凭据，恢复 CDN TLS 证书校验 |
| 装饰和宠物订单在参数错误后留下状态修改 | 所有新增校验在修改状态前完成；充值数量拒绝小数、布尔值和非有限数值 |
| 过期装饰仍能装备、仍出现在花盆上 | 装备和展示共用有效期判断；续期可恢复原装备，永久装饰不会被降为限时 |
| 宠物剩余天数停留在购买时的值 | 初始化按当前时间重算，过期归零，读取不修改存档 |
| 游戏时间依赖服务器系统时区 | 协议日期统一使用北京时间，与日礼包规则一致 |
| 写入失败后遗留临时文件、并发读取状态不一致 | 存档与缓存使用独立临时文件、同步写入并原子替换，失败清理；游戏初始化和购买共用状态锁 |
| 启动脚本将其他程序误当成游戏服务 | 新增 `/healthz`；识别端口冲突和服务就绪；复用服务时正常退出；后台运行忽略挂断，前台退出清理自建服务 |
| 相对存档路径可能在启动后改变位置 | 服务不再改变工作目录，加载与保存使用同一个相对路径基准 |

## 验证方式

```bash
python3 -m unittest discover -s tests -v
node tests/shop_client.cjs
node tests/payments_client.cjs
bash -n start_rose.sh
python3 -m py_compile private_server.py premium_activities.py
```

新增 HTTP 和启动脚本测试使用临时目录、回环地址及临时端口。存档失败测试实际模拟
`os.replace` 失败，核对磁盘原文件、内存回滚和临时文件清理。
最终结果：63 项 Python 测试、两组 Node 客户端检查和 36 个补丁包语法检查全部通过；
Shell 与 Python 语法检查通过。另单独复验了相对存档路径下的真实启动、充值写盘和退出清理。

浏览器验证使用独立的 `/tmp/rose-audit-browser-player.json`，从不带登录参数的首页进入，
确认自动补齐 URL、显示新手介绍，并进入花园及新手指引。默认玩家存档和原验证存档
均通过 SHA-256 对比确认未改变。
界面截图见 [project-audit-garden.jpg](verification/project-audit-garden.jpg)。

## 续查与修复（2026-10-23）

| 问题 | 修复与验证 |
|---|---|
| 进入花园时 FairyGUI `createObject` 异常 | 调用栈实际指向 `BottomNavigation`；第二段初始化缺少 `usePersonalTheme`，将客户端默认 0 覆盖为 undefined，随后错误请求 `roseLifeFrame_undefined`。服务端补齐当前主题，客户端对缺值和非法值回退默认导航；有效主题保持原资源路径 |
| 花盆配置 NaN 警告及装备后解析异常 | `onInitFlowerPotProps` 用子串匹配，把 `fpot` 等容器当成花盆编号。改为只接受 `pot` 加数字的字段；装备槽位改为客户端认可的标量字段，真正未知的数字编号仍报告 |
| 宝宝续费和奖励已入存档，但界面未显示 | 实际客户端读取 `TakeonPetInfo`、`TPetInfo0..5`，原实现只提供 `pets` 数组。补齐命名字段、传统宝宝奖励实例、改名、上下场、三类喂食和普通宝宝续期。旧奖励计数按存档时间一次性迁移，防止刷新反复续期；无定制外观的天赋宝宝使用已有默认资源，生日显示为北京时间日期 |
| 聚灵熔炼只购买灵石，不消耗材料或提升属性；仓库炼制按钮未启动模块 | 实现 cmd=192 的材料熔炼，读取真实材料经验与金币费用，保存四项属性并在初始化恢复；校验不足、重复、已装备材料、属性上限和跨等级灵石费用。客户端预览与服务器费用一致，属性影响实际生长与收获；仓库先启动熔炼模块再派发操作 |
| 仙藤盆炼制请求返回空成功 | 实现等级炼制、属性炼制、重置预览、保存和放弃；初始化提供 `hanglevel`、`hangpercent`、`need`、`attrneed`、`hpattribute`。灵石、灵玉和金币实际扣除，失败与保存回滚有测试 |
| 未实现活动仍返回本地成功凭据 | 改为 `result=2` 和明确的未执行提示，不保存虚假购买次数。后台花单初始化探测不再弹窗打断登录，用户主动打开时仍能看到未实现提示；宝石等未实现子操作同样拒绝 |
| 镜像完整性结论依赖失踪的旧脚本 | 新增 `tools/verify_mirror.py`，按实际 import 元数据解析 `.bin`、`.py`、`.bytes` 和纹理扩展名，并读取全镜像生成 SHA-256 清单。找回两份原生资源；背景图的 `.jpg` 文件实为完整 PNG，按内容格式校验 |
| 缺资源反代遗漏活动工程和罕见扩展名 | 加入 `.py`、`.bytes` 原生资源；rose 路径 404 时补查 act/main 对应路径，落盘缓存保留原始字节；不执行下载内容 |

### 明确的本地规则

- 聚灵属性每 100 经验升一级；上限按客户端为加速 10%、增产 15%、魅力和经验各 20%。
  材料经验、金币费用、灵石起用等级取自 `SmeltPotConfig.xml`。
- 仙藤盆每成功一次增加 1 点炼制进度，100 点升级；每次使用 1 枚选定灵石和
  `1000 × (当前等级 + 1)` 金币。属性炼制消耗 1 枚灵石、1 枚对应灵玉，成功增加
  1% 属性，轮换选择属性。成功率表和总属性上限来自 `refineConfig.xml`。
  成功判定采用可复现的本地轮换，重置只改变分配、保留总属性；这些不是原服随机算法与费用。
- 两类规则在响应中分别标为 `local_smelt_rule`、`local_fairy_rule`，不据此宣称恢复原服平衡。

### 续查验证

```bash
python3 -m unittest discover -s tests -v
node tests/shop_client.cjs
node tests/payments_client.cjs
node tests/runtime_client.cjs
python3 patch_runtime_bundles.py
python3 tools/verify_mirror.py --probe-missing --manifest verification/mirror-sha256.json
bash -n start_rose.sh
python3 -m py_compile private_server.py premium_activities.py gameplay.py tools/verify_mirror.py
```

最终结果：91 项 Python 测试、三组 Node 客户端回归、36 个支付补丁包语法检查、
Shell 与 Python 语法检查全部通过。运行时回归还实际加载了本轮修改的两个 main、
SmeltPot、FlowerOrder 和 Warehouse 模块。

客户端补丁支持重复应用，对意外的上游版本变化明确报错。新增测试执行实际打包模块，
覆盖主题回退、花盆字段、生长时间拷贝、灵石费用预览和后台探测提示边界。
Python 测试覆盖宝宝奖励迁移与养成、两类炼盆、预览提交、实际收获加成、并发扣料、
真实文件替换失败回滚及活动 CDN 回退。镜像报告见
[mirror-audit.json](verification/mirror-audit.json)，补回资源的来源和哈希见
[mirror-repair.json](verification/mirror-repair.json)。

浏览器使用 `/tmp/rose-audit-followup-player.json` 和 8091 端口。验证存档预置金币和材料，
随后通过真实接口领取宝宝、购买花盆，完成实际喂养与熔炼：进化草 5→4、宝宝进化度
0→1；20 份砂砾消耗完，金币 10,000,000→9,360,000，加速属性 0→2%。
重启服务后接口与磁盘核对继续保留这些结果，见
[followup-persistence.json](verification/followup-persistence.json)。场景验证窗口内没有新的 JS error，
也没有花盆 NaN 警告；仍有既存 WebGL NPOT 纹理提示和无在线活动时的 JuBao 提示。
截图见 [花园](verification/followup-garden.png)、[喂养成功](verification/followup-baby-feed.png)、
[熔炼完成](verification/followup-smelt.png)，控制台摘要见
[followup-browser.json](verification/followup-browser.json)。仙藤炼制流程由协议回归覆盖，
没有将其描述成完整浏览器操作验证。

默认存档与原验证存档的 SHA-256 与修改前一致：

- `local_player_state.json`：`16b80a69998742b459c013d2887ef6403986ddb6a3eafa2851977a949181f2c9`
- `local_player_state.validation.json`：`bbff6b499567b48687cd63fb8e44dd1c86569e834b83e4618911072ec52817e5`

## 仍有的边界

- 原服远程动态概率、部分奖励与升级曲线无法从现有客户端完整恢复；已实现的本地规则
  如上标明。宝石镶嵌与合成、宝宝探险、花单以及其他未实现活动返回明确失败，仍需逐项实现。
- 完整镜像检查覆盖 358 个配置、738 个 import、358 个脚本入口、12,607 个原生资源引用。
  其中 12,606 个原生资源可校验；Flowers 的一份 `.bin` 在两处 CDN 路径仍为 404，
  不把整个镜像标为 100% 完整。SHA-256 是本地基线，上游未提供权威摘要清单。
- 服务仍使用单人本地存档，不提供多用户鉴权；显式设置 `ROSE_HOST=0.0.0.0` 才开启局域网监听。

当前工作区的 `.git` 是不可用的占位目录，无法获得 Git diff 或创建提交；改动保留在工作区文件中。

## 逆向证据边界

- 聚灵客户端静态证据：`ev_0386f5a512acf140eebd71d757a4cc10add650cf3a2f60a334489c62e6879f57`。
- Plantation 静态分析在 30 秒达到限制，保留父证据
  `ev_5b82d266845b6a57323bb6e8d21902016bbd62306704fec81f7d21c9c10fc23f`，
  摘要视图 `ev_1ebde4dce342076fe55f8dac09975a6358146e3c6d89c55efafd5953f0500903`。
  覆盖是 partial，不能据此宣称完整语义覆盖。
- 本轮结论同时核对实际 bundle 方法、XML、真实本地 HTTP 请求、独立存档和浏览器画面；
  静态推断、本地运行验证与原服行为的未知部分分别记录。
