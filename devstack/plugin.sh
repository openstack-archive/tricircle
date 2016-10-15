# Devstack extras script to install Tricircle

# Test if any tricircle services are enabled
# is_tricircle_enabled
function is_tricircle_enabled {
    [[ ,${ENABLED_SERVICES} =~ ,"t-api" ]] && return 0
    return 1
}

# create_tricircle_accounts() - Set up common required tricircle
# service accounts in keystone
# Project               User            Roles
# -------------------------------------------------------------------------
# $SERVICE_TENANT_NAME  tricircle       service

function create_tricircle_accounts {
    if [[ "$ENABLED_SERVICES" =~ "t-api" ]]; then
        create_service_user "tricircle"

        if [[ "$KEYSTONE_CATALOG_BACKEND" = 'sql' ]]; then
            local tricircle_api=$(get_or_create_service "tricircle" \
                "Tricircle" "Cross Neutron Networking Automation Service")
            get_or_create_endpoint $tricircle_api \
                "$CENTRAL_REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0"
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

# common config-file configuration for tricircle services
function init_common_tricircle_conf {
    local conf_file=$1

    touch $conf_file
    iniset $conf_file DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
    iniset $conf_file DEFAULT verbose True
    iniset $conf_file DEFAULT use_syslog $SYSLOG
    iniset $conf_file DEFAULT tricircle_db_connection `database_connection_url tricircle`

    iniset $conf_file client admin_username admin
    iniset $conf_file client admin_password $ADMIN_PASSWORD
    iniset $conf_file client admin_tenant demo
    iniset $conf_file client auto_refresh_endpoint True
    iniset $conf_file client top_pod_name $CENTRAL_REGION_NAME

    iniset $conf_file oslo_concurrency lock_path $TRICIRCLE_STATE_PATH/lock
}

function configure_tricircle_api {

    if is_service_enabled t-api ; then
        echo "Configuring Tricircle API"

        init_common_tricircle_conf $TRICIRCLE_API_CONF

        setup_colorized_logging $TRICIRCLE_API_CONF DEFAULT tenant_name

        if is_service_enabled keystone; then

            create_tricircle_cache_dir

            # Configure auth token middleware
            configure_auth_token_middleware $TRICIRCLE_API_CONF tricircle \
                $TRICIRCLE_AUTH_CACHE_DIR

        else
            iniset $TRICIRCLE_API_CONF DEFAULT auth_strategy noauth
        fi

    fi
}

function configure_tricircle_xjob {
    if is_service_enabled t-job ; then
        echo "Configuring Tricircle xjob"

        init_common_tricircle_conf $TRICIRCLE_XJOB_CONF

        setup_colorized_logging $TRICIRCLE_XJOB_CONF DEFAULT
    fi
}

function start_central_neutron_server {
    local server_index=0
    local region_name=$1
    local q_port=$2

    get_or_create_service "neutron" "network" "Neutron Service"
    get_or_create_endpoint "network" \
        "$region_name" \
        "$Q_PROTOCOL://$SERVICE_HOST:$q_port/" \
        "$Q_PROTOCOL://$SERVICE_HOST:$q_port/" \
        "$Q_PROTOCOL://$SERVICE_HOST:$q_port/"

    # reconfigure central neutron server to use our own central plugin
    echo "Configuring central Neutron plugin for Tricircle"

    cp $NEUTRON_CONF $NEUTRON_CONF.$server_index
    iniset $NEUTRON_CONF.$server_index database connection `database_connection_url $Q_DB_NAME$server_index`
    iniset $NEUTRON_CONF.$server_index DEFAULT bind_port $q_port
    iniset $NEUTRON_CONF.$server_index DEFAULT core_plugin "tricircle.network.central_plugin.TricirclePlugin"
    iniset $NEUTRON_CONF.$server_index DEFAULT service_plugins ""
    iniset $NEUTRON_CONF.$server_index DEFAULT tricircle_db_connection `database_connection_url tricircle`
    iniset $NEUTRON_CONF.$server_index DEFAULT notify_nova_on_port_data_changes False
    iniset $NEUTRON_CONF.$server_index DEFAULT notify_nova_on_port_status_changes False
    iniset $NEUTRON_CONF.$server_index client admin_username admin
    iniset $NEUTRON_CONF.$server_index client admin_password $ADMIN_PASSWORD
    iniset $NEUTRON_CONF.$server_index client admin_tenant demo
    iniset $NEUTRON_CONF.$server_index client auto_refresh_endpoint True
    iniset $NEUTRON_CONF.$server_index client top_pod_name $CENTRAL_REGION_NAME

    if [ "$Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS" != "" ]; then
        iniset $NEUTRON_CONF.$server_index tricircle type_drivers local,shared_vlan
        iniset $NEUTRON_CONF.$server_index tricircle tenant_network_types local,shared_vlan
        iniset $NEUTRON_CONF.$server_index tricircle network_vlan_ranges `echo $Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS | awk -F= '{print $2}'`
        iniset $NEUTRON_CONF.$server_index tricircle bridge_network_type shared_vlan
        iniset $NEUTRON_CONF.$server_index tricircle enable_api_gateway False
    fi

    recreate_database $Q_DB_NAME$server_index
    $NEUTRON_BIN_DIR/neutron-db-manage --config-file $NEUTRON_CONF.$server_index --config-file /$Q_PLUGIN_CONF_FILE upgrade head

    enable_service q-svc$server_index
    run_process q-svc$server_index "$NEUTRON_BIN_DIR/neutron-server --config-file $NEUTRON_CONF.$server_index --config-file /$Q_PLUGIN_CONF_FILE"
}


if [[ "$Q_ENABLE_TRICIRCLE" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo summary "Tricircle pre-install"
    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Tricircle"
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configuring Tricircle"
        export NEUTRON_CREATE_INITIAL_NETWORKS=False
        sudo install -d -o $STACK_USER -m 755 $TRICIRCLE_CONF_DIR

        enable_service t-api t-job

        configure_tricircle_api
        configure_tricircle_xjob

        echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto

        setup_package $TRICIRCLE_DIR -e

        recreate_database tricircle
        python "$TRICIRCLE_DIR/cmd/manage.py" "$TRICIRCLE_API_CONF"

        if is_service_enabled q-svc ; then
            start_central_neutron_server $CENTRAL_REGION_NAME $TRICIRCLE_NEUTRON_PORT
        fi

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Tricircle Service"

        if is_service_enabled t-api; then

            create_tricircle_accounts

            run_process t-api "python $TRICIRCLE_API --config-file $TRICIRCLE_API_CONF"
        fi

        if is_service_enabled t-job; then

            run_process t-job "python $TRICIRCLE_XJOB --config-file $TRICIRCLE_XJOB_CONF"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then

        if is_service_enabled t-api; then
           stop_process t-api
        fi

        if is_service_enabled t-job; then
           stop_process t-job
        fi

        if is_service_enabled q-svc0; then
           stop_process q-svc0
        fi
    fi
fi
