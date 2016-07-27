#!/usr/bin/env python
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
from iosxr_iso2vbox import set_logging, run
import logging

logger = logging.getLogger(__name__)
set_logging()

try:
    raw_input
except NameError:
    raw_input = input

# Some defaults
terminal_type = 'ansi'
linux_prompt = r"[#$]"
xr_prompt = r"[$#]"
login_timeout = 600
hostname = "localhost"
username = "vagrant"
password = "vagrant"


def check_result(result, success_message):
    '''
    Function to check result of a pexpect operation.
    Accepts a success message.
    '''
    if result == 0:
        logger.debug('Test passed: %s' % success_message)
        return True
    elif result == 1:
        logger.warning('EOF - Test failed')
        return False
    elif result == 2:
        logger.warning(' Timed out - Test failed')
        return False
    else:
        logger.warning(' Generic - Test failed')
        return False


def bringup_vagrant():
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

    logger.debug("Bringing up '%s'..." % input_box)

    run(['vagrant', 'init', 'XRv64-test'])  # Single node for now, in future could bring up two nodes and do more testing
    run(['vagrant', 'box', 'add', '--name', 'XRv64-test', input_box, '--force'])
    output = run(['vagrant', 'up'])
    print(output)

    # Find the correct port to connect to
    port = subprocess.check_output('vagrant port --guest 57722', shell=True)
    logger.debug('Connecting to port %s' % port)

    try:
        s = pxssh.pxssh(options={
            "StrictHostKeyChecking": "no",
            "UserKnownHostsFile": "/dev/null"})
        s.login(hostname, username, password, terminal_type, linux_prompt, login_timeout, port)
        logger.debug('Sucessfully brought up VM and logged in')
        s.logout()
    except pxssh.ExceptionPxssh, e:
        logger.error("pxssh failed on login")
        logger.error(e)


def test_linux():
    '''
    Verify logging into IOS XR Linux.
    Verify user is 'vagrant'.
    Verify can ping 'google.com'.
    Verify resolv.conf is populated.
    '''
    logger.debug('Testing XR Linux...')
    linux_port = subprocess.check_output('vagrant port --guest 57722', shell=True)
    logger.debug('Connecting to port %s' % linux_port)

    try:
        s = pxssh.pxssh(options={
            "StrictHostKeyChecking": "no",
            "UserKnownHostsFile": "/dev/null"})
        s.login(hostname, username, password, terminal_type, linux_prompt, login_timeout, linux_port, auto_prompt_reset=False)

        s.prompt()
        logger.debug('Successfully logged into XR Linux')

        logger.debug('Check user:')
        s.sendline('whoami')
        output = s.expect(['vagrant', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'Correct user found'):
            return False
        s.prompt()

        logger.debug('Check pinging the internet:')
        s.sendline("ping -c 4 google.com | grep '64 bytes' | wc -l")
        output = s.expect(['4', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'Successfully pinged'):
            return False
        s.prompt()

        logger.debug('Check resolv.conf is correctly populated:')
        s.sendline("cat /etc/resolv.conf | grep 220")
        output = s.expect(['nameserver 208.67.220.220', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'nameserver 208.67.220.220 is successfully populated'):
            return False
        s.prompt()

        s.sendline("cat /etc/resolv.conf | grep 222")
        output = s.expect(['nameserver 208.67.222.222', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'nameserver 208.67.222.222 is successfully populated'):
            return False
        s.prompt()

        logger.debug('Check vagrant public key has been replaced by private:')
        s.sendline('grep "public" ~/.ssh/authorized_keys -c')
        output = s.expect(['0', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'SSH public key successfully replaced'):
            return False
        s.prompt()
        s.logout()
    except pxssh.ExceptionPxssh as e:
        logger.error("pxssh failed on login.")
        logger.error(e)
        return False
    else:
        logger.debug("Vagrant SSH to XR Linux is sane")
        return True


def test_xr():
    '''
    Log into IOS XR Console and run some basic sanity tests.

    Verify logging into IOS XR Console directly.
    Verify show version.
    Verify show run.
    '''
    global iosxr_port

    if 'k9' not in input_box:
        logger.warning('Not a crypto image, will not test XR as no SSH to access.')
        return True

    logger.debug('Testing XR Console...')
    iosxr_port = subprocess.check_output('vagrant port --guest 22', shell=True)
    logger.debug('Connecting to port %s' % iosxr_port)

    try:
        s = pxssh.pxssh(options={
            "StrictHostKeyChecking": "no",
            "UserKnownHostsFile": "/dev/null"})

        s.force_password = True
        s.PROMPT = 'RP/0/RP0/CPU0:ios# '

        s.login(hostname, username, password, terminal_type, xr_prompt, login_timeout, iosxr_port, auto_prompt_reset=False)
        s.prompt()
        s.sendline('term length 0')
        s.prompt()
        logger.debug('Successfully logged into XR Console')

        logger.debug('Check show version:')
        s.sendline('show version | i cisco IOS XRv x64')
        output = s.expect(['XRv x64', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'XRv x64 correctly found in show version'):
            return False
        s.prompt()

        logger.debug('Check show run for username vagrant:')
        s.sendline('show run | i username')
        output = s.expect(['username vagrant', pexpect.EOF, pexpect.TIMEOUT])
        if not check_result(output, 'Username vagrant found'):
            return False
        s.prompt()

        if 'full' in input_box:
            logger.debug('Check show run for grpc:')
            s.sendline('show run grpc')
            output = s.expect(['port 57777', pexpect.EOF, pexpect.TIMEOUT])
            if not check_result(output, 'grpc is configured'):
                return False
            s.prompt()

        s.logout()
    except pxssh.ExceptionPxssh as e:
        logger.error("pxssh failed on login.")
        logger.debug(e)
    else:
        logger.debug("Vagrant SSH to XR Console is sane")
        return True


def main():
    # Get virtualbox
    global input_box
    global verbose

    parser = argparse.ArgumentParser(description='Pass in a vagrant box')
    parser.add_argument("a", nargs='?', default="check_string_for_empty")
    parser.add_argument('-v', '--verbose',
                        action='store_const', const=logging.DEBUG,
                        default=logging.INFO, help='turn on verbose messages')

    args = parser.parse_args()
    verbose = args.verbose

    if args.a == 'check_string_for_empty':
        sys.exit('No argument given, Usage: iosxr_test.py <boxname>')
    else:
        input_box = args.a
        if not os.path.exists(input_box):
            sys.exit(input_box, 'does not exist')

    logger.setLevel(level=args.verbose)

    # Bring the newly generated virtualbox up
    bringup_vagrant()

    # Test IOS XR Linux
    result_linux = test_linux()

    # Test IOS XR Console
    result_xr = test_xr()

    logger.debug('result_linux=%s, result_xr=%s' % (result_linux, result_xr))

    if not (result_linux and result_xr):
        sys.exit('Failed basic test, box is not sane')
    else:
        logger.info('Both IOS XR and IOS Linux test suites passed')
        return

if __name__ == "__main__":
    main()
