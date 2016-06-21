#!/usr/bin/python
'''
A library of python expect classes and functions used to connect to a Cisco IOS
XR router. This file is designed to be called by pointing to another python
file with the actual CLI to be configured, or the functions within can be used
individually.

A typical use might be to do:

iosxr_pexpect.py -cmds 'socat TCP:localhost:<port> -,raw,echo=0,escape=0x1d' -config iosxr_setup

or:

iosxr_pexpect.py -cmds 'telnet localhost 15199' -config iosxr_setup

Pre-installed requirements:
python-pexpect
'''

import imp
import sys
import re
import os
import argparse
import logging
import pexpect
import time
import string


class Color:
    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[%dm"
    BOLD_SEQ = "\033[1m"


class ColorFormatter(logging.Formatter):
    FORMAT = ("%(asctime)s " +
              "($BOLD%(filename)-20s$RESET:%(lineno)-4d) " +
              "%(levelname)s " +
              "%(message)s")

    BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE = range(8)

    RESET_SEQ = "\033[0m"
    COLOR_SEQ = "\033[1;%dm"
    BOLD_SEQ = "\033[1m"

    COLORS = {
        'WARNING': RED,
        'INFO': GREEN,
        'DEBUG': BLUE,
        'CRITICAL': RED,
        'ERROR': RED
    }

    def formatter_msg(self, msg, use_color=True):
        if use_color:
            msg = msg.replace("$RESET", self.RESET_SEQ).replace("$BOLD", self.BOLD_SEQ)
        else:
            msg = msg.replace("$RESET", "").replace("$BOLD", "")
        return msg

    def __init__(self, use_color=True):
        msg = self.formatter_msg(self.FORMAT, use_color)

        logging.Formatter.__init__(self, msg, datefmt='%Y-%m-%d,%H:%M:%S')
        self.use_color = use_color

    def format(self, record):
        levelname = record.levelname

        if self.use_color and levelname in self.COLORS:
            fore_color = 30 + self.COLORS[levelname]
            levelname_color = self.COLOR_SEQ % fore_color + levelname + self.RESET_SEQ
            record.levelname = levelname_color

        return logging.Formatter.format(self, record)


class IosxrPexpect(object):
    #
    # A node in our network
    #
    class NodeSession(object):

        def __init__(self, node, port, port_name, pexpect):
            self.node = node
            self.port = port
            self.port_name = port_name
            self.pexpect = pexpect
            self.name = "(%s:%s %s)" % (node.name, port, port_name)

            reset = Color.RESET_SEQ
            if node.name == "node1":
                fg = Color.COLOR_SEQ % (Color.GREEN + 30)
                self.name = "(%s%s:%s %s%s)" % (fg, node.name, port, port_name, reset)
            elif node.name == "node2":
                fg = Color.COLOR_SEQ % (Color.BLUE + 30)
                self.name = "(%s%s:%s %s%s)" % (fg, node.name, port, port_name, reset)
            else:
                self.name = "(%s:%s %s)" % (node.name, port, port_name)

        #
        # Wrapper functions so we can call the node object and pass in the
        # pexpect session object
        #
        def send(self, send_txt, debug=""):
            return self.node.send(self, send_txt, debug)

        def read_data(self, debug="", timeout=1):
            return self.node.read_data(self, debug, timeout)

        def wait(self, wait_txt, debug="", timeout=1):
            return self.node.wait(self, wait_txt, debug, timeout)

        def repeat_until(self, send_txt, match_txt, debug="", timeout=1):
            return self.node.repeat_until(self, send_txt, match_txt, debug, timeout)

        def wait_xr_conf_mode(self):
            return self.node.wait_xr_conf_mode(self)

        def wait_xr_exec(self):
            return self.node.wait_xr_exec(self)

        #
        # Get an IP address from the given interface
        #
        def get_cisco_ip_address(self, nic, debug="Get IP address"):
            import re

            self.send("show ipv4 interface %s | i Internet address" % nic)

            time.sleep(2)

            output = self.wait("[\$#]", debug)

            ip = re.search(r'Internet address is (\S+)\/(\S+)', output)
            if ip:
                return ip.group(1)
            else:
                self.log("Failed to get IP address for %s" % nic)
                return None

        #
        # Waits until an ip address is found on the given interface
        #
        def must_get_cisco_ip_address(self, nic, debug="Get IP address"):

            time_started = time.time()
            while time.time() - time_started < self.node.maxtime:
                ip = self.get_cisco_ip_address(nic, debug)
                if ip is not None:
                    return ip

            self.fatal("Failed to get IP address for %s" % nic)

        #
        # API to allow tester to print a log message in the same format as other commands
        #
        def log(self, txt):

            msg = "%s: %s" % (self.name, txt)
            self.node.parent.logger.info(msg)

        #
        # API to allow tester to raise failure and exit the script
        #
        def fatal(self, txt):

            msg = "%s: %s" % (self.name, txt)
            self.node.parent.logger.error(msg)
            raise Exception(msg)

    class Node(object):
        name = ""
        cmdline = ""
        login = ""
        password = ""

        #
        # Max time to wait to complete any one block of commands, like
        # logging into a router
        #
        maxtime = 1800

        #
        # Serial port enumeration
        #
        class tty:
            xr, aux, admin, host = range(4)

        def __init__(self, parent, name,
                     clean=False,
                     login="vagrant",
                     password="vagrant"):

            self.name = name
            self.login = login
            self.password = password
            self.parent = parent
            self.ports = []
            self.sessions = []
            self.ttys = ["xr", "aux", "admin", "host"]
            self.clean = clean

            reset = Color.RESET_SEQ
            if name == "node1":
                fg = Color.COLOR_SEQ % (Color.GREEN + 30)
                self.debug_name = "%s%s%s" % (fg, name, reset)
            elif name == "node2":
                fg = Color.COLOR_SEQ % (Color.BLUE + 30)
                self.debug_name = "%s%s%s" % (fg, name, reset)
            else:
                self.debug_name = name

            self.start()

        #
        # Create a telnet session to the router
        #
        def pexpect_spawn(self, cmd, port, port_name, debug=""):

            msg = "(%s): Spawn (%s) %s" % (self.debug_name, cmd, debug)
            self.parent.logger.info(msg)

            self.session = IosxrPexpect.NodeSession(self, port, port_name, pexpect.spawn(cmd))
            self.sessions.append(self.session)

            if self.parent.opts.debug:
                self.parent.logger.info('Sessions: %s', self.sessions)

            return self.session

        #
        # Kick off telnet sessions to the router
        #
        def spawn_all_telnet_sessions(self, debug=""):

            if self.parent.opts.cmds is not None:
                index = 0

                for telnet_cmd in self.parent.opts.cmds:
                    port_name = telnet_cmd

                    msg = "(%s, port %s): Connect %s" % (self.debug_name, port_name, debug)
                    self.parent.logger.info(msg)

                    index += 1
                    self.pexpect_spawn(telnet_cmd, "", port_name, debug)
            else:
                index = 0
                for port in self.ports:
                    telnet_cmd = "telnet localhost %s" % port

                    port_name = self.ttys[index]
                    msg = "(%s, port %s): Connect %s" % (self.debug_name, port_name, debug)
                    self.parent.logger.info(msg)

                    index += 1
                    session = self.pexpect_spawn(telnet_cmd, port, port_name, debug)
                    self.send(session, "\377\375\042\377\373\001")

        #
        # Read data from the pexpect session
        #
        def read_data(self, session, debug="", timeout=1):

            #
            # Wait enough time for data to arrive else we just grab bits
            # and pieces of output
            #
            time.sleep(timeout)

            #
            # Slurp in data
            #
            session.pexpect.expect("")
            try:
                data = session.pexpect.read_nonblocking(size=10000, timeout=0)
            except pexpect.EOF:
                raise Exception("%s EOF on connection for: %s" % (session.name, debug))
            except pexpect.TIMEOUT:
                data = ""

            #
            # Print what we slurped?
            #
            if self.parent.opts.quiet == 0:
                data_no_newline = data.rstrip()
                if data_no_newline != "":
                    msg = "%s: %s" % (session.name, debug)
                    self.parent.logger.info(msg)
                    print data

            return data

        #
        # Open a XR console and return the NodeSession object
        #
        def wait_xr_login(self, username=None, userpass=None):

            if username is None:
                username = self.login

            if userpass is None:
                userpass = self.password

            time_seen_username_prompt = 0

            #
            # Get the XR telnet session
            #
            session = self.sessions[self.tty.xr]

            msg = "%s: Waiting for XR login prompt" % session.name
            self.parent.logger.info(msg)

            #
            # Do not run forever
            #
            time_started = time.time()

            #
            # Force an immediate enter first time around
            #
            time_pressed_enter = 0
            while time.time() - time_started < self.maxtime:

                debug = "Keep waiting for XR login prompt"
                data = self.read_data(session, debug, timeout=5)

                #
                # Operate on the last line only as we get lots of backed up
                # output when hitting enter during router boot
                #
                if self.parent.opts.debug:
                    print "data [%s]" % data

                lines = string.split(data, '\n')
                for data in reversed(lines):
                    if data != "":
                        #
                        # No point hitting enter if output is appearing
                        #
                        time_pressed_enter = time.time()
                        break

                if self.parent.opts.debug:
                    print "last line [%s]" % data

                #
                # First sign of life?
                #
                if re.search("Press RETURN to get started", data, re.MULTILINE):
                    msg = "%s: Got 'Press RETURN to get started'" % session.name
                    self.parent.logger.info(msg)

                    msg = "%s: Pressing enter to wake up router" % session.name
                    self.parent.logger.info(msg)
                    self.send(session, "")

                    self.parent.logger.info(
                            "Wait for first login request")
                    continue

                #
                # System asking for first login
                #
                if re.search("Enter root-system username:", data, re.MULTILINE):
                    msg = "%s: Got 'Enter root-system username:'" % session.name
                    self.parent.logger.info(msg)

                    self.send(session, username)

                    msg = "%s: Sent XR login '%s'" % (session.name, username)
                    self.parent.logger.info(msg)

                    self.parent.logger.info(
                        "Wait for password request")
                    continue

                #
                # Got login, now enter secret
                #
                if re.search("Enter secret:", data, re.MULTILINE):
                    msg = "%s: Got 'Enter secret'" % session.name
                    self.parent.logger.info(msg)

                    self.send(session, userpass)

                    msg = "%s: Sent password '%s'" % (session.name, userpass)
                    self.parent.logger.info(msg)

                    self.parent.logger.info(
                            "Wait for secret re-enter request")
                    continue

                #
                # Got login, now enter secret again
                #
                if re.search("Enter secret again", data, re.MULTILINE):
                    msg = "%s: Got 'Enter secret again'" % session.name
                    self.parent.logger.info(msg)

                    self.send(session, userpass)

                    msg = "%s: Sent password again '%s'" % \
                          (session.name, userpass)
                    self.parent.logger.info(msg)

                    self.parent.logger.info(
                            "Wait for secret request retry")
                    continue

                #
                # Login
                #
                if re.search("Username:", data, re.MULTILINE):
                    msg = "%s: Got 'Username'" % session.name
                    self.parent.logger.info(msg)

                    skip_username = 0

                    if time_seen_username_prompt != 0:
                        if time.time() - time_seen_username_prompt < 5:
                            msg = "%s: Got repeated 'Username' too soon, ignore" % session.name
                            self.parent.logger.info(msg)

                            self.send(session, "")
                            skip_username = 1

                    msg = "time_seen_username_prompt '%d'" % (time_seen_username_prompt)
                    self.parent.logger.info(msg)
                    msg = "skip_username '%d'" % (skip_username)
                    self.parent.logger.info(msg)

                    if skip_username == 0:
                        time_seen_username_prompt = time.time()

                        self.send(session, username)

                        msg = "%s: Sent username '%s'" % (session.name, username)
                        self.parent.logger.info(msg)
                        time.sleep(1)

                        self.parent.logger.info(
                                "Wait for password request")
                        continue

                #
                # Password
                #
                if re.search("Password:", data, re.MULTILINE):
                    msg = "%s: Got 'Password:'" % session.name
                    self.parent.logger.info(msg)

                    self.send(session, userpass)

                    msg = "%s: Sent password '%s'" % (session.name, userpass)
                    self.parent.logger.info(msg)

                    self.parent.logger.info(
                            "Wait for console access")
                    continue

                #
                # In conf t mode? Try to exit
                #
                if re.search("ios.config.*#", data, re.MULTILINE):
                    msg = "%s: Got 'ios.config.*#:'" % session.name
                    self.parent.logger.info(msg)

                    self.send(session, "exit")

                    msg = "%s: Exiting conf t mode" % session.name
                    self.parent.logger.info(msg)

                    self.parent.logger.info(
                            "Wait for console access after exit")
                    continue

                #
                # Changes half committed? We're in a mess
                #
                if re.search("Uncommitted changes found", data, re.MULTILINE):
                    self.send(session, "no")

                    msg = "%s: Aborting previous config" % session.name
                    self.parent.logger.info(msg)

                    self.parent.logger.info(
                            "Wait for console access after aborting config")
                    continue
                #
                # XR prompt ? We're in.
                #
                if re.search("ios#", data, re.MULTILINE):
                    msg = "%s: Successfully logged into XR" % session.name
                    self.parent.logger.info(msg)
                    return session

                if re.search("RP.*/CPU.*#", data, re.MULTILINE):
                    msg = "%s: Successfully logged into XR" % session.name
                    self.parent.logger.info(msg)
                    return session

                #
                # Press enter every x seconds to get some output
                #
                if (time.time() - time_pressed_enter) > 5:
                    time_pressed_enter = time.time()
                    self.send(session, "")

            raise Exception("%s timed out trying to login to XR" % session.name)

        def wait_xr_exec(self, session):

            msg = "%s: Waiting for XR exec prompt" % session.name
            self.parent.logger.info(msg)

            self.send(session, "")

            #
            # Do not run forever
            #
            time_started = time.time()
            time_pressed_enter = time_started
            while time.time() - time_started < self.maxtime:
                #
                # Press enter every 10 seconds to get some output
                #
                if (time.time() - time_pressed_enter) > 10:
                    time_pressed_enter = time.time()
                    self.send(session, "")

                data = self.read_data(session, "Waiting on XR exec prompt")

                #
                # XR prompt ? We're in.
                #
                if re.search("ios#", data, re.MULTILINE):
                    msg = "%s: Successfully entered exec mode" % session.name
                    self.parent.logger.info(msg)
                    return

            raise Exception("%s timed out trying to get into exec mode" %
                            session.name)

        def wait_xr_conf_mode(self, session):

            msg = "%s: Waiting for XR conf t prompt" % session.name
            self.parent.logger.info(msg)

            self.send(session, "")
            self.send(session, "conf t")

            #
            # Do not run forever
            #
            time_started = time.time()
            time_pressed_enter = time_started
            while time.time() - time_started < self.maxtime:
                #
                # Press enter every 10 seconds to get some output
                #
                if (time.time() - time_pressed_enter) > 10:
                    time_pressed_enter = time.time()
                    self.send(session, "")

                data = self.read_data(session, "Waiting on XR conf t prompt")

                #
                # XR prompt ? We're in.
                #
                if re.search("RP.*/CPU.*config.#", data, re.MULTILINE):
                    msg = "%s: Successfully entered conf t mode" % session.name
                    self.parent.logger.info(msg)
                    return

                #
                # XR prompt ? We're in.
                #
                if re.search("ios.config.#", data, re.MULTILINE):
                    msg = "%s: Successfully entered conf t mode" % session.name
                    self.parent.logger.info(msg)
                    return

            raise Exception("%s timed out trying to get into conf t mode" %
                            session.name)

        def repeat_until(self, session, send_txt, match_txt, debug="", timeout=1):

            if debug == "":
                msg = "%s: Repeat \"%s\" until \"%s\"" % \
                    (session.name, send_txt, match_txt)
            else:
                msg = "%s: Repeat \"%s\" until \"%s\" (%s)" % \
                    (session.name, send_txt, match_txt, debug)

            self.parent.logger.info(msg)
            count = 0

            #
            # Do not run forever
            #
            time_started = time.time()

            while time.time() - time_started < self.maxtime:
                self.send(session, send_txt)

                data = self.read_data(session, debug, timeout)

                if re.search(match_txt, data, re.MULTILINE):
                    if debug == "":
                        msg = "%s: Success, repeat \"%s\" until \"%s\"" % \
                            (session.name, send_txt, match_txt)
                    else:
                        msg = "%s: Success, repeat \"%s\" until \"%s\" (%s)" % \
                            (session.name, send_txt, match_txt, debug)

                    self.parent.logger.info(msg)

                    return data

                count += 1

                if debug == "":
                    msg = "%s: Repeat (retry %d) \"%s\" until \"%s\"" % \
                        (session.name, count, send_txt, match_txt)
                else:
                    msg = "%s: Repeat (retry %d) \"%s\" until \"%s\" (%s)" % \
                        (session.name, count, send_txt, match_txt, debug)

                self.parent.logger.info(msg)

            raise Exception("%s timed out (%s) trying to match %s" %
                            (session.name, debug, send_txt))

        #
        # Wrapper for pexpect sendline
        #
        def send(self, session, send_txt, debug=""):

            if send_txt == "":
                if debug == "":
                    msg = "%s: Send <enter>" % session.name
                else:
                    msg = "%s: Send <enter> (%s)" % (session.name, debug)
            else:
                if debug == "":
                    msg = "%s: Send \"%s\"" % (session.name, send_txt)
                else:
                    msg = "%s: Send \"%s\" (%s)" % (session.name, send_txt, debug)

            self.parent.logger.info(msg)

            session.pexpect.sendline(send_txt)

        #
        # Keep waiting for a regular expression
        #
        def wait(self, session, wait_txt, debug="", timeout=1):

            if debug == "":
                msg = "%s: Wait \"%s\"" % (session.name, wait_txt)
            else:
                msg = "%s: Wait \"%s\" (%s)" % (session.name, wait_txt, debug)

            self.parent.logger.info(msg)

            #
            # Do not run forever
            #
            time_started = time.time()
            time_pressed_enter = time_started
            while time.time() - time_started < self.maxtime:

                data = self.read_data(session, debug, timeout)

                #
                # XR prompt ? We're in.
                #
                if re.search(wait_txt, data, re.MULTILINE):
                    return data

                #
                # Press enter every 10 seconds to get some output
                #
                if (time.time() - time_pressed_enter) > 10:
                    if debug == "":
                        msg = "%s: Still waiting \"%s\"" % (session.name, wait_txt)
                    else:
                        msg = "%s: Still waiting \"%s\" (%s)" % (session.name, wait_txt, debug)

                    self.parent.logger.info(msg)

                    time_pressed_enter = time.time()
                    self.send(session, "")

            raise Exception("%s timed out (%s) trying to match %s" %
                            (session.name, debug, wait_txt))

        #
        # Close telnet sessions
        #
        def close(self):

            index = 0
            for session in self.sessions:

                port_name = self.ttys[index]
                msg = '%s: Close %s %s' % (session.name, port_name, session.port)
                self.parent.logger.info(msg)
                index += 1

                session.pexpect.close(force=True)

        #
        # Start a node running
        #
        def start(self, options=""):
            if self.clean:
                options += "-clean "

            self.spawn_all_telnet_sessions()

    def fatal(self, msg):
        self.node.parent.logger.error(msg)
        raise Exception(msg)

    def main(self):
        self.handler = logging.StreamHandler()
        self.handler.setLevel(logging.INFO)
        self.handler.setFormatter(ColorFormatter(logging.INFO))

        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.INFO)

        logging.addLevelName(logging.INFO,
                             "\033[1;31m%s\033[1;0m" % logging.getLevelName(logging.INFO))
        logging.addLevelName(logging.ERROR,
                             "\033[1;41m%s\033[1;0m" % logging.getLevelName(logging.ERROR))

        #
        # Initialize the parser
        #
        arger = argparse.ArgumentParser()

        arger.add_argument("-v", "--verbose", action="count", default=0)
        arger.add_argument("-d", "--debug", action="count", default=0)
        arger.add_argument("-quiet", "--quiet", action="count", default=0)

        arger.add_argument("-config", "--config",
                           help="name of configuration file to run",
                           required=True)

        arger.add_argument("-clean", "--clean",
                           action="count", default=0,
                           help="kills running nodes")

        arger.add_argument('-cmds', '--cmds', nargs='+',
                           help='commands to spawn for expect')

        #
        # Parse
        #
        self.opts = arger.parse_args()

        #
        # Pull in the configuration module to run.
        #
        pathname = os.path.dirname(sys.argv[0])
        full_pathname = os.path.abspath(pathname)
        full_path_config_file = os.path.abspath(pathname) + '/' + self.opts.config + '.py'

        if self.opts.debug:
            self.logger.info('path: %s', pathname)
            self.logger.info('sys.argv[0]: %s', sys.argv[0])
            self.logger.info('full path: %s', full_pathname)
            self.logger.info('config script: %s', self.opts.config)
            self.logger.info('full_path_config_file: %s', full_path_config_file)

        my_module = imp.load_source(self.opts.config, full_path_config_file)

        #
        # Create a new configuration and invoke it.
        #
        try:
            router = my_module.get_instance(self)
        except NameError:
            router = my_module.Iosxr_PexpectConfig(self)

        if self.opts.clean:
            router.clean_node()
        else:
            router.pre_node()
            router.run_node()
            router.post_node()

if __name__ == '__main__':
    IosxrPexpect().main()

exit(1)
