#!/bin/sh
/sbin/mount -u -o rw /
mkdir -p /tmp
cd /tmp
/sbin/m5 readfile > /tmp/script.sh

if [ -s /tmp/script.sh ]; then
	chmod +x /tmp/script.sh
	/tmp/script.sh
fi
echo "Done Executing"
/sbin/m5 exit
