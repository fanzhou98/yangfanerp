#!/bin/zsh
cd -- "${0:A:h}"
erp_launch_args=()
if [[ -f data/lan-access.enabled ]]; then
  erp_wifi_ip=$(/usr/sbin/ipconfig getifaddr en0 2>/dev/null)
  erp_wifi_mask=$(/usr/sbin/ipconfig getoption en0 subnet_mask 2>/dev/null)
  if [[ -n "$erp_wifi_ip" && -n "$erp_wifi_mask" ]]; then
    erp_launch_args+=(--lan-address "$erp_wifi_ip/$erp_wifi_mask")
  else
    print '未检测到 Wi-Fi 地址，本次仅开启电脑本机访问。'
  fi
fi
if [[ -x /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 ]]; then
  exec /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 server.py "${erp_launch_args[@]}"
fi
exec python3 server.py "${erp_launch_args[@]}"
