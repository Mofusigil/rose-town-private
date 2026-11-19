# 玫瑰小镇 本地私服 (Rose Town Local Private Server)

在本地把 `https://meigui.qq.com/?from=platform` 的 H5 版玫瑰小镇完整跑起来：
一个 HTTP 服务同时 **托管本地镜像的客户端** 和 **模拟游戏后端网关**，客户端加载后可
登录并进入主场景（Garden）。已实现的本地付费入口直接成功：点券商品不检查或扣除点券，
支付确认自动通过，充值入口在本地发放点券。种子、道具、装饰、VIP、阳光卡和宠物
续费状态保存在 `local_player_state.json`，刷新页面和重启服务后继续保留。

## 一键启动

```bash
cd /home/asriel/Projects/rose_town
./start_rose.sh                      # 启动并打开游戏，Ctrl-C 关闭本次启动的服务
# 或 python3 private_server.py       # 默认监听 127.0.0.1:8088
```

浏览器直接打开 `http://127.0.0.1:8088/` 即可，服务会自动补齐本地登录参数。
已有的完整登录链接仍然有效：

```
http://localhost:8088/index.html?open=portal&PingPong=448984620&openid=AADAD8430DD37E40107C2D2D944712AF&token=localtoken&openkey=localtoken&appid=102072120&session_type=openkey
```

需要 Python 3.9+ 和 Node.js（Node.js 仅用于客户端回归检查），服务端没有额外 pip 依赖。
可用 `ROSE_PORT=9090` 更换端口；需要局域网访问时显式设置 `ROSE_HOST=0.0.0.0`。
这是共享同一存档的单人模拟服务，不提供多用户鉴权。

`./start_rose.sh --server-only --no-wait` 可以后台启动；脚本会输出服务 PID。
再次启动时通过 `/healthz` 识别已有游戏服务；遇到其他程序或没有健康接口的旧版服务，
会明确提示端口冲突。复用已有服务时脚本正常退出，不会关闭该服务。
`ROSE_STDOUT_LOG=/tmp/rose-server.log` 可指定启动日志路径。

进入后客户端会依次请求 `rosary0908_get_user_info` → `rosary0909_get_init_first_self`
→ `rosary0907_get_init_second` → `rosary0908_get_plant_info_self`，全部命中本地
mock 网关后切换到 **Garden 主场景**（splash 隐藏、Canvas/GRoot 渲染）。

## 组成

| 文件/目录 | 说明 |
|---|---|
| `private_server.py` | 私服主体：静态托管 + `/cgi-bin/<cmd>` mock 网关 + 缺资源按需反代 CDN |
| `premium_activities.py` | 礼卡、彩蛋、宠物PK等活动的本地业务响应 |
| `gameplay.py` | 宝宝领取与养成、聚灵熔炼、仙藤盆等级与属性炼制 |
| `tools/verify_mirror.py` | 按实际资源元数据检查完整性、生成 SHA-256 基线 |
| `site/h5/meigui/lib/local-payments.js` | 本地支付确认、余额检查、付费上下文和充值 |
| `site/h5/meigui/` | 客户端镜像（自 baobaocdn `cdn/h5/meigui/rose/` 还原，保持原目录结构） |
| `private_server.log` | 每次 CGI 请求记录（命令 + 表单体） |
| `site/h5/meigui/index.html` | 客户端入口页（原 CDN 版，lib 引用已本地化） |

## 实现要点（还原自逆向结论 fact 96/97/98/99）

1. **协议**：`POST /cgi-bin/<rosary*命令>?gprand=<rand>`，body 为
   `application/x-www-form-urlencoded`（含注入的 `openid/token/openkey/appid/session_type/
   benew0908/ossType/cgiVersion`），响应 `{"result":0,"resultstr":"ok",...}`；
   `_go` 灰度后缀自动归一化。
2. **登录态注入**：客户端 `HttpSettings.pretreatmentRequest` 从 URL/localStorage/cookie 取
   `PingPong/openid/token/...` 注入每个请求；`PingPong` 非空才注入，故 URL 必须带 PingPong。
   服务会在访问 `/` 或 `/index.html` 时补齐缺失参数，保留已有活动入口参数。
3. **域名改写**：服务在 *响应时* 把 `https://cgi.meigui.qq.com/cgi-bin/` 与
   `https://baobaocdn.qq.com/cdn/h5/meigui/` 改写为本地地址，因此即使后台爬虫把镜像里的
   `assets/main/index.57d00.js` 覆盖回原样，路由也始终指向本地（无需长期改文件）。
4. **进入主场景必需的响应字段**：除 `result:0` 外，`rosary0907_get_init_second` /
   `rosary0909_get_init_first_self` 必须带 `prop<startID>` 字段（见 `DECOR_PROPS`，取值来自
   `DecorateCommon`），否则客户端 `parseSpecilProp → updateMaginTreeIdAndTips` 会因
   `getPropsById(undefined)` 崩溃、进而卡在 Preload 场景。
5. **缺资源反代**：图标/音乐/图片等未镜像资源由服务端按需从 `baobaocdn` 拉取并落地缓存，
   同时规避浏览器跨域（同源加载）。首次返回和缓存命中使用相同的本地域名改写，
   缓存原始文件采用原子替换；CDN 连接验证 TLS 证书。
6. **请求与存档边界**：静态请求拒绝目录穿越和指向镜像外的符号链接；网关拒绝跨源浏览器请求，
   POST 请求体最多 1 MiB，非法路由和报文返回明确错误。日志会隐藏登录凭据。
   存档写入失败时回滚内存、保留原文件，并清理临时文件；初始化快照与购买共用状态锁。
7. **期限处理**：过期装饰不能装备，也不继续显示；永久装饰不会被续期改成限时。
   宠物剩余天数按当前时间重算，游戏时间字段统一为北京时间，不受系统时区影响。

## 玩法与边界

- 初始化已补齐个人主题，客户端对缺失主题使用默认导航。花盆库存只解析 `pot` 加数字的字段，
  修复了此前的 FairyGUI `createObject` 异常与花盆配置 NaN 警告。
- 宝宝奖励生成可使用的实例；支持宝宝屋显示、改名、上下场、三类喂养、续费和重新加载。
  旧存档中的宝宝奖励计数会一次性迁移为实例，使用原存档时间确定有效期。
- 聚灵熔炼会消耗真实材料和金币，保存加速、增产、魅力及经验属性；仙藤盆支持等级炼制、
  属性炼制、重置预览、保存和放弃。原服缺失的升级阈值与费用采用明确标注的本地规则，
  详见 [PROJECT_AUDIT.md](PROJECT_AUDIT.md)。
- 宝石镶嵌与合成、宝宝探险、花单和其他尚未实现的活动会明确提示未执行，不再保存虚假成功凭据。
  后台花单初始化探测不会弹窗打断登录，主动打开未实现玩法时显示提示。
- 镜像已重新扫描，补回两份原生资源；剩余一份 Flowers `.bin` 在两处源站路径仍为 404。
  可运行 `python3 tools/verify_mirror.py --probe-missing` 复核。详见
  [MIRROR_COMPLETENESS.md](MIRROR_COMPLETENESS.md)。
- 一朵、九朵、九十九朵、九百九十九朵玫瑰的赠送/获赠魅力来自动态服务端字段
  `valentinesDay2020sndCharm` / `valentinesDay2020rcvCharm`，本地配置没有这些数值；
  未提供时显示“以赠送结果为准”，合法的0和正常花束数值仍如实显示。

## 商店修复与验证

客户端修复同时覆盖商品提示和购买弹窗，并允许行情缺失时打开种子购买弹窗。
运行时补丁同时覆盖 rose 与 act 两个主包，并修复仓库首次打开熔炼模块的流程。
共享数值校验在 `site/h5/meigui/lib/shop-fixes.js`；若重新下载覆盖原CDN bundle，依次运行
`python3 patch_shop_bundles.py`、`python3 patch_payment_bundles.py`、
`python3 patch_runtime_bundles.py` 重应用补丁
（仅支持当前已验证的bundle版本，版本变化会明确报错）。

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/shop_client.cjs
node tests/payments_client.cjs
node tests/runtime_client.cjs
```

Python 回归测试也覆盖静态路径边界、首次 CDN 加载、HTTP 报文校验、跨源请求、
期限推进、真实文件替换失败，以及启动脚本的端口冲突、复用、后台运行和退出清理。
2026-10-23 的检查详情见 [PROJECT_AUDIT.md](PROJECT_AUDIT.md)。

付费行为、覆盖边界和验证记录见 [PAYMENT_CONTENT.md](PAYMENT_CONTENT.md)。
可用 `ROSE_STATE_FILE=/tmp/rose-test-state.json ROSE_PORT=8089 python3 private_server.py`
启动独立测试存档。

本次浏览器验证使用的存档已保存在 `local_player_state.validation.json`；其中保留了
页面上的充值、VIP和购买/领奖记录。可用以下命令继续打开该验证页：

```bash
ROSE_STATE_FILE=local_player_state.validation.json ROSE_PORT=8089 python3 private_server.py
```

将上方登录URL的端口改为8089即可。默认8088服务仍使用原玩家存档。
