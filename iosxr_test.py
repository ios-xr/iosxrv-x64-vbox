#!/usr/bin/python
'''
Author: Rich Wellum (richwellum@gmail.com)

A tool to run some basic tests on a IOS XRv vagrant box, using pxssh module.

This will verify both IOS XR Linux and IOS XR Console access.

Is called from iosxr_iso2vbox post generation to verify sanity of
the Virtualbox,

Can also be run manually, like this:

python iosxr_test.py iosxrv-fullk9-x64.box
'''

from __future__ import print_function
import sys
import pexpect
from pexpect import pxssh
import subprocess
import argparse
import os
from iosxr_iso2vbox import run

try:
    raw_input
except NameError:
    raw_input = input

# Some defaults
terminal_type = 'ansi'
linux_prompt = r"[#$]"
xr_prompt = "[$#]"
login_timeout = 10
hostname = "localhost"
username = "vagrant"
password = "vagrant"
linux_port = 2222
xr_port = 2223


def bringup_vagrant(input_box):
    '''
    Bring up a vagrant box.

    Clean up ssh keys from the generation of the virtualbox.

    Use pxssh to fascilitate the ssh process.
    '''
    # Clean up Vagrantfile
    try:
        os.remove('Vagrantfile')
    except OSError:
        pass

    print('Cleaning up ssh keys')
    run('ssh-keygen -R [localhost]:2222')
    run('ssh-keygen -R [localhost]:2223')

    print("Bringing up '%s'..." % input_box)

    run('vagrant init XRv64')  # Single node for now, in future could bring up two nodes and do more testing
    run('vagrant box add --name XRv64 %s --force' % input_box)
    run('vagrant up')

    ports = str(subprocess.check_output('vagrant port', shell=True))
    print(ports)

    try:
        s = pexpect.pxssh.pxssh()
        s.login(hostname, username, password, terminal_type, linux_prompt, login_timeout, linux_port)
    except pxssh.ExceptionPxssh, e:
        print("pxssh failed on login")
        print(str(e))


def test_linux():
    '''
    Verify logging into IOS XR Linux.
    Verify user is 'vagrant'.
    Verify can ping 'google.com'.
    Verify resolv.conf is populated.
    '''
    print('Testing XR Linux...')

    try:
        s = pxssh.pxssh()
        s.login(hostname, username, password, terminal_type, linux_prompt, login_timeout, linux_port)

        print('Check user:')
        s.sendline('whoami')
        result = s.expect(['vagrant', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>Correct user found')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - wrong user name')
            return False
        s.prompt()

        print('Check pinging the internet:')
        s.sendline("ping -c 4 google.com | grep '64 bytes' | wc -l")
        result = s.expect(['4', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>Successfully pinged')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - ping failed')
            return False
        s.prompt()

        print('Check resolv.conf is correctly populated:')
        s.sendline("cat /etc/resolv.conf | grep 220")
        result = s.expect(['nameserver 208.67.220.220', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>nameserver 208.67.220.220 is successfully populated')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - nameserver 208.67.220.220 is not populated in resolv.conf')
            return False
        s.prompt()

        s.sendline("cat /etc/resolv.conf | grep 222")
        result = s.expect(['nameserver 208.67.222.222', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>nameserver 208.67.222.222 is successfully populated')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - nameserver 208.67.220.222 is not populated in resolv.conf')
            return False
        s.prompt()

        print('Check vagrant public key has been replaced by private:')
        s.sendline('grep "public" ~/.ssh/authorized_keys -c')
        result = s.expect(['0', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>SSH public key successfully replaced')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - SSH public key not successfully replaced')
            return False

        s.prompt()
        s.logout()
    except pxssh.ExceptionPxssh as e:
        print("pxssh failed on login.")
        print(e)
        return False
    else:
        print("Vagrant SSH to XR Linux is sane")
        return True


def test_xr():
    '''
    Log into IOS XR Console and run some basic sanity tests.

    Verify logging into IOS XR Console directly.
    Verify show version.
    Verify show run.
    '''

    print('Testing XR Console...')

    try:
        s = pxssh.pxssh()
        s.force_password = True
        s.PROMPT = 'RP/0/RP0/CPU0:ios# '

        print('Check logging into XR Console')
        s.login(hostname, username, password, terminal_type, xr_prompt, login_timeout, xr_port, auto_prompt_reset=False)
        s.prompt()
        s.sendline('term length 0')
        s.prompt()
        print('==>Successfully logged into XR Console')

        print('Check show version')
        s.sendline('show version | i cisco IOS XRv x64')
        result = s.expect(['XRv x64', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>XRv x64 correctly found in show version')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - show version failed')
            return False
        s.prompt()

        print('Check show run grpc')
        s.sendline('show run grpc')
        result = s.expect(['port 57777', pexpect.EOF, pexpect.TIMEOUT])
        if result == 0:
            print('==>GRPC port 57777 correctly found in show run')
        elif result == 1:
            print('EOF')
            return False
        elif result == 2:
            print('Timed out - show run failed')
            return False

        s.prompt()
        s.logout()

    except pxssh.ExceptionPxssh as e:
        print("pxssh failed on login.")
        print(e)
    else:
        print("Vagrant SSH to XR Console is sane")
        return True


def main():
    # Get virtualbox
    parser = argparse.ArgumentParser(description='Pass in a vagrant box')
    parser.add_argument("a", nargs='?', default="check_string_for_empty")
    args = parser.parse_args()

    if args.a == 'check_string_for_empty':
        print('No argument given')
        print('Usage: iosxr_test.py <boxname>')
        sys.exit(1)
    else:
        input_box = args.a
        if not os.path.exists(input_box):
            print(input_box, 'does not exist')
            sys.exit()

    # Comment this code out when testing iosxr_test.py
    print('Destroying previous default VM')
    run('vagrant destroy --force')

    # Bring the newly generated virtualbox up
    bringup_vagrant(input_box)

    # Test IOS XR Linux
    result_linux = test_linux()

    # Test IOS XR Console
    result_xr = test_xr()

    # Testing finished - clean up now
    run('vagrant destroy --force')

    if result_linux or result_xr is False:
        return False
    else:
        return True

if __name__ == "__main__":
    main()
