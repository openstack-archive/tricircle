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
                "Cascading" "OpenStack Cascading Service")
            get_or_create_endpoint $tricircle_api \
                "$REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0"
        fi
    fi
}

# create_nova_apigw_accounts() - Set up common required nova_apigw
# work as nova api serice
# service accounts in keystone
# Project               User            Roles
# -----------------------------------------------------------------
# $SERVICE_TENANT_NAME  nova_apigw      service

function create_nova_apigw_accounts {
    if [[ "$ENABLED_SERVICES" =~ "t-ngw" ]]; then
        create_service_user "nova_apigw"

        if [[ "$KEYSTONE_CATALOG_BACKEND" = 'sql' ]]; then
            local tricircle_nova_apigw=$(get_or_create_service "nova" \
                "compute" "Nova Compute Service")

            remove_old_endpoint_conf $tricircle_nova_apigw

            get_or_create_endpoint $tricircle_nova_apigw \
                "$REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_NOVA_APIGW_HOST:$TRICIRCLE_NOVA_APIGW_PORT/v2.1/"'$(tenant_id)s' \
                "$SERVICE_PROTOCOL://$TRICIRCLE_NOVA_APIGW_HOST:$TRICIRCLE_NOVA_APIGW_PORT/v2.1/"'$(tenant_id)s' \
                "$SERVICE_PROTOCOL://$TRICIRCLE_NOVA_APIGW_HOST:$TRICIRCLE_NOVA_APIGW_PORT/v2.1/"'$(tenant_id)s'
        fi
    fi
}

# create_cinder_apigw_accounts() - Set up common required cinder_apigw
# work as cinder api serice
# service accounts in keystone
# Project               User            Roles
# ---------------------------------------------------------------------
# $SERVICE_TENANT_NAME  cinder_apigw    service

function create_cinder_apigw_accounts {
    if [[ "$ENABLED_SERVICES" =~ "t-cgw" ]]; then
        create_service_user "cinder_apigw"

        if [[ "$KEYSTONE_CATALOG_BACKEND" = 'sql' ]]; then
            local tricircle_cinder_apigw=$(get_or_create_service "cinder" \
                "volumev2" "Cinder Volume Service")

            remove_old_endpoint_conf $tricircle_cinder_apigw

            get_or_create_endpoint $tricircle_cinder_apigw \
                "$REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CINDER_APIGW_HOST:$TRICIRCLE_CINDER_APIGW_PORT/v2/"'$(tenant_id)s' \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CINDER_APIGW_HOST:$TRICIRCLE_CINDER_APIGW_PORT/v2/"'$(tenant_id)s' \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CINDER_APIGW_HOST:$TRICIRCLE_CINDER_APIGW_PORT/v2/"'$(tenant_id)s'
        fi
    fi
}


# common config-file configuration for tricircle services
function remove_old_endpoint_conf {
    local service=$1

    local endpoint_id
    interface_list="public admin internal"
    for interface in $interface_list; do
        endpoint_id=$(openstack endpoint list \
            --service "$service" \
            --interface "$interface" \
            --region "$REGION_NAME" \
            -c ID -f value)
        if [[ -n "$endpoint_id" ]]; then
            # Delete endpoint
            openstack endpoint delete "$endpoint_id"
        fi
    done
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
    iniset $conf_file client top_pod_name $REGION_NAME

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

function configure_tricircle_nova_apigw {
    if is_service_enabled t-ngw ; then
        echo "Configuring Tricircle Nova APIGW"

        init_common_tricircle_conf $TRICIRCLE_NOVA_APIGW_CONF

        setup_colorized_logging $TRICIRCLE_NOVA_APIGW_CONF DEFAULT tenant_name

        if is_service_enabled keystone; then

            create_tricircle_cache_dir

            # Configure auth token middleware
            configure_auth_token_middleware $TRICIRCLE_NOVA_APIGW_CONF tricircle \
                $TRICIRCLE_AUTH_CACHE_DIR

        else
            iniset $TRICIRCLE_NOVA_APIGW_CONF DEFAULT auth_strategy noauth
        fi

    fi
}

function configure_tricircle_cinder_apigw {
    if is_service_enabled t-cgw ; then
        echo "Configuring Tricircle Cinder APIGW"

        init_common_tricircle_conf $TRICIRCLE_CINDER_APIGW_CONF

        setup_colorized_logging $TRICIRCLE_CINDER_APIGW_CONF DEFAULT tenant_name

        if is_service_enabled keystone; then

            create_tricircle_cache_dir

            # Configure auth token middleware
            configure_auth_token_middleware $TRICIRCLE_CINDER_APIGW_CONF tricircle \
                $TRICIRCLE_AUTH_CACHE_DIR

        else
            iniset $TRICIRCLE_CINDER_APIGW_CONF DEFAULT auth_strategy noauth
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

function start_new_neutron_server {
    local server_index=$1
    local region_name=$2
    local q_port=$3

    get_or_create_service "neutron" "network" "Neutron Service"
    get_or_create_endpoint "network" \
        "$region_name" \
        "$Q_PROTOCOL://$SERVICE_HOST:$q_port/" \
        "$Q_PROTOCOL://$SERVICE_HOST:$q_port/" \
        "$Q_PROTOCOL://$SERVICE_HOST:$q_port/"

    cp $NEUTRON_CONF $NEUTRON_CONF.$server_index
    iniset $NEUTRON_CONF.$server_index database connection `database_connection_url $Q_DB_NAME$server_index`
    iniset $NEUTRON_CONF.$server_index nova region_name $region_name
    iniset $NEUTRON_CONF.$server_index DEFAULT bind_port $q_port

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

        enable_service t-api t-ngw t-cgw t-job

        configure_tricircle_api
        configure_tricircle_nova_apigw
        configure_tricircle_cinder_apigw
        configure_tricircle_xjob

        echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto

        setup_package $TRICIRCLE_DIR -e

        recreate_database tricircle
        python "$TRICIRCLE_DIR/cmd/manage.py" "$TRICIRCLE_API_CONF"

        if is_service_enabled q-svc ; then
            start_new_neutron_server 1 $POD_REGION_NAME $TRICIRCLE_NEUTRON_PORT

            # reconfigure neutron server to use our own plugin
            echo "Configuring Neutron plugin for Tricircle"
            Q_PLUGIN_CLASS="tricircle.network.plugin.TricirclePlugin"

            iniset $NEUTRON_CONF DEFAULT core_plugin "$Q_PLUGIN_CLASS"
            iniset $NEUTRON_CONF DEFAULT service_plugins ""
            iniset $NEUTRON_CONF DEFAULT tricircle_db_connection `database_connection_url tricircle`
            iniset $NEUTRON_CONF DEFAULT notify_nova_on_port_data_changes False
            iniset $NEUTRON_CONF DEFAULT notify_nova_on_port_status_changes False
            iniset $NEUTRON_CONF client admin_username admin
            iniset $NEUTRON_CONF client admin_password $ADMIN_PASSWORD
            iniset $NEUTRON_CONF client admin_tenant demo
            iniset $NEUTRON_CONF client auto_refresh_endpoint True
            iniset $NEUTRON_CONF client top_pod_name $REGION_NAME

            if [ "$Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS" != "" ]; then
                iniset $NEUTRON_CONF tricircle type_drivers local,shared_vlan
                iniset $NEUTRON_CONF tricircle tenant_network_types local,shared_vlan
                iniset $NEUTRON_CONF tricircle network_vlan_ranges `echo $Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS | awk -F= '{print $2}'`
                iniset $NEUTRON_CONF tricircle bridge_network_type shared_vlan
            fi
        fi

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Tricircle Service"

        if is_service_enabled t-api; then

            create_tricircle_accounts

            run_process t-api "python $TRICIRCLE_API --config-file $TRICIRCLE_API_CONF"
        fi

        if is_service_enabled t-ngw; then

            create_nova_apigw_accounts

            run_process t-ngw "python $TRICIRCLE_NOVA_APIGW --config-file $TRICIRCLE_NOVA_APIGW_CONF"

            # Nova services are running, but we need to re-configure them to
            # move them to bottom region
            iniset $NOVA_CONF neutron region_name $POD_REGION_NAME
            iniset $NOVA_CONF neutron url "$Q_PROTOCOL://$SERVICE_HOST:$TRICIRCLE_NEUTRON_PORT"
            iniset $NOVA_CONF cinder os_region_name $POD_REGION_NAME

            get_or_create_endpoint "compute" \
                "$POD_REGION_NAME" \
                "$NOVA_SERVICE_PROTOCOL://$NOVA_SERVICE_HOST:$NOVA_SERVICE_PORT/v2.1/"'$(tenant_id)s' \
                "$NOVA_SERVICE_PROTOCOL://$NOVA_SERVICE_HOST:$NOVA_SERVICE_PORT/v2.1/"'$(tenant_id)s' \
                "$NOVA_SERVICE_PROTOCOL://$NOVA_SERVICE_HOST:$NOVA_SERVICE_PORT/v2.1/"'$(tenant_id)s'

            stop_process n-api
            stop_process n-cpu
            # remove previous failure flag file since we are going to restart service
            rm -f "$SERVICE_DIR/$SCREEN_NAME"/n-api.failure
            rm -f "$SERVICE_DIR/$SCREEN_NAME"/n-cpu.failure
            sleep 20
            run_process n-api "$NOVA_BIN_DIR/nova-api"
            run_process n-cpu "$NOVA_BIN_DIR/nova-compute --config-file $NOVA_CONF" $LIBVIRT_GROUP
        fi

        if is_service_enabled t-cgw; then

            create_cinder_apigw_accounts

            run_process t-cgw "python $TRICIRCLE_CINDER_APIGW --config-file $TRICIRCLE_CINDER_APIGW_CONF"

            get_or_create_endpoint "volumev2" \
                "$POD_REGION_NAME" \
                "$CINDER_SERVICE_PROTOCOL://$CINDER_SERVICE_HOST:$CINDER_SERVICE_PORT/v2/"'$(tenant_id)s' \
                "$CINDER_SERVICE_PROTOCOL://$CINDER_SERVICE_HOST:$CINDER_SERVICE_PORT/v2/"'$(tenant_id)s' \
                "$CINDER_SERVICE_PROTOCOL://$CINDER_SERVICE_HOST:$CINDER_SERVICE_PORT/v2/"'$(tenant_id)s'
        fi

        if is_service_enabled t-job; then

            run_process t-job "python $TRICIRCLE_XJOB --config-file $TRICIRCLE_XJOB_CONF"
        fi
    fi

    if [[ "$1" == "unstack" ]]; then

        if is_service_enabled t-api; then
           stop_process t-api
        fi

        if is_service_enabled t-ngw; then
           stop_process t-ngw
        fi

        if is_service_enabled t-cgw; then
           stop_process t-cgw
        fi

        if is_service_enabled t-job; then
           stop_process t-job
        fi

        if is_service_enabled q-svc1; then
           stop_process q-svc1
        fi
    fi
fi
