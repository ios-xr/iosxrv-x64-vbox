#!/usr/bin/python
'''
Author: Rich Wellum (richwellum@gmail.com)

A tool to upload an image to a maven repo like artifactory using curl, the image
typically being a vagrant virtualbox, but could be anything.

E.g. iosxrv-x64-vbox/iosxr_store_box.py -b iosxrv-fullk9-x64.box --release --verbose --message "A new box because..."')

This was originally part of iosxr_ios2vbox.py, but doesn't belong to the
generation of a box. Also future plans are to store images via jenkins so this will
be a temporarily living tool.

User can select snapshot or release, the release images get synced to
devhub.cisco.com - where they are available to customers.

This tool also sends an email out to an email address or an alias to inform them
of the new image.

It is designed to be called from other tools, like iosxr_ios2vbox.py.

It will rely on the following environment variables to work:

ARTIFACTORY_USERNAME
ARTIFACTORY_PASSWORD
ARTIFACTORY_LOCATION_SNAPSHOT
ARTIFACTORY_LOCATION_RELEASE
ARTIFACTORY_SENDER
ARTIFACTORY_RECEIVER
'''

from __future__ import print_function
import sys
import os
import getopt
import subprocess
import smtplib


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
    input_box = ''
    verbose = False
    test = False
    master_opts = '==> iosxr_store_box.py [-b box] [-m, --message], [-r, --release] [-v, --verbose] [-h, --help] [-t, --test]'
    artifactory_release = False

    # Get info from environment and check it's all there
    artifactory_username = os.environ.get('ARTIFACTORY_USERNAME')
    artifactory_password = os.environ.get('ARTIFACTORY_PASSWORD')
    sender = os.environ.get('ARTIFACTORY_SENDER')
    receiver = os.environ.get('ARTIFACTORY_RECEIVER')

    if artifactory_username is None:
        print('==> Please set ARTIFACTORY_USERNAME in your environment')
        sys.exit()
    if artifactory_password is None:
        print('==> Please set ARTIFACTORY_PASSWORD in your environment')
        sys.exit()
    if sender is None:
        print('==> Please set SENDER in your environment')
        sys.exit()
    if receiver is None:
        print('==> Please set RECEIVER in your environment')
        sys.exit()

    # Suck in the input ISO and handle errors
    try:
        opts, args = getopt.getopt(argv, 'b:m:rvht', ['box=', 'message=', 'release', 'verbose', 'help', 'test'])
    except getopt.GetoptError:
        print('Input error')
        print(master_opts)
        sys.exit(2)
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            print('==> A tool to copy a box to a maven-like repo')
            print(master_opts)
            print('==> E.g. iosxrv-x64-vbox/iosxr_store_box.py -b iosxrv-fullk9-x64.box --release, --message "A new box because..."')
            print('==> E.g. iosxrv-x64-vbox/iosxr_store_box.py -b iosxrv-fullk9-x64.box -r -v -m "Latest box for release."')
            sys.exit()
        if opt in ('-b', '--box'):
            input_box = arg
        if opt in ('-m', '--message'):
            message = arg
            if not message:
                message = 'No reason for update specified'
        elif opt in ('-r', '--release'):
            artifactory_release = True
        elif opt in ('-v', '--verbose'):
            verbose = True
        elif opt in ('-t', '--test'):
            test = True

    if not input_box:
        print('No input box detected, use -b to specify a box')
        sys.exit()

    if not os.path.exists(input_box):
        print('==>', input_box, 'does not exist')
        sys.exit()

    boxname = os.path.basename(os.path.splitext(input_box)[0]) + '.box'

    prog = 'iosxr_store_box.py'

    # If verbose is set then print
    if verbose:
        def verboseprint(*args):
            '''
            If user runs with -v or -verbose print logs

            Print each argument separately so caller doesn't need to
            stuff everything to be printed into a single string
            '''
            print('==> %s: ' % prog, end="")
            for arg in args:
                print(arg,)
    else:
        def verboseprint(*args):
            pass

    verboseprint("Input box is: '%s'" % input_box)
    verboseprint("Message is:   '%s'" % message)
    verboseprint("Sender is:    '%s'" % sender)
    verboseprint("Receiver is:  '%s'" % receiver)
    verboseprint("Release is:   '%s'" % artifactory_release)
    verboseprint("Test is:      '%s'" % test)

    '''
    Copy the box to artifactory. This will most likely change to Atlas, or maybe both.
    The code below shows how to make two copies, one is the latest and one has a date on it.
    '''
    # Find the appopriate LOCATION
    if artifactory_release is True:
        location = os.environ.get('ARTIFACTORY_LOCATION_RELEASE')
    else:
        location = os.environ.get('ARTIFACTORY_LOCATION_SNAPSHOT')

    if location is None:
        print('==> Please set LOCATION_RELEASE or LOCATION_SNAPSHOT in your environment')
        sys.exit()

    box_out = os.path.join(location, boxname)

    if test is True:
        verboseprint('Test only: copying %s to %s' % (input_box, box_out))
    else:
        verboseprint('Copying %s to %s' % (box_out, box_out))
        run('curl -X PUT -u %s:%s -T %s %s' % (artifactory_username, artifactory_password, input_box, box_out))

    # Format an email message and send to the interest list
    email = """From: <%s>
To: IOS XRv (64-bit) Box Interest <%s>
Subject: A new IOS XRv (64-bit) vagrant box has been posted to artifactory %s

Reason for update: %s
\nVagrant Box: %s
\nTo use:
\n vagrant init 'IOS XRv'
\n vagrant box add --name 'IOS XRv' %s --force
\n vagrant up
\n vagrant ssh
        """ % (sender, receiver, location, message, box_out, box_out)

    verboseprint('Email is:')
    print(email)

    if test is False:
        try:
            smtpObj = smtplib.SMTP('mail.cisco.com')
            smtpObj.sendmail(sender, receiver, email)
            verboseprint('Successfully sent update email')
        except smtplib.SMTPException:
            verboseprint('Error: unable to send update email')
    else:
        verboseprint('Test only: Not sending email')

if __name__ == '__main__':
    main(sys.argv[1:])
