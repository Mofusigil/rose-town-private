# 玫瑰小镇 H5 镜像完整性复查

复查日期：2026-10-23。镜像目录：`site/h5/meigui/`。

## 当前结果

| 类别 | 配置引用 | 已校验 | 缺失 |
|---|---:|---:|---:|
| bundle 配置 | 358 | 358 | 0 |
| import 元数据 | 738 | 738 | 0 |
| 原生资源 | 12,607 | 12,606 | 1 |
| bundle 代码入口 | 358 | 358 | 0 |
| 两个 settings 脚本 | 2 | 2 | 0 |
| 单列外部资源 | 7 | 7 | 0 |

本轮逐字节读取约 2.79 GB 本地镜像，并生成 SHA-256 基线；没有重下载整个镜像。
缺失项仍存在，不能将镜像称为 100% 完整。旧报告的 357 个代码入口漏计了 act main，
正确数量为 358。

## 已修复的遗漏

旧脚本尝试了常见扩展名，遗漏了 import 元数据中的 `.py` 和 `.bytes`。
本次从 act/main CDN 路径补回：

| bundle | 资源 | 大小 |
|---|---|---:|
| Act_2609ShuangHuiYingChangAn | `c686e4cc-29b1-4156-b3bb-2b482daf847b.cae22.py` | 7,778 B |
| 2201HappyDumplingsRes | `6da83eaa-2f9a-463a-afe9-d3fde2df63f7.48040.bytes` | 43,557 B |

资源按原始字节保存，没有执行其中的内容。下载 URL、HTTP 200 与 SHA-256 记录在
[mirror-repair.json](verification/mirror-repair.json)。本地网关现在也支持这些扩展名，
rose 资源路径 404 时会补查 act/main 对应路径。

`img/mark_bg.jpg` 实际是完整 PNG；校验器按文件签名核对结束标记，避免把合法背景图
误判为损坏。旧的初次扫描输出保留在 `verification/mirror-before-repair.json`，其中这条
“JPEG 损坏”是修正前校验逻辑的误判。

## 剩余缺失

`assets/Flowers/native/94/94af83ad-ee00-4de8-b4d4-91493f084ca1.b472a.bin`
是配置引用的 `cc.BufferAsset`。按实际 `.bin` 扩展名复查 rose 和 act/main 两条源站路径，
均返回 HTTP 404。此结论只覆盖报告中列出的两条地址，不代表其他历史版本或存储位置不存在副本。
未用占位内容伪造该资源。

## 可复现检查

```bash
python3 tools/verify_mirror.py
python3 tools/verify_mirror.py --probe-missing --manifest verification/mirror-sha256.json
python3 tools/verify_mirror.py --strict  # 将已知缺失也作为非零退出
```

脚本只读取本地内容；`--probe-missing` 仅探测当前缺失原生资源的准确 URL，不落盘下载。
它从两个 settings 的 bundleVers、各 config 的 versions/packs/uuids 和编译 import 元数据
解析实际路径，不执行镜像 JavaScript。当前报告见 [mirror-audit.json](verification/mirror-audit.json)，
全文件摘要见 [mirror-sha256.json](verification/mirror-sha256.json)。

图片检查覆盖文件头与结束标记，不等于逐像素完整解码；不透明二进制资源只做本地摘要，
不声称语义正确。上游没有发布权威哈希清单，所以 SHA-256 用于后续本地比对，不能证明与
源站未公开的原始版本完全一致。运行期任意动态资源名也不在静态枚举的完整性承诺内。

REA 的 lib 静态分析保留了 Evidence
`ev_d588dbece7e28e0e85b6351228cbac63ea6e1298a858e97fbd2b1cc34ba2dae5`；
压缩引擎与部分脚本达到分析资源限制，覆盖为 partial。路径规则同时通过直接读取引擎
与实际 import 元数据核对，不能从 REA 的部分分析推断完整代码覆盖。
