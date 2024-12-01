#!/bin/bash

# Script to set up the project on Debian 12

echo "Updating package lists..."
sudo apt update

echo "Installing system dependencies..."
sudo apt install -y python3 python3-pip python3-venv build-essential libasound2-dev libpjsua-dev

echo "Setting up Python virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "Setup complete. Use 'source venv/bin/activate' to activate the environment."