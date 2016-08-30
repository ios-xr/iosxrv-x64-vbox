#!/usr/bin/env python
'''
Author: Rich Wellum (richwellum@gmail.com)
Adapted for use with IOS XE by Ralph Schmieder (rschmied@cisco.com)

This is a tool to take an IOS XR Virtual Machine ISO image and convert it into
a Vagrant Virtualbox fully networked and ready for application development.

tested with csr1000v-universalk9.16.03.01.iso (Denali)

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

Takes an IOS XE ISO either locally or remotely and converts it to a virtualbox Vagrant box.

Creates an embedded Vagrantfile, that will be included in
box/include/Vagrantfile. This Vagrantfile configures:

  . Guest forwarding ports for 22, 80, 443 and 830
  . ssh username and password and SSH pub key
  . Serial ports for configuration 

This embedded Vagrantfile is compatible with additional non-embedded
vagrantfiles for more advanced multi-node topologies.

Backs up existing box files.

Creates and registers a new Virtualbox VM.

Adds appropriate memory, display and CPU's.

Sets four NICS for networking.

Sets up port forwarding for the guest SSH, NETCONF and RESTCONF.

Sets up storage - hdd and dvd(for ISO).

Starts the VM, then uses pexpect to configure XE for
basic networking, with user name vagrant/vagrant and SSH key

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
import textwrap

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
                              stderr=subprocess.PIPE)
    tup_output = output.communicate()

    if output.returncode != 0:
        logger.debug('Command failed with code %d:', output.returncode)
    else:
        logger.debug('Command succeeded with code %d:', output.returncode)

    logger.debug('Output for: ' + s_cmd)
    logger.debug(tup_output[0])

    if not hide_error and 0 != output.returncode:
        logger.error('Error output for: ' + s_cmd)
        logger.error(tup_output[1])
        if not cont_on_error:
            sys.exit('Quitting due to run command error')
        else:
            logger.debug(
                'Continuing despite error cont_on_error=%d', cont_on_error)

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


def configure_xe(verbose=False):
    '''
    Bring up XE and do some initial config.
    Using socat to do the connection as telnet has an
    odd double return on vbox
    '''
    logger.info('Logging into Vagrant Virtualbox and configuring IOS XE')

    localhost = 'localhost'
    prompt = r'\w(\(config\))?[#>]'

    def send_line(line):
        child.sendline("\r\n")
        child.expect(prompt)
        child.sendline(line)

    try:
        child = pexpect.spawn(
            "socat TCP:%s:%s -,raw,echo=0,escape=0x1d" % (localhost, CONSOLE_PORT))

        if verbose:
            child.logfile = sys.stdout

        child.timeout = 600  # Long time for full configuration, waiting for ip address etc

        # wait for indication that boot has gone through
        child.expect(r'CRYPTO-6-GDOI_ON_OFF: GDOI is OFF', child.timeout)
        child.sendline("\r\n")  # Send enter
        time.sleep(5)
        child.sendline("\r\n")  # Send enter
        child.expect(prompt)
        send_line("term width 300")

        # enable plus config mode
        send_line("enable")
        send_line("conf t")

        # no TFTP config
        send_line("no logging console")
        time.sleep(5)
        send_line("\r\n")
        send_line("no service config")

        # hostname / domain-name
        send_line("hostname csr1kv")
        send_line("ip domain-name dna.lab")

        # key generation
        send_line("crypto key generate rsa modulus 2048")

        # passwords and username
        send_line("username vagrant priv 15 password vagrant")
        send_line("enable password cisco")
        send_line("enable secret cisco")

        # line configuration
        send_line("line vty 0 4")
        send_line("login local")

        # netconf
        send_line("netconf ssh")
        send_line("netconf-yang")

        # restconf
        send_line("ip http server")
        send_line("ip http secure-server")
        send_line("restconf")

        # ssh vagrant insecure key
        send_line("ip ssh pubkey-chain")
        send_line("username vagrant")
        send_line("key-string")
        send_line("AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eWW6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o9HZyN1Q9qgCgzUFtdOKL")
        send_line("v6IedplqoPkcmF0aYet2PkEDo3MlTBckFXPITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pzC6kivAIhyfHilFR61RGL+G")
        send_line("PXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZEnDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXzcWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ==")
        send_line("exit")

        # done and save
        send_line("end")
        send_line("copy run start")
        send_line("\r\n")

        # just to be sure
        logger.debug('Waiting 10 seconds...')
        time.sleep(10)

    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT(
            'Timeout (%s) exceeded in read().' % str(child.timeout))


def main(argv):
    input_iso = ''
    create_ova = False

    parser = argparse.ArgumentParser(
        formatter_class = argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent('''\
            A tool to create an IOS XE Vagrant VirtualBox box from an IOS XE ISO.

            The ISO will be installed, booted, configured 

            "vagrant ssh" provides access to IOS XE management interface
            with internet access.
        '''),

        epilog=textwrap.dedent('''\
            E.g.:
                box build with local iso: 
                    %(prog)s csr1000v-universalk9.16.03.01.iso
                box build with remote iso: 
                    %(prog)s user@server:/myboxes/csr1000v-universalk9.16.03.01.iso
        '''))

    parser.add_argument('ISO_FILE',
                        help='local ISO filename or remote URI ISO filename')
    parser.add_argument('-o', '--create_ova', action='store_true',
                        help='additionally use VBoxManage to export an OVA')
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
        logger.debug(
            'Will attempt to scp the remote image to current working dir. You may be required to enter your password.')
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

    ram = 4096
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
    run(['VBoxManage', 'createvm', '--name', vmname,
         '--ostype', 'Linux26_64', '--basefolder', base_dir])

    logger.debug('Register VM')
    run(['VBoxManage', 'registervm', vbox])

    # Setup memory, display, cpus etc
    logger.debug('VRAM 6')
    run(['VBoxManage', 'modifyvm', vmname, '--vram', '4'])

    logger.debug('Add ACPI')
    run(['VBoxManage', 'modifyvm', vmname, '--memory', str(ram), '--acpi', 'on'])

    #logger.debug('Add one CPU')
    #run(['VBoxManage', 'modifyvm', vmname, '--cpus', '2'])

    # Setup networking - including ssh
    logger.debug('Create NICs')
    run(['VBoxManage', 'modifyvm', vmname, '--nic1', 'nat', '--nictype1', '82540EM'])
    run(['VBoxManage', 'modifyvm', vmname, '--cableconnected1', 'on'])
    run(['VBoxManage', 'modifyvm', vmname, '--nic2', 'nat', '--nictype2', '82540EM'])
    run(['VBoxManage', 'modifyvm', vmname, '--cableconnected2', 'off'])
    run(['VBoxManage', 'modifyvm', vmname, '--nic3', 'nat', '--nictype3', '82540EM'])
    run(['VBoxManage', 'modifyvm', vmname, '--cableconnected3', 'off'])
    run(['VBoxManage', 'modifyvm', vmname, '--nic4', 'nat', '--nictype4', '82540EM'])
    run(['VBoxManage', 'modifyvm', vmname, '--cableconnected4', 'off'])
    #run(['VBoxManage', 'modifyvm', vmname, '--nic5', 'nat', '--nictype5', 'virtio'])
    #run(['VBoxManage', 'modifyvm', vmname, '--nic6', 'nat', '--nictype6', 'virtio'])
    #run(['VBoxManage', 'modifyvm', vmname, '--nic7', 'nat', '--nictype7', 'virtio'])
    #run(['VBoxManage', 'modifyvm', vmname, '--nic8', 'nat', '--nictype8', 'virtio'])

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
    run(['VBoxManage', 'modifyvm', vmname, '--uart1', '0x3f8',
         '4', '--uartmode1', 'tcpserver', str(CONSOLE_PORT)])

    logger.debug('Add an aux port')
    run(['VBoxManage', 'modifyvm', vmname, '--uart2', '0x2f8',
         '3', '--uartmode2', 'tcpserver', str(AUX_PORT)])

    # Option 3: Connect via telnet
    # VBoxManage modifyvm $VMNAME --uart1 0x3f8 4 --uartmode1 tcpserver 6000
    # VBoxManage modifyvm $VMNAME --uart2 0x2f8 3 --uartmode2 tcpserver 6001

    # Setup storage
    logger.debug('Create a HDD')
    run(['VBoxManage', 'createhd', '--filename', vdi, '--size', '16384'])

    logger.debug('Add IDE Controller')
    run(['VBoxManage', 'storagectl', vmname,
         '--name', 'IDE_Controller', '--add', 'ide'])

    logger.debug('Attach HDD')
    run(['VBoxManage', 'storageattach', vmname, '--storagectl', 'IDE_Controller',
         '--port', '0', '--device', '0', '--type', 'hdd', '--medium', vdi])

    logger.debug('VM HD info: ')
    run(['VBoxManage', 'showhdinfo', vdi])

    logger.debug('Add DVD drive')
    run(['VBoxManage', 'storageattach', vmname, '--storagectl', 'IDE_Controller',
         '--port', '1', '--device', '0', '--type', 'dvddrive', '--medium', input_iso])

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

    # Configure IOS XR and IOS XR Linux
    # do print steps for logging set to DEBUG
    # default is INFO
    print(args.verbose)
    configure_xe(args.verbose < logging.INFO)

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
    #logger.debug('Remove serial uarts before exporting')
    #run(['VBoxManage', 'modifyvm', vmname, '--uart1', 'off'])
    #run(['VBoxManage', 'modifyvm', vmname, '--uart2', 'off'])

    # Shrink the VM
    logger.debug('Compact VDI')
    run(['VBoxManage', 'modifymedium', '--compact', vdi])

    logger.debug('Building Vagrant box')

    # Add in embedded Vagrantfile
    vagrantfile_pathname = os.path.join(
        pathname, 'include', 'embedded_vagrantfile_xe')

    run(['vagrant', 'package', '--base', vmname, '--vagrantfile',
         vagrantfile_pathname, '--output', box_out])
    logger.info('Created: %s', box_out)

    # Create OVA
    if create_ova is True:
        logger.info('Creating OVA %s', ova_out)
        run(['VBoxManage', 'export', vmname, '--output', ova_out])
        logger.debug('Created OVA %s', ova_out)

    # Clean up VM used to generate box
    cleanup_vmname(vmname, vbox)

    logger.info("vagrant init iosxe")
    logger.info("vagrant box add --name iosxe %s --force", box_out)
    logger.info('vagrant up')

    logger.info(
        'Note that both the XE Console and NETCONF/RESTCONF username and password is vagrant/vagrant')

if __name__ == '__main__':
    main(sys.argv[1:])
