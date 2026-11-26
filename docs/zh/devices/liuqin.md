# 小米平板 6 Pro（liuqin）

小米平板 6 Pro（liuqin） 是搭载 SM8475 的设备。下面的移植是独立的社区项目，UniXNU 组织不维护它。

| 仓库 | 维护者 |
| --- | --- |
| [UniXNU-liuqin](https://github.com/1696108518/UniXNU-liuqin) | [1696108518](https://github.com/1696108518) |
| [UniXNU-liuqin](https://github.com/boomoodxf/UniXNU-liuqin) | [boomoodxf](https://github.com/boomoodxf) |

## 状态

仓库包含板级文件、defconfig 和内核 USB 调试口。下一步是 UEFI 集成。

## 维护

维护者拥有仓库和发布决定。UniXNU 文档记录移植及其状态，不接管维护。

## 本地 macOS 调试

本地 macOS 27.3（26C5035r）实验使用
`scripts/liuqin-analysis/r102-gpu/prepare-and-build-gpu.py` 构建，横屏桌面基线为
`797da65`。r103 输入代码加入刘琴的 WN8030 键盘桥、触控板指针报告和 NT36532
触摸屏指针。键盘使用 `0xa94000` 的 QUP1 SE5，触摸屏使用 `0x990000` 的 QUP0
SE4，共享 TLMM 汇总中断。输入构建会检查目标内核的 IOHIDDevice 虚表和指针认证标识。

可选的持久 Data 方案使用 userdata 中已认证根镜像之后的空间，并保留末尾 64 MiB。
首次初始化会回读并验证 APFS 种子；后续启动保留已填充的数据，并通过设备上的任务扩容
APFS 容器。USB 调试保留用于主机验证，内核矩阵和状态绘制已关闭。真机已进入桌面，
用户确认触摸屏可用。APFS 已扩容至 213964931072 字节（199.27 GiB），后续启动复用了
已完成的 Data 存储，扩容结果和初始化标记均保留。签名辅助程序复用修复后的启动已进入桌面，
`USER PREPARE` 和 `ADAPTER PREPARE` 均返回零。但用户反馈该次启动中键盘和触摸屏均无响应，
采集后 USB 调试端口也不可见。单独启用 I2C 主序列器状态生成没有解决超时；
补充 Linux 引擎时钟及输出初始化的后续启动中，用户确认触摸屏恢复，
164 帧成功送达 HID，未出现错误。键盘仍然超时且没有中断，触控板尚未确认。

后续 `--with-input --with-wireless` 构建进一步加入了 GPU Write-Combining、
GPU DCVS 调频、DPU 双缓冲与 120/144/60 Hz 刷新率切换、背光/按键/霍尔保护套支持、
桌面空载 CPU 与发热优化（`no-lc=1`、进程黑名单、`disabled.501.plist`）、
WCN6855 蓝牙（GENI UART20 3.2 Mbps 及 macOS 27.3 `bluetoothd`/`BlueTool`/`QcaBTType0.dylib`）
与 WCN6855 Wi-Fi（SM8475 PCIe0 RC + QMP V6 PHY + 128 MiB Apps SMMU `cb73` + MHI/QMI +
Linux `v7.0.14` `ath11k`/`mac80211`/`cfg80211` + `en0` + `unixnu-wpa_supplicant` + `wpa_cli`）。
在干净采集 `boot-gpu-20261125-012843`（`--stay-up`）中，120 Hz 桌面下蓝牙与 Wi-Fi 同时在线
（蓝牙 3.2 Mbps `BT STAT` 正常收发；Wi-Fi `WIFI_READY` 102 信道、`en0` 挂载、
`unixnu-wpa_supplicant` 连接并完成真机空口扫描，扫到 19 个 AP，`boot-gpu-20261125-012145`
中跨 2.4/5 GHz 扫到 25 个 AP）。WPA2 关联与 DHCP 尚未在真机测试。构建方法和证据路径见
`scripts/liuqin-analysis/r103-storage/README.md`。

## 来源

- [板级配置: 1696108518/UniXNU-liuqin](https://github.com/1696108518/UniXNU-liuqin/blob/907b8e91c88e71f698292abfd8db49ba90492dc4/board.toml)
