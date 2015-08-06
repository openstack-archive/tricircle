# Devstack extras script to install Tricircle
function configure_tricircle_plugin {
    echo "Configuring Neutron for Tricircle"

    if is_service_enabled q-svc ; then
        Q_PLUGIN_CLASS="tricircle.networking_tricircle.plugin.TricirclePlugin"

        #NEUTRON_CONF=/etc/neutron/neutron.conf
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins ""
    fi

    if is_service_enabled t-svc ; then
	echo "Configuring Neutron for Tricircle Cascade Service"
	sudo install -d -o $STACK_USER -m 755 $TRICIRCLE_CONF_DIR
	cp -p $TRICIRCLE_DIR/etc/cascade_service.conf $TRICIRCLE_CASCADE_CONF

	iniset $TRICIRCLE_CASCADE_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
	iniset $TRICIRCLE_CASCADE_CONF DEFAULT verbose true
	setup_colorized_logging $TRICIRCLE_CASCADE_CONF DEFAULT
	iniset $TRICIRCLE_CASCADE_CONF DEFAULT bind_host $TRICIRCLE_CASCADE_LISTEN_ADDRESS
	iniset $TRICIRCLE_CASCADE_CONF DEFAULT use_syslog $SYSLOG
	iniset_rpc_backend tricircle $TRICIRCLE_CASCADE_CONF
	iniset $TRICIRCLE_CASCADE_CONF database connection `database_connection_url tricircle`
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

        recreate_database tricircle
        python "$TRICIRCLE_DIR/cmd/manage.py" "$TRICIRCLE_CASCADE_CONF"

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Cascading Service"

        if is_service_enabled t-svc; then
            run_process t-svc "python $TRICIRCLE_CASCADE_SERVICE --config-file $TRICIRCLE_CASCADE_CONF"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then

        if is_service_enabled t-svc; then
           stop_process t-svc
        fi
    fi
fi
