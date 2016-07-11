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
import shlex
import argparse
from argparse import RawDescriptionHelpFormatter
import re

# Telnet ports used to access IOS XR via socat
console_port = 65000
aux_port = 65001


def run(command_string, debug=False):
    '''
    Execute a CLI command string and return the result.

    Note this does not handle operators which need whitespace.

    In those cases the raw commands will need to be used.

    E.g. passing grep 'a string separated by spaces'.
    '''
    argv = command_string.split()
    if debug is True:
        print ('argv: %s' % argv)
    result = subprocess.check_output(argv)
    return result


def main(argv):
    input_iso = ''
    copy_to_artifactory = False
    create_ova = False
    verbose = False
    artifactory_reason = ''

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
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='turn on verbose messages')

    args = parser.parse_args()

    # Handle Input ISO (Local or URI)
    if re.search(':/', args.ISO_FILE):
        # URI Image
        cmdstring = 'scp %s@%s .' % (getpass.getuser(), args.ISO_FILE)
        print('==> Will attempt to scp the remote image to current working dir. You may be required to enter your password.')
        print('==> %s\n' % cmdstring)
        subprocess.call(cmdstring, shell=True)
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

    # Handle verbose - no special handling needed as boolean
    verbose = args.verbose

    if not os.path.exists(input_iso):
        print('==>', input_iso, 'does not exist')
        sys.exit()

    # Set Virtualbox VM name from the input ISO
    vmname = os.path.basename(os.path.splitext(input_iso)[0])

    # If verbose is set then print
    if verbose:
        def verboseprint(*args):
            '''
            If user runs with -v or -verbose print logs

            Print each argument separately so caller doesn't need to
            stuff everything to be printed into a single string
            '''
            print('==> %s: ' % vmname, end="")
            for arg in args:
                print(arg,)
    else:
        def verboseprint(*args):
            pass

    verboseprint('Input ISO is %s' % input_iso)

    # Set the RAM according to mini of full ISO
    if 'mini' in input_iso:
        ram = 3072
        verboseprint('%s is a mini image, RAM allocated is %s MB' % (input_iso, ram))
    elif 'full' in input_iso:
        ram = 4096
        verboseprint('%s is a full image, RAM allocated is %s MB' % (input_iso, ram))
    else:
        verboseprint('%s is neither a mini nor a full image. Abort' % input_iso)
        sys.exit()

    version = str(subprocess.check_output('VBoxManage -v', shell=True))
    verboseprint('Virtual Box Manager Version: %s' % version)

    # Set up paths
    base_dir = os.path.join(os.getcwd(), 'machines')
    box_dir = os.path.join(base_dir, vmname)
    vbox = os.path.join(box_dir, vmname + '.vbox')
    vdi = os.path.join(box_dir, vmname + '.vdi')
    box_out = os.path.join(box_dir, vmname + '.box')
    ova_out = os.path.join(box_dir, vmname + '.ova')
    pathname = os.path.abspath(os.path.dirname(sys.argv[0]))

    verboseprint('pathname: %s' % pathname)
    verboseprint('VM Name:  %s' % vmname)
    verboseprint('base_dir: %s' % base_dir)
    verboseprint('box_dir:  %s' % box_dir)
    verboseprint('box_out:  %s' % box_out)

    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    if not os.path.exists(box_dir):
        os.makedirs(box_dir)

    # Delete existing Box
    if os.path.exists(box_out):
        os.remove(box_out)
        verboseprint('Found and deleted previous %s' % box_out)

    # Delete existing OVA
    if os.path.exists(ova_out) and create_ova is True:
        os.remove(ova_out)
        verboseprint('Found and deleted previous %s' % ova_out)

    # Destroy default vagrant box
    verboseprint('Destroy default box')
    run('vagrant destroy --force')

    # Remove any running boxes with the same name
    vms_list_running = str(run('vboxmanage list runningvms'))
    if vmname in vms_list_running:
        verboseprint('is running, powering off...')
        time.sleep(2)
        run('VBoxManage controlvm %s poweroff' % vmname)

    # Unregister and delete any boxes with the same name
    vms_list = str(run('vboxmanage list vms'))
    if vmname in vms_list:
        verboseprint('%s exists, cleaning up...' % vmname)
        time.sleep(2)
        verboseprint('unregister VM')
        run('VBoxManage unregistervm %s --delete' % vbox)
    else:
        verboseprint('%s does not exist, nothing to clean up' % vmname)

    # Remove stale SSH entry
    verboseprint('Removing stale SSH entries')
    run('ssh-keygen -R [localhost]:2222')
    run('ssh-keygen -R [localhost]:2223')

    # Create and register a new VirtualBox VM
    verboseprint('Create VM')
    run('VBoxManage createvm --name %s --ostype Linux26_64 --basefolder %s' % (vmname, base_dir))

    verboseprint('Register VM')
    run('VBoxManage registervm %s ' % vbox)

    # Setup memory, display, cpus etc
    verboseprint('VRAM 12')
    run('VBoxManage modifyvm %s --vram 12' % vmname)

    verboseprint('Add ACPI')
    run('VBoxManage modifyvm %s --memory %s --acpi on' % (vmname, ram))

    verboseprint('Add two CPUs')
    run('VBoxManage modifyvm %s --cpus 2' % vmname)

    # Setup networking - including ssh
    verboseprint('Create four NICs')
    run('VBoxManage modifyvm %s --nic1 nat --nictype1 virtio' % vmname)
    run('VBoxManage modifyvm %s --nic2 nat --nictype2 virtio' % vmname)
    run('VBoxManage modifyvm %s --nic3 nat --nictype3 virtio' % vmname)
    run('VBoxManage modifyvm %s --nic4 nat --nictype4 virtio' % vmname)

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
    # cmdstring='VBoxManage modifyvm %s --uart1 0x3f8 4 --uartmode1 server /tmp/serial1' % vmname
    verboseprint('Add a console port')
    run('VBoxManage modifyvm %s --uart1 0x3f8 4 --uartmode1 tcpserver %s' % (vmname, console_port))

    verboseprint('Add an aux port')
    run('VBoxManage modifyvm %s --uart2 0x2f8 3 --uartmode2 tcpserver %s' % (vmname, aux_port))

    # Option 3: Connect via telnet
    # VBoxManage modifyvm $VMNAME --uart1 0x3f8 4 --uartmode1 tcpserver 6000
    # VBoxManage modifyvm $VMNAME --uart2 0x2f8 3 --uartmode2 tcpserver 6001

    # Setup storage
    verboseprint('Create a HDD')
    run('VBoxManage createhd --filename %s --size 46080' % vdi)

    verboseprint('Add IDE Controller')
    run('VBoxManage storagectl %s --name IDE_Controller --add ide' % vmname)

    verboseprint('Attach HDD')
    run('VBoxManage storageattach %s --storagectl IDE_Controller --port 0 --device 0 --type hdd --medium %s' % (vmname, vdi))

    verboseprint('VM HD info: ')
    run('VBoxManage showhdinfo %s' % vdi)

    verboseprint('Add DVD drive')
    run('VBoxManage storageattach %s --storagectl IDE_Controller --port 1 --device 0 --type dvddrive --medium %s' % (vmname, input_iso))

    # Change boot order to hd then dvd
    verboseprint('Boot order disk first')
    run('vboxmanage modifyvm %s --boot1 disk' % vmname)

    verboseprint('Boot order DVD second')
    run('vboxmanage modifyvm %s --boot2 dvd' % vmname)

    # Print some information about the VM
    verboseprint('VM Info:')
    run('VBoxManage showvminfo %s' % vmname)

    # Start the VM for installation of ISO - must be started in the background
    verboseprint('Starting VM...')
    cmdstring = ('VBoxHeadless --startvm %s' % vmname)
    args = shlex.split(cmdstring)
    subprocess.Popen(args)
    time.sleep(2)

    while True:
        vms_list = str(run('VBoxManage showvminfo %s' % vmname))
        if 'running (since' in vms_list:
            verboseprint('Successfully started to boot VM disk image')
            break
        else:
            verboseprint('Failed to install VM disk image\n')
            continue

    # Use iosxr_pexpect.py to bring up XR and do some initial config.
    # Using socat to do the connection as telnet has an
    # odd double return on vbox
    verboseprint('Bringing up with iosxr_pexpect.py to install to disk and configure')
    iosxr_pexpect_path = os.path.join(pathname, 'iosxr_pexpect.py')
    cmdstring = "python %s -cmds 'socat TCP:localhost:%s -,raw,echo=0,escape=0x1d' -config iosxr_setup" % (iosxr_pexpect_path, console_port)
    subprocess.call(cmdstring, shell=True)
    # Todo: this isn't suppressing the output
    # subprocess.call(cmdstring, shell=True, stdout=open(os.devnull, 'wb'))

    # Powerdown VM prior to exporting
    verboseprint('Waiting for machine to shutdown')
    run('VBoxManage controlvm %s poweroff' % vmname)

    while True:
        vms_list_running = str(run('vboxmanage list runningvms'))

        if vmname in vms_list_running:
            verboseprint('Still shutting down')
            sys.exit(1)
        else:
            verboseprint('Successfully shut down')
            break

    # Disable uart before exporting
    verboseprint('Remove serial uarts before exporting')
    run('VBoxManage modifyvm %s --uart1 off' % vmname)
    run('VBoxManage modifyvm %s --uart2 off' % vmname)

    # Potentially shrink vm
    verboseprint('Compact VDI')
    run('VBoxManage modifymedium --compact %s' % vdi)

    verboseprint('Creating Virtualbox')

    # Add in embedded Vagrantfile
    vagrantfile_pathname = os.path.join(pathname, 'include', 'embedded_vagrantfile')

    run('vagrant package --base %s --vagrantfile %s --output %s' % (vmname, vagrantfile_pathname, box_out))
    verboseprint('Created: %s' % box_out)

    # Create OVA
    if create_ova is True:
        verboseprint('Creating OVA %s' % ova_out)
        run('VBoxManage export %s --output %s' % (vmname, ova_out))
        verboseprint('Created OVA %s' % ova_out)

    # Run basic sanity tests
    verboseprint('Running basic unit tests on VirtualBox...')
    iosxr_test_path = os.path.join(pathname, 'iosxr_test.py')
    cmdstring = "python %s %s" % (iosxr_test_path, box_out)
    result = (subprocess.check_output(cmdstring, shell=True))
    if result is False:
        # Fail noisily
        sys.exit('Failed basic test, box %s is not sane' % box_out)
    else:
        verboseprint('Passed basic test, box %s is sane' % box_out)

    verboseprint('Single node use:')
    verboseprint(" vagrant init 'IOS XRv'")
    verboseprint(" vagrant box add --name 'IOS XRv' %s --force" % box_out)
    verboseprint(' vagrant up')

    verboseprint('Multinode use:')
    verboseprint(" Copy './iosxrv-x64-vbox/vagrantfiles/simple-mixed-topo/Vagrantfile' to the directory running vagrant and do:")
    verboseprint(" vagrant box add --name 'IOS XRv' %s --force" % box_out)
    verboseprint(' vagrant up')
    verboseprint(" Or: 'vagrant up rtr1', 'vagrant up rtr2'")

    verboseprint('Note that both the XR Console and the XR linux shell username and password is vagrant/vagrant')

    # Clean up Vagrantfile
    try:
        os.remove('Vagrantfile')
    except OSError:
        pass

    if copy_to_artifactory is True:
        iosxr_store_box_path = os.path.join(pathname, 'iosxr_store_box.py')
        if verbose is True:
            add_verbose = '-v'

        cmdstring = "python %s -b %s  %s -m '%s'" % (iosxr_store_box_path, box_out, add_verbose, artifactory_reason)
        subprocess.call(cmdstring, shell=True)

if __name__ == '__main__':
    main(sys.argv[1:])
