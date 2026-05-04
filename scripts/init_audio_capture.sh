#!/bin/bash
# Initialize Qualcomm audio mixer for 3.5mm mic capture on Particle Tachyon
set -e

echo "Setting up audio capture path..."

amixer -D hw:0 cset numid=6728 "One"
amixer -D hw:0 cset numid=5225 192,192
amixer -D hw:0 cset numid=5227 8
amixer -D hw:0 cset numid=5228 8
amixer -D hw:0 cset numid=5226 0
amixer -D hw:0 cset numid=6746 "Line 1L"
amixer -D hw:0 cset numid=6750 "left data = left ADC, right data = left ADC"
amixer -D hw:0 cset numid=599 on,on

echo "Audio capture path initialized."
