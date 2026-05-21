# SIFT Workstation Setup Guide

Quick setup guide for running SIFT Workstation for the Find Evil! hackathon.

---

## Recommended VM Software

### macOS (Intel)
**VMware Fusion** (Recommended)
- Best performance and compatibility
- Free for personal use
- Download: [vmware.com/products/fusion.html](https://www.vmware.com/products/fusion.html)

**Alternative: VirtualBox**
- Free and open source
- Download: [virtualbox.org](https://www.virtualbox.org/)

### macOS (Apple Silicon M1/M2/M3)
**UTM** (Recommended)
- Native Apple Silicon support
- Free and open source
- Download: [mac.getutm.app](https://mac.getutm.app/)

**Note**: SIFT OVA may need conversion for UTM. See troubleshooting below.

### Windows
**VMware Workstation Player** (Recommended)
- Free for personal use
- Download: [vmware.com/products/workstation-player.html](https://www.vmware.com/products/workstation-player.html)

**Alternative: VirtualBox**
- Free and open source
- Download: [virtualbox.org](https://www.virtualbox.org/)

### Linux
**VirtualBox** (Recommended)
- Native Linux support
- Install via package manager: `sudo apt install virtualbox`

---

## Setup Steps

### 1. Download SIFT Workstation

1. Go to [sans.org/tools/sift-workstation](https://www.sans.org/tools/sift-workstation/)
2. Sign in (create free SANS account if needed)
3. Download: `sift-2026-04-22.ova` (~8.8GB)

### 2. Import OVA File

**VMware (Fusion/Workstation):**
```
1. Open VMware
2. File → Open → Select sift-2026-04-22.ova
3. Choose import location
4. Click "Import"
```

**VirtualBox:**
```
1. Open VirtualBox
2. File → Import Appliance
3. Select sift-2026-04-22.ova
4. Review settings (adjust if needed)
5. Click "Import"
```

**UTM (Apple Silicon):**
```
1. Convert OVA to QCOW2:
   - Extract OVA: tar -xvf sift-2026-04-22.ova
   - Convert VMDK: qemu-img convert -f vmdk -O qcow2 sift-disk1.vmdk sift.qcow2
2. Create new VM in UTM:
   - Type: Virtualize
   - OS: Linux
   - Import sift.qcow2 as disk
```

### 3. Configure VM Settings

**Recommended Settings:**
- **RAM**: 8GB (minimum 4GB)
- **CPUs**: 4 cores (minimum 2)
- **Disk**: 50GB (pre-configured)
- **Network**: NAT or Bridged

**To adjust in VMware:**
```
1. Select VM → Settings
2. Processors & Memory → Set to 8GB RAM, 4 cores
3. Network Adapter → NAT
```

**To adjust in VirtualBox:**
```
1. Select VM → Settings
2. System → Base Memory: 8192 MB
3. System → Processor: 4 CPUs
4. Network → Adapter 1: NAT
```

### 4. Boot SIFT Workstation

1. Start the VM
2. Wait for Ubuntu to boot
3. Login with default credentials:
   - **Username**: `sansforensics`
   - **Password**: `forensics`

### 5. Update System

```bash
sudo apt update && sudo apt upgrade -y
```

### 6. Install Protocol SIFT

```bash
curl -fsSL https://raw.githubusercontent.com/teamdfir/protocol-sift/main/install.sh | bash
source ~/.bashrc
```

### 7. Verify Installation

```bash
# Test core tools
fls -V
vol.py --info
log2timeline.py --version

# Test Protocol SIFT
protocol-sift --version
```

---

## Quick Test

Run a simple forensic command to verify everything works:

```bash
# List available tools
ls /usr/bin/ | grep -E "(fls|mmls|icat|vol)"

# Check Volatility profiles
vol.py --info | head -20
```

---

## Troubleshooting

### VM Won't Boot
- **Check virtualization**: Ensure VT-x/AMD-V is enabled in BIOS
- **Reduce resources**: Try 4GB RAM, 2 CPUs if system is limited
- **Check disk space**: Ensure 50GB+ free on host

### Slow Performance
- **Increase RAM**: Allocate 8GB instead of 4GB
- **Use SSD**: Store VM on SSD, not HDD
- **Close other apps**: Free up host system resources

### Network Not Working
- **Change adapter**: Try Bridged instead of NAT
- **Restart networking**: `sudo systemctl restart NetworkManager`
- **Check firewall**: Temporarily disable host firewall

### Protocol SIFT Install Fails
```bash
# Install dependencies manually
sudo apt install -y python3 python3-pip git curl
pip3 install anthropic requests flask

# Clone and install manually
git clone https://github.com/teamdfir/protocol-sift.git ~/protocol-sift
cd ~/protocol-sift
pip3 install -r requirements.txt
```

### Apple Silicon (M1/M2/M3) Issues
- **Use UTM**: Native ARM support, better performance
- **Enable Rosetta**: For x86 compatibility if needed
- **Alternative**: Run Ubuntu ARM64 + install SIFT tools manually

---

## Next Steps

1. **Join Protocol SIFT Slack**: [Join here](https://join.slack.com/t/sansaihackathon/shared_invite/zt-3srjz86zo-bwHi_v1aKTg2IJAU4_4OwA)
2. **Download sample data**: Get forensic images to test with
3. **Test Engram integration**: Connect agents to shared memory
4. **Review hackathon ideas**: Plan your project approach

---

## Resources

- **SIFT Documentation**: [sans.org/tools/sift-workstation](https://www.sans.org/tools/sift-workstation/)
- **SIFT Cheat Sheet**: [sans.org/posters/sift-cheat-sheet](https://www.sans.org/posters/sift-cheat-sheet/)
- **Protocol SIFT**: [github.com/teamdfir/protocol-sift](https://github.com/teamdfir/protocol-sift)
- **Find Evil! Hackathon**: [findevil.devpost.com](https://findevil.devpost.com)

---

**Last Updated**: May 21, 2026
