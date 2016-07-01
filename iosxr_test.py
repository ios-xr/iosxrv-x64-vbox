#!/usr/bin/python
'''
Author: Rich Wellum (richwellum@gmail.com)

A tool to run some basic tests on a vagrant box
'''

from __future__ import print_function
import sys
import pexpect
from pexpect import pxssh
import subprocess
import argparse
import os

try:
    raw_input
except NameError:
    raw_input = input

terminal_type = 'ansi'
original_prompt = r"[#$]"
login_timeout = 0
host = "localhost"
user = "vagrant"
password = "vagrant"
linux_port = 2222
xr_port = 2223


def run(command_string, debug=False):
    '''
    Execute a CLI command string and return the result.

    Note this does not handle operators which need whitespace.

    In those cases the raw commands will need to be used.

    E.g. passing grep 'a string separated by spaces'.
    '''
    argv = command_string.split()
    if debug is True:
        print('argv: %s' % argv)
    return subprocess.check_output(argv)


def bringup_vagrant(input_box):
    '''
    Bring up a vagrant box.
    '''
    # Clean up Vagrantfile
    try:
        os.remove('Vagrantfile')
    except OSError:
        pass

    print("Bringing up '%s'..." % input_box)
    run('vagrant init XRv64')
    run('vagrant box add --name XRv64 %s --force' % input_box)
    run('vagrant up')

    count = 0
    max_count = 1
    while (count < max_count):
        try:
            s = pexpect.pxssh.pxssh()
            s.login(host, user, password, terminal_type, original_prompt, login_timeout, linux_port)
            break
        except pxssh.ExceptionPxssh, e:
            print("pxssh failed on login, attempt %s/%s. Waiting one minute.." % (count, max_count))
            print(str(e))
            count += 1


def test_linux():
    '''
    Verify log into IOS XR Linux.
    Verify user is vagrant.
    Verify can ping google.com.
    '''
    try:
        s = pxssh.pxssh()
        s.login(host, user, password, terminal_type, original_prompt, login_timeout, linux_port)

        s.sendline('whoami')
        s.expect('vagrant')
        s.prompt()

        s.sendline("ping -c 4 google.com | grep '64 bytes' | wc -l")
        s.expect('4')
        s.prompt()

        s.sendline('uptime')
        s.prompt()

        s.sendline('cat /etc/resolv.conf | grep 220')
        s.expect('nameserver 208.67.220.220')
        s.prompt()

        s.sendline('cat /etc/resolv.conf | grep 222')
        s.expect('nameserver 208.67.222.222')
        s.prompt()

        s.logout()
    except pxssh.ExceptionPxssh as e:
        print("pxssh failed on login.")  # Return this and check in iso2vbox
        print(e)
    else:
        print("Vagrant SSH is sane")  # Return this and check in iso2vbox


def test_xr():
    try:
        s = pxssh.pxssh()
        s.login(host, user, password, terminal_type, login_timeout, xr_port)
        s.sendline('show version')
        s.prompt()
        print(s.before)
        s.sendline('show run')
        s.prompt()
        print(s.before)
    except pxssh.ExceptionPxssh as e:
        print("pxssh failed on login.")
        print(e)


def main():

    # Grab vagrant box
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

    bringup_vagrant(input_box)
    test_linux()
    # test_xr()
    run('vagrant destroy --force')

if __name__ == "__main__":
    main()
