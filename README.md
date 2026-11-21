# UniXNU-munch

Redmi K40S / POCO F4（`munch`，SM8250-AC）的 UniXNU 设备仓库，目标 **iOS 16.7.16（20H392，
iPhone X / D22AP 身份）**，UEFI 为 **edk2-msm**，payload 为 **ESP/FAT32 分区**。

## 文件

| 路径 | 用途 |
| --- | --- |
| `board.toml` | board/SoC/profile、组件、userdata 几何、固件路径、payload/ADT 身份 |
| `feeds.toml` | SM8250 common 与 UFS 驱动的固定 commit |
| `configs/munch_defconfig` | munch 的 XNU 配置（UFS、GOP 显示、触摸、USB 调试等） |
| `dts/munch.dts` | 板级设备树（内存、CPU、UFS、触摸、保留区） |
| `os-profiles/ios-16.7.16-20H392/` | iOS 16.7.16 profile（上游没有，随仓库携带） |
| `scripts/make-munch-adt.py` | 生成 `kernel.macho.adt`（SM8250 GIC/UFS/GPU + iPhone X 身份） |
| `scripts/build-payload.sh` | 组装 ESP 目录并调用 FAT32 生成器 |
| `scripts/make_fat32.py` | 无 mtools 依赖的 FAT32 镜像写入器 |
| `scripts/package_bootimg.py` | Android boot header v3 打包（munch stock ABL 要求 v3） |
| `scripts/install-os-profile.sh` | 把本仓库的 iOS 16 profile 链接进 UniXNU checkout |
| `scripts/check-munch.py` | 构建前检查（复用 iPadOS 17 移植的检查，按 iOS 16 调整） |
| `package/`、`kits/` | 板级驱动/探针（来自现有 munch 移植，需按 iOS 16 ABI 复核） |
| `porting.toml` | 移植记录（按子系统记录输入、实现、证据与限制） |

## 与上游 UniXNU 的关系

UniXNU 上游的固件与打包层假设 Mu-Silicium：

- `./unixnu build firmware` 读取 `Resources/Configs/<device>.toml`，调用 `mkbootimg.py`，
  编译 `BootShim/BootShim.S`；
- payload 发现依赖 Mu-Silicium SEC 写入的 FDT HOB（`DAEE82E6-8090-4E72-BFB9-78C13CD4E359`），
  由 `UniXNURamDiskDxe` 发布块设备；
- OS profile 只有 iPadOS 17（arm64）与 iPadOS 26/27、macOS 27（arm64e）。

本仓库保留 format-2 的 `board.toml`/`porting.toml` 作为配置与记录，但实际构建走：

- `uefi/edk2-msm-munch` 的 DSC/FDF（已加入 `UniXNU.inf`、`UniXNUDxe.inf`、`DarwinBoot.inf`）；
- 真实 ESP 分区，`UniXNU.efi` 通过 SimpleFileSystem 扫描 `\EFI\UniXNU\unixnu.toml`；
- ios-sweet 的 xnu-8796.141.3 内核与补丁集，ADT 由 `make-munch-adt.py` 生成。

详见仓库根目录的 `docs/PORTING-NOTES.md`。

## 构建

```sh
# 在仓库根目录
./scripts/bootstrap.sh
./scripts/build-uefi.sh

# 内核在 macOS 上构建（docs/BUILD.md），然后：
KERNEL=... ADT=... TRUST=... ./UniXNU-munch/scripts/build-payload.sh
```

## 硬件值来源

`dts/munch.dts` 与 `configs/munch_defconfig` 来自现有 munch 移植（WuBarlynn/unixnu-munch，
BSD-2-Clause），其硬件值与 alioth（Redmi K40 / POCO F3）一致：

| 项目 | 值 |
| --- | --- |
| SoC | SM8250-AC（kona），4×A55 + 4×A77 |
| 内存 | 6/8/12 GiB，起始 `0x80000000` |
| 显示 | 1080×2400 AMOLED，cont_splash `0x9c000000` / `0x2300000` |
| 存储 | UFS 3.1，host `0x1d84000`，PHY `0x1d87000` |
| 触摸 | FocalTech，GENI SE4，6 MHz，reset GPIO 33，IRQ GPIO 39 |
| 按键 | PM8150：power / volume up / volume down |

## 状态

设备配置与打包工具已就绪；UEFI 已在本工作区构建通过（FD 7 MiB）；真机启动未验证。
逐项状态见 `porting.toml` 与根目录 `docs/LIMITATIONS.md`。
