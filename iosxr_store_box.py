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
import smtplib
from iosxr_iso2vbox import run, set_logging
import argparse
from argparse import RawDescriptionHelpFormatter
import logging
import hashlib

logger = logging.getLogger(__name__)
set_logging()


def generate_hash(file):
    global hash_file
    # SHA256 the box file and store in same location
    sha256_hash = hashlib.sha256(open(file, 'rb').read()).hexdigest()
    logger.debug('SHA256: %s' % sha256_hash)
    hash_file = os.path.splitext(file)[0] + '.sha256'
    f = open(hash_file, 'w')
    f.write(sha256_hash)
    f.close()
    logger.debug('Hash file is %s' % hash_file)


def main(argv):
    input_box = ''
    test_only = False
    artifactory_release = False

    # Get info from environment and check it's all there
    artifactory_username = os.environ.get('ARTIFACTORY_USERNAME')
    artifactory_password = os.environ.get('ARTIFACTORY_PASSWORD')
    sender = os.environ.get('ARTIFACTORY_SENDER')
    receiver = os.environ.get('ARTIFACTORY_RECEIVER')

    if artifactory_username is None:
        sys.exit("Please set ARTIFACTORY_USERNAME in your environment\n"
                 "E.g., 'export ARTIFACTORY_USERNAME=<username>'")
    if artifactory_password is None:
        sys.exit("Please set ARTIFACTORY_PASSWORD in your environment\n"
                 "E.g. export 'ARTIFACTORY_PASSWORD=<PASSWORD>'")
    if sender is None:
        sys.exit("Please set SENDER in your environment\n"
                 "E.g. export 'ARTIFACTORY_SENDER=$USER@me.com'")
    if receiver is None:
        sys.exit("Please set RECEIVER in your environment\n"
                 "E.g. export 'ARTIFACTORY_RECEIVER=updates@me.com'")

    # Suck in the input BOX and handle errors
    parser = argparse.ArgumentParser(
        formatter_class=RawDescriptionHelpFormatter,
        description='A tool to upload an image to a maven repo like artifactory ' +
        'using curl, the image typically being a vagrant virtualbox.\n' +
        'User can select snapshot or release, the release images get synced to ' +
        'devhub.cisco.com - where they are available to customers.\n' +
        'This tool also sends an email out to an email address or an alias to ' +
        'inform them of the new image.\n' +
        'It is designed to be called from other tools, like iosxr_ios2vbox.py.\n\n' +
        'It will rely on the following environment variables to work:\n ' +
        'ARTIFACTORY_USERNAME\n ' +
        'ARTIFACTORY_PASSWORD\n ' +
        'ARTIFACTORY_LOCATION_SNAPSHOT\n ' +
        'ARTIFACTORY_LOCATION_RELEASE\n ' +
        'ARTIFACTORY_SENDER\n ' +
        'ARTIFACTORY_RECEIVER',
        epilog="E.g.:\n" +
        "iosxrv-x64-vbox/iosxr_store_box.py iosxrv-fullk9-x64.box --release --verbose --message 'A new box because...'\n" +
        "iosxrv-x64-vbox/iosxr_store_box.py iosxrv-fullk9-x64.box --release, --message 'A new box because...'\n"
        "iosxrv-x64-vbox/iosxr_store_box.py iosxrv-fullk9-x64.box -r -v -m 'Latest box for release.'\n")

    parser.add_argument('BOX_FILE',
                        help='BOX filename')
    parser.add_argument('-m', '--message',
                        default='No reason for update specified',
                        help='Optionally specify a reason for uploading this box')
    parser.add_argument('-r', '--release', action='store_true',
                        help="upload to '$ARTIFACTORY_LOCATION_RELEASE' rather than '$ARTIFACTORY_LOCATION_SNAPSHOT'.")
    parser.add_argument('-v', '--verbose',
                        action='store_const', const=logging.DEBUG,
                        default=logging.INFO, help='turn on verbose messages')
    parser.add_argument('-t', '--test_only', action='store_true',
                        help='test only, do not store the box or send an email')

    args = parser.parse_args()

    input_box = args.BOX_FILE
    if args.message is None:
        # User did not add -m at all - and we always need a message
        args.message = 'No reason for update specified'
    message = args.message
    artifactory_release = args.release
    test_only = args.test_only

    if not input_box:
        sys.exit('No input box detected, use -b to specify a box')

    if not os.path.exists(input_box):
        sys.exit('%s does not exist' % input_box)

    boxname = os.path.basename(os.path.splitext(input_box)[0]) + '.box'

    logger.setLevel(level=args.verbose)

    logger.debug("Input box is:  '%s'" % input_box)
    logger.debug("Message is:    '%s'" % message)
    logger.debug("Sender is:     '%s'" % sender)
    logger.debug("Receiver is:   '%s'" % receiver)
    logger.debug("Release is:    '%s'" % artifactory_release)
    logger.debug("Test Only is:  '%s'" % test_only)

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
        sys.exit("Please set LOCATION_RELEASE or LOCATION_SNAPSHOT in your environment\n"
                 "E.g.: export 'ARTIFACTORY_LOCATION_SNAPSHOT=http://location', or: \n"
                 "E.g.: export 'ARTIFACTORY_LOCATION_RELEASE=http://location'")

    box_out = os.path.join(location, boxname)
    generate_hash(input_box)
    hash_out = os.path.join(location, os.path.basename(hash_file))

    if test_only is True:
        logger.debug('Test only: copying %s to %s' % (input_box, box_out))
        logger.debug('Test only: copying %s to %s' % (hash_file, hash_out))
    else:
        # Copy to artifactory
        logger.debug('Copying %s to %s' % (input_box, box_out))
        run(['curl', '-X', 'PUT', '-u', artifactory_username + ':' + artifactory_password, '-T', input_box, box_out, '--progress-bar'])
        logger.debug('Copying %s to %s' % (hash_file, hash_out))
        run(['curl', '-X', 'PUT', '-u', artifactory_username + ':' + artifactory_password, '-T', hash_file, hash_out])

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

    if args.verbose == logging.DEBUG or test_only:
        print('Email is:')
        print(email)

    if test_only is False:
        try:
            smtpObj = smtplib.SMTP('mail.cisco.com')
            smtpObj.sendmail(sender, receiver, email)
            logger.info('Successfully sent update email')
        except smtplib.SMTPException:
            logger.error('Unable to send update email')
    else:
        logger.debug('Test only: Not sending email')

if __name__ == '__main__':
    main(sys.argv[1:])
