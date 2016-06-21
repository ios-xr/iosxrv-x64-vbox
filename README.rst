============================================
xr-cp-vbox soon to be iosxr-create-vbox
============================================

--------------
Contributions
--------------
All contributions under this project are done so under the BSD
license detailed in the LICENSE file contained in this repo.

------------------------------
Purpose of this repository
------------------------------
The purpose of this workflow is to provide an IOS XR Virtual Machine
to the user in the vagrant virtualbox format, without being concerned
with the underlying architecture or networking that the VM is running
on; so that the end user can access the app-hosting Linux environment,
or simply begin to play with IOS XR - all with the convenience and
economic benefit of using their existing laptop hardware.

Currently this supports IOS XRv (64-bit) only but will be adapted to
also handle IOS XRv9k images.

^^^^^^^^^^^^^^^^^^^^^^^^^
An IOS XRv (64-bit) VM:
^^^^^^^^^^^^^^^^^^^^^^^^^
Is an IOS XR Control Plane image built on with the latest XR
architecture, with a 64-bit Wind River Linux (WRL) kernel.

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
E.g. 'vagrant add' and 'vagrant ssh'.

IOS XR is pre-booted and pre-configured in XR and WRL, with IP
connectivity out of the box with an embedded Vagrantfile providing
username/password and port-forwarding as well as internet connectivity
(dhcp using vagrants ip address pool) for ease of use.

App-hosting space (WRL7) is preconfigured with a user 'vagrant',
password-less ssh, domain servers so the user can access the internet;
basically set up to do app development out-of-the-box.

Therefore the user does not have to worry about networking, wiring,
NICs and NIC drivers, connectivity, memory allocation etc - it's all
going to work out of the 'box'.

A ‘vagrant ssh’ command takes the user directly to the app-hosting
space, no password needed. No messy configuration of resolv.conf
issues for DNS lookup.

The box also allows IOS XR Console access, ssh if a k9 image, telnet if not.

The IOS XR configuration that comes with the box that allows external
connectivity is:

RP/0/RP0/CPU0:ios#show run
Wed May 11 16:28:40.484 UTC
Building configuration...
!! IOS XR Configuration version = 6.1.1.14I
!! Last configuration change at Tue May 10 13:02:15 2016 by vagrant
!
telnet vrf default ipv4 server max-servers 10
username vagrant
group root-lr
group cisco-support
secret 5 $1$.8ox$u9e4lV0IOOezL2efarypX/
!
tpa
address-family ipv4
update-source MgmtEth0/RP0/CPU0/0
!
!
interface MgmtEth0/RP0/CPU0/0
ipv4 address dhcp
!
router static
address-family ipv4 unicast
0.0.0.0/0 MgmtEth0/RP0/CPU0/0 10.0.2.2
!
!
ssh server v2
ssh server vrf default
grpc
port 57777
!
end

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

1. git clone this repo.
2. Install virtualbox and vagrant (see guide below).
3. Download the appropriate ISO file, e.g. iosxrv-fullk9-x64.iso
4. Generate the virtualbox box:
   E.g. xr-cp-vbox/iosxr_iso2vbox.py -i iosxrv-fullk9-x64.iso

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
How to install vagrant and virtualbox
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
This example is specific to OSX and is a guide only, users should
research what their particular environment requires to run vagrant,
virtualbox and pexpect:

* Recommend using the Homebrew package manager.
* Make sure you install version 5.x virtualbox
* Vagrant latest version is: 1.8.2
* Website:  http://brew.sh/
* /usr/bin/ruby -e "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install)"
* brew cask install virtualbox
* brew cask install vagrant
  * Source: http://sourabhbajaj.com/mac-setup/Vagrant/README.html
* Note you may need to install pexpect too:
* brew cask install python
* pip install pexpect

^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Once box is created - how do I run it?
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
How to bring up a single node instance:
  * vagrant init 'IOS XRv'
  * vagrant box add --name 'IOS XRv' iosxrv-fullk9-x64.box --force
  * vagrant up
  * vagrant ssh - to access opernns App Hosting / XR Linux space (wait for vagrant to finish and prompt you)
  * To access XR Console:
  * 'ssh -p 2222 vagrant@127.0.0.1'
  * Note the port can be changed by vagrant so 'vagrant port' will
    list the ports.

Bring up multiple node instances:
  * Copy a multi-node Vagrantfile from
    - vagrantfiles/simple-mixed-topo/Vagrantfile
  * Note that this Vagrantfile will pull the ubuntu VM from Atlas.
  * Add the box to vagrant:
    - vagrant box add --name 'IOS XRv' iosxrv-fullk9-x64.box --force;
  * vagrant up
  * To access opernns App Hosting / XR Linux spaces
  * vagrant ssh rtr1 / vagrant ssh rtr2
  * To access XR Console:
  * 'vagrant port <node name>' will list the ports.
  * Then do: ssh vagrant@localhost -p <port from above>
  * E.g: ssh vagrant@localhost -p 2223
  * Repeat for each node

