#!/usr/bin/sh

echo "installing uv" 
wget -qO- https://astral.sh/uv/install.sh | sh

echo "copy settings"
cp default_config.json config.json

echo "copy udev rules"
sudo cp 90-brother_ql.rules /etc/udev/rules.d/
sudo cp 90-seiko_slp.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "copy service 
sudo cp stikka-NG.service /etc/systemd/system/
