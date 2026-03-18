#!/bin/sh
# --------------------------------------------------------------
# sets permissions for streamfwd to capture network data
#   for modular input
# --------------------------------------------------------------
capable=0
os_has_setcap=0
built_with=0
setcap_installed=0
is_admin=0

os_built_with_file_caps() {
    kernel_version=`uname -r`
    make_file=/boot/config-$kernel_version
    found=$(echo `find /boot -type f -name config-$kernel_version`)
    if [ $found ] ; then
        command_run_ext=`grep 'CONFIG_EXT[0-9]_FS_XATTR=y' $make_file`;
        command_run_cap=`grep 'CONFIG_SECURITY_FILE_CAPABILITIES=y' $make_file`;
        ext_result=$(echo $command_run_ext)
        if [ "$ext_result" ] ; then
            cap_result=$(echo  $command_run_cap)
            if [ "$cap_result" ]; then
                built_with=1;
            fi
        fi
    else
        built_with=1
    fi
}

is_setcap_installed () {
    utility_name="setcap"
    index=1
    set /usr/sbin /usr/bin /usr/local/bin /usr/local/sbin /bin /sbin
    dir_count=$#
    while [ $index -le $dir_count ]
    do
        dir=`echo $* | cut -d " " -f$index,$index`
        result=$(echo `find $dir -type f -name $utility_name`);
        if [ $result ] ; then
            setcap_installed=1
            break
        fi
        index=`expr $index + 1`
    done
}

os_supports_setcap () {
    os_name=`uname -s`
    if [ $os_name = "Linux" ] ; then
        os_major_version=$(echo `uname -r | cut -d . -f1,1`)
        os_minor_version=$(echo `uname -r | cut -d . -f2,2`)
        micro_version=`uname -r | cut -d . -f3,3`
        os_micro_version=$(echo $micro_version | cut -d - -f1,1)
        if [ $os_major_version -eq 2 ] && [ $os_minor_version -eq 6 ] && [ $os_micro_version -ge 24 ] ; then
            os_built_with_file_caps
            if [ $built_with -eq 1 ] ; then
                os_has_setcap=1;
            fi
        elif [ $os_major_version  -eq 2 ] && [ $os_minor_version -gt 6 ] ; then
            os_has_setcap=1;
        elif [ $os_major_version -gt 2 ] ; then
            os_has_setcap=1;
        fi
    fi
}

has_capabilities () {
    os_supports_setcap
    if  [ $os_has_setcap -eq 1 ] ; then
        is_setcap_installed
        if [ $setcap_installed -eq 1 ] ; then
            capable=1;
        fi
    fi
}

check_user () {
    user_name=$(echo `whoami`)
    if [ $user_name != "root" ] ; then
        echo "You must run this script as a root user" 2>&1
        exit 1
    fi
}

run_as_root() {
    chown root $1
    chmod 4711 $1
}

set_capabilities() {
    setcap cap_sys_nice,cap_net_raw,cap_net_admin+ep $1
}



check_user
has_capabilities;
dir_name=`dirname $0`

if [ $capable -eq 1 ] ; then
    echo "setting capabilities"
    for exec_name in $dir_name/linux_x86/bin/streamfwd $dir_name/linux_x86_64/bin/streamfwd
    do
        if [ -f "$exec_name" ]; then
            set_capabilities $exec_name
        fi
    done
    echo "setting setuid for streamfwd-rhel6 - linux 64 bit version"
    run_as_root $dir_name/linux_x86_64/bin/streamfwd-rhel6
else
    echo "setting setuid"
    for exec_name in $dir_name/linux_x86/bin/streamfwd $dir_name/linux_x86_64/bin/streamfwd $dir_name/linux_x86_64/bin/streamfwd-rhel6 $dir_name/darwin_x86_64/bin/streamfwd
    do
        if [ -f "$exec_name" ]; then
            run_as_root $exec_name
        fi
    done
fi
