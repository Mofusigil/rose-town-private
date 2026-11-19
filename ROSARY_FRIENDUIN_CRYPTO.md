# 玫瑰小镇 frienduin / catchFrienduin 加密算法还原 (intent 106)

## 结论一句话
客户端 `rose_town` 的好友 uin 在 `needEncrypt=1` 时用
`Rose.Models.UserDataUitls.EncryptUin(uin)` 加密后作为 `frienduin`/`catchFrienduin`
（十六进制串）POST；算法 = **修改版 TEA (16 轮, delta=0x9E3779B9) + 自定义 CBC/PCBC 混合模式**，
固定 16 字节密钥 `rosa1094megigahe`。私服用 `DecryptUin(hex)` 即可还原明文 QQ 号（uint32）。

## 1. 定位
- 文件：`site/h5/meigui/assets/main/index.57d00.js`（模块名 `UserData`，cc._RF 名 "UserData"）
- 可读版：`site/h5/meigui/_src_readable/main.index.beautified.js` 第 35454 / 35461 行
- 定义：`o.UserDataUitls.EncryptUin` / `o.UserDataUitls.DecryptUin`
- 便捷 getter：`FriendHomeData.encryptUin` = `UserDataUitls.EncryptUin(this.uin)`（uin 为好友明文 QQ）

## 2. 算法拆解
### 2.1 密钥 (16 bytes)
`EncryptUin` 里以 4 个 uint32 大端写入密钥缓冲：
```
1919906661 825438516 1835626089 1734438245
 = 0x726F7361 0x31303934 0x6D656769 0x67616865
 = ASCII "rosa" "1094" "megi" "gahe"   -> 密钥字符串 "rosa1094megigahe"
```
### 2.2 分组密码：修改版 TEA（function u / c）
- 8 字节分组，两 word v0/v1，key = k[0..3]（大端读入）。
- delta = 2654435769 = 0x9E3779B9，**仅 16 轮**（标准 TEA 为 32 轮）。
- 加密 (u)：`sum=0`；每轮 `sum+=delta; v0+=((v1<<4)+k0)^(v1+sum)^((v1>>5)+k1); v1+=((v0<<4)+k2)^(v0+sum)^((v0>>5)+k3)`。
- 解密 (c)：`sum=16*delta mod 2^32 = 3816266640`；每轮 `v1-=((v0<<4)+k2)^(v0+sum)^((v0>>5)+k3); v0-=((v1<<4)+k0)^(v1+sum)^((v1>>5)+k1); sum-=delta`。
- 所有运算按 uint32 取模（JS 用 ByteBuffer 每轮回写实现回绕）。
### 2.3 外层模式（function t 加密 / r 解密）
字节流构造（明文 n=4）：
```
[ h0=(rand&0xF8)|a , a 个随机字节, 2 个随机字节, n 个明文字节, 若干 0 填充 ]
  a = (n+1+2+7)%8; a>0 时 a=8-a     # n=4 -> a=2
```
- 伪 CBC 链：`y` = 上一输出块(初值 8 个 0)，`c` = 掩码寄存器(初值 8 个 0)。
- 每块：`X = P ^ y; E = TEA_enc(X); out = E ^ c; c = X; y = out; 输出 out`。
- 填充长度藏在首字节低 3 位（`h0 & 7`）；解密据此推算明文长度 `r = len - 1 - (h0&7) - 2 - 7`。
- 4 字节明文 → 恒定 16 字节密文（=2 个 8 字节块）→ 32 个 hex 字符。
- 因为首块含随机字节，**同一 uin 每次加密结果不同**（随机化），但都可被解开。
### 2.4 编码
- `EncryptUin` 返回 **小写十六进制字符串**（`s(buf,0,len,false,false)`）。
- `DecryptUin` 的 hex 解析会 `toUpperCase()`，**大小写不敏感**，允许空白。
- `DecryptUin` 恢复值为 uint32（QQ 号范围），本身即为明文 QQ。

## 3. 客户端调用点（needEncrypt=1 都会先 EncryptUin）
| 玩法 | 文件 | 关键参数 |
|---|---|---|
| 偷好友花 `rosary0904_steal` | Plantation/index.ff6cb.js | `{soilno, needEncrypt:1, frienduin:_friendUin}` |
| 抓蝶 `rosary0904_gain` | Plantation/index.ff6cb.js | `{soilno, catch:1, catchFrienduin:_friendUin}` |
| 好友赠礼 `rosary0903_send` | FriendGift/index.2c45b.js | `{frienduin:EncryptUin(n), rosetype, sendcount, position, needEncrypt:1}` |
| 好友庭院 `rosary0903_get_takeon_pets` | PetHouseMap/index.c997b.js, FriendHome/index.d8a08.js | `{needEncrypt:1, frienduin:EncryptUin(uin), GetPetType}`, `GetFriendPetHouseInfo` |
| 好友家园初始化 `InitSecond`/`GetFriendInfo` | FriendHome/index.d8a08.js | `{frienduin:EncryptUin(uin), selforfriend:1, needEncrypt:1}` |
| 送魅力花 `rosary0903_sale`(BuyGmaePropsOther) | Shop/index.b24c8.js | `{buycount:1, frienduin:EncryptUin(s), buytype:41, needEncrypt:1}` |
| 好友列表批量 | Friend/index.4b648.js | `t["uin"+(i+1)] = EncryptUin(uin)` |
其中 `_friendUin = FriendHomeData.encryptUin`（getter 内部调用 EncryptUin）。

**反向也用到**：服务端在好友列表等响应里下发的是密文 `uin` 字段，
客户端用 `DecryptUin(y[0])` 解析（main.index.beautified.js 14931、34743 行）
——所以私服**既要能 DecryptUin(请求)，也要能 EncryptUin(响应)**。

## 4. 私服使用
可直接 `import rose_uin_crypto as c`：
```python
c.DecryptUin("d6ddd2fadd5b56733e0bc0f67caa4afd")   # -> 明文 QQ(int)
c.EncryptUin(123456789)                            # -> 32 hex 串 (随机化)
```
`needEncrypt=1` 且 `frienduin` 为非 `0` 的 32-hex 串时调用 DecryptUin 还原；
`frienduin=0` 表示自己/非好友（保持原样）。对非 32-hex 的输入按原文或 0 处理。

## 5. 验证
- Node 直跑客户端原始函数：uin 0/1/42/10001/123456789/2147483647/4000000000 全部 round-trip OK。
- 交叉验证：Python `DecryptUin` 解开 Node 产出的 9 组密文（含 4294967295）全部 = 原 uin；
  反向 Node `DecryptUin` 解开 Python 产出密文亦全部 OK → 双向等价。
