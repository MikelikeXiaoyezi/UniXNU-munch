# 用 GitHub Actions 构建 iOS 16 内核

XNU 必须在 macOS 上构建。本工程提供一个 macOS workflow，不需要本地 Mac。

## 1. 推送仓库

`UniXNU-munch` 是一个独立设备仓库。把它推到 GitHub（公开或私有均可），
workflow 位于：

```text
UniXNU-munch/.github/workflows/build-xnu-ios16.yml
```

在仓库的 **Actions** 页面启用 workflow。

## 2. 运行 `build-xnu-ios16`

`Run workflow` 时可填：

| 输入 | 默认 | 说明 |
| --- | --- | --- |
| `kernel_config` | `DEVELOPMENT` | `DEVELOPMENT` 保留符号，适合 bring-up；`RELEASE` 更小 |
| `unique_chip_id` | `0x1234567890abcdef` | ADT 的 `/chosen/unique-chip-id`；真机建议从设备读取 |
| `root_volume_uuid` | 空 | OS APFS 卷 UUID；userdata 生成后再填 |

workflow 会：

1. 取 `dipa-studio/ios-sweet` 的固定 commit（`45263be`）；
2. 取 `blacktop/darwin-xnu-build` 的固定 commit（`6639065`）；
3. 把 `ios-sweet/xnu/patches` 复制进去；
4. 用 `MACOS_VERSION=13.5`（xnu-8796）、`MACHINE_CONFIG=SWEET` 构建；
5. 上传两个 artifact：
   - `xnu-kernel`：`kernel.development.*` 等；
   - `munch-adt`：`kernel.macho.adt`。

> **重要：** 当前补丁集来自 **sweet（SM7150）**，不是 munch。它能产出 xnu-8796 内核，
> 但 munch 的 UFS、显示、触摸、DWC3 地址尚未适配。预期能到达内核入口/早期日志，
> **不是完整的 iOS 启动**。munch 板级补丁应放在 `xnu/patches-munch/`，workflow 会自动
> 在 `ios-sweet` 补丁之后复制它们。

## 3. 下载并组装

从 Actions run 下载 artifact：

```sh
gh run download -R <you>/UniXNU-munch -n xnu-kernel -D build/ios16.7.16/xnu
gh run download -R <you>/UniXNU-munch -n munch-adt  -D build/ios16.7.16/xnu
```

kernel 文件名可能是 `kernel.development.vmapple` 或 `kernel.development.sweet`；
DarwinBoot 只要求它是 Mach-O，所以直接使用该文件：

```sh
KERNEL=build/ios16.7.16/xnu/kernel.development.*
ADT=build/ios16.7.16/xnu/kernel.macho.adt
./UniXNU-munch/scripts/build-payload.sh
```

脚本默认使用已生成的 trust cache：

```text
build/ios16.7.16/kernel.macho.trustcache
```

它会生成 `build/payload/volume/` 和 `build/munch-esp.img`（FAT32，`MUNCHESP`）。

## 4. 写 ESP 并启动

见 `docs/BRINGUP.md`。简要顺序：

1. 把 `build/munch-esp.img` 写到设备的 ESP 分区；
2. UEFI 已在 `boot_b`（UniXNU 界面已经出现）；
3. 重启进入 UniXNU，菜单应出现 `iOS 16.7.16 (munch)`；
4. 选择后 DarwinBoot 校验 kernel/ADT/trust cache 并进入内核。

## 5. munch 板级适配清单

要在 munch 上走到 iOS 用户态，至少需要把 sweet 的板级假设改成：

| 子系统 | sweet（SM7150） | munch（SM8250-AC） |
| --- | --- | --- |
| UFS | `0x1d84000`（相同） | `0x1d84000`，PHY `0x1d87000` |
| GIC | `0x17a00000` / `0x17a60000`（相同） | 相同 |
| 显示 | cont_splash `0x9c000000` | 相同，1080×2400 |
| 触摸 | Goodix GT9896，GENI SE7 | FocalTech，GENI SE4，reset GPIO 33，IRQ GPIO 39 |
| USB | DWC3 `0xa600000` | 相同控制器，但 PHY/时钟配置不同 |
| CPU | 2×A76 + 6×A55 | 4×A77 + 4×A55 |
| GPU | Adreno 618 | Adreno 650 |

CPU 拓扑差异会直接影响 `cpu_data`/SMP 补丁；触摸和 GPU 是后续 bring-up 项。
先把内核入口、GIC、timer、UART/framebuffer 控制台跑通，再逐项替换驱动。
