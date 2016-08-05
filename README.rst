===============
iosxrv-x64-vbox
===============

--------------
Contributions
--------------
All contributions under this project are done so under the BSD
license detailed in the LICENSE file contained in this repo.

------------------------------
Purpose of this repository
------------------------------
The purpose of this workflow is to provide an IOS XR Virtual Machine
to the user in the Vagrant_ VirtualBox_ format, without being concerned
with the underlying architecture or networking that the VM is running
on; so that the end user can access the app-hosting Linux environment,
or simply begin to play with IOS XR - all with the convenience and
economic benefit of using their existing laptop hardware.

Currently this supports IOS XRv (64-bit) only but will be adapted to
also handle `IOS XRv 9000`_ images.

^^^^^^^^^^^^^^^^^^^^^^^^^
An IOS XRv (64-bit) VM:
^^^^^^^^^^^^^^^^^^^^^^^^^
Is an IOS XR Control Plane image built on with the latest XR
architecture, with a 64-bit `Wind River Linux`_ (WRL) kernel.

This includes eXR – access to the WR7 Linux kernel including Netstack,
giving access to the underlying server's interfaces and an app-hosting
environment.

Small enough at 3G (mini) or 4G (full) to run on hardware with limited
RAM (like a mac laptop).

Forwarding is supplied by SPP/Virtio - the same as the legacy IOS XRv
(32-bit) platform.

This is the migration path from IOS XRv (32-bit) for education and
simulation purposes.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
An IOS XRv (64-bit) Vagrant Virtualbox:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Is a virtual machine image containing IOS XRv (64-bit) and metadata,
that can be brought up by standard vagrant commands.
E.g. ``vagrant add`` and ``vagrant ssh``.

IOS XR is pre-installed and pre-configured in XR and WRL, with IP
connectivity out of the box with an embedded Vagrantfile providing
username/password and port-forwarding as well as internet connectivity
(DHCP using Vagrant's IP address pool) for ease of use.

App-hosting space (WRL7_) is preconfigured with a user 'vagrant',
password-less SSH, domain servers so the user can access the internet;
basically set up to do app development out-of-the-box.

Therefore the user does not have to worry about networking, wiring,
NICs and NIC drivers, connectivity, memory allocation etc - it's all
going to work out of the 'box'.

A ``vagrant ssh`` command takes the user directly to the app-hosting
space, no password needed. No messy configuration of ``/etc/resolv.conf``
issues for DNS lookup.

The box also allows IOS XR Console access, via SSH if a k9 image,
via telnet if not.

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
The iosxr_iso2vbox.py tool is:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
A tool written to convert an IOS XRv (64-bit) ISO image to a
Virtualbox image that can be brought up by vagrant.

The tool creates the Virtualbox image, brings it up, configures XR and
opernns Linux so that future uses of the box bring it up fully
networked and ready to run.

^^^^^^^^^^^^^^^^^^^^^^
How to use this tool
^^^^^^^^^^^^^^^^^^^^^^

1. git clone this repo:

   ::

      git clone https://github.com/ios-xr/iosxrv-x64-vbox.git

2. Install VirtualBox, Vagrant and socat (see guide below).
3. Download the appropriate ISO file, e.g. ``iosxrv-fullk9-x64.iso``
4. Generate the VirtualBox box:

   ::

      ./iosxrv-x64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso

5. Example with verbosity off

   ::

      iosxrv-x64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso
      [iosxr_iso2vbox.py:428 -                 main() ] Creating Vagrant VirtualBox
      [iosxr_iso2vbox.py:155 -         configure_xr() ] Logging into Vagrant Virtualbox and configuring IOS XR
      [iosxr_iso2vbox.py:584 -                 main() ] Powering down and generating Vagrant VirtualBox
      [iosxr_iso2vbox.py:614 -                 main() ] Created: /Users/rwellum/Desktop/Boxes/machines/iosxrv-fullk9-x64/iosxrv-fullk9-x64.box
      [iosxr_iso2vbox.py:624 -                 main() ] Running basic unit tests on Vagrant VirtualBox...
      [iosxr_iso2vbox.py:645 -                 main() ] Passed basic test, box /Users/rwellum/Desktop/Boxes/machines/iosxrv-fullk9-x64/iosxrv-fullk9-x64.box is sane

6. Full help output

   ::

      iosxrv-x64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso -h
      usage: iosxr_iso2vbox.py [-h] [-o] [-s] [-d] [-v]
             ISO_FILE

      A tool to create an IOS XRv Vagrant VirtualBox box from an IOS XRv ISO.

      The ISO will be installed, booted, configured and unit-tested.
      "vagrant ssh" provides access to IOS XR Linux global-vrf namespace
      with internet access.

      positional arguments:
      ISO_FILE              local ISO filename or remote URI ISO filename...

      optional arguments:
      -h, --help            show this help message and exit
      -o, --create_ova      additionally use vboxmanage to export an OVA
      -s, --skip_test       skip unit testing
      -d, --debug           will exit with the VM in a running state. Use: socat
                            TCP:localhost:65000 -,raw,echo=0,escape=0x1d to access
      -v, --verbose         turn on verbose messages

      E.g.:
      box build with local iso: iosxr-xrv64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso
      box build with remote iso: iosxr-xrv64-vbox/iosxr_iso2vbox.py user@server:/myboxes/iosxrv-fullk9-x64.iso
      box build with ova export and verbose: iosxr-xrv64-vbox/iosxr_iso2vbox.py iosxrv-fullk9-x64.iso -o -v

^^^^^^^^^^^^^^^^^^^^^^^^^^^
The iosxr_store.py tool is:
^^^^^^^^^^^^^^^^^^^^^^^^^^^
A tool written to copy a generated box to a repository, with a
generated message to an alias.

^^^^^^^^^^^^^^^^^^^^^^
How to use this tool
^^^^^^^^^^^^^^^^^^^^^^

::

   rwellum@RWELLUM-M-34DF:[~/Desktop/Boxes]: iosxrv-x64-vbox/iosxr_store_box.py -h
   usage: iosxr_store_box.py [-h] [-m MESSAGE] [-r] -s SUBDIR [-v] [-t] BOX_FILE

   A tool to upload an image to a maven repo like artifactory using curl, the image typically being a vagrant virtualbox.
   User can select snapshot or release, the release images get synced to devhub.cisco.com - where they are available to customers.
   This tool also sends an email out to an email address or an alias to inform them of the new image.
   It is designed to be called from other tools, like iosxr_ios2vbox.py.

   It will rely on the following environment variables to work:
     ARTIFACTORY_USERNAME
     ARTIFACTORY_PASSWORD
     ARTIFACTORY_LOCATION_SNAPSHOT
     ARTIFACTORY_LOCATION_RELEASE
     ARTIFACTORY_SENDER
     ARTIFACTORY_RECEIVER

   positional arguments:
     BOX_FILE              BOX filename

     optional arguments:
       -h, --help            show this help message and exit
       -m MESSAGE, --message MESSAGE
                             Optionally specify a reason for uploading this box
       -r, --release         upload to '$ARTIFACTORY_LOCATION_RELEASE' rather than
                             '$ARTIFACTORY_LOCATION_SNAPSHOT'.
       -s SUBDIR, --subdirectory SUBDIR
                             subdirectory to upload to, e.g '6.1.1', 'stable'
       -v, --verbose         turn on verbose messages
       -t, --test_only       test only, do not store the box or send an email

       E.g.:
       iosxrv-x64-vbox/iosxr_store_box.py iosxrv-fullk9-x64.box --release --verbose --message 'A new box because...'
       iosxrv-x64-vbox/iosxr_store_box.py iosxrv-fullk9-x64.box --release, --message 'A new box because...'
       iosxrv-x64-vbox/iosxr_store_box.py iosxrv-fullk9-x64.box -r -v -m
       'Latest box for release.'

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
How to install Vagrant, VirtualBox and socat
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
This example is specific to OS X and is a guide only, users should
research what their particular environment requires to run Vagrant_,
VirtualBox_, and Pexpect_:

* Recommend using the Homebrew_ package manager.
* Make sure you install version 5.x virtualbox
* Vagrant latest version is: 1.8.2

::

   /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
   brew cask install virtualbox
   brew cask install vagrant
   brew install socat

See also: http://sourabhbajaj.com/mac-setup/Vagrant/README.html

You may need to install Pexpect too:
::

   brew cask install python
   pip install pexpect


^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Once box is created - how do I bring it up?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

'''''''''''''''''''''''''''''''''''''''
How to bring up a single node instance:
'''''''''''''''''''''''''''''''''''''''

* Add the box to Vagrant and bring up the node:
  ::

     vagrant init 'IOS XRv'
     vagrant box add --name 'IOS XRv' iosxrv-fullk9-x64.box --force
     vagrant up

* Wait for vagrant to finish and prompt you

* To access operns App Hosting / XR Linux space:
  ::

     vagrant ssh

* To access XR Console:
  ::

     ssh -p 2222 vagrant@127.0.0.1

  Note this port number can be changed by Vagrant, so ``vagrant port`` will
  list the ports.

''''''''''''''''''''''''''''''''''''''''
How to bring up multiple node instances:
''''''''''''''''''''''''''''''''''''''''

* Copy a multi-node Vagrantfile from ``iosxrv-x64-vbox/vagrantfiles/simple-mixed-topo/Vagrantfile``
* Note that this Vagrantfile will pull the ubuntu VM from Atlas.
* Add the box to Vagrant and bring up the topology:
  ::

     vagrant box add --name 'IOS XRv' iosxrv-fullk9-x64.box --force
     vagrant up

* To access opernns App Hosting / XR Linux spaces:
  ::

    vagrant ssh rtr1
    vagrant ssh rtr2

* To access XR Console:
  ::

    # List the ports assigned to a given node
    vagrant port rtr2
    # Then do: ssh vagrant@localhost -p <port from above>
    # E.g: ssh vagrant@localhost -p 2223
    # Repeat for each node

.. _`IOS XRv 9000`: http://www.cisco.com/c/en/us/support/routers/ios-xrv-9000-router/tsd-products-support-series-home.html
.. _Homebrew: http://brew.sh/
.. _Pexpect: https://pexpect.readthedocs.io/
.. _Vagrant: https://www.vagrantup.com/
.. _VirtualBox: https://www.virtualbox.org/
.. _`Wind River Linux`: http://www.windriver.com/products/linux/
.. _WRL7: http://www.windriver.com/announces/wr-linux-7/
