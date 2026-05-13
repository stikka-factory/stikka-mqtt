#!/usr/bin/sh

# This script will install stikka-NG on a  raspberry pi with the username pi. 
# It will install the necessary dependencies, 
# copy the configuration files, 
# and set up the systemd service.


echo "installing uv" 
wget -qO- https://astral.sh/uv/install.sh | sh

echo "installing pythion dependencies"
uv sync

echo "installing npm"
sudo apt update
sudo apt install npm -y

echo "copy settings"
cp default_config.json config.json

echo "copy udev rules"
sudo cp 90-brother_ql.rules /etc/udev/rules.d/
sudo cp 90-seiko_slp.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger

echo "copy service"
sudo cp stikka-NG.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable stikka-NG.service
sudo systemctl start stikka-NG.service