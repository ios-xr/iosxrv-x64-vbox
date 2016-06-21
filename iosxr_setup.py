'''
Author: Rich Wellum (richwellum@gmail.com)

Login to IOS XR, apply some config and then exit.

Called by iosxr_iso2vbox.py
'''

import time


class XrLogin(object):

    def __init__(self, pysun, name="xr"):
        self.pysun = pysun
        self.xr_telnet_sessions = []
        self.vm_host_telnet_sessions = []
        self.name = name

    #
    # Launch nodes
    #
    def pre_node(self):
        pysun = self.pysun
        pysun.logger.info("logging in")
        self.xr = pysun.Node(pysun, self.name)

    #
    # Open XR sessions
    #
    def open_sessions(self, username, password):
        self.xr1 = self.xr.wait_xr_login(username, password)
        self.xr_telnet_sessions.append(self.xr1)

    #
    # Back to back network config
    #
    def setup_networking(self, host_ip=None, gateway=None, allow_root_login=False):
        xr1 = self.xr1

        #
        # Configure xr
        #
        xr1.repeat_until("sh run | inc MgmtEth",
                         match_txt="interface MgmtEth",
                         debug="Check interface ready",
                         timeout=5)
        xr1.wait_xr_conf_mode()

        # Bring up dhcp on MGMT for vagrant access
        xr1.send("interface MgmtEth0/RP0/CPU0/0")
        xr1.send(" ipv4 address dhcp")
        xr1.send(" no shutdown")

        # TPA source update
        xr1.send("tpa address-family ipv4 update-source MgmtEth0/RP0/CPU0/0")

        if gateway is not None:
            xr1.send("router static address-family ipv4 unicast 0.0.0.0/0 MgmtEth0/RP0/CPU0/0 %s" % gateway)

        xr1.send("ssh server v2")
        xr1.send("ssh server vrf default")
        time.sleep(2)  # Give the parser a little time
        xr1.send("commit")
        time.sleep(2)  # Give the commit a little time
        xr1.send("commit")  # Second commit helps when parser is holding onto config buffer

        xr1.send("grpc")
        xr1.send(" port 57777")
        xr1.send("telnet vrf default ipv4 server max-servers 10")
        time.sleep(2)  # Give the parser a little time
        xr1.send("commit")
        time.sleep(2)  # Give the commit a little time
        xr1.send("commit")  # Second commit helps when parser is holding onto config buffer

        xr1.send("end")
        xr1.wait("end")

        if host_ip is not None:
            xr1.repeat_until("sh ipv4 int brief",
                             match_txt=host_ip,
                             debug="Configure network",
                             timeout=5)

        # Needed for jenkins if using root password
        if allow_root_login:
            xr1.send("run sed -i 's/PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config_operns")

        # Add passwordless sudo as required by jenkins
        xr1.send("run echo '####Added by pysun to give vagrant passwordless access' >> /etc/sudoers")
        xr1.send("run echo '%sudo ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers")

        # Add public key, so users can ssh without a password
        # https://github.com/purpleidea/vagrant-builder/blob/master/v6/files/ssh.sh
        xr1.send("run [ -d ~vagrant/.ssh ] || mkdir ~vagrant/.ssh")
        xr1.send("run chmod 0700 ~vagrant/.ssh")
        xr1.send("run echo 'ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eWW6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXPITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pzC6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZEnDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXzcWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ== vagrant insecure public key' > ~vagrant/.ssh/authorized_keys")
        xr1.send("run chmod 0600 ~vagrant/.ssh/authorized_keys")
        xr1.send("run chown -R vagrant:vagrant ~vagrant/.ssh/")

        # Add user scratch space - should be able transfer a file to
        # /misc/app_host/scratch using the scp with user vagrant
        # E.g: scp -P 2200 Vagrantfile vagrant@localhost:/misc/app_host/scratch
        xr1.send("run groupadd app_host")
        xr1.send("run usermod -a -G app_host vagrant")
        xr1.send("run mkdir /misc/app_host/scratch")
        xr1.send("run chgrp -R app_host /misc/app_host/scratch")
        xr1.send("run chmod 777 /misc/app_host/scratch")

        # Add Cisco OpenDNS IPv4 nameservers as a default DNS resolver
        # almost all users who have internet connectivity will be able to reach those.
        # This will prevent users from needing to supply another Vagrantfile or editing /etc/resolv.conf manually
        xr1.send("run echo '# Cisco OpenDNS IPv4 nameservers' >> /etc/resolv.conf")
        xr1.send("run echo 'nameserver 208.67.222.222' >> /etc/resolv.conf")
        xr1.send("run echo 'nameserver 208.67.220.220' >> /etc/resolv.conf")

        # Start operns sshd server so vagrant ssh can access app-hosting space
        xr1.send("run service sshd_operns start")

        # Wait for it to come up
        xr1.repeat_until("run service sshd_operns status",
                         match_txt="is running...",
                         debug="Check sshd_operns is up",
                         timeout=5)

        xr1.send("run chkconfig --add sshd_operns")

        # Generate a crypto key on XR. Note will fail if not a k9 image.
        xr1.send("crypto key generate rsa")

    def get_mgmt_ip(self):
        xr1 = self.xr1

        ip = xr1.must_get_cisco_ip_address("MgmtEth0/RP0/CPU0/0")
        xr1.log("Got IP %s" % ip)

    #
    # An example of how to create a login session and use it to configure
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
        pysun = self.pysun
        pysun.Node(pysun, "xr", clean=True, b2b=False, mgmt=True)


def get_instance(pysun):
    return XrLogin(pysun)
