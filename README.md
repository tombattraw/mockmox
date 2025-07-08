A VM management framework intended to abstract away most details of qemu/KVM VM management. I tried Proxmox but was endlessly annoyed by the layers of GUI management and dislike the CLI, so I'm building my own, since, as we all know, building projects in-house is *always* superior to a tested and widely-accepted third-party solution. 

Sadly, not all requirements can be satisfied with just PIP. If you're running mockmox on the same system, install all below packages on it.
Otherwise, install the "client" packages on the system with the script, and the "server" packages on the system running libvirtd.

Server:
Arch: virt-manager
Debian/Ubuntu/Mint: virtinst python3-virtinst
RHEL/CentOS/Fedora: virt-install python3-virtinst
