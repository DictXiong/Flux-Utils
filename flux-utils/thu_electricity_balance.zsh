#!/usr/bin/env zsh
set -e

fatal() {
    echo FATAL: $@ > /dev/stderr
    exit 1
}

test -n "$FLUX_THU_USER" || fatal "set FLUX_THU_USER to your student id"
test -n "$FLUX_THU_PASS" || fatal "set FLUX_THU_PASS to your my-home password"

tmp=$(curl -fsSL http://myhome.tsinghua.edu.cn/web_netweb_user/noLogin.aspx | grep VIEWSTATE)
viewstate=$(echo $tmp | head -n 1 | sed 's/.*value="\(.*\)".*/\1/g')
viewstategen=$(echo $tmp | tail -n 1 | sed 's/.*value="\(.*\)".*/\1/g')
test -n "$viewstate" || fatal "error getting viewstate"
test -n "$viewstategen" || fatal "error getting viewstategen"

tmp=$(curl -v --location 'http://myhome.tsinghua.edu.cn/web_netweb_user/noLogin.aspx' --form "__VIEWSTATE=\"$viewstate\"" --form "__VIEWSTATEGENERATOR=\"$viewstategen\"" --form "net_Default_LoginCtrl1\$txtUserName=\"$FLUX_THU_USER\"" --form "net_Default_LoginCtrl1\$txtPassword=\"$FLUX_THU_PASS\"" --form 'net_Default_LoginCtrl1$btnLogin="%B5%C7++%C2%BC"' 2>&1 >/dev/null | grep ASP.NET_SessionId)
sess_id=$(echo $tmp | sed 's/.*SessionId=\(.*\); path.*/\1/g')
test -n "$sess_id" || fatal "error getting sess_id"

tmp=$(curl -fsSL -b "ASP.NET_SessionId=$sess_id" http://myhome.tsinghua.edu.cn/web_Netweb_List/Netweb_Home_electricity_Detail.aspx)
raw_time=$(echo $tmp | grep Netweb_Home_electricity_DetailCtrl1_lbltime | sed 's?.*Red">\(.*\)</font.*?\1?g' )
test -n "$raw_time" || fatal "error getting time from web page"
ts=$(date -d $raw_time +%s)000000000
balance=$(echo $tmp | grep Netweb_Home_electricity_DetailCtrl1_lblele | sed 's?.*Red">\(.*\)</font.*?\1?g' )
test -n "$balance" || fatal "error getting balance from web page"
echo electricity_balance value=$balance $ts
