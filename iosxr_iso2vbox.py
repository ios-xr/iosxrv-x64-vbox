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
import tarfile

# Telnet ports used to access IOS XR via socat
CONSOLE_PORT = 65000
AUX_PORT = 65001

# General-purpose retry interval and timeout value (10 minutes)
RETRY_INTERVAL = 5
TIMEOUT = 600

logger = logging.getLogger(__name__)


def set_logging():
    '''
    Set basic logging format.
    '''
    FORMAT = "[%(asctime)s.%(msecs)03d %(levelname)8s: %(funcName)20s:%(lineno)s] %(message)s"
    logging.basicConfig(format=FORMAT, datefmt="%H:%M:%S")


class AbortScriptException(Exception):
    """Abort the script and clean up before exiting."""


def run(cmd, hide_error=False, cont_on_error=False):
    '''
    Run command to execute CLI and catch errors and display them whether
    in verbose mode or not.

    Allow the ability to hide errors and also to continue on errors.
    '''
    s_cmd = ' '.join(cmd)
    logger.debug("Command: '%s'", s_cmd)

    output = subprocess.Popen(cmd,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    tup_output = output.communicate()

    if output.returncode != 0:
        logger.debug('Command failed with code %d:', output.returncode)
    else:
        logger.debug('Command succeeded with code %d:', output.returncode)

    logger.debug('Output for "%s":\n%s', s_cmd, tup_output[0])

    if not hide_error and 0 != output.returncode:
        logger.error('Error output for: ' + s_cmd)
        logger.error(tup_output[1])
        if not cont_on_error:
            raise AbortScriptException(
                "Command '{0}' failed with return code {1}".format(
                    s_cmd, output.returncode))
        logger.debug('Continuing despite error %d', output.returncode)

    return tup_output[0]


def cleanup_vmname(vmname, delete=False):
    """Power off the given virtualbox VM.

    If delete is True, also unregister and delete the VM.
    """
    # Power off VM if it is running
    vms_list_running = run(['VBoxManage', 'list', 'runningvms'])
    if re.search('"' + vmname + '"', vms_list_running):
        logger.debug("'%s' is running, powering off...", vmname)
        run(['VBoxManage', 'controlvm', vmname, 'poweroff'])

        logger.debug('Waiting for machine to shutdown')

        elapsed_time = 0
        while True:
            vms_list_running = run(['VBoxManage', 'list', 'runningvms'])
            if not re.search('"' + vmname + '"', vms_list_running):
                logger.debug('Successfully shut down')
                break
            elif elapsed_time < TIMEOUT:
                logger.warning("VM is not yet stopped after %d seconds; "
                               "sleep %d seconds and retry", elapsed_time,
                               RETRY_INTERVAL)
                time.sleep(RETRY_INTERVAL)
                elapsed_time = elapsed_time + RETRY_INTERVAL
                continue
            else:
                # Dump verbose output in case it helps...
                run(['VBoxManage', 'showvminfo', vmname])
                raise AbortScriptException(
                    "VM still not stopped after {0} seconds!"
                    .format(elapsed_time))

    if delete:
        vms_list = run(['VBoxManage', 'list', 'vms'])
        if re.search('"' + vmname + '"', vms_list):
            logger.debug("'%s' is registered, unregistering and deleting it",
                         vmname)
            run(['VBoxManage', 'unregistervm', vmname, '--delete'])


def pause_to_debug():
    """Pause the script for manual debugging of the VM before continuing."""
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


def configure_xr(verbosity):
    """Bring up XR and do some initial config.

    Uses socat to do the connection as telnet has an
    odd double return on vbox.
    """
    logger.info('Logging into Vagrant Virtualbox and configuring IOS XR')

    localhost = 'localhost'
    prompt = r"[$#]$"

    def xr_cli_wait_for_output(command, pattern):
        """Execute a XR CLI command and try to find a pattern.

        Try up to five times, waiting RETRY_INTERVAL between each try,
        then register an error.
        """
        total = 5
        found_match = False

        for attempt in range(total):
            try:
                logger.debug("Looking for '%s' in output of '%s'",
                             pattern, command)
                child.sendline(command)
                child.expect(prompt)
                if re.search(pattern, child.before):
                    found_match = True
                    logger.debug("Found '%s' in '%s'", pattern, command)
                    break
                logger.debug("No match found; sleeping %d before retrying",
                             RETRY_INTERVAL)
                time.sleep(RETRY_INTERVAL)
            except pexpect.TIMEOUT:
                logger.warning("Timed out without returning to prompt. "
                               "The device may be in a bad state now.")
            logger.debug("Iteration '%s' out of '%s'", (attempt + 1), total)

        if not found_match:
            raise Exception("No '%s' in '%s'" % (pattern, command))

    try:
        child = pexpect.spawn("socat TCP:%s:%s -,raw,echo=0,escape=0x1d" %
                              (localhost, CONSOLE_PORT))

        if verbosity == logging.DEBUG:
            child.logfile = sys.stdout

        # Need to wait a while for full configuration, IP address, etc.
        child.timeout = TIMEOUT

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

        # Set term len
        child.sendline("term length 0")
        child.expect(prompt)

        # ZTP causes some startup issues so disable it during box creation
        child.sendline("run mkdir -p /disk0:/ztp/state")
        child.expect(prompt)
        child.sendline("run touch /disk0:/ztp/state/state_is_complete")
        child.expect(prompt)
        child.sendline("ztp terminate noprompt")
        child.expect(prompt)

        # Get the image build information
        child.sendline("show version")
        child.expect(prompt)
        child.sendline("run cat /etc/build-info.txt")
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
        xr_cli_wait_for_output('sh run interface', 'interface MgmtEth')

        child.sendline("conf t")
        child.expect("ios.config.*#", 10)

        # Enable telnet
        child.sendline("telnet vrf default ipv4 server max-servers 10")
        child.expect("config")

        # Bring up dhcp on MGMT for vagrant access
        child.sendline("interface MgmtEth0/RP0/CPU0/0")
        child.expect("config-if")
        child.sendline(" ipv4 address dhcp")
        child.expect("config-if")
        child.sendline(" no shutdown")
        child.expect("config-if")

        # TPA source update
        child.sendline("tpa address-family ipv4 update-source MgmtEth0/RP0/CPU0/0")
        child.expect("config")

        child.sendline("router static address-family ipv4 unicast 0.0.0.0/0 MgmtEth0/RP0/CPU0/0 10.0.2.2")
        child.expect("config")

        # Configure ssh if a k9/crypto image
        if crypto:
            child.sendline("ssh server v2")
            child.expect("config")
            child.sendline("ssh server vrf default")
            child.expect("config")

        # Configure gRPC protocol if MGBL package is available
        if mgbl:
            child.sendline("grpc")
            child.expect("config-grpc")
            child.sendline(" port 57777")
            child.expect("config-grpc")

        # Commit changes and end
        child.sendline("commit")
        child.expect("config")

        child.sendline("end")
        child.expect(prompt)

        # Spin waiting for an ip address to be associated with the interface
        xr_cli_wait_for_output('sh ipv4 int brief', '10.0.2.15')

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
        xr_cli_wait_for_output('show ipv4 interface MgmtEth0/RP0/CPU0/0', '10.0.2.15')

        logger.debug('Waiting 30 seconds...')
        time.sleep(30)

    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT('Timeout (%s) exceeded in read().' % str(child.timeout))
    finally:
        logger.info("Closing socat session")
        child.close()


def parse_args():
    """Parse sys.argv and return args"""
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
                        help='local ISO filename or remote URI ISO filename')
    parser.add_argument('-o', '--create_ova', action='store_true',
                        help='additionally use VBoxManage to export an OVA')
    parser.add_argument('-s', '--skip_test', action='store_true',
                        help='skip unit testing')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='will exit with the VM in a running state. Use: socat TCP:localhost:65000 -,raw,echo=0,escape=0x1d to access')
    parser.add_argument('-v', '--verbose',
                        action='store_const', const=logging.DEBUG,
                        default=logging.INFO, help='turn on verbose messages')

    return parser.parse_args()


def define_vbox_vm(vmname, base_dir, input_iso):
    """Create and configure (but do not start) the VirtualBox VM."""
    logger.info('Creating and configuring VirtualBox VM')

    # Set the RAM according to mini of full ISO
    if 'mini' in input_iso:
        ram = 3072
        logger.debug('%s is a mini image, RAM allocated is %s MB',
                     input_iso, ram)
    elif 'full' in input_iso:
        ram = 4096
        logger.debug('%s is a full image, RAM allocated is %s MB',
                     input_iso, ram)
    else:
        sys.exit('%s is neither a mini nor a full image. Abort' % input_iso)

    version = run(['VBoxManage', '-v'])
    logger.debug('Virtual Box Manager Version: %s', version)

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    logger.debug('base_dir: %s', base_dir)

    box_dir = os.path.join(base_dir, vmname)
    if not os.path.exists(box_dir):
        os.makedirs(box_dir)
    logger.debug('box_dir:  %s', box_dir)

    vbox = os.path.join(box_dir, vmname + '.vbox')
    logger.debug('vbox:     %s', vbox)

    # Clean up existing vm's
    cleanup_vmname(vmname, delete=True)

    if os.path.exists(vbox):
        # Shouldn't happen if cleanup was successful, but be safe
        os.remove(vbox)

    vdi = os.path.join(box_dir, vmname + '.vdi')
    if os.path.exists(vdi):
        # Ditto failsafe
        os.remove(vdi)

    # Remove stale SSH entry
    logger.debug('Removing stale SSH entries')
    run(['ssh-keygen', '-R', '[localhost]:2222'])
    run(['ssh-keygen', '-R', '[localhost]:2223'])

    # Create and register a new VirtualBox VM
    logger.debug('Create VM')
    run(['VBoxManage', 'createvm', '--name', vmname,
         '--ostype', 'Linux26_64', '--basefolder', base_dir])

    logger.debug('Register VM')
    run(['VBoxManage', 'registervm', vbox])

    # Setup memory, display, cpus etc
    logger.debug('VRAM 12')
    run(['VBoxManage', 'modifyvm', vmname, '--vram', '12'])

    logger.debug('Add ACPI')
    run(['VBoxManage', 'modifyvm', vmname, '--memory', str(ram),
         '--acpi', 'on'])

    logger.debug('Add two CPUs')
    run(['VBoxManage', 'modifyvm', vmname, '--cpus', '2'])

    # Setup networking - including ssh
    logger.debug('Create eight NICs')
    for i in range(1, 9):
        run(['VBoxManage', 'modifyvm', vmname,
             '--nic' + str(i), 'nat', '--nictype' + str(i), 'virtio'])

    # logger.debug('Enable packet capture on Mgmt NIC')
    # run(['VBoxManage', 'modifyvm', vmname, '--nictrace1', 'on',
    #      '--nictracefile1', os.path.join(base_dir, 'Mgmt.pcap')])

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
    run(['VBoxManage', 'modifyvm', vmname,
         '--uart1', '0x3f8', '4', '--uartmode1', 'tcpserver',
         str(CONSOLE_PORT)])

    logger.debug('Add an aux port')
    run(['VBoxManage', 'modifyvm', vmname,
         '--uart2', '0x2f8', '3', '--uartmode2', 'tcpserver',
         str(AUX_PORT)])

    # Option 3: Connect via telnet
    # VBoxManage modifyvm $VMNAME --uart1 0x3f8 4 --uartmode1 tcpserver 6000
    # VBoxManage modifyvm $VMNAME --uart2 0x2f8 3 --uartmode2 tcpserver 6001

    # Setup storage
    logger.debug('Create a HDD')
    run(['VBoxManage', 'createhd', '--filename', vdi, '--size', '46080'])

    logger.debug('Add IDE Controller')
    run(['VBoxManage', 'storagectl', vmname,
         '--name', 'IDE_Controller', '--add', 'ide'])

    logger.debug('Attach HDD')
    run(['VBoxManage', 'storageattach', vmname,
         '--storagectl', 'IDE_Controller', '--port', '0', '--device', '0',
         '--type', 'hdd', '--medium', vdi])

    logger.debug('VM HD info: ')
    run(['VBoxManage', 'showhdinfo', vdi])

    logger.debug('Add DVD drive')
    run(['VBoxManage', 'storageattach', vmname, '--storagectl', 'IDE_Controller', '--port', '1', '--device', '0', '--type', 'dvddrive', '--medium', input_iso])

    # Change boot order to hd then dvd
    logger.debug('Boot order disk first')
    run(['VBoxManage', 'modifyvm', vmname, '--boot1', 'disk'])

    logger.debug('Boot order DVD second')
    run(['VBoxManage', 'modifyvm', vmname, '--boot2', 'dvd'])

    return vbox

def live_config_vbox_vm(vmname, box_dir, verbose, debug=False):
    """Start the VM, add XR and Linux configs, and power it off when done."""
    # Start the VM for installation of ISO - must be started as a sub process
    logger.debug('Starting VM...')
    start_process(['VBoxHeadless', '--startvm', vmname])

    elapsed_time = 0
    while True:
        vms_list_running = run(['VBoxManage', 'list', 'runningvms'])
        if re.search('"' + vmname + '"', vms_list_running):
            logger.debug('Successfully started to boot VM disk image')
            break
        elif elapsed_time < TIMEOUT:
            logger.warning("VM is not yet running after %d seconds; "
                           "sleep %d seconds and retry", elapsed_time,
                           RETRY_INTERVAL)
            time.sleep(RETRY_INTERVAL)
            elapsed_time = elapsed_time + RETRY_INTERVAL
            continue
        else:
            # Dump verbose output in case it helps...
            run(['VBoxManage', 'showvminfo', vmname])
            raise AbortScriptException(
                "VM still not running after {0} seconds!"
                .format(elapsed_time))

    # Configure IOS XR and IOS XR Linux
    configure_xr(verbose)

    # Good place to stop and take a look if --debug was entered
    if debug:
        pause_to_debug()

    # Power off but do not delete the VM
    cleanup_vmname(vmname)

    # Disable uart before exporting
    logger.debug('Remove serial uarts before exporting')
    run(['VBoxManage', 'modifyvm', vmname, '--uart1', 'off'])
    run(['VBoxManage', 'modifyvm', vmname, '--uart2', 'off'])

    # Shrink the VM
    logger.debug('Compact VDI')
    vdi = os.path.join(box_dir, vmname + '.vdi')
    run(['VBoxManage', 'modifymedium', '--compact', vdi])


def vbox_to_vagrant(vmname, box_dir):
    """Package the VirtualBox .vbox into a Vagrant .box."""
    box_out = os.path.join(box_dir, vmname + '.box')
    # Delete existing Box
    if os.path.exists(box_out):
        os.remove(box_out)
        logger.debug('Found and deleted previous %s', box_out)

    logger.info("Generating Vagrant VirtualBox")

    # Add in embedded Vagrantfile
    pathname = os.path.abspath(os.path.dirname(sys.argv[0]))
    vagrantfile_pathname = os.path.join(
        pathname, 'include', 'embedded_vagrantfile')

    run(['vagrant', 'package', '--base', vmname,
         '--vagrantfile', vagrantfile_pathname, '--output', box_out])

    # Delete existing temporary file
    box_tmp = os.path.join(box_dir, vmname)
    if os.path.exists(box_tmp):
        os.remove(box_tmp)
        logger.debug('Found and deleted previous %s', box_tmp)

    logger.info("Adding metadata.json to final box")
    run(['gunzip', '--force', '-S', '.box', box_out])
    with tarfile.open(box_tmp, 'a') as tarf:
        tarf.add(os.path.join(pathname, "metadata.json"))
    run(['gzip', '--force', '-S', '.box', box_tmp])
    # gzip automatically cleans up - no need for os.remove(box_tmp)

    logger.info('Created: %s', box_out)
    return box_out


def vbox_to_ova(vmname, box_dir):
    """Export the VirtualBox VM to OVA format."""
    ova_out = os.path.join(box_dir, vmname + '.ova')

    # Delete existing OVA
    if os.path.exists(ova_out):
        os.remove(ova_out)
        logger.debug('Found and deleted previous %s', ova_out)

    logger.info('Creating OVA %s', ova_out)
    run(['VBoxManage', 'export', vmname, '--output', ova_out])
    logger.debug('Created OVA %s', ova_out)


def main():
    """Main function."""
    input_iso = ''
    create_ova = False

    args = parse_args()

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

    # Set up paths
    base_dir = os.path.join(os.getcwd(), 'machines')

    logger.debug('Input ISO is %s', input_iso)
    logger.debug('VM Name:  %s', vmname)
    logger.debug('base_dir: %s', base_dir)

    vbox = define_vbox_vm(vmname, base_dir, input_iso)

    box_dir = os.path.dirname(vbox)

    try:
        live_config_vbox_vm(vmname, box_dir, args.verbose, args.debug)

        box_out = vbox_to_vagrant(vmname, box_dir)

        # Create OVA
        if create_ova is True:
            vbox_to_ova(vmname, box_dir)
    except:
        if args.debug:
            print("Exception caught:")
            print(sys.exc_info())
            pause_to_debug()
        # Continue with exception handling
        raise
    finally:
        # Attempt to clean up after ourselves even if something went wrong
        cleanup_vmname(vmname, delete=True)

    # Run basic sanity tests unless -s
    if not args.skip_test:
        logger.info('Running basic unit tests on Vagrant VirtualBox...')

        # hackety hack hack hack...
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))

        from iosxr_test import main as test_main
        test_main(box_out, args.verbose)

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


if __name__ == '__main__':
    main()
