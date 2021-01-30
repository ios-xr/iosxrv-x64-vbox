#!/usr/bin/env python
'''
Author: Rich Wellum (richwellum@gmail.com)
    Adapted and enhanced (fwiw) for use with IOS XE
    by Ralph Schmieder (rschmied@cisco.com)

This is a tool to take an IOS XE Virtual Machine ISO image and convert it into
a Vagrant box (using VirtualBox), fully networked and ready NETCONF/RESTCONF.

Tested with csr1000v-universalk9.16.03.01.iso (Denali)

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

Takes an IOS XE ISO either locally or remotely and converts it to a VirtualBox Vagrant box.

Adds an embedded Vagrantfile, that will be included in
box/include/Vagrantfile. This Vagrantfile configures:

  . Guest forwarding ports for 22, 80, 443 and 830
  . SSH username and password and SSH (insecure) pub key
  . Serial console port for configuration (disconnected by default)

This embedded Vagrantfile is compatible with additional non-embedded
Vagrantfiles for more advanced multi-node topologies.

  . Backs up existing box files.
  . Creates and registers a new VirtualBox VM.
  . Adds appropriate memory, display and CPUs.
  . Sets one NIC for networking.
  . Sets up port forwarding for the guest SSH, NETCONF and RESTCONF.
  . Sets up storage - hdd and dvd(for ISO).
  . Starts the VM, then uses pexpect to configure XE for
    basic networking, with user name vagrant/vagrant and SSH key
  . Configures NETCONF and RESTCONF (config and operational data)
  . Closes the VM down, once configured.

The resultant box image, will come up fully networked and ready for use
with RESTCONF and NETCONF.

NOTE: If more than one interface in the resulting Vagrant box is required
      then those additional interfaces need to be added in the actual
      Vagrantfile.
'''

from __future__ import print_function
import sys
import os
import time
import subprocess
import getpass
import argparse
import re
import logging
import hashlib
from logging import StreamHandler
from whichcraft import which
import textwrap
import tempfile
import pexpect.exceptions

try:
    import pexpect
except ImportError:
    sys.exit('The "pexpect" Python module is not installed. Please install it using pip or OS packaging.')


# Telnet ports used to access IOS XE via socat
CONSOLE_PORT = 65000

# The background is set with 40 plus the number of the color,
# and the foreground with 30.
BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)


logger = logging.getLogger(__name__)


class ColorHandler(StreamHandler):
    """
    Add colors to logging output
    partial credits to
    http://opensourcehacker.com/2013/03/14/ultima-python-logger-somewhere-over-the-rainbow/
    """

    def __init__(self, colored):
        super(ColorHandler, self).__init__()
        self.colored = colored

    COLORS = {
        'WARNING': YELLOW,
        'INFO': WHITE,
        'DEBUG': BLUE,
        'CRITICAL': YELLOW,
        'ERROR': RED
    }

    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[1;%dm"
    BOLD_SEQ = "\033[1m"

    level_map = {
        logging.DEBUG: (None, CYAN, False),
        logging.INFO: (None, WHITE, False),
        logging.WARNING: (None, YELLOW, True),
        logging.ERROR: (None, RED, True),
        logging.CRITICAL: (RED, WHITE, True),
    }

    def addColor(self, text, bg, fg, bold):
        ctext = ''
        if bg is not None:
            ctext = self.COLOR_SEQ % (40 + bg)
        if bold:
            ctext = ctext + self.BOLD_SEQ
        ctext = ctext + self.COLOR_SEQ % (30 + fg) + text + self.RESET_SEQ
        return ctext

    def colorize(self, record):
        if record.levelno in self.level_map:
            bg, fg, bold = self.level_map[record.levelno]
        else:
            bg, fg, bold = None, WHITE, False

        # exception?
        if record.exc_info:
            formatter = logging.Formatter(format)
            record.exc_text = self.addColor(
                formatter.formatException(record.exc_info), bg, fg, bold)

        record.msg = self.addColor(str(record.msg), bg, fg, bold)
        return record

    def format(self, record):
        if self.colored:
            message = logging.StreamHandler.format(self, self.colorize(record))
        else:
            message = logging.StreamHandler.format(self, record)
        return message


def run(cmd, hide_error=False, cont_on_error=False):
    """
    Run command to execute CLI and catch errors and display them whether
    in verbose mode or not.

    Allow the ability to hide errors and also to continue on errors.
    """

    s_cmd = ' '.join(cmd)
    logger.info("'%s'", s_cmd)

    output = subprocess.Popen(cmd,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    tup_output = output.communicate()

    if output.returncode != 0:
        logger.error('Failed (%d):', output.returncode)
    else:
        logger.debug('Succeeded (%d):', output.returncode)

    logger.debug('Output [%s]' % tup_output[0])

    if not hide_error and 0 != output.returncode:
        logger.error('Error [%s]' % tup_output[1])
        if not cont_on_error:
            sys.exit('Quitting due to run command error')
        else:
            logger.debug(
                'Continuing despite error cont_on_error=%d', cont_on_error)

    return tup_output[0].decode()


def cleanup_vmname(name, box_name):
    """
    Cleanup and unregister (delete) our working box.
    """

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
    logger.critical("Pause before debug")
    logger.critical(
        "Use: 'socat TCP:localhost:65000 -,raw,echo=0,escape=0x1d' to access the VM")
    raw_input("Press Enter to continue.")
    # To debug post box creation, add the following line to Vagrantfile
    # config.vm.provider "virtualbox" do |v|
    #   v.customize ["modifyvm", :id, "--uart1", "0x3F8", 4, "--uartmode1", 'tcpserver', 65000]
    # end


def start_process(args):
    """
    Start vboxheadless process
    """

    logger.debug('args: %s', args)
    with open(os.devnull, 'w') as fp:
        subprocess.Popen((args), stdout=fp)
    time.sleep(2)


def configure_xe(verbose=False, wait=True):
    """
    Bring up XE and do some initial config.
    Using socat to do the connection as telnet has an
    odd double return on vbox
    """

    logger.warn('Waiting for IOS XE to boot (may take 3 minutes or so)')
    localhost = 'localhost'

    PROMPT = r'[\w-]+(\([\w-]+\))?[#>]'
    # don't want to rely on specific hostname
    # PROMPT = r'(Router|csr1kv).*[#>]'
    CRLF = "\r\n"

    def send_line(line=CRLF):
        child.sendline(line)
        if line != CRLF:
            logger.info('IOS Config: %s' % line)
            child.expect(re.escape(line))

    def send_cmd(cmd):
        if not isinstance(cmd, list):
            cmd = list((cmd,))
        for c in cmd:
            send_line(c)
        child.expect(PROMPT)

    try:
        # child = pexpect.spawn("socat TCP:%s:%s -,raw,echo=0,escape=0x1d" % (localhost, CONSOLE_PORT))
        child = pexpect.spawn("telnet %s %s" % (localhost, CONSOLE_PORT))

        if verbose:
            child.logfile = open("tmp.log", "w")

        # Long time for full configuration, waiting for ip address etc
        child.timeout = 600

        # wait for indication that boot has gone through
        if (wait):
            child.expect(r'Press RETURN to get started!', child.timeout)
            # child.expect(r'CRYPTO-6-GDOI_ON_OFF: GDOI is OFF', child.timeout)
            logger.warn(
                'Logging into Vagrant Virtualbox and configuring IOS XE')

        send_line()
        time.sleep(5)
        send_line()

        # enable plus config mode, but remember to set term len to 0
        # first, or, as of a 16.12 IOS XE image, the config won't save
        # properly
        send_cmd("enable")
        send_cmd("term len 0")
        send_cmd("term width 300")
        send_cmd("conf t")

        # no TFTP config
        send_cmd("no logging console")
        time.sleep(5)
        send_cmd("no service config")

        # configure DHCP on Gi1
        send_cmd("interface GigabitEthernet1")
        send_cmd("ip address dhcp")
        send_cmd("no shutdown")
        send_cmd("no negotiation auto")
        send_cmd("no speed")
        send_cmd("exit")

        # restconf & netconf
        send_cmd("netconf-yang")
        send_cmd("ip http server")
        send_cmd("ip http secure-server")
        send_cmd("restconf")

        # hostname / domain-name
        send_cmd("hostname csr1kv")
        send_cmd("domain dna.lab")
        send_cmd("exit")

        # key generation
        # send_cmd("crypto key generate rsa modulus 2048")
        # time.sleep(5)

        # passwords and username
        send_line()
        send_cmd("username vagrant priv 15 password vagrant")
        send_cmd("enable password cisco")
        send_cmd("enable secret cisco123")
        send_cmd("ip ssh server algorithm authentication password publickey")

        # line configuration
        send_cmd("line vty 0 4")
        send_cmd("login local")
        send_cmd("transport input ssh")

        # ssh vagrant insecure public key
        send_cmd("ip ssh pubkey-chain")
        send_cmd("username vagrant")
        send_cmd("key-string")
        send_cmd("AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eW")
        send_cmd("W6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o")
        send_cmd("9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXP")
        send_cmd("ITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pz")
        send_cmd("C6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZE")
        send_cmd("nDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXz")
        send_cmd("cWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ==")
        send_cmd("exit")

        # done and save
        send_cmd("end")
        send_cmd("wr mem")
        # send_cmd(["copy run start", CRLF])

        # just to be sure
        logger.warn('Waiting 10 seconds...')
        time.sleep(10)

    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT('Timeout (%s) exceeded in read().' % str(child.timeout))


def configure_wait_only(verbose=False, wait=True):
    """
    Bring up virtual image with the assumption that config is provided by
    other means, namely a config ISO, and this routine only has to wait
    for that.
    """

    logger.warn('Waiting for IOS XE to boot (may take 3 minutes or so)')
    localhost = 'localhost'

    PROMPT = r'[\w-]+(\([\w-]+\))?[#>]'
    # don't want to rely on specific hostname
    # PROMPT = r'(Router|csr1kv).*[#>]'
    CRLF = "\r\n"

    def send_line(line=CRLF):
        child.sendline(line)
        if line != CRLF:
            logger.info('IOS Config: %s' % line)
            child.expect(re.escape(line))

    def send_cmd(cmd):
        if not isinstance(cmd, list):
            cmd = list((cmd,))
        for c in cmd:
            send_line(c)
        child.expect(PROMPT)

    try:
        # child = pexpect.spawn("socat TCP:%s:%s -,raw,echo=0,escape=0x1d" % (localhost, CONSOLE_PORT))
        child = pexpect.spawn("telnet %s %s" % (localhost, CONSOLE_PORT))

        if verbose:
            child.logfile = open("tmp.log", "w")

        # Long time for full configuration, waiting for ip address etc
        child.timeout = 600

        # wait for indication that boot has gone through
        if (wait):
            child.expect(r'Press RETURN to get started!', child.timeout)

        time.sleep(5)
        send_line()
        send_line()
        time.sleep(60)
        
    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT('Timeout (%s) exceeded in read().' % str(child.timeout))


def configure_c8000v(verbose=False, wait=True):
    """
    Bring up Catalyst 8000v  and do some initial config.
    Using socat to do the connection as telnet has an
    odd double return on vbox
    """

    logger.warn('Waiting for IOS XE to boot (may take 3 minutes or so)')
    localhost = 'localhost'

    PROMPT = r'[\w-]+(\([\w-]+\))?[#>]'
    # don't want to rely on specific hostname
    # PROMPT = r'(Router|csr1kv).*[#>]'
    CRLF = "\r\n"

    def send_line(line=CRLF):
        child.sendline(line)
        if line != CRLF:
            logger.info('IOS Config: %s' % line)
            child.expect(re.escape(line))

    def send_cmd(cmd):
        if not isinstance(cmd, list):
            cmd = list((cmd,))
        for c in cmd:
            send_line(c)
        child.expect(PROMPT)

    try:
        # child = pexpect.spawn("socat TCP:%s:%s -,raw,echo=0,escape=0x1d" % (localhost, CONSOLE_PORT))
        child = pexpect.spawn("telnet %s %s" % (localhost, CONSOLE_PORT))

        if verbose:
            child.logfile = open("tmp.log", "w")

        # Long time for full configuration, waiting for ip address etc
        child.timeout = 600

        # wait for indication that boot has gone through
        if (wait):
            child.expect(r'Autoinstall will terminate if any input is detected on console', child.timeout)
            send_line()
            send_line()

            child.expect(r'Would you like to terminate autoinstall', child.timeout)
            send_cmd('yes')

            child.expect(r'OK to enter CLI now', child.timeout)
            send_line()

            time.sleep(5)

            # child.expect(r'Press RETURN to get started!', child.timeout)

            # original csr1kv
            # child.expect(r'CRYPTO-6-GDOI_ON_OFF: GDOI is OFF', child.timeout)
            logger.warn(
                'Logging into Vagrant Virtualbox and configuring IOS XE')

        send_line()
        time.sleep(5)
        send_line()

        # enable plus config mode, but remember to set term len to 0
        # first, or, as of a 16.12 IOS XE image, the config won't save
        # properly
        send_cmd("enable")
        send_cmd("term len 0")
        send_cmd("term width 300")
        send_cmd("conf t")

        # no TFTP config
        send_cmd("no logging console")
        time.sleep(5)
        send_cmd("no service config")

        # hostname / domain-name
        send_cmd("hostname c8kv")
        send_cmd("ip domain name example.net")
        # send_cmd("exit")

        # key generation
        # send_cmd("crypto key generate rsa modulus 2048")
        # time.sleep(5)

        # sshg setup
        send_line()
        send_cmd("ip ssh server algorithm authentication password publickey")

        # line configuration
        send_cmd("line vty 0 4")
        send_cmd("login local")
        send_cmd("transport input ssh")
        send_cmd("exit")

        # ssh vagrant insecure public key
        send_cmd("ip ssh pubkey-chain")
        send_cmd("username vagrant")
        send_cmd("key-string")
        send_cmd("AAAAB3NzaC1yc2EAAAABIwAAAQEA6NF8iallvQVp22WDkTkyrtvp9eW")
        send_cmd("W6A8YVr+kz4TjGYe7gHzIw+niNltGEFHzD8+v1I2YJ6oXevct1YeS0o")
        send_cmd("9HZyN1Q9qgCgzUFtdOKLv6IedplqoPkcmF0aYet2PkEDo3MlTBckFXP")
        send_cmd("ITAMzF8dJSIFo9D8HfdOV0IAdx4O7PtixWKn5y2hMNG0zQPyUecp4pz")
        send_cmd("C6kivAIhyfHilFR61RGL+GPXQ2MWZWFYbAGjyiYJnAmCP3NOTd0jMZE")
        send_cmd("nDkbUvxhMmBYSdETk1rRgm+R4LOzFUGaHqHDLKLX+FIPKcF96hrucXz")
        send_cmd("cWyLbIbEgE98OHlnVYCzRdK8jlqm8tehUc9c9WhQ==")
        send_cmd("exit")

        # configure DHCP on Gi1
        send_cmd("interface GigabitEthernet1")
        send_cmd("ip address dhcp")
        send_cmd("no shutdown")
        send_cmd("no negotiation auto")
        send_cmd("no speed")
        send_cmd("exit")

        # restconf & netconf
        send_cmd("netconf-yang")
        send_cmd("ip http server")
        send_cmd("ip http secure-server")
        send_cmd("restconf")

        # password setup
        send_cmd("username vagrant privilege 15 password vagrant")
        send_cmd("username cisco privilege 15 password cisco")
        send_cmd("enable password cisco")
        send_cmd("enable secret cisco123")

        # done and save
        send_cmd("end")
        send_cmd("wr mem")
        # send_cmd(["copy run start", CRLF])

        # just to be sure
        logger.warn('Waiting 10 seconds...')
        time.sleep(10)

    except pexpect.TIMEOUT:
        raise pexpect.TIMEOUT('Timeout (%s) exceeded in read().' % str(child.timeout))


def main(argv):
    input_iso = ''

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent('''\
            A tool to create an IOS XE Vagrant VirtualBox box from an IOS XE ISO.

            The ISO will be installed, booted and configured.

            "vagrant ssh" provides access to the IOS XE management interface
            with internet access. It uses the insecure Vagrant SSH key.
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
    parser.add_argument('--config-file', type=str,
                        help='provide a configuration file rather than built-in config')
    parser.add_argument('--platform', type=str, default='csr',
                        help='platform to determine CLI')
    parser.add_argument('--ram', type=int, default=8,
                        help='GB of RAM to configure')
    parser.add_argument('-o', '--create_ova', action='store_true',
                        help='additionally use VBoxManage to export an OVA')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='will exit with the VM in a running state. Use: socat TCP:localhost:65000 -,raw,echo=0,escape=0x1d to access')
    parser.add_argument('-n', '--nocolor', action='store_true',
                        help='don\'t use colors for logging')
    parser.add_argument('--virtio', action='store_true', default=False,
                        help='set NIC type to virtio (only for IOS-XE 16.7 onwards)')
    parser.add_argument('--leave-uart', action='store_true', default=False,
                        help='leave UART 1 enabled')
    parser.add_argument('-v', '--verbose',
                        action='store_const', const=logging.INFO,
                        default=logging.WARN, help='turn on verbose messages')
    args = parser.parse_args()

    # check valid platforms
    valid_platforms = ['csr', 'c8kv']
    if args.platform not in valid_platforms:
        sys.exit('Invalid platform \'{}\''.format(args.platform))

    # setup logging
    root_logger = logging.getLogger()
    root_logger.setLevel(level=args.verbose)
    handler = ColorHandler(colored=(not args.nocolor))
    formatter = logging.Formatter("==> %(message)s")
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    logger = logging.getLogger("box-builder")

    # PRE-CHECK: is socat installed?
    # logger.warn('Check whether "socat" is installed')
    # if not which('socat'):
    #     sys.exit(
    #         'The "socat" utility is not installed. Please install it prior to using this script.')

    # PRE-CHECK: is telnet installed?
    logger.warn('Check whether "telnet" is installed')
    if not which('telnet'):
        sys.exit(
            'The "telnet" utility is not installed. Please install it prior to using this script.')

    # PRE-CHECK: is mkisofs installed?
    logger.warn('Check whether "mkisofs" is installed if we need it')
    if args.config_file and not which('mkisofs'):
        sys.exit(
            'The "telnet" utility is not installed. Please install it prior to using this script.')

    # Handle Input ISO (Local or URI)
    if re.search(':/', args.ISO_FILE):
        # URI Image
        cmd_string = 'scp %s@%s .' % (getpass.getuser(), args.ISO_FILE)
        logger.warn('Will attempt to scp the remote image to current working dir. You may be required to enter your password.')
        logger.debug('%s\n', cmd_string)
        subprocess.call(cmd_string, shell=True)
        input_iso = os.path.basename(args.ISO_FILE)
    else:
        # Local image
        input_iso = args.ISO_FILE

    # if debug flag then set the logger to debug
    if args.debug:
        args.verbose = logging.DEBUG

    if not os.path.exists(input_iso):
        sys.exit('%s does not exist' % input_iso)

    if args.config_file and (not os.path.exists(args.config_file)):
        sys.exit('%s does not exist' % args.config_file)

    # Set Virtualbox VM name from the input ISO and then hash it as vbox6
    # complains about long path name
    hash = hashlib.md5()
    hash.update(os.path.basename(os.path.splitext(input_iso)[0]))
    vmname = hash.hexdigest()
    logger.warn('Input ISO is %s', input_iso)

    # playing it safe, should be OK in 3G / 3072
    ram = int(args.ram * 1024)
    logger.warn('Creating VirtualBox VM')

    version = run(['VBoxManage', '-v'])
    logger.info('Virtual Box Manager Version: %s', version)

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
    if os.path.exists(ova_out) and args.create_ova is True:
        os.remove(ova_out)
        logger.debug('Found and deleted previous %s', ova_out)

    # Clean up existing vm's
    cleanup_vmname(vmname, vbox)

    # Remove stale SSH entry
    # logger.debug('Removing stale SSH entries')
    # run(['ssh-keygen', '-R', '[localhost]:2222'])
    # run(['ssh-keygen', '-R', '[localhost]:2223'])

    # Create and register a new VirtualBox VM
    logger.debug('Create VM')
    run(['VBoxManage', 'createvm', '--name', vmname,
         '--ostype', 'Linux26_64', '--basefolder', base_dir])

    logger.debug('Register VM')
    run(['VBoxManage', 'registervm', vbox])

    # Setup memory, display, cpus etc
    logger.debug('VRAM 4')
    run(['VBoxManage', 'modifyvm', vmname, '--vram', '4'])

    logger.debug('Add ACPI')
    run(['VBoxManage', 'modifyvm', vmname, '--memory', str(ram), '--acpi', 'on'])

    #logger.debug('Add two CPUs')
    #run(['VBoxManage', 'modifyvm', vmname, '--cpus', '2'])

    # Setup networking - including ssh
    # it seems to be totally irrelevant how many interfaces are provisioned into
    # the inital box as the vagrant box create reduces the amount to 1 anyway.
    # if one wants more interfaces for individiual boxes then those have to be
    # added either in the vagrant file template or in the actual file inside the
    # box (after vagrant init).
    logger.debug('Create NICs')
    if args.virtio is True:
        run(['VBoxManage', 'modifyvm', vmname, '--nic1', 'nat', '--nictype1', 'virtio'])
    else:
        run(['VBoxManage', 'modifyvm', vmname, '--nic1', 'nat', '--nictype1', '82540EM'])
    run(['VBoxManage', 'modifyvm', vmname, '--cableconnected1', 'on'])

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
         '3', '--uartmode2', 'disconnected'])

    # Option 3: Connect via telnet
    # VBoxManage modifyvm $VMNAME --uart1 0x3f8 4 --uartmode1 tcpserver 6000
    # VBoxManage modifyvm $VMNAME --uart2 0x2f8 3 --uartmode2 tcpserver 6001

    # Setup storage
    logger.debug('Create a HDD')
    run(['VBoxManage', 'createhd', '--filename', vdi, '--size', '8192'])

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
         '--port', '0', '--device', '1', '--type', 'dvddrive', '--medium', input_iso])

    if args.config_file:
        logger.debug('Creating and configuring config ISO')
        config_iso_dir = tempfile.gettempdir()
        config_iso_fname = os.path.join(config_iso_dir, 'csr_config.iso')
        run(['mkisofs', '-l', '-o', config_iso_fname, args.config_file])
        run(['VBoxManage', 'storageattach', vmname,
             '--storagectl', 'IDE_Controller',
             '--port', '1',
             '--device', '0',
             '--type', 'dvddrive',
             '--medium', config_iso_fname])

    # Change boot order to hd then dvd
    logger.debug('Boot order disk first')
    run(['VBoxManage', 'modifyvm', vmname, '--boot1', 'disk'])

    logger.debug('Boot order DVD second')
    run(['VBoxManage', 'modifyvm', vmname, '--boot2', 'dvd'])

    # Start the VM for installation of ISO - must be started as a sub process
    logger.warn('Starting VM...')
    start_process(['VBoxHeadless', '--startvm', vmname])

    while True:
        vms_list = run(['VBoxManage', 'showvminfo', vmname])
        if 'running (since' in vms_list:
            logger.warn('Successfully started to boot VM disk image')
            break
        else:
            logger.warning('Failed to install VM disk image\n')
            time.sleep(5)
            continue

    # Good place to stop and take a look if --debug was entered
    if args.debug:
        pause_to_debug()
    else:
        # Configure IOS XE
        #
        # do print steps for logging set to DEBUG and INFO
        # DEBUG also prints the I/O with the device on the console
        # default is WARN
        #
        # A "config ISO" is created using a command like this:
        #
        #     mkisofs -l -o csr_config.iso iosxe_config.txt
        #
        try:
            if args.config_file:
                configure_wait_only(args.verbose < logging.WARN)
            elif args.platform == 'c8kv':
                configure_c8000v(args.verbose < logging.WARN)
            else:
                configure_xe(args.verbose < logging.WARN)
        except pexpect.exceptions.TIMEOUT as e:
            logger.error('Failed to apply config to XE!!')
            logger.warn('Waiting for machine to shutdown')
            run(['VBoxManage', 'controlvm', vmname, 'poweroff'])
            cleanup_vmname(vmname, vbox)
            return

    # Good place to stop and take a look if --debug was entered
    # if args.debug:
    #     pause_to_debug()

    logger.warn('Powering down and generating Vagrant VirtualBox')

    # Powerdown VM prior to exporting
    logger.warn('Waiting for machine to shutdown')
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
    if not args.leave_uart:
        run(['VBoxManage', 'modifyvm', vmname, '--uart1', 'off'])
    run(['VBoxManage', 'modifyvm', vmname, '--uart2', 'off'])

    # Remove DVD media before exporting
    run(['VBoxManage', 'storageattach', vmname,
         '--storagectl', 'IDE_Controller',
         '--port', '0',
         '--device', '1',
         '--type', 'dvddrive',
         '--medium', 'none'])
    run(['VBoxManage', 'storageattach', vmname,
         '--storagectl', 'IDE_Controller',
         '--port', '1',
         '--device', '0',
         '--type', 'dvddrive',
         '--medium', 'none'])

    # Shrink the VM
    logger.warn('Compact VDI')
    run(['VBoxManage', 'modifymedium', '--compact', vdi])

    logger.warn('Building Vagrant box')

    # Add the embedded Vagrantfile
    if args.virtio is True:
        vagrantfile_pathname = os.path.join(
            pathname, 'include', 'embedded_vagrantfile_xe_virtio')
    else:
        vagrantfile_pathname = os.path.join(
            pathname, 'include', 'embedded_vagrantfile_xe')

    run(['vagrant', 'package', '--base', vmname, '--vagrantfile',
         vagrantfile_pathname, '--output', box_out])
    logger.warn('Created: %s', box_out)

    # Create OVA
    if args.create_ova is True:
        logger.warn('Creating OVA %s', ova_out)
        run(['VBoxManage', 'export', vmname, '--output', ova_out])
        logger.debug('Created OVA %s', ova_out)

    # Clean up VM used to generate box
    cleanup_vmname(vmname, vbox)

    logger.warn('Add box to system:')
    logger.warn('  vagrant box add --name iosxe %s --force', box_out)
    logger.warn('Initialize environment:')
    logger.warn('  vagrant init iosxe')
    logger.warn('Bring up box:')
    logger.warn('  vagrant up')

    logger.warn('Note:')
    logger.warn(
        '  Both the XE SSH and NETCONF/RESTCONF username and password is vagrant/vagrant')


if __name__ == '__main__':
    main(sys.argv[1:])
