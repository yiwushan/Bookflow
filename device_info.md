# System Configuration Report
# Generated: Sat Apr  4 17:24:40 CST 2026
# Hostname: OnePlus6T

## Operating System
```
PRETTY_NAME="Ubuntu 24.04.4 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.4 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo
```

## Kernel
```
Linux OnePlus6T 6.16.0-rc2-sdm845+ #2 SMP PREEMPT Sat Jan 10 00:19:12 CST 2026 aarch64 aarch64 aarch64 GNU/Linux
```

## CPU Information
```
Architecture:                            aarch64
CPU op-mode(s):                          32-bit, 64-bit
Byte Order:                              Little Endian
CPU(s):                                  8
On-line CPU(s) list:                     0-7
Vendor ID:                               Qualcomm
Model name:                              Kryo-3XX-Gold
Model:                                   13
Thread(s) per core:                      1
Core(s) per socket:                      4
Socket(s):                               1
Stepping:                                0x6
Frequency boost:                         disabled
CPU(s) scaling MHz:                      100%
CPU max MHz:                             2649.6001
CPU min MHz:                             825.6000
BogoMIPS:                                38.40
Flags:                                   fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop
Model name:                              Kryo-3XX-Silver
Model:                                   12
Thread(s) per core:                      1
Core(s) per socket:                      4
Socket(s):                               1
Stepping:                                0x7
CPU(s) scaling MHz:                      100%
CPU max MHz:                             1766.4000
CPU min MHz:                             300.0000
BogoMIPS:                                38.40
Flags:                                   fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp cpuid asimdrdm lrcpc dcpop
NUMA node(s):                            1
NUMA node0 CPU(s):                       0-7
Vulnerability Gather data sampling:      Not affected
Vulnerability Ghostwrite:                Not affected
Vulnerability Indirect target selection: Not affected
Vulnerability Itlb multihit:             Not affected
Vulnerability L1tf:                      Not affected
Vulnerability Mds:                       Not affected
Vulnerability Meltdown:                  Not affected
Vulnerability Mmio stale data:           Not affected
Vulnerability Old microcode:             Not affected
Vulnerability Reg file data sampling:    Not affected
Vulnerability Retbleed:                  Not affected
Vulnerability Spec rstack overflow:      Not affected
Vulnerability Spec store bypass:         Not affected
Vulnerability Spectre v1:                Mitigation; __user pointer sanitization
Vulnerability Spectre v2:                Mitigation; Branch predictor hardening, but not BHB
Vulnerability Srbds:                     Not affected
Vulnerability Tsx async abort:           Not affected
```

## Memory Information
```
               total        used        free      shared  buff/cache   available
Mem:           7.4Gi       2.6Gi       1.8Gi       126Mi       3.3Gi       4.8Gi
Swap:             0B          0B          0B
```

## Disk Information
```
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda17      9.8G  4.1G  5.2G  44% /
tmpfs           3.7G     0  3.7G   0% /dev/shm
tmpfs           1.5G  1.7M  1.5G   1% /run
tmpfs           5.0M     0  5.0M   0% /run/lock
tmpfs           755M  8.0K  755M   1% /run/user/1000
```

## GPU Information (if any)
```
No GPU found
NVIDIA driver not installed or no NVIDIA GPU
```

## Network Configuration
### IP Addresses
```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host noprefixroute 
       valid_lft forever preferred_lft forever
2: usb0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    link/ether c6:60:47:7d:22:e7 brd ff:ff:ff:ff:ff:ff
    inet 172.16.42.1/16 brd 172.16.255.255 scope global usb0
       valid_lft forever preferred_lft forever
    inet6 fe80::c460:47ff:fe7d:22e7/64 scope link 
       valid_lft forever preferred_lft forever
3: rmnet_ipa0: <> mtu 1500 qdisc noop state DOWN group default qlen 1000
    link/[519] 
4: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default qlen 1000
    link/ether 2e:8f:0c:a3:9d:e3 brd ff:ff:ff:ff:ff:ff
    inet 10.16.12.170/17 brd 10.16.127.255 scope global dynamic noprefixroute wlan0
       valid_lft 24391sec preferred_lft 24391sec
    inet6 2001:da8:201d:1107::fa48/128 scope global dynamic noprefixroute 
       valid_lft 28301sec preferred_lft 28301sec
    inet6 fe80::ea6e:1e81:d403:365b/64 scope link noprefixroute 
       valid_lft forever preferred_lft forever
```

### DNS Configuration
```
# This is /run/systemd/resolve/stub-resolv.conf managed by man:systemd-resolved(8).
# Do not edit.
#
# This file might be symlinked as /etc/resolv.conf. If you're looking at
# /etc/resolv.conf and seeing this text, you have followed the symlink.
#
# This is a dynamic resolv.conf file for connecting local clients to the
# internal DNS stub resolver of systemd-resolved. This file lists all
# configured search domains.
#
# Run "resolvectl status" to see details about the uplink DNS servers
# currently in use.
#
# Third party programs should typically not access this file directly, but only
# through the symlink at /etc/resolv.conf. To manage man:resolv.conf(5) in a
# different way, replace this symlink by a static file or a different symlink.
#
# See man:systemd-resolved.service(8) for details about the supported modes of
# operation for /etc/resolv.conf.

nameserver 127.0.0.53
options edns0 trust-ad
search .
```

## Installed Software
### Python
```
Python 3.12.3
```

### Node.js
```
v20.20.2
```

### Docker
```
Not installed
```

### Docker Compose
```
Not installed
```

### GCC/G++
```
gcc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
```

### Go
```
Not installed
```

### Rust
```
Not installed
```

### Java
```
/home/athbe/playground/system-config.sh: line 106: java: command not found
```

## Available Ports
```
Netid State  Recv-Q Send-Q               Local Address:Port  Peer Address:PortProcess
udp   UNCONN 0      0                        127.0.0.1:7891       0.0.0.0:*          
udp   UNCONN 0      0                       127.0.0.54:53         0.0.0.0:*          
udp   UNCONN 0      0                       127.0.0.53:53         0.0.0.0:*          
udp   UNCONN 0      0                          0.0.0.0:67         0.0.0.0:*          
udp   UNCONN 0      0                     10.16.12.170:123        0.0.0.0:*          
udp   UNCONN 0      0                      172.16.42.1:123        0.0.0.0:*          
udp   UNCONN 0      0                        127.0.0.1:123        0.0.0.0:*          
udp   UNCONN 0      0                          0.0.0.0:123        0.0.0.0:*          
udp   UNCONN 0      0      [fe80::ea6e:1e81:d403:365b]:123              *:*          
udp   UNCONN 0      0       [2001:da8:201d:1107::fa48]:123              *:*          
udp   UNCONN 0      0      [fe80::c460:47ff:fe7d:22e7]:123              *:*          
udp   UNCONN 0      0                            [::1]:123              *:*          
udp   UNCONN 0      0                                *:123              *:*          
udp   UNCONN 0      0      [fe80::ea6e:1e81:d403:365b]:546              *:*          
udp   UNCONN 0      0                                *:1053             *:*          
tcp   LISTEN 0      4096                       0.0.0.0:22         0.0.0.0:*          
tcp   LISTEN 0      4096                 127.0.0.53%lo:53         0.0.0.0:*          
tcp   LISTEN 0      4096                     127.0.0.1:7891       0.0.0.0:*          
tcp   LISTEN 0      4096                     127.0.0.1:7890       0.0.0.0:*          
tcp   LISTEN 0      4096                     127.0.0.1:41745      0.0.0.0:*          
tcp   LISTEN 0      4096                    127.0.0.54:53         0.0.0.0:*          
tcp   LISTEN 0      4096                     127.0.0.1:33493      0.0.0.0:*          
tcp   LISTEN 0      4096                     127.0.0.1:45143      0.0.0.0:*          
tcp   LISTEN 0      511                      127.0.0.1:45169      0.0.0.0:*          
tcp   LISTEN 0      4096                             *:9090             *:*          
tcp   LISTEN 0      4096                          [::]:22            [::]:*          
tcp   LISTEN 0      4096                             *:1053             *:*          
```

## Environment Variables (selected)
```
HOME=/home/athbe
LANG=C.UTF-8
PATH=/home/athbe/.vscode-server/data/User/globalStorage/github.copilot-chat/debugCommand:/home/athbe/.vscode-server/data/User/globalStorage/github.copilot-chat/copilotCli:/home/athbe/.vscode-server/cli/servers/Stable-cfbea10c5ffb233ea9177d34726e6056e89913dc/server/bin/remote-cli:/home/athbe/.nvm/versions/node/v20.20.2/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games:/usr/local/games:/snap/bin
SHELL=/bin/bash
USER=athbe
```

## Systemd Services (active)
```
  UNIT                                              LOAD   ACTIVE SUB     DESCRIPTION
  bluetooth.service                                 loaded active running Bluetooth service
  bootmac@bluetooth.service                         loaded active exited  Set bluetooth MAC address
  dbus.service                                      loaded active running D-Bus System Message Bus
  getty@tty1.service                                loaded active running Getty on tty1
  kmod-static-nodes.service                         loaded active exited  Create List of Static Device Nodes
  ldconfig.service                                  loaded active exited  Rebuild Dynamic Linker Cache
  NetworkManager.service                            loaded active running Network Manager
  ntpsec.service                                    loaded active running Network Time Service
  orbital.service                                   loaded active running Orbital OS
  pd-mapper.service                                 loaded active running Qualcomm PD mapper service
  qrtr-ns.service                                   loaded active running QIPCRTR Name Service
  rmtfs.service                                     loaded active running Qualcomm remotefs service
  serial-getty@ttyMSM0.service                      loaded active running Serial Getty on ttyMSM0
  ssh.service                                       loaded active running OpenBSD Secure Shell server
  systemd-backlight@backlight:ae94000.dsi.0.service loaded active exited  Load/Save Screen Backlight Brightness of backlight:ae94000.dsi.0
  systemd-binfmt.service                            loaded active exited  Set Up Additional Binary Formats
  systemd-journal-catalog-update.service            loaded active exited  Rebuild Journal Catalog
  systemd-journal-flush.service                     loaded active exited  Flush Journal to Persistent Storage
  systemd-journald.service                          loaded active running Journal Service
  systemd-logind.service                            loaded active running User Login Management
  systemd-modules-load.service                      loaded active exited  Load Kernel Modules
  systemd-random-seed.service                       loaded active exited  Load/Save OS Random Seed
  systemd-remount-fs.service                        loaded active exited  Remount Root and Kernel File Systems
  systemd-resolved.service                          loaded active running Network Name Resolution
  systemd-sysctl.service                            loaded active exited  Apply Kernel Variables
  systemd-sysusers.service                          loaded active exited  Create System Users
  systemd-tmpfiles-setup-dev-early.service          loaded active exited  Create Static Device Nodes in /dev gracefully
  systemd-tmpfiles-setup-dev.service                loaded active exited  Create Static Device Nodes in /dev
  systemd-tmpfiles-setup.service                    loaded active exited  Create Volatile Files and Directories
```
