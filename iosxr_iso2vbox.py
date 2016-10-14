#!/usr/bin/env python
'''
Author: Rich Wellum (richwellum@gmail.com)

This is a tool to take an IOS XR Virtual Machine ISO image and convert it into
a Vagrant Virtualbox fully networked and ready for application development.

At this point, only IOS XRv (64-bit) / (iosxrv-x64) is compatible but IOS XRv9k
is planned.

Pre-installed requirements:
python-pexpect
vagrant
virtualbox

Within OSX, these tools can be installed by homebrew (but not limited to):

/usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
brew cask install virtualbox
brew cask install vagrant
brew cask install python
pip install pexpect

Full Description:

Takes an IOS XR Virtual Machine IOS, currently IOS XRv (64-bit) ISO,
either locally or remotely and converts it to a virtualbox box.

Creates an embedded Vagrantfile, that will be included in
box/include/Vagrantfile. This Vagrantfile configures:

  . A guest forwarding port for 57722
  . ssh username and password
  . Serial ports for configuration

This embedded Vagrantfile is compatible with additional non-embedded
vagrantfiles for more advanced multi-node topologies.

Backs up existing box files.

Creates and registers a new Virtualbox VM.

Adds appropriate memory, display and CPU's.

Sets four NICS for networking.

Sets up port forwarding for the guest SSH.

Sets up storage - hdd and dvd(for ISO).

Starts the VM, then uses pexpect to configure XR and XR Aux for
basic networking and XR Linux usage, with user name vagrant/vagrant.

Closes the VM down once configured and then runs basic sanity tests.

The resultant box image, will come up fully networked and ready for app hosting
and deployment.
'''

from __future__ import print_function
import sys
import os
import time
import subprocess
import getpass
import argparse
from argparse import RawDescriptionHelpFormatter
import re
import logging
import pexpect
import tempfile
import shutil

# Telnet ports used to access IOS XR via socat
CONSOLE_PORT = 65000
AUX_PORT = 65001

logger = logging.getLogger(__name__)


def set_logging():
    '''
    Set basic logging format.
    '''
    FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s()] %(message)s"
    logging.basicConfig(format=FORMAT)


def run(cmd, hide_error=False, cont_on_error=False):
    '''
    Run command to execute CLI and catch errors and display them whether
    in verbose mode or not.

    Allow the ability to hide errors and also to continue on errors.
    '''
    s_cmd = ' '.join(cmd)
    logger.debug("Command: '%s'\n", s_cmd)

    output = subprocess.Popen(cmd,
                              stdout=subprocess.PIPE,
                              stdin=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    tup_output = output.communicate()

    if output.returncode != 0:
        logger.debug('Command failed with code %d:', output.returncode)
    else:
        logger.debug('Command succeeded with code %d:', output.returncode)

    logger.debug('Output for: ' + s_cmd)
    logger.debug(tup_output[0])

    if not hide_error and 0 != output.returncode:
        print('Error output for: ' + s_cmd)
        print(tup_output[1])
        if not cont_on_error:
            sys.exit(0)
        else:
            logger.debug('Continuing despite error cont_on_error=%d', cont_on_error)

    return tup_output[0]


def cleanup_vmname(name, box_name):
    '''
    Cleanup and unregister (delete) our working box.
    '''
    # Power off VM if it is running
    vms_list_running = run(['VBoxManage', 'list', 'runningvms'])
    if name in vms_list_running:
        logger.debug("'%s' is running, powering off...", name)
        run(['VBoxManage', 'controlvm', name, 'poweroff'])

    # Unregister and delete
    vms_list = run(['VBoxManage', 'list', 'vms'])
    if name in vms_list:
        logger.debug("'%s' is registered, unregistering and deleting", name)
        run(['VBoxManage', 'unregistervm', box_name, '--delete'])


def pause_to_debug():
    print("Pause before debug")
    print("Use: 'socat TCP:localhost:65000 -,raw,echo=0,escape=0x1d' to access the VM")
    raw_input("Press Enter to continue.")
    # To debug post box creation, add the following lines to Vagrantfile
    # config.vm.provider "virtualbox" do |v|
    #   v.customize ["modifyvm", :id, "--uart1", "0x3F8", 4, "--uartmode1", 'tcpserver', 65005]
    #   v.customize ["modifyvm", :id, "--uart2", "0x2F8", 3, "--uartmode2", 'tcpserver', 65006]
    # end


def start_process(args):
    '''
    Start vboxheadless process
    '''
    logger.debug('args: %s', args)
    with open(os.devnull, 'w') as fp:
        subprocess.Popen((args), stdout=fp)
    time.sleep(2)


def configure_xr(argv):
    '''
    Bring up XR and do some initial config.
    Using socat to do the connection as telnet has an
    odd double return on vbox
    '''
    logger.info('Logging into Vagrant Virtualbox and configuring IOS XR')

    localhost = 'localhost'
    prompt = r"[$#]"

    def xr_cli_wait_for_output(command, pattern):
        '''
        Execute a XR CLI command and try to find a pattern.
        Try up to five times them register an error.
        Each retry has a 5s turn around.
        '''
        total = 5
        found_match = False

        for attempt in range(total):
            try:
                child.sendline(command)
                child.expect(pattern, 5)
                found_match = True
                break
            except pexpect.TIMEOUT:
                logger.debug("Iteration '%s' out of '%s'", attempt, total)

        if not found_match:
            raise Exception("No '%s' in '%s'" % (pattern, command))

    try:
        child = pexpect.spawn("socat TCP:%s:%s -,raw,echo=0,escape=0x1d" % (localhost, CONSOLE_PORT))

        if argv == logging.DEBUG:
            child.logfile = sys.stdout

        child.timeout = 600  # Long time for full configuration, waiting for ip address etc

        # Setup username and password and log in
        child.expect('Press RETURN to get started.', child.timeout)
        child.sendline("")  # Send enter
        child.expect('Enter root-system username:', child.timeout)
        child.sendline("vagrant")
        child.expect("Enter secret:")
        child.sendline("vagrant")
        child.expect("Enter secret again:")
        child.sendline("vagrant")
        child.expect("Username:")
        child.sendline("vagrant")
        child.expect("Password:")
        child.sendline("vagrant")
        child.expect(prompt)

        # Set term width
        child.sendline("term width 300")
        child.expect(prompt)

        # ZTP causes some startup issues so disable it during box creation
        child.sendline("ztp terminate noprompt")
        child.expect(prompt)

        # Determine if the image is a crypto/k9 image or not
        # This will be used to determine whether to configure ssh or not
        child.sendline("bash -c rpm -qa | grep k9sec")
        child.expect(prompt)
        output = child.before
        if '-k9sec' in output:
            crypto = True
            logger.debug("Crypto k9 image detected")
        else:
            crypto = False
            logger.debug("Non crypto k9 image detected")

        # Determine if the image has the MGBL package needed for gRPC
        child.sendline("bash -c rpm -qa | grep mgbl")
        child.expect(prompt)
        output = child.before
        if '-mgbl' in output:
            mgbl = True
            logger.debug("MGBL package detected")
        else:
            mgbl = False
            logger.debug("MGBL package not detected")

        # Wait for a management interface to be available
        xr_cli_wait_for_output('sh run interface | inc MgmtEth', 'interface MgmtEth')

        child.sendline("conf t")
        child.expect("ios.config.*#", 10)

        # Enable telnet
        child.sendline("telnet vrf default ipv4 server max-servers 10")
        child.expect("config")

        # Bring up dhcp on MGMT for vagrant access
        child.sendline("interface MgmtEth0/RP0/CPU0/0")
        child.sendline(" ipv4 address dhcp")
        # child.sendline(" ipv4 address 10.0.2.15/24")
        child.sendline(" no shutdown")
        child.expect("config-if")

        # TPA source update
        # if not xrv9k:
        child.sendline("tpa address-family ipv4 update-source MgmtEth0/RP0/CPU0/0")
        child.expect("config")

        # add east west config if sunstone lite image
        # if xrv9k:
        #     child.sendline("tpa east-west MgmtEth0/RP0/CPU0/0")
        #     child.expect("config")

        # if not xrv9k:
        child.sendline("router static address-family ipv4 unicast 0.0.0.0/0 MgmtEth0/RP0/CPU0/0 10.0.2.2")
        child.expect("config")

        # Configure ssh if a k9/crypto image
        if crypto:
            child.sendline("ssh server v2")
            child.expect("config")
            child.sendline("ssh server vrf default")
            child.expect("config")

        # Configure gRPC protocol if MGBL package is available
        # if mgbl:
        #     child.sendline("grpc")
        #     child.sendline(" port 57777")
        #     child.expect("config-grpc")

        # Commit changes and end
        child.sendline("commit")
        child.expect("config")

        child.sendline("end")
        child.expect(prompt)

        # Spin waiting for an ip address to be associated with the interface
        xr_cli_wait_for_output('sh ipv4 int brief | i 10.0.2.15', '10.0.2.15')

        # Needed for jenkins if using root password
        child.sendline("bash -c sed -i 's/PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config_operns")
        child.expect(prompt)

        # Add passwordless sudo
        child.sendline("bash -c echo '####Added by iosxr_setup to give vagrant passwordless access' | (EDITOR='tee -a' visudo)")
        child.expect(prompt)
        child.sendline("bash -c echo 'vagrant ALL=(ALL) NOPASSWD: ALL' | (EDITOR='tee -a' visudo)")
        child.expect(prompt)

        # Add public key, so users can ssh without a password
        # https://github.com/purpleidea/vagrant-builder/blob/master/v6/files/ssh.sh
        child.sendline("bash -c [ -d ~vagrant/.ssh ] || mkdir ~vagrant/.ssh")
        child.expect(prompt)
        child.sendline("bash -c chmod 0700 ~vagrant/.ssh")
        child.expect(prompt)
        child.sendline("bash -c echo 'ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eWW6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXPITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pzC6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZEnDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXzcWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ== vagrant insecure public key' > ~vagrant/.ssh/authorized_keys")
        child.expect(prompt)
        child.sendline("bash -c chmod 0600 ~vagrant/.ssh/authorized_keys")
        child.expect(prompt)
        child.sendline("bash -c chown -R vagrant:vagrant ~vagrant/.ssh/")
        child.expect(prompt)

        # Add Cisco OpenDNS IPv4 nameservers as a default DNS resolver
        # almost all users who have internet connectivity will be able to reach those.
        # This will prevent users from needing to supply another Vagrantfile or editing /etc/resolv.conf manually
        # Doing this in xrnns (run) because the syncing of /etc/netns/global-vrf/resolv.conf to
        # /etc/resolv.conf requires 'ip netns exec global-vrf bash'.
        child.sendline("run echo '# Cisco OpenDNS IPv4 nameservers' >> /etc/resolv.conf")
        child.expect(prompt)
        child.sendline("run echo 'nameserver 208.67.222.222' >> /etc/resolv.conf")
        child.expect(prompt)
        child.sendline("run echo 'nameserver 208.67.220.220' >> /etc/resolv.conf")
        child.expect(prompt)

        # TODO: Experimental - one possible way to get connectivity
        child.sendline("bash -c ip route add default via 10.0.2.2 src 10.0.2.15")
        child.expect(prompt)

        # Start operns sshd server so vagrant ssh can access app-hosting space
        child.sendline("bash -c service sshd_operns start")
        child.expect(prompt)

        # Wait for sshd_operns to come up
        xr_cli_wait_for_output('bash -c service sshd_operns status', 'is running...')

        child.sendline("bash -c chkconfig --add sshd_operns")
        child.expect("RP/0/RP0/CPU0:ios")

        # Set up IOS XR ssh if a k9/crypto image
        if crypto:
            child.sendline("crypto key generate rsa")
            child.expect("How many bits in the modulus")
            child.sendline("2048")  # Send enter to get default 2048
            child.expect(prompt)  # Wait for the prompt

        # Final check to make sure MGMT stayed up
        xr_cli_wait_for_output('show ipv4 interface MgmtEth0/RP0/CPU0/0 | i Internet address', '10.0.2.15')

        logger.debug('Waiting 10 seconds...')
        time.sleep(10)

    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT('Timeout (%s) exceeded in read().' % str(child.timeout))


def main(argv):
    input_iso = ''
    create_ova = False
    global xrv9k
    xrv9k = False

    parser = argparse.ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        description='A tool to create an IOS XRv Vagrant VirtualBox box from ' +
        'an IOS XRv ISO.\n' '\nThe ISO will be installed, booted, configured ' +
        'and unit-tested. \n"vagrant ssh" provides access ' +
        'to IOS XR Linux global-vrf namespace \nwith internet access.',
        epilog="E.g.:\n" +
        "box build with local iso: iosxr-xrv64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso\n" +
        "box build with remote iso: iosxr-xrv64-vbox/iosxr_iso2vbox.py user@server:/myboxes/iosxrv-fullk9-x64.iso\n" +
        "box build with ova export, verbose and upload to artifactory: iosxr-xrv64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso -o -v -a 'New Image'\n")
    parser.add_argument('ISO_FILE',
                        help='local ISO filename or remote URI ISO filename...')
    parser.add_argument('-o', '--create_ova', action='store_true',
                        help='additionally use VBoxManage to export an OVA')
    parser.add_argument('-s', '--skip_test', action='store_true',
                        help='skip unit testing')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='will exit with the VM in a running state. Use: socat TCP:localhost:65000 -,raw,echo=0,escape=0x1d to access')
    parser.add_argument('-v', '--verbose',
                        action='store_const', const=logging.DEBUG,
                        default=logging.INFO, help='turn on verbose messages')

    args = parser.parse_args()

    # Handle Input ISO (Local or URI)
    if re.search(':/', args.ISO_FILE):
        # URI Image
        cmd_string = 'scp %s@%s .' % (getpass.getuser(), args.ISO_FILE)
        logger.debug('Will attempt to scp the remote image to current working dir. You may be required to enter your password.')
        logger.debug('%s\n', cmd_string)
        subprocess.call(cmd_string, shell=True)
        input_iso = os.path.basename(args.ISO_FILE)
    else:
        # Local image
        input_iso = args.ISO_FILE

    # Handle create OVA
    create_ova = args.create_ova

    if not os.path.exists(input_iso):
        sys.exit('%s does not exist' % input_iso)

    # Set Virtualbox VM name from the input ISO
    vmname = os.path.basename(os.path.splitext(input_iso)[0])

    set_logging()
    logger.setLevel(level=args.verbose)

    logger.debug('Input ISO is %s', input_iso)

    # Set the RAM according to mini of full ISO
    if 'mini' in input_iso:
        ram = 3072
        logger.debug('%s is a mini image, RAM allocated is %s MB', input_iso, ram)
    elif 'full' in input_iso:
        ram = 4096
        logger.debug('%s is a full image, RAM allocated is %s MB', input_iso, ram)
    else:
        sys.exit('%s is neither a mini nor a full image. Abort' % input_iso)

    # Determine if it's a sunstone ISO
    if 'xrv9k' in input_iso:
        logger.debug('Found an XRv9k image')
        xrv9k = True
        ram = 6144
        # ram = 5120

    logger.info('Creating Vagrant VirtualBox')

    version = run(['VBoxManage', '-v'])
    logger.debug('Virtual Box Manager Version: %s', version)

    # Set up paths
    base_dir = os.path.join(os.getcwd(), 'machines')
    box_dir = os.path.join(base_dir, vmname)
    vbox = os.path.join(box_dir, vmname + '.vbox')
    vdi = os.path.join(box_dir, vmname + '.vdi')
    box_out = os.path.join(box_dir, vmname + '.box')
    ova_out = os.path.join(box_dir, vmname + '.ova')
    pathname = os.path.abspath(os.path.dirname(sys.argv[0]))

    logger.debug('pathname: %s', pathname)
    logger.debug('VM Name:  %s', vmname)
    logger.debug('base_dir: %s', base_dir)
    logger.debug('box_dir:  %s', box_dir)
    logger.debug('box_out:  %s', box_out)
    logger.debug('vbox:     %s', vbox)

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    if not os.path.exists(box_dir):
        os.makedirs(box_dir)

    # Delete existing Box
    if os.path.exists(box_out):
        os.remove(box_out)
        logger.debug('Found and deleted previous %s', box_out)

    # Delete existing OVA
    if os.path.exists(ova_out) and create_ova is True:
        os.remove(ova_out)
        logger.debug('Found and deleted previous %s', ova_out)

    # Clean up existing vm's
    cleanup_vmname(vmname, vbox)

    # Remove stale SSH entry
    logger.debug('Removing stale SSH entries')
    run(['ssh-keygen', '-R', '[localhost]:2222'])
    run(['ssh-keygen', '-R', '[localhost]:2223'])

    # Create and register a new VirtualBox VM
    logger.debug('Create VM')
    run(['VBoxManage', 'createvm', '--name', vmname, '--ostype', 'Linux26_64', '--basefolder', base_dir])

    logger.debug('Register VM')
    run(['VBoxManage', 'registervm', vbox])

    # Setup memory, display, cpus etc
    logger.debug('VRAM 12')
    run(['VBoxManage', 'modifyvm', vmname, '--vram', '12'])

    logger.debug('Add ACPI')
    run(['VBoxManage', 'modifyvm', vmname, '--memory', str(ram), '--acpi', 'on'])

    if xrv9k:
        logger.debug('Add one CPU')
        run(['VBoxManage', 'modifyvm', vmname, '--cpus', '1'])
    else:
        logger.debug('Add two CPUs')
        run(['VBoxManage', 'modifyvm', vmname, '--cpus', '2'])

    # Setup networking - including ssh
    logger.debug('Create eight NICs')
    if xrv9k:
        nictype = '82540EM'
    else:
        nictype = 'virtio'

    run(['VBoxManage', 'modifyvm', vmname, '--nic1', 'nat', '--nictype1', '%s' % nictype])
    run(['VBoxManage', 'modifyvm', vmname, '--nic2', 'nat', '--nictype2', '%s' % nictype])
    run(['VBoxManage', 'modifyvm', vmname, '--nic3', 'nat', '--nictype3', '%s' % nictype])
    run(['VBoxManage', 'modifyvm', vmname, '--nic4', 'nat', '--nictype4', '%s' % nictype])
    if not xrv9k:
        run(['VBoxManage', 'modifyvm', vmname, '--nic5', 'nat', '--nictype5', '%s' % nictype])
        run(['VBoxManage', 'modifyvm', vmname, '--nic6', 'nat', '--nictype6', '%s' % nictype])
        run(['VBoxManage', 'modifyvm', vmname, '--nic7', 'nat', '--nictype7', '%s' % nictype])
        run(['VBoxManage', 'modifyvm', vmname, '--nic8', 'nat', '--nictype8', '%s' % nictype])

    # Add Serial ports
    #
    # 1. what kind of serial port the virtual machine should see by selecting
    # an I/O base
    # address and interrupt (IRQ). For these, we recommend to use the
    # traditional values, which are:
    # a) COM1: I/O base 0x3F8, IRQ 4
    # b) COM2: I/O base 0x2F8, IRQ 3
    # c) COM3: I/O base 0x3E8, IRQ 4
    # d) COM4: I/O base 0x2E8, IRQ 3
    # [--uartmode<1-N> disconnected|
    #  server <pipe>|
    #  client <pipe>|
    #  tcpserver <port>|
    #  tcpclient <hostname:port>|
    #  file <file>|
    #  <devicename>]

    # Option 1: Output to a simple file: 'tail -f /tmp/serial' (no file?)
    # VBoxManage modifyvm $VMNAME --uart1 0x3f8 4 --uartmode1 file /tmp/serial1

    # Option 2: Connect via socat as telnet has double echo issue)
    # But can still use telnet in conjunction with socat
    logger.debug('Add a console port')
    run(['VBoxManage', 'modifyvm', vmname, '--uart1', '0x3f8', '4', '--uartmode1', 'tcpserver', str(CONSOLE_PORT)])

    logger.debug('Add an aux port')
    run(['VBoxManage', 'modifyvm', vmname, '--uart2', '0x2f8', '3', '--uartmode2', 'tcpserver', str(AUX_PORT)])

    # Option 3: Connect via telnet
    # VBoxManage modifyvm $VMNAME --uart1 0x3f8 4 --uartmode1 tcpserver 6000
    # VBoxManage modifyvm $VMNAME --uart2 0x2f8 3 --uartmode2 tcpserver 6001

    # Setup storage
    logger.debug('Create a HDD')
    run(['VBoxManage', 'createhd', '--filename', vdi, '--size', '46080'])

    logger.debug('Add IDE Controller')
    run(['VBoxManage', 'storagectl', vmname, '--name', 'IDE_Controller', '--add', 'ide'])

    logger.debug('Attach HDD')
    run(['VBoxManage', 'storageattach', vmname, '--storagectl', 'IDE_Controller', '--port', '0', '--device', '0', '--type', 'hdd', '--medium', vdi])

    logger.debug('VM HD info: ')
    run(['VBoxManage', 'showhdinfo', vdi])

    logger.debug('Add DVD drive')
    run(['VBoxManage', 'storageattach', vmname, '--storagectl', 'IDE_Controller', '--port', '1', '--device', '0', '--type', 'dvddrive', '--medium', input_iso])

    # Add another DVD drive to carry the Profile for sunstone lite
    # Needs brew install dvdrtools
    if xrv9k:
        logger.debug('Add another drive for sunstone_lite profile')
        temp_dir = tempfile.mkdtemp()
        try:
            yaml_file = os.path.join(temp_dir, 'xrv9k.yaml')
            with open(yaml_file, 'w') as yaml:
                yaml.write("PROFILE : lite\n"
                           "CTRL_ETH : FALSE\n"
                           "HOST_ETH : FALSE\n"
                           "UVFCP_CPUSHARES : 30\n"
                           "UVFDP_CPUSHARES : 50\n"
                           "NUM_OF_1GHUGEPAGES : 1\n")

            run(['mkisofs', '-output', './bootstrap-scapa.iso', '-l', '-V', 'config-1', '--relaxed-filenames', '--iso-level', '2', temp_dir])
            shutil.rmtree(temp_dir)
        except OSError:
            pass

        run(['VBoxManage', 'storageattach', vmname, '--storagectl', 'IDE_Controller', '--port', '1', '--device', '1', '--type', 'dvddrive', '--medium', './bootstrap-scapa.iso'])

    # Change boot order to hd then dvd
    logger.debug('Boot order disk first')
    run(['VBoxManage', 'modifyvm', vmname, '--boot1', 'disk'])

    logger.debug('Boot order DVD second')
    run(['VBoxManage', 'modifyvm', vmname, '--boot2', 'dvd'])

    # Start the VM for installation of ISO - must be started as a sub process
    logger.debug('Starting VM...')
    start_process(['VBoxHeadless', '--startvm', vmname])

    while True:
        vms_list = run(['VBoxManage', 'showvminfo', vmname])
        if 'running (since' in vms_list:
            logger.debug('Successfully started to boot VM disk image')
            break
        else:
            logger.warning('Failed to install VM disk image\n')
            time.sleep(5)
            continue

    # Debug before config is entered
    if args.debug:
        pause_to_debug()

    # Configure IOS XR and IOS XR Linux
    configure_xr(args.verbose)

    # Good place to stop and take a look if --debug was entered
    if args.debug:
        pause_to_debug()

    logger.info('Powering down and generating Vagrant VirtualBox')

    # Powerdown VM prior to exporting
    logger.debug('Waiting for machine to shutdown')
    run(['VBoxManage', 'controlvm', vmname, 'poweroff'])

    while True:
        vms_list_running = run(['VBoxManage', 'list', 'runningvms'])
        if vmname in vms_list_running:
            logger.debug('Still shutting down')
            continue
        else:
            logger.debug('Successfully shut down')
            break

    # Disable uart before exporting
    logger.debug('Remove serial uarts before exporting')
    run(['VBoxManage', 'modifyvm', vmname, '--uart1', 'off'])
    run(['VBoxManage', 'modifyvm', vmname, '--uart2', 'off'])

    # Shrink the VM
    logger.debug('Compact VDI')
    run(['VBoxManage', 'modifymedium', '--compact', vdi])

    logger.debug('Building Virtualbox')

    # Add in embedded Vagrantfile
    vagrantfile_pathname = os.path.join(pathname, 'include', 'embedded_vagrantfile')

    run(['vagrant', 'package', '--base', vmname, '--vagrantfile', vagrantfile_pathname, '--output', box_out])
    logger.info('Created: %s', box_out)

    # Create OVA
    if create_ova is True:
        logger.info('Creating OVA %s', ova_out)
        run(['VBoxManage', 'export', vmname, '--output', ova_out])
        logger.debug('Created OVA %s', ova_out)

    # Clean up VM used to generate box
    cleanup_vmname(vmname, vbox)

    # Run basic sanity tests unless -s
    if not args.skip_test:
        logger.info('Running basic unit tests on Vagrant VirtualBox...')

        if args.verbose == logging.DEBUG:
            verbose_str = '-v'
        else:
            # Shhhh...
            verbose_str = ''

        iosxr_test_path = os.path.join(pathname, 'iosxr_test.py')
        cmd_string = "python %s %s %s" % (iosxr_test_path, box_out, verbose_str)
        subprocess.check_output(cmd_string, shell=True)
        # Clean up default test VM
        run(['vagrant', 'destroy', '--force'], cont_on_error=True)

    logger.info('Single node use:')
    logger.info(" vagrant init 'IOS XRv'")
    logger.info(" vagrant box add --name 'IOS XRv' %s --force", box_out)
    logger.info(' vagrant up')

    logger.info('Multinode use:')
    logger.info(" Copy './iosxrv-x64-vbox/vagrantfiles/simple-mixed-topo/Vagrantfile' to the directory running vagrant and do:")
    logger.info(" vagrant box add --name 'IOS XRv' %s --force", box_out)
    logger.info(' vagrant up')
    logger.info(" Or: 'vagrant up rtr1', 'vagrant up rtr2'")

    logger.info('Note that both the XR Console and the XR linux shell username and password is vagrant/vagrant')

    # Clean up Vagrantfile
    try:
        os.remove('Vagrantfile')
    except OSError:
        pass

if __name__ == '__main__':
    main(sys.argv[1:])
