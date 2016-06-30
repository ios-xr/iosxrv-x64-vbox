'''
Author: Rich Wellum (richwellum@gmail.com)

Login to a running IOS XR VM, then apply a combination of XR and XR linux
config to provide features to enable a vagrantbox that has internet
connectivity on bringup. As well as other needed features like SSH and DNS.

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
    # Send a global-vrf XR Linux command - wait for prompt
    # Could do bash -c or run ip netns exec global-vrf bash
    #
    def send_operns(self, command):
        xr1 = self.xr1

        xr1.send("bash -c %s" % command)
        xr1.wait("[\$#]")

    #
    # Send a xrnns XR Linux command - wait for prompt
    #
    def send_xrnns(self, command):
        xr1 = self.xr1

        xr1.send("run %s" % command)
        xr1.wait("[\$#]")

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
        xr1.send("bash -c rpm -qa | grep k9sec")
        time.sleep(2)
        output = xr1.wait("[\$#]")
        k9 = re.search(r'-k9sec', output)
        if k9:
            xr1.log("Crypto k9 image detected")

        # Determine if the image is a full or mini by searching for the mgbl rpm
        # which only exists in the full image
        # This will be used to configure features only available in a full image
        xr1.send("bash -c rpm -qa | grep mgbl")
        time.sleep(2)
        output = xr1.wait("[\$#]")
        full = re.search(r'-mgbl', output)

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

        # Configure GRPC protocol if a full image
        if full:
            xr1.send("grpc")
            xr1.send(" port 57777")
            xr1.wait("config-grpc")

        # Commit changes and end
        xr1.send("commit")
        xr1.wait("config")

        xr1.send("end")
        xr1.wait("[\$#]")

        # Spin waiting for an ip address to be associated with the interface
        if host_ip is not None:
            xr1.repeat_until("sh ipv4 int brief",
                             match_txt=host_ip,
                             debug="Configure network",
                             timeout=5)

        # Needed for jenkins if using root password
        if allow_root_login:
            xr1.send("bash -c sed -i 's/PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config_operns")

        # Add passwordless sudo as required by jenkins
        self.send_operns("echo '####Added by iosxr_setup to give vagrant passwordless access' >> /etc/sudoers")
        self.send_operns("echo '%sudo ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers")
        self.send_operns("echo 'vagrant ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers")

        # Add public key, so users can ssh without a password
        # https://github.com/purpleidea/vagrant-builder/blob/master/v6/files/ssh.sh
        self.send_operns("[ -d ~vagrant/.ssh ] || mkdir ~vagrant/.ssh")
        self.send_operns("chmod 0700 ~vagrant/.ssh")
        self.send_operns("echo 'ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eWW6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXPITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pzC6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZEnDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXzcWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ== vagrant insecure public key' > ~vagrant/.ssh/authorized_keys")
        self.send_operns("chmod 0600 ~vagrant/.ssh/authorized_keys")
        self.send_operns("chown -R vagrant:vagrant ~vagrant/.ssh/")

        # Add user scratch space - should be able transfer a file to
        # /misc/app_host/scratch using the scp with user vagrant
        # E.g: scp -P 2200 Vagrantfile vagrant@localhost:/misc/app_host/scratch
        self.send_operns("groupadd app_host")
        self.send_operns("usermod -a -G app_host vagrant")
        self.send_operns("mkdir -p /misc/app_host/scratch")
        self.send_operns("chgrp -R app_host /misc/app_host/scratch")
        self.send_operns("chmod 777 /misc/app_host/scratch")

        # Add Cisco OpenDNS IPv4 nameservers as a default DNS resolver
        # almost all users who have internet connectivity will be able to reach those.
        # This will prevent users from needing to supply another Vagrantfile or editing /etc/resolv.conf manually
        # Doing this in xrnns because the syncing of cat /etc/netns/global-vrf/resolv.conf to
        # /etc/resolv.conf requires 'ip netns exec global-vrf bash'.
        xr1.send("run echo '# Cisco OpenDNS IPv4 nameservers' > /etc/resolv.conf")
        xr1.send("run echo 'nameserver 208.67.222.222' >> /etc/resolv.conf")
        xr1.send("run echo 'nameserver 208.67.220.220' >> /etc/resolv.conf")

        # Start operns sshd server so vagrant ssh can access app-hosting space
        self.send_operns("service sshd_operns start")

        # Wait for it to come up
        xr1.repeat_until("bash -c service sshd_operns status",
                         match_txt="is running...",
                         debug="Check sshd_operns is up",
                         timeout=5)

        self.send_operns("chkconfig --add sshd_operns")

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
