#!/bin/bash
 set -x
 sudo rm -rf /home/vagrant/config_logs
 sudo rm -rf /home/vagrant/config_failed_logs
 INTNS_CMD="sudo nsenter -t 1 -n --"


 while :
  do
      $INTNS_CMD /pkg/bin/config -p15 -X -f $1 -c "config" > /home/vagrant/config_logs 2>&1
      if [ $? -ne 0 ] ; then
          # If we need to wait for stable system, let's wait, otherwise we will quit (likely issue in config)
          if [ `grep "SYSTEM CONFIGURATION IS STILL IN PROGRESS" /home/vagrant/config_logs | wc -l` -ne 0 ]; then
              echo "SYSTEM CONFIGURATION going on, let us retry";
              sleep 5;
          elif [ `grep "Successfully entered exclusive" /home/vagrant/config_logs | wc -l` -ne 0 ]; then
              $INTNS_CMD -- /pkg/bin/cfgmgr_show_failed -c > /home/vagrant/config_failed_logs 2>&1
              if [ `grep "ERROR" /home/vagrant/config_failed_logs | wc -l` -eq 1 ]; then
                  echo "Configuration is applied with possible error"
                  echo "Failure is saved to /home/vagrant/config_failed_logs"
                  break
              fi
          else
              echo "Couldn't acquire lock, retry in 5sec..";
              sleep 5;
          fi
    else
      # command completed fine
      break
    fi
  done


