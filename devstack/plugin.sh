# Devstack extras script to install Tricircle

# Test if any tricircle services are enabled
# is_tricircle_enabled
function is_tricircle_enabled {
    [[ ,${ENABLED_SERVICES} =~ ,"t-svc-" ]] && return 0
    return 1
}

# create_tricircle_accounts() - Set up common required tricircle
# service accounts in keystone
# Project               User            Roles
# -------------------------------------------------------------------------
# $SERVICE_TENANT_NAME  tricircle       service

function create_tricircle_accounts {
    if [[ "$ENABLED_SERVICES" =~ "t-svc-api" ]]; then
        create_service_user "tricircle"

        if [[ "$KEYSTONE_CATALOG_BACKEND" = 'sql' ]]; then
            local tricircle_dispatcher=$(get_or_create_service "tricircle" \
                "Cascading" "OpenStack Cascading Service")
            get_or_create_endpoint $tricircle_dispatcher \
                "$REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CASCADE_API_HOST:$TRICIRCLE_CASCADE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CASCADE_API_HOST:$TRICIRCLE_CASCADE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CASCADE_API_HOST:$TRICIRCLE_CASCADE_API_PORT/v1.0"
        fi
    fi
}

# create_tricircle_cache_dir() - Set up cache dir for tricircle
function create_tricircle_cache_dir {

    # Delete existing dir
    sudo rm -rf $TRICIRCLE_AUTH_CACHE_DIR
    sudo mkdir -p $TRICIRCLE_AUTH_CACHE_DIR
    sudo chown `whoami` $TRICIRCLE_AUTH_CACHE_DIR

}


function configure_tricircle_plugin {
    echo "Configuring Neutron for Tricircle"

    if is_service_enabled q-svc ; then
        Q_PLUGIN_CLASS="tricircle.networking.plugin.TricirclePlugin"

        #NEUTRON_CONF=/etc/neutron/neutron.conf
        iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
        iniset $NEUTRON_CONF DEFAULT service_plugins ""
    fi

    if is_service_enabled t-svc ; then
        echo "Configuring Neutron for Tricircle Cascade Service"
        sudo install -d -o $STACK_USER -m 755 $TRICIRCLE_CONF_DIR
        cp -p $TRICIRCLE_DIR/etc/dispatcher.conf $TRICIRCLE_DISPATCHER_CONF

        TRICIRCLE_POLICY_FILE=$TRICIRCLE_CONF_DIR/policy.json
        cp $TRICIRCLE_DIR/etc/policy.json $TRICIRCLE_POLICY_FILE

        iniset $TRICIRCLE_DISPATCHER_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
        iniset $TRICIRCLE_DISPATCHER_CONF DEFAULT verbose True
        setup_colorized_logging $TRICIRCLE_DISPATCHER_CONF DEFAULT tenant
        iniset $TRICIRCLE_DISPATCHER_CONF DEFAULT bind_host $TRICIRCLE_DISPATCHER_LISTEN_ADDRESS
        iniset $TRICIRCLE_DISPATCHER_CONF DEFAULT use_syslog $SYSLOG
        iniset_rpc_backend tricircle $TRICIRCLE_DISPATCHER_CONF
        iniset $TRICIRCLE_DISPATCHER_CONF database connection `database_connection_url tricircle`
    fi
}

function configure_tricircle_cascade_api {
    echo "Configuring tricircle cascade api service"

    if is_service_enabled t-svc-api ; then
        cp -p $TRICIRCLE_DIR/etc/api.conf $TRICIRCLE_CASCADE_API_CONF
        iniset $TRICIRCLE_CASCADE_API_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
        iniset $TRICIRCLE_CASCADE_API_CONF DEFAULT verbose True
        iniset $TRICIRCLE_CASCADE_API_CONF DEFAULT use_syslog $SYSLOG
        iniset $TRICIRCLE_CASCADE_API_CONF database connection `database_connection_url tricircle`

        iniset $TRICIRCLE_CASCADE_API_CONF client admin_username admin
        iniset $TRICIRCLE_CASCADE_API_CONF client admin_password $ADMIN_PASSWORD
        iniset $TRICIRCLE_CASCADE_API_CONF client admin_tenant demo
        iniset $TRICIRCLE_CASCADE_API_CONF client auto_refresh_endpoint True
        iniset $TRICIRCLE_CASCADE_API_CONF client top_site_name $OS_REGION_NAME

        setup_colorized_logging $TRICIRCLE_CASCADE_API_CONF DEFAULT tenant_name

        if is_service_enabled keystone; then

            create_tricircle_cache_dir

            # Configure auth token middleware
            configure_auth_token_middleware $TRICIRCLE_CASCADE_API_CONF tricircle \
                $TRICIRCLE_AUTH_CACHE_DIR

        else
            iniset $TRICIRCLE_CASCADE_API_CONF DEFAULT auth_strategy noauth
        fi

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
        configure_tricircle_cascade_api

        echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto

        recreate_database tricircle
        python "$TRICIRCLE_DIR/cmd/manage.py" "$TRICIRCLE_DISPATCHER_CONF"

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Cascading Service"

        if is_service_enabled t-svc; then
            run_process t-svc "python $TRICIRCLE_DISPATCHER --config-file $TRICIRCLE_DISPATCHER_CONF --config-dir $TRICIRCLE_CONF_DIR"
        fi

        if is_service_enabled t-svc-api; then

            create_tricircle_accounts

            run_process t-svc-api "python $TRICIRCLE_CASCADE_API --config-file $TRICIRCLE_CASCADE_API_CONF"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then

        if is_service_enabled t-svc; then
           stop_process t-svc
        fi

        if is_service_enabled t-svc-api; then
           stop_process t-svc-api
        fi
    fi
fi
