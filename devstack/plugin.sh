# Devstack extras script to install Tricircle
function configure_tricircle_plugin {
    echo "Configuring Neutron for Tricircle"

    if is_service_enabled q-svc ; then
        Q_PLUGIN_CLASS="tricircle.networking_tricircle.plugin.TricirclePlugin"

        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins ""
    fi
}


if [[ "$Q_ENABLE_TRICIRCLE" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo summary "Tricircle pre-install"
    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Tricircle"

        git_clone $TRICIRCLE_REPO $TRICIRCLE_DIR $TRICIRCLE_BRANCH


    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configure Tricircle"
        configure_tricircle_plugin
        echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto
    fi
fi
