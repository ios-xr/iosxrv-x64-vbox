#!/usr/bin/python
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

Starts the VM, then uses iosxr_pexpect.py and iosxr_setup.py to configure
XR and XR Aux for basic networking and XR Linux usage, with user name
vagrant/vagrant.

Closes the VM down once configured and then waits for vagrant ssh to be
confirmed.

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

# Telnet ports used to access IOS XR via socat
console_port = 65000
aux_port = 65001

logger = logging.getLogger(__name__)


def set_logging():
    FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
    logging.basicConfig(format=FORMAT)


def cleanup_vms(name, box_name):
    '''
    Cleans up any running box with the passed in name.
    Unregisters and deletes any box with the passed in box_name.
    Repeats for and default VM's.
    '''
    regex_list = [name, 'default']

    # Remove any running boxes with the same name
    vms_list_running = run(['vboxmanage', 'list', 'runningvms'])
    for regex in regex_list:
        if re.search(regex, vms_list_running):
            logger.debug("'%s' is running, powering off..." % regex)
            run(['VBoxManage', 'controlvm', regex, 'poweroff'])
        else:
            logger.debug("'%s' is not running, nothing to poweroff" % name)

    # Unregister and delete any boxes with the same name
    vms_list = run(['vboxmanage', 'list', 'vms'])
    for regex in regex_list:
        if re.search(regex, vms_list):
            logger.debug("'%s' is registered, unregistering and deleting" % name)
            run(['VBoxManage', 'unregistervm', box_name, '--delete'])
        else:
            logger.debug("'%s' is not registered, nothing to unregister and delete" % name)


def runxx(argv):
    logger.debug('argv: %s', argv)
    if verbose:
        subprocess.check_call(argv)
        return ""
    else:
        output = subprocess.check_output(argv, stderr=subprocess.STDOUT)
        logger.debug(output)
        return output


def run(cmd, hide_error=False, cont_on_error=False):
    '''
    Add description here
    '''
    # if hide_error and verbose:
    # raise ValueError("cannot specify both verbose and hide_error as true")

    output = subprocess.Popen(cmd,
                              stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    tup_output = output.communicate()

    s_cmd = ' '.join(cmd)
    logger.debug("command: '%s'\n" % s_cmd)

    if 0 != output.returncode:
        logger.debug('Command failed with code %d:' % output.returncode)
    else:
        logger.debug('Command succeeded with code %d:' % output.returncode)

    logger.debug('Output for: ' + s_cmd)
    logger.debug(tup_output[0])

    if not hide_error and 0 != output.returncode:
        print('Error output for: ' + s_cmd)
        print(tup_output[1])
        if not cont_on_error:
            sys.exit(0)
        else:
            logger.debug('Continuing despite error cont_on_error=%d' % cont_on_error)

    return tup_output[0]


def run2(args):
    '''
    Execute a CLI command. Arguments in the form of a list.
    Displays args and output when verbose.
    Always returns errors.
    Returns output.
    '''
    output = subprocess.Popen((args),
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).communicate()[0]
    logger.debug('args: %s' % args)
    logger.debug(output)
    return output


def start_vboxheadless(args):
    '''
    Start vboxheadless process
    '''
    logger.debug('args: %s' % args)
    with open(os.devnull, 'w') as fp:
        subprocess.Popen((args), stdout=fp)
    time.sleep(2)


def main(argv):
    input_iso = ''
    copy_to_artifactory = False
    create_ova = False
    artifactory_reason = ''
    global verbose

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
    parser.add_argument('-a', '--artifactory', nargs='?', metavar="'New box reason'",
                        const='No reason for update specified',
                        help='Upload box to Artifactory. You can optionally specify a reason for uploading this box.')
    parser.add_argument('-o', '--create_ova', action='store_true',
                        help='additionally use vboxmanage to export an OVA')
    parser.add_argument('-v', '--verbose',
                        action='store_const', const=logging.DEBUG,
                        default=logging.INFO, help='turn on verbose messages')

    args = parser.parse_args()

    # Handle Input ISO (Local or URI)
    if re.search(':/', args.ISO_FILE):
        # URI Image
        cmd_string = 'scp %s@%s .' % (getpass.getuser(), args.ISO_FILE)
        logger.debug('==> Will attempt to scp the remote image to current working dir. You may be required to enter your password.')
        logger.debug('==> %s\n' % cmd_string)
        subprocess.call(cmd_string, shell=True)
        input_iso = os.path.basename(args.ISO_FILE)
    else:
        # Local image
        input_iso = args.ISO_FILE

    # Handle artifactory
    if args.artifactory is not None:
        copy_to_artifactory = True
        if args.artifactory is not 'No reason for update specified':
            artifactory_reason = args.artifactory

    # Handle create OVA
    create_ova = args.create_ova

    if not os.path.exists(input_iso):
        sys.exit('==>', input_iso, 'does not exist')

    # Set Virtualbox VM name from the input ISO
    vmname = os.path.basename(os.path.splitext(input_iso)[0])

    set_logging()
    logger.setLevel(level=args.verbose)

    verbose = args.verbose

    logger.debug('Input ISO is %s' % input_iso)

    # Set the RAM according to mini of full ISO
    if 'mini' in input_iso:
        ram = 3072
        logger.debug('%s is a mini image, RAM allocated is %s MB' % (input_iso, ram))
    elif 'full' in input_iso:
        ram = 4096
        logger.debug('%s is a full image, RAM allocated is %s MB' % (input_iso, ram))
    else:
        sys.exit('%s is neither a mini nor a full image. Abort' % input_iso)

    logger.info('Creating Vagrant VirtualBox')

    version = run(['VBoxManage', '-v'])
    logger.debug('Virtual Box Manager Version: %s' % version)

    # Set up paths
    base_dir = os.path.join(os.getcwd(), 'machines')
    box_dir = os.path.join(base_dir, vmname)
    vbox = os.path.join(box_dir, vmname + '.vbox')
    vdi = os.path.join(box_dir, vmname + '.vdi')
    box_out = os.path.join(box_dir, vmname + '.box')
    ova_out = os.path.join(box_dir, vmname + '.ova')
    pathname = os.path.abspath(os.path.dirname(sys.argv[0]))

    logger.debug('pathname: %s' % pathname)
    logger.debug('VM Name:  %s' % vmname)
    logger.debug('base_dir: %s' % base_dir)
    logger.debug('box_dir:  %s' % box_dir)
    logger.debug('box_out:  %s' % box_out)

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    if not os.path.exists(box_dir):
        os.makedirs(box_dir)

    # Delete existing Box
    if os.path.exists(box_out):
        os.remove(box_out)
        logger.debug('Found and deleted previous %s' % box_out)

    # Delete existing OVA
    if os.path.exists(ova_out) and create_ova is True:
        os.remove(ova_out)
        logger.debug('Found and deleted previous %s' % ova_out)

    # Destroy default vagrant box
    # logger.debug('Destroy default box')
    # run(['vagrant', 'destroy', '--force'], cont_on_error=True)

    # Clean up existing vm's
    cleanup_vms(vmname, vbox)

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

    logger.debug('Add two CPUs')
    run(['VBoxManage', 'modifyvm', vmname, '--cpus', '2'])

    # Setup networking - including ssh
    logger.debug('Create four NICs')
    run(['VBoxManage', 'modifyvm', vmname, '--nic1', 'nat', '--nictype1', 'virtio'])
    run(['VBoxManage', 'modifyvm', vmname, '--nic2', 'nat', '--nictype2', 'virtio'])
    run(['VBoxManage', 'modifyvm', vmname, '--nic3', 'nat', '--nictype3', 'virtio'])
    run(['VBoxManage', 'modifyvm', vmname, '--nic4', 'nat', '--nictype4', 'virtio'])

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

    # Option 2: Connect via socat (using this for iosxr_pexpect.py connect
    # as telnet has double echo issue)
    # But can still use telnet in conjunction with socat
    # cmd_string='VBoxManage modifyvm %s --uart1 0x3f8 4 --uartmode1 server /tmp/serial1' % vmname
    logger.debug('Add a console port')
    run(['VBoxManage', 'modifyvm', vmname, '--uart1', '0x3f8', '4', '--uartmode1', 'tcpserver', str(console_port)])

    logger.debug('Add an aux port')
    run(['VBoxManage', 'modifyvm', vmname, '--uart2', '0x2f8', '3', '--uartmode2', 'tcpserver', str(aux_port)])

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

    # Change boot order to hd then dvd
    logger.debug('Boot order disk first')
    run(['vboxmanage', 'modifyvm', vmname, '--boot1', 'disk'])

    logger.debug('Boot order DVD second')
    run(['vboxmanage', 'modifyvm', vmname, '--boot2', 'dvd'])

    # Print some information about the VM
    # logger.debug('VM Info:')
    # run(['VBoxManage', 'showvminfo', vmname])

    # Start the VM for installation of ISO - must be started as a sub process
    logger.debug('Starting VM...')
    start_vboxheadless(['VBoxHeadless', '--startvm', vmname])

    # while True:
    for x in range(0, 3):
        vms_list = run(['VBoxManage', 'showvminfo', vmname])
        if 'running (since' in vms_list:
            logger.debug('Successfully started to boot VM disk image')
            break
        else:
            logger.warning('Failed to install VM disk image\n')
            continue

    # Use iosxr_pexpect.py to bring up XR and do some initial config.
    # Using socat to do the connection as telnet has an
    # odd double return on vbox
    # logger.info('Bringing up with iosxr_pexpect.py to install to disk and configure')
    logger.info('Bring XRv up and configure')
    # iosxr_pexpect_path = os.path.join(pathname, 'iosxr_pexpect.py')
    if args.verbose == logging.DEBUG:
        logger.debug('Verbose enabled')
        verbose_str = '-v'
    else:
        # Shhhh...
        logger.debug('Verbose not enabled')
        verbose_str = ''

    # cmd_string = "python %s %s -cmds 'socat TCP:localhost:%s -,raw,echo=0,escape=0x1d' -config iosxr_setup" % (verbose_str, iosxr_pexpect_path, console_port)
    # Call socat connection from a script so it can be run in the background
    # f = open('runme.sh', 'w')
    # f.write(cmd_string)
    # f.close()
    # rc = subprocess.call("chmod 766 ./runme.sh; ./runme.sh %s" % verbose_pipe, shell=True)
    # if rc == 0:
    #     sys.exit('Configuring XR failed, exiting')

    # Try again
    # run(['python', verbose_str, iosxr_pexpect_path, '-cmds', "socat TCP:localhost:%s -,raw,echo=0,escape=0x1d" % console_port, '-config', 'iosxr_setup'])
    localhost = 'localhost'

    try:
        child = pexpect.spawn("socat TCP:%s:%s -,raw,echo=0,escape=0x1d" % (localhost, console_port))
        if args.verbose == logging.DEBUG:
            child.logfile = sys.stdout
            # child.logfile = open("/tmp/mylog", "w")

        child.timeout = 10000  # Long time for full configuration, waiting for ip address etc
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
        child.expect("[$#]")

        # ZTP causes some startup issues so disable it during box creation
        child.sendline("ztp terminate noprompt")
        child.expect("[$#]")

        # Determine if the image is a crypto/k9 image or not
        # This will be used to determine whether to configure ssh or not
        child.sendline("bash -c rpm -qa | grep k9sec")
        o = child.expect('-k9sec')
        if o == 0:
            k9 = True
            logger.debug("Crypto k9 image detected")
        else:
            k9 = False
            logger.debug("Non crypto k9 image detected")

        # output = child.read()

        # Determine if the image has the MGBL package needed for gRPC
        child.sendline("bash -c rpm -qa | grep mgbl")
        o = child.expect('-mgbl')
        if o == 0:
            mgbl = True
            logger.debug("MGBL package detected")
        else:
            mgbl = False
            logger.debug("MGBL package not detected")

        # Wait for a management interface to be available
        child.sendline("sh run | inc MgmtEth")
        child.expect("interface MgmtEth")

        child.sendline("conf t")
        child.expect("ios.config.*#", 10)

        # Enable telnet
        child.sendline("telnet vrf default ipv4 server max-servers 10")
        child.expect("config")

        child.sendline("show run")
        print(child.read)

        # Bring up dhcp on MGMT for vagrant access
        child.sendline("interface MgmtEth0/RP0/CPU0/0")
        child.sendline(" ipv4 address dhcp")
        child.sendline(" no shutdown")
        child.expect("config-if")

        # TPA source update
        child.sendline("tpa address-family ipv4 update-source MgmtEth0/RP0/CPU0/0")
        child.expect("config")

        child.sendline("router static address-family ipv4 unicast 0.0.0.0/0 MgmtEth0/RP0/CPU0/0 10.0.0.2")
        child.expect("config")

        # Configure ssh if a k9/crypto image
        if k9:
            child.sendline("ssh server v2")
            child.expect("config")
            child.sendline("ssh server vrf default")
            child.expect("config")

        # Configure gRPC protocol if MGBL package is available
        if mgbl:
            child.sendline("grpc")
            child.sendline(" port 57777")
            child.expect("config-grpc")

        # Commit changes and end
        child.sendline("commit")
        child.expect("config")

        child.sendline("end")
        child.expect("[$#]")

        # Spin waiting for an ip address to be associated with the interface
        while True:
            try:
                child.sendline("sh ipv4 int brief | i 10.0.2.15")
                child.expect("10.0.2.15", 5)
                # output = child.read()
                # if re.search(r"10.0.0.15", output, re.MULTILINE):
                # logger.debug("HERE1")
                break
            except pexpect.TIMEOUT:
                time.sleep(5)
                logger.debug("Waiting 5s then checking for dhcp ip address")
                continue

        # Needed for jenkins if using root password
        child.sendline("bash -c sed -i 's/PermitRootLogin no/PermitRootLogin yes/' /etc/ssh/sshd_config_operns")

        # Add passwordless sudo as required by jenkins sudo not
        # vagrant because we are operating in xrnns and global-vrf
        # user space
        child.sendline("bash -c echo '####Added by iosxr_setup to give vagrant passwordless access' | (EDITOR='tee -a' visudo)")
        child.sendline("bash -c echo 'vagrant ALL=(ALL) NOPASSWD: ALL' | (EDITOR='tee -a' visudo)")

        # Add public key, so users can ssh without a password
        # https://github.com/purpleidea/vagrant-builder/blob/master/v6/files/ssh.sh
        child.sendline("bash -c [ -d ~vagrant/.ssh ] || mkdir ~vagrant/.ssh")
        child.sendline("bash -c chmod 0700 ~vagrant/.ssh")
        child.sendline("bash -c echo 'ssh-rsa AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eWW6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXPITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pzC6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZEnDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXzcWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ== vagrant insecure public key' > ~vagrant/.ssh/authorized_keys")
        child.sendline("bash -c chmod 0600 ~vagrant/.ssh/authorized_keys")
        child.sendline("bash -c chown -R vagrant:vagrant ~vagrant/.ssh/")

        # output = self.send_operns('ls -ld /misc/app_host/scratch')
        # if not re.search('/misc/app_host/scratch', output):
        #     # Add user scratch space - should be able transfer a file to
        #     # /misc/app_host/scratch using the scp with user vagrant
        #     # E.g: scp -P 2200 Vagrantfile vagrant@localhost:/misc/app_host/scratch
        #     child.sendline("bash -c groupadd app_host")
        #     child.sendline("bash -c usermod -a -G app_host vagrant")
        #     child.sendline("bash -c mkdir -p /misc/app_host/scratch")
        #     child.sendline("bash -c chgrp -R app_host /misc/app_host/scratch")
        #     child.sendline("bash -c chmod 777 /misc/app_host/scratch")

        # Add Cisco OpenDNS IPv4 nameservers as a default DNS resolver
        # almost all users who have internet connectivity will be able to reach those.
        # This will prevent users from needing to supply another Vagrantfile or editing /etc/resolv.conf manually
        # Doing this in xrnns because the syncing of /etc/netns/global-vrf/resolv.conf to
        # /etc/resolv.conf requires 'ip netns exec global-vrf bash'.
        child.sendline("run echo '# Cisco OpenDNS IPv4 nameservers' >> /etc/resolv.conf")
        child.sendline("run echo 'nameserver 208.67.222.222' >> /etc/resolv.conf")
        child.sendline("run echo 'nameserver 208.67.220.220' >> /etc/resolv.conf")

        # Start operns sshd server so vagrant ssh can access app-hosting space
        child.sendline("bash -c service sshd_operns start")

        # Wait for it to come up
        while True:
            child.sendline("bash -c service sshd_operns status")
            o = child.expect('is running...')
            if o == 0:
                break
            else:
                time.sleep(5)
                continue

        child.sendline("bash -c chkconfig --add sshd_operns")

        child.expect("RP/0/RP0/CPU0:ios")

        # Set up IOS XR ssh if a k9/crypto image
        if k9:
            child.sendline("crypto key generate rsa")
            child.expect("How many bits in the modulus")
            child.sendline("")  # Send enter to get default 2048
            child.expect("[$#]")  # Wait for the prompt

    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT('Timeout (%s) exceeded in read().' % str(child.timeout))
    # Powerdown VM prior to exporting
    logger.debug('Waiting for machine to shutdown')
    run(['VBoxManage', 'controlvm', vmname, 'poweroff'])

    while True:
        vms_list_running = run(['vboxmanage', 'list', 'runningvms'])

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
    logger.info('Created: %s' % box_out)

    # Create OVA
    if create_ova is True:
        logger.info('Creating OVA %s' % ova_out)
        run(['VBoxManage', 'export', vmname, '--output', ova_out])
        logger.debug('Created OVA %s' % ova_out)

    # Run basic sanity tests
    logger.info('Running basic unit tests on VirtualBox...')
    iosxr_test_path = os.path.join(pathname, 'iosxr_test.py')
    cmd_string = "python %s %s %s" % (iosxr_test_path, box_out, verbose_str)
    result = (subprocess.check_output(cmd_string, shell=True))
    if result is False:
        # Fail noisily
        sys.exit('Failed basic test, box %s is not sane' % box_out)
    else:
        logger.info('Passed basic test, box %s is sane' % box_out)

    logger.debug('Single node use:')
    logger.debug(" vagrant init 'IOS XRv'")
    logger.debug(" vagrant box add --name 'IOS XRv' %s --force" % box_out)
    logger.debug(' vagrant up')

    logger.debug('Multinode use:')
    logger.debug(" Copy './iosxrv-x64-vbox/vagrantfiles/simple-mixed-topo/Vagrantfile' to the directory running vagrant and do:")
    logger.debug(" vagrant box add --name 'IOS XRv' %s --force" % box_out)
    logger.debug(' vagrant up')
    logger.debug(" Or: 'vagrant up rtr1', 'vagrant up rtr2'")

    logger.debug('Note that both the XR Console and the XR linux shell username and password is vagrant/vagrant')

    # Clean up existing vm's
    cleanup_vms(vmname, vbox)

    # Clean up Vagrantfile
    try:
        os.remove('Vagrantfile')
    except OSError:
        pass

    if copy_to_artifactory is True:
        logger.info('Copying Vagrant Virtualbox to Artifactory')
        iosxr_store_box_path = os.path.join(pathname, 'iosxr_store_box.py')
        if args.verbose == logging.DEBUG:
            add_verbose = '-v'

        cmd_string = "python %s %s %s -m '%s'" % (iosxr_store_box_path, box_out, add_verbose, artifactory_reason)
        subprocess.call(cmd_string, shell=True)

if __name__ == '__main__':
    main(sys.argv[1:])
