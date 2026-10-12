---
title: 经堡垒机（JumpServer）向生产云服务器部署 Superset wheel（实战记录）
sidebar_position: 7
---

<!--
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
-->

# 经堡垒机向生产云服务器部署 Superset wheel（实战记录）

本文记录一次**真实的生产升级**：把包含 8 个新增 ECharts 图表的 Superset fork，从构建机出的 wheel 部署到**只能经 JumpServer 堡垒机跳转**的阿里云生产服务器 `10.100.19.1`（`/mnt/data/superset`）。

配套文档：完整的「构建机出 wheel → 云服务器 pip install」流程见
[production-deployment.zh.md](production-deployment.zh.md)；本文只聚焦**堡垒机环境下的传输与远程执行**，以及两个踩过的坑与稳定做法。

:::warning 凭据安全
本文所有堡垒机 / 服务器密码均以占位符（如 `<JUMP_PASSWORD>`）表示。真实凭据见内部《AGI-服务器与组件连接信息》，**不要**把明文密码写进仓库文档或提交到 git。含密码的临时 `expect` 脚本用完必须删除（本地与构建机 `/tmp` 两侧）。
:::

## 一、环境与目标

| 角色 | 值 | 说明 |
|---|---|---|
| 堡垒机 | `jumpserver.poweroak.ltd:2222` | SSH 登录进交互菜单，`/<IP>` 搜索资产选编号连接 |
| 堡垒机账号 | `<JUMP_USER>` / `<JUMP_PASSWORD>` | 无 MFA |
| 目标机 | `10.100.19.1`（PV-Generation-Forecast-01） | hostname `iZj6cfnk9g4pw5dxgxj1ngZ`，唯一可访问外网的节点 |
| 部署路径 | `/mnt/data/superset` | venv 在 `/mnt/data/superset/venv`，服务 `superset.service` |
| 运维账号 | `cloudapp` | 免密 sudo；集群节点间免密 SSH |
| 构建机 | 独立 Linux（本例 `gt@192.168.56.101`） | 已产出 `apache_superset-6.0.1-py3-none-any.whl` |

**升级性质**：本次是**纯前端改动**（新增图表插件 + 缩略图），无 DB schema 变更，所以升级动作只需
`pip install --force-reinstall --no-deps` + 重启服务，**无需** `superset db upgrade`。

## 二、两个关键的坑（本文核心价值）

### 坑 1：堡垒机菜单分页导致选错资产

`/10.100.19.1` 是**模糊搜索**，实际返回 2 台资产：

```
ID | 名称                              | 地址
 1 | HK:SaaS:AGI-Starrocks-01          | 10.100.19.18   ← 坑
 2 | HK:SaaS:PV-Generation-Forecast-01 | 10.100.19.1    ← 真正目标
```

自动化（`expect`）分配的 pty **终端行数很小**时，JumpServer 会按终端高度分页——出现「总数量 2，总页数 2，**每页行数 1**」，于是：

- **第 1 页只有 ID 1 = StarRocks-01（10.100.19.18）**
- 真正的目标机在**第 2 页**（`下一页：n`）

此时盲选 `2`，`2` 不会选中第 2 行（第 1 页根本没有第 2 行），会被解释成别的上下文，**误连到完全不相关的主机**（本次实测飘到了一台德国节点 `10.83.32.2`）。

**修复**：给 `expect` 的 pty 强制设大终端尺寸，让两行落在同一页：

```tcl
set stty_init "rows 60 cols 220"
```

设大之后，`/10.100.19.1` 一页显示两行，`ID 2` 稳定就是 `10.100.19.1`。**并且**在任何写操作前，务必再用主机身份守卫二次确认（见下）。

### 坑 2：expect 提前匹配到「命令回显里的结束标记」

一个常见但隐蔽的 `expect` bug：如果你发送的远程命令里带有结束哨兵，例如

```tcl
send -- {...; echo __P2END__}
```

终端会把整行命令**回显**回来（含 `echo __P2END__` 这几个字），`expect { -re "__P2END__" }` 会**匹配到回显里的字样**，误以为命令已经执行完，于是提前发送 `exit` / `Ctrl-C`。本次实测因此在**备份刚开始**时就打断了流程，导致首次安装其实**没执行**（幸而两阶段设计使服务毫发无伤）。

**修复**：用**运行时才生成**的哨兵，让命令文本里根本不含最终字样：

```tcl
# 命令里是 echo DEP_$((6*7))_END，bash 运行后才输出 DEP_42_END
send -- {...; echo DEP_$((6*7))_END}
send -- "\r"
expect { -re "DEP_42_END" { } timeout { } }
```

`$((6*7))` 由 bash 计算成 `42`，只有**真正执行到最后**才会打印 `DEP_42_END`，回显里没有这个字样，杜绝提前匹配。

## 三、其他要点

- **中文/换行安全传输脚本**：PowerShell → ssh → bash 多层转义会破坏引号、并把 `\r` 或中文搞乱。稳妥做法是本地把脚本按字节去掉 `0x0D`（对 UTF-8 安全）后 **base64 编码**，传到构建机再 `base64 -d` 还原执行，彻底绕开引号/编码问题。
- **Tcl 花括号包裹远程命令**：`expect` 的 `send -- "..."`（双引号）会把 `$var`、`[cmd]` 当 Tcl 语法解析。发送含 `$(...)`、`${...}`、`$?` 的 bash 命令时，用 `send -- {...}`（花括号）按字面发送，再单独 `send -- "\r"` 发回车。
- **JumpServer SFTP 不适合传大文件**：SFTP 资产树只能浏览目录；实测进入资产后 `put`/`ls` 报 `Connection lost`（这些资产多半只开了 SSH、未开可用 SFTP 后端）。目标机的取文件方式应走「**目标机自身外网下载**」或终端 `rz` 上传。
- **主机身份守卫**：注意 `10.100.19.18` 是 `10.100.19.1` 的前缀，用带**尾随空格**的模式区分：

```bash
H=$(hostname -I)
case "$H" in *"10.100.19.1 "*) echo HOSTGUARD_OK ;; *) echo HOSTGUARD_FAIL ;; esac
```

## 四、稳定的部署流程（两阶段）

> 核心原则：**先只读校验、再写操作**；每次写操作前用 HOSTGUARD 二次确认主机身份。

### 传输 wheel 到目标机

目标机 `10.100.19.1` 可访问外网、可用 `rz`。任选其一：

- **`rz` 上传**（本例采用）：本地先把 wheel 拷到你的 Windows，堡垒机 `/10.100.19.1` → 选 **2** 进入目标机，`cd /mnt/data/superset && rz` 选择文件上传。
- **目标机外网拉取**：把 wheel 上传到内部 OSS / 私有源，目标机 `curl -L -o ... <URL>`。

上传后务必**核对 sha256** 与构建机一致：

```bash
# 构建机
sha256sum /opt/superset-build/dist/apache_superset-*.whl
# 目标机
sha256sum /mnt/data/superset/apache_superset-*.whl
```

### 阶段一：只读校验（不做任何写操作）

进入目标机后校验：主机身份 `hostname -I` 含 `10.100.19.1`、wheel 存在且 sha256 一致、
`/mnt/data/superset/venv` 存在、`superset.service` 状态、当前版本。任一不符立即中止。

### 阶段二：备份 + 安装 + 重启 + 验证

```bash
cd /mnt/data/superset
source venv/bin/activate

# 1. 备份当前已安装的 superset 包（回滚快照）
PKG=$(python -c "import superset,os;print(os.path.dirname(superset.__file__))")
mkdir -p /mnt/data/superset/backup
tar -czf /mnt/data/superset/backup/superset_pkg_$(date +%Y%m%d-%H%M%S).tar.gz \
    -C "$(dirname $PKG)" "$(basename $PKG)"

# 2. 停服务 → 装新 wheel（纯前端改动，--no-deps）→ 启服务
sudo systemctl stop superset
pip install /mnt/data/superset/apache_superset-6.0.1-py3-none-any.whl \
    --force-reinstall --no-deps
sudo systemctl start superset

# 3. 健康检查
systemctl is-active superset
curl -fsS -o /dev/null -w "health=%{http_code}\n" http://127.0.0.1:8088/health   # 期望 200
curl -s   -o /dev/null -w "login=%{http_code}\n"  http://127.0.0.1:8088/login/    # 期望 200

# 4. 验证新图表已进产物（部署后的 static assets 含新 viz key）
grep -rl nested_pie \
    /mnt/data/superset/venv/lib/python3.10/site-packages/superset/static/assets/ \
    >/dev/null 2>&1 && echo CHART_PRESENT || echo CHART_ABSENT
```

本次实测结果：`INSTALL_RC=0`、`is-active=active`、`health=200`、`login=200`、`CHART_PRESENT`，
安装耗时约 35 秒，停机 < 1 分钟。

## 五、回滚

若新版异常，用阶段二生成的快照回滚：

```bash
cd /mnt/data/superset
source venv/bin/activate
PKG=$(python -c "import superset,os;print(os.path.dirname(superset.__file__))")

sudo systemctl stop superset
rm -rf "$PKG"
tar -xzf /mnt/data/superset/backup/superset_pkg_<TS>.tar.gz -C "$(dirname $PKG)"
sudo systemctl start superset
curl -fsS http://127.0.0.1:8088/health
```

> 因为是同版本号（6.0.1）、`--no-deps`、纯前端差异，对后端服务的风险极低；快照回滚即可完全还原。

## 六、可复用的 expect 模板

以下模板综合了两个坑的修复（大终端 + 运行时哨兵 + 花括号 + HOSTGUARD）。真实使用时把 `<JUMP_*>` 换成实际值，**用完即删**。

```tcl
#!/usr/bin/expect -f
set stty_init "rows 60 cols 220"     ;# 坑1修复：大终端避免菜单分页
set timeout 360
log_user 1
spawn ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o PreferredAuthentications=password -o PubkeyAuthentication=no \
    <JUMP_USER>@jumpserver.poweroak.ltd
expect { -re "(?i)password" { send -- "<JUMP_PASSWORD>\r" } timeout { exit 2 } }
expect { -re "Opt>" {} timeout { exit 4 } }
send -- "/10.100.19.1\r"
sleep 6
send -- "2\r"                        ;# 大终端下 ID 2 稳定为 10.100.19.1
sleep 9
# HOSTGUARD：尾随空格区分 .1 与 .18
send -- {H=$(hostname -I); case "$H" in *"10.100.19.1 "*) echo HOSTGUARD_OK ;; *) echo HOSTGUARD_FAIL ;; esac}
send -- "\r"
expect {
    -re "HOSTGUARD_OK" {}
    -re "HOSTGUARD_FAIL" { send -- "exit\r"; expect eof; exit 9 }
    timeout { send -- "exit\r"; exit 8 }
}
# 坑2修复：运行时算术哨兵，命令文本不含 DEP_42_END
send -- {echo DEP_$((6*7))_BEGIN; cd /mnt/data/superset; source venv/bin/activate; sudo systemctl stop superset && echo STOPPED_OK; pip install /mnt/data/superset/apache_superset-6.0.1-py3-none-any.whl --force-reinstall --no-deps; echo INSTALL_RC=$?; sudo systemctl start superset && echo STARTED_OK; sleep 10; echo ISACTIVE=$(systemctl is-active superset); curl -fsS -o /dev/null -w "HEALTH=%{http_code}\n" http://127.0.0.1:8088/health; echo DEP_$((6*7))_END}
send -- "\r"
expect { -re "DEP_42_END" {} timeout { puts "\nTIMEOUT" } }
send -- "exit\r"; sleep 2; send -- "q\r"; sleep 1; send -- "\x03"; send -- "exit\r"
expect eof
```

## 七、教训清单（一句话版）

1. 堡垒机自动化务必 `stty rows` 拉大终端，否则分页会让你选错资产。
2. 结束哨兵用运行时算术生成，避免 expect 匹配到命令回显。
3. 任何写操作前先 HOSTGUARD 校验主机身份（注意 `.1` 与 `.18` 前缀）。
4. 跨 PowerShell/ssh/bash 传脚本用 base64；expect 发 bash 命令用花括号。
5. 先只读校验、再写操作；先备份、再安装；装完立即健康检查 + 产物验证。
6. 含明文密码的临时脚本，两侧用完即删。
