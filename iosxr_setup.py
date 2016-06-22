'''
Author: Rich Wellum (richwellum@gmail.com)

Login to a runn IOS XR VM, apply a combination of XR and XR linux config to
provide features to enable a vagrantbox that has internet connectivity on
bringup. As well as other needed features like SSH and DNS.

Called by iosxr_iso2vbox.py
'''

import time
import re


class XrLogin(object):

    def __init__(self, iosxr_pexpect, name="xr"):
        self.iosxr_pexpect = iosxr_pexpect
        self.xr_telnet_sessions = []
        self.vm_host_telnet_sessions = []
        self.name = name

    #
    # Launch nodes
    #
    def pre_node(self):
        iosxr_pexpect = self.iosxr_pexpect
        iosxr_pexpect.logger.info("logging in")
        self.xr = iosxr_pexpect.Node(iosxr_pexpect, self.name)

    #
    # Open XR sessions
    #
    def open_sessions(self, username, password):
        self.xr1 = self.xr.wait_xr_login(username, password)
        self.xr_telnet_sessions.append(self.xr1)

    #
    # Configure a vagrant box
    #
    def setup_networking(self, host_ip=None, gateway=None, allow_root_login=False):
        xr1 = self.xr1

        #
        # Configure xr
        #

        # ZTP causes some startup issues so disable it during box creation
        xr1.send("ztp terminate noprompt")

        # Determine if the image is a crypto/k9 image or not
        # This will be used to determine whether to configure ssh or not
        xr1.send("run rpm -qa | grep k9sec")
        time.sleep(2)
        output = xr1.wait("[\$#]")
        k9 = re.search(r'iosxrv-k9sec', output)

        # Wait for a management interface to be available
        xr1.repeat_until("sh run | inc MgmtEth",
                         match_txt="interface MgmtEth",
                         debug="Check interface ready",
                         timeout=5)

        # Send conf t until configuration mode is entered
        xr1.wait_xr_conf_mode()

        # Enable telnet
        xr1.send("telnet vrf default ipv4 server max-servers 10")
        xr1.wait("config")

        # Bring up dhcp on MGMT for vagrant access
        xr1.send("interface MgmtEth0/RP0/CPU0/0")
        xr1.send(" ipv4 address dhcp")
        xr1.send(" no shutdown")
        xr1.wait("config-if")

        # TPA source update
        xr1.send("tpa address-family ipv4 update-source MgmtEth0/RP0/CPU0/0")
        xr1.wait("config")

        if gateway is not None:
            xr1.send("router static address-family ipv4 unicast 0.0.0.0/0 MgmtEth0/RP0/CPU0/0 %s" % gateway)
            xr1.wait("config")

        # Configure ssh if a k9/crypto image
        if k9:
            xr1.send("ssh server v2")
            xr1.wait("config")
            xr1.send("ssh server vrf default")
            xr1.wait("config")

        # Configure GRPC protocol
        xr1.send("grpc")
        xr1.send(" port 57777")
        xr1.wait("config-grpc")

        # Commit changes and end
        xr1.send("commit")
        # A sleep and another commit can help if config locks are seen.
        # time.sleep(5)
        # xr1.send("commit")
        xr1.wait("config")

        xr1.send("end")
        xr1.wait("#")

        # Spin waiting for an ip address to be associated with the interface
        if host_ip is not None:
            xr1.repeat_until("sh ipv4 int brief",
                             match_txt=host_ip,
                             debug="Configure network",
                             timeout=5)

        # Needed for jenkins if using root password
        if allow_root_login:
            xr1.send("run sed -i 's/PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config_operns")

        #
        # Send commands to XR Linux
        #
        xr1.send("run")

        # Add passwordless sudo as required by jenkins
        xr1.send("echo '####Added by iosxr_setup to give vagrant passwordless access' >> /etc/sudoers")
        xr1.send("echo '%sudo ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers")

        # Add public key, so users can ssh without a password
        # https://github.com/purpleidea/vagrant-builder/blob/master/v6/files/ssh.sh
        xr1.send("[ -d ~vagrant/.ssh ] || mkdir ~vagrant/.ssh")
        xr1.send("chmod 0700 ~vagrant/.ssh")
        xr1.send("echo 'ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eWW6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXPITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pzC6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZEnDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXzcWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ== vagrant insecure public key' > ~vagrant/.ssh/authorized_keys")
        xr1.send("chmod 0600 ~vagrant/.ssh/authorized_keys")
        xr1.send("chown -R vagrant:vagrant ~vagrant/.ssh/")

        # Add user scratch space - should be able transfer a file to
        # /misc/app_host/scratch using the scp with user vagrant
        # E.g: scp -P 2200 Vagrantfile vagrant@localhost:/misc/app_host/scratch
        xr1.send("groupadd app_host")
        xr1.send("usermod -a -G app_host vagrant")
        xr1.send("mkdir /misc/app_host/scratch")
        xr1.send("chgrp -R app_host /misc/app_host/scratch")
        xr1.send("chmod 777 /misc/app_host/scratch")

        # Add Cisco OpenDNS IPv4 nameservers as a default DNS resolver
        # almost all users who have internet connectivity will be able to reach those.
        # This will prevent users from needing to supply another Vagrantfile or editing /etc/resolv.conf manually
        xr1.send("echo '# Cisco OpenDNS IPv4 nameservers' >> /etc/resolv.conf")
        xr1.send("echo 'nameserver 208.67.222.222' >> /etc/resolv.conf")
        xr1.send("echo 'nameserver 208.67.220.220' >> /etc/resolv.conf")

        # Start operns sshd server so vagrant ssh can access app-hosting space
        xr1.send("service sshd_operns start")

        # Wait for it to come up
        xr1.repeat_until("service sshd_operns status",
                         match_txt="is running...",
                         debug="Check sshd_operns is up",
                         timeout=5)

        xr1.send("chkconfig --add sshd_operns")
        xr1.send("exit")
        xr1.wait("RP/0/RP0/CPU0:ios")

        # Set up IOS XR ssh if a k9/crypto image
        if k9:
            xr1.send("crypto key generate rsa")
            xr1.wait("How many bits in the modulus")
            xr1.send("")  # Send enter to get default 2048

    def get_mgmt_ip(self):
        xr1 = self.xr1

        ip = xr1.must_get_cisco_ip_address("MgmtEth0/RP0/CPU0/0")
        xr1.log("Got IP %s" % ip)

    #
    # Create a login session and use it to configure
    #
    def run_node(self):
        self.open_sessions('vagrant', 'vagrant')
        self.setup_networking('10.0.2.15', '10.0.2.2')
        self.get_mgmt_ip()

    #
    # Close telnet sessions
    #
    def post_node(self):
        self.xr.close()

    #
    # Shut down running nodes
    #
    def clean_node(self):
        iosxr_pexpect = self.iosxr_pexpect
        iosxr_pexpect.Node(iosxr_pexpect, "xr", clean=True, b2b=False, mgmt=True)


def get_instance(iosxr_pexpect):
    return XrLogin(iosxr_pexpect)
