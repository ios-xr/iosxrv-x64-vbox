# README-CSR1000v.md

`iosxe_iso2vbox.py` is a tool to create an IOS XE Vagrant VirtualBox box from an IOS XE ISO image. The ISO will be installed into a VM, booted and configured. 

It can then be used as a *box* within Vagrant to bring up an IOS XE router that is fully configured to be used with NETCONF and RESTCONF.

`vagrant ssh` provides access to the IOS XE management interface with Internet access of IOS XE via the host. It includes and uses the insecure Vagrant SSH key to provide 'passwordless' authentication.

## Origin
For information about additional requirements and dependencies see the master [README.rst](README.rst) file. 

This script is a copy of the [iosxr_iso2vbox.py](iosxr_iso2vbox.py) and has been substantially modified and adapted for use with IOS XE. Also, logging and router interaction have been changed.

## Contributions
All contributions under this project are done so under the BSD license detailed in the LICENSE file contained in this repo.

## How to use this tool

1. *git clone* this repo:

		git clone https://github.com/ios-xr/iosxrv-x64-vbox.git

2. Install VirtualBox, Vagrant and socat (see [README.rst](README.rst) for more detail).
3. Download the appropriate ISO file, e.g. `csr1000v-universalk9.16.03.01.iso` from CCO (software image download requires a login with proper access rights)
4. Generate the (VirtualBox-flavored) Vagrant box by calling the script and provide the path to the CSR1kv ISO file. The rest is done automatically. The script has instructions printed when it is done. 

		./iosxe_iso2vbox.py csr1000v-universalk9.16.03.01.iso
5. There are a couple of command line options that can be applied. Their purpose is mainly for troubleshooting by increasing the verbosity of the output.
6. Full help output

```
$ python iosxe_iso2vbox.py --help
usage: iosxe_iso2vbox.py [-h] [-o] [-d] [-n] [--virtio] [-v] ISO_FILE

A tool to create an IOS XE Vagrant VirtualBox box from an IOS XE ISO.

The ISO will be installed, booted and configured.

"vagrant ssh" provides access to the IOS XE management interface
with internet access. It uses the insecure Vagrant SSH key.

positional arguments:
  ISO_FILE          local ISO filename or remote URI ISO filename

optional arguments:
  -h, --help        show this help message and exit
  -o, --create_ova  additionally use VBoxManage to export an OVA
  -d, --debug       will exit with the VM in a running state. Use: socat
                    TCP:localhost:65000 -,raw,echo=0,escape=0x1d to access
  -n, --nocolor     don't use colors for logging
  --virtio          set NIC type to virtio (only for IOS-XE 16.7 onwards)
  -v, --verbose     turn on verbose messages

E.g.:
    box build with local iso:
        iosxe_iso2vbox.py csr1000v-universalk9.16.03.01.iso
    box build with remote iso:
        iosxe_iso2vbox.py user@server:/myboxes/csr1000v-universalk9.16.03.01.iso
```


## Vagrant Box Usage
As a result of the build script, a *box* file is created. The path to that file with instruction is printed to the screen as a result of a successful build. To bring up a Vagrant instance based on that IOS XE box one has to go through the following steps:

1.	`vagrant box add --name iosxe cisco-iosxe.box --force ` (where `cisco-iosxe.box` is the resulting box name as printed by the script), `--force` is only required if you already have a box installed and need to overwrite it with a newer version of the box
2. Create a directory, in that directory do a `vagrant init iosxe` (assuming the name is `iosxe`. That name can be changed when adding the box to Vagrant)
3. Then bring up the box via `vagrant up`
4. The box will boot and will print a license banner as shown below when fully started
5. Login to the router using `vagrant ssh`

> **Note:** This is not the serial console. The serial console is **not** exposed. A serial port can be added in the Vagrantfile that adds a serial port. See the build-script for an example. 
> 
> **Note:** The resulting Vagrant box has only ONE interface. If additional interfaces are required then those must be added in the actual Vagrantfile within the directory where the box has been deployed. If multiple routers should be deployed which are connected to each other than the XR `vagrantfiles` directory has additional examples which can be adapted for use with IOS XE.
 
## Sample Output

### Create the Box / Run the Script

	(iosxrv-x64-vbox) host:iosxrv-x64-vbox user$ ./iosxe_iso2vbox.py ~/Downloads/csr1000v-universalk9.16.03.01.iso
	==> Input ISO is /home/user/Downloads/csr1000v-universalk9.16.03.01.iso
	==> Creating VirtualBox VM
	==> Starting VM...
	==> Successfully started to boot VM disk image
	==> Waiting for IOS XE to boot (may take 3 minutes or so)
	==> Logging into Vagrant Virtualbox and configuring IOS XE
	==> Waiting 10 seconds...
	==> Powering down and generating Vagrant VirtualBox
	==> Waiting for machine to shutdown
	==> Compact VDI
	==> Building Vagrant box
	==> Created: /home/user/iosxe-tools/iosxrv-x64-vbox/machines/csr1000v-universalk9.16.03.01/csr1000v-universalk9.16.03.01.box
	==> Add box to system:
	==>   vagrant box add --name iosxe /home/user/iosxe-tools/iosxrv-x64-vbox/machines/csr1000v-universalk9.16.03.01/csr1000v-universalk9.16.03.01.box --force
	==> Initialize environment:
	==>   vagrant init iosxe
	==> Bring up box:
	==>   vagrant up
	==> Note:
	==>   Both the XE SSH and NETCONF/RESTCONF username and password is vagrant/vagrant
	(iosxrv-x64-vbox) host:iosxrv-x64-vbox user$

### Add Box to Vagrant and Starting an Instance

	(iosxrv-x64-vbox) host:iosxrv-x64-vbox user$ vagrant box add --name iosxe /home/user/iosxe-tools/iosxrv-x64-vbox/machines/csr1000v-universalk9.16.03.01/csr1000v-universalk9.16.03.01.box --force
	==> box: Box file was not detected as metadata. Adding it directly...
	==> box: Adding box 'iosxe' (v0) for provider:
	    box: Unpacking necessary files from: file:///home/user/iosxe-tools/iosxrv-x64-vbox/machines/csr1000v-universalk9.16.03.01/csr1000v-universalk9.16.03.01.box
	==> box: Successfully added box 'iosxe' (v0) for 'virtualbox'!
	(iosxrv-x64-vbox) host:iosxrv-x64-vbox user$
	Initialize Vagrant Box Instance and Up the Instance
	(iosxrv-x64-vbox) host:iosxrv-x64-vbox user$ mkdir TEST
	(iosxrv-x64-vbox) host:iosxrv-x64-vbox user$ cd TEST/
	(iosxrv-x64-vbox) host:TEST user$ vagrant init iosxe
	A `Vagrantfile` has been placed in this directory. You are now
	ready to `vagrant up` your first virtual environment! Please read
	the comments in the Vagrantfile as well as documentation on
	`vagrantup.com` for more information on using Vagrant.
	(iosxrv-x64-vbox) host:TEST user$ vagrant up
	Bringing machine 'default' up with 'virtualbox' provider...
	==> default: Importing base box 'iosxe'...
	==> default: Matching MAC address for NAT networking...
	==> default: Setting the name of the VM: TEST_default_1473426485832_89279
	==> default: Clearing any previously set network interfaces...
	==> default: Preparing network interfaces based on configuration...
	    default: Adapter 1: nat
	==> default: Forwarding ports...
	    default: 830 (guest) => 2223 (host) (adapter 1)
	    default: 80 (guest) => 2224 (host) (adapter 1)
	    default: 443 (guest) => 2225 (host) (adapter 1)
	    default: 22 (guest) => 2222 (host) (adapter 1)
	==> default: Running 'pre-boot' VM customizations...
	==> default: Booting VM...
	==> default: Waiting for machine to boot. This may take a few minutes...
	    default: SSH address: 127.0.0.1:2222
	    default: SSH username: vagrant
	    default: SSH auth method: private key
	==> default: Machine booted and ready!
	==> default: Checking for guest additions in VM...
	    default: No guest additions were detected on the base box for this VM! Guest
	    default: additions are required for forwarded ports, shared folders, host only
	    default: networking, and more. If SSH fails on this machine, please install
	    default: the guest additions and repackage the box to continue.
	    default:
	    default: This is not an error message; everything may continue to work properly,
	    default: in which case you may ignore this message.
	 
	==> default: Machine 'default' has a post `vagrant up` message. This is a message
	==> default: from the creator of the Vagrantfile, and not from Vagrant itself:
	==> default:
	==> default:
	==> default:     Welcome to the IOS XE VirtualBox.
	==> default:     To connect to the XE via ssh, use: 'vagrant ssh'.
	==> default:     To ssh to XE's NETCONF or RESTCONF agent, use:
	==> default:     'vagrant port' (vagrant version > 1.8)
	==> default:     to determine the port that maps to the guestport,
	==> default:
	==> default:     The password for the vagrant user is vagrant
	==> default:
	==> default:     IMPORTANT:  READ CAREFULLY
	==> default:     The Software is subject to and governed by the terms and conditions
	==> default:     of the End User License Agreement and the Supplemental End User
	==> default:     License Agreement accompanying the product, made available at the
	==> default:     time of your order, or posted on the Cisco website at
	==> default:     www.cisco.com/go/terms (collectively, the 'Agreement').
	==> default:     As set forth more fully in the Agreement, use of the Software is
	==> default:     strictly limited to internal use in a non-production environment
	==> default:     solely for demonstration and evaluation purposes. Downloading,
	==> default:     installing, or using the Software constitutes acceptance of the
	==> default:     Agreement, and you are binding yourself and the business entity
	==> default:     that you represent to the Agreement. If you do not agree to all
	==> default:     of the terms of the Agreement, then Cisco is unwilling to license
	==> default:     the Software to you and (a) you may not download, install or use the
	==> default:     Software, and (b) you may return the Software as more fully set forth
	==> default:     in the Agreement.
	(iosxrv-x64-vbox) host:TEST user$

### Accessing the Router
	(iosxrv-x64-vbox) host:TEST user$ vagrant ssh
	 
	csr1kv#
	csr1kv#
	csr1kv#

### Using NETCONF
Display the mapped ports:

	(iosxrv-x64-vbox) host:TEST user$ vagrant port
	The forwarded ports for the machine are listed below. Please note that
	these values may differ from values configured in the Vagrantfile if the
	provider supports automatic port collision detection and resolution.
	 
	 
	   830 (guest) => 2223 (host)
	    80 (guest) => 2224 (host)
	   443 (guest) => 2225 (host)
	    22 (guest) => 2222 (host)
	(iosxrv-x64-vbox) host:TEST user$

And then SSH to the box (note that the password is 'vagrant':

	(iosxrv-x64-vbox) host:TEST user$ ssh -p 2223 vagrant@localhost -s netconf
	The authenticity of host '[localhost]:2223 ([127.0.0.1]:2223)' can't be established.
	RSA key fingerprint is SHA256:pH+NMr2hIAbmNUgaJHBg8tyNJEQwTQX+jucUrJTU7RY.
	Are you sure you want to continue connecting (yes/no)? yes
	Warning: Permanently added '[localhost]:2223' (RSA) to the list of known hosts.
	vagrant@localhost's password:
	<?xml version="1.0" encoding="UTF-8"?>
	<hello xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
	<capabilities>
	<capability>urn:ietf:params:netconf:base:1.0</capability>
	<capability>urn:ietf:params:netconf:base:1.1</capability>
	<capability>urn:ietf:params:netconf:capability:writable-running:1.0</capability>
	<capability>urn:ietf:params:netconf:capability:xpath:1.0</capability>
	[...]

> **Note:** The SSH server for NETCONF is different from the SSH server of the IOS device and hence does not know the Vagrant insecure SSH key (e.g. the pub key has not been 'accepted' into the SSH daemon / authorized_keys). We have to use password authentication in this case unless there is a way to inject the SSH pub key into the NETCONF agent.

### Using RESTCONF

#### IOS-XE 16.6.1 And Later

IOS-XE 16.6.1 and later support RFC 8040-compliant RESTCONF. For example, try this command:

```
curl -k -u vagrant:vagrant \
    -H 'Accept: application/yang-data+json' \
    https://localhost:2224/restconf/data/native?content=config
```

The `-k` is required to address the default self-signed certificate that is created in the vagrant image. The `Accept` header shows how to extract JSON-formatted data from the image. And, finally, the URL parameter `content=config` indicates that only configuration data should be retrieved (yes, there is a matching `content=nonconfig`). Also note the use of **https**; IOS-XE 16.6.1 onwards does not support unencrypted RESTCONF traffic.

Please see [RFC8040](https://tools.ietf.org/html/rfc8040) for more details.

#### IOS-XE 16.5.1 And Earlier

Again, using vagrant port determine the port where the RESTCONF agent is listening on (see above for the example used). The RESTCONF API entry point is at `/restconf/api`:

	(iosxrv-x64-vbox) host:TEST user$ curl --user vagrant:vagrant http://localhost:2224/restconf/api
	<api xmlns="http://tail-f.com/ns/rest" xmlns:y="http://tail-f.com/ns/rest">
	  <version>0.5</version>
	  <config/>
	  <running/>
	  <operational/>
	  <operations>
	    <bd:clear-mac-address>/api/operations/bd:clear-mac-address</bd:clear-mac-address>
	    <bd:clear-bridge-domain>/api/operations/bd:clear-bridge-domain</bd:clear-bridge-domain>
	[...]

> **Note:** The data returned by the RESTCONF agent is represented as XML. If we want it to be JSON encoded then we need to send the appropriate HTTP header. E.g. `Accept: application/vnd.yang.data+json` would have achieved JSON encoding.

