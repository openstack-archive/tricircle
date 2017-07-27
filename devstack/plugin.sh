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
        create_service_user "tricircle" "admin"
        local tricircle_api=$(get_or_create_service "tricircle" \
            "tricircle" "Cross Neutron Networking Automation Service")

        local tricircle_api_url="$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST/tricircle/v1.0"
        if [[ "$TRICIRCLE_DEPLOY_WITH_WSGI" == "False" ]]; then
            tricircle_api_url="$SERVICE_PROTOCOL://$TRICIRCLE_API_HOST:$TRICIRCLE_API_PORT/v1.0/"
        fi

        get_or_create_endpoint $tricircle_api \
            "$CENTRAL_REGION_NAME" \
            "$tricircle_api_url" \
            "$tricircle_api_url" \
            "$tricircle_api_url"
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

    iniset $conf_file client auth_url http://$KEYSTONE_SERVICE_HOST/identity
    iniset $conf_file client identity_url http://$KEYSTONE_SERVICE_HOST/identity/v3
    iniset $conf_file client admin_username admin
    iniset $conf_file client admin_password $ADMIN_PASSWORD
    iniset $conf_file client admin_tenant demo
    iniset $conf_file client auto_refresh_endpoint True
    iniset $conf_file client top_region_name $CENTRAL_REGION_NAME

    iniset $conf_file oslo_concurrency lock_path $TRICIRCLE_STATE_PATH/lock
}

function init_local_nova_conf {
    iniset $NOVA_CONF glance api_servers http://$KEYSTONE_SERVICE_HOST:9292
    iniset $NOVA_CONF placement os_region_name $CENTRAL_REGION_NAME
}

# common config-file configuration for local Neutron(s)
function init_local_neutron_conf {

    iniset $NEUTRON_CONF DEFAULT core_plugin tricircle.network.local_plugin.TricirclePlugin
    if [[ "$TRICIRCLE_DEPLOY_WITH_CELL" == "True" ]]; then
        iniset $NEUTRON_CONF nova region_name $CENTRAL_REGION_NAME
    fi

    iniset $NEUTRON_CONF client auth_url http://$KEYSTONE_SERVICE_HOST/identity
    iniset $NEUTRON_CONF client identity_url http://$KEYSTONE_SERVICE_HOST/identity/v3
    iniset $NEUTRON_CONF client admin_username admin
    iniset $NEUTRON_CONF client admin_password $ADMIN_PASSWORD
    iniset $NEUTRON_CONF client admin_tenant demo
    iniset $NEUTRON_CONF client auto_refresh_endpoint True
    iniset $NEUTRON_CONF client top_pod_name $CENTRAL_REGION_NAME

    iniset $NEUTRON_CONF tricircle real_core_plugin neutron.plugins.ml2.plugin.Ml2Plugin
    iniset $NEUTRON_CONF tricircle local_region_name $REGION_NAME
    iniset $NEUTRON_CONF tricircle central_neutron_url http://$KEYSTONE_SERVICE_HOST:$TRICIRCLE_NEUTRON_PORT
}

# Set the environment variables for local Neutron(s)
function init_local_neutron_variables {

    export Q_USE_PROVIDERNET_FOR_PUBLIC=True

    Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=${Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS:-}
    Q_ML2_PLUGIN_VXLAN_TYPE_OPTIONS=${Q_ML2_PLUGIN_VXLAN_TYPE_OPTIONS:-}
    # if VLAN options were not set in local.conf, use default VLAN bridge
    # and VLAN options
    if [ "$Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS" == "" ]; then

        export TRICIRCLE_ADD_DEFAULT_BRIDGES=True

        local vlan_option="bridge:$TRICIRCLE_DEFAULT_VLAN_RANGE"
        local ext_option="extern:$TRICIRCLE_DEFAULT_EXT_RANGE"
        local vlan_ranges=(network_vlan_ranges=$vlan_option,$ext_option)
        Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS=$vlan_ranges
        Q_ML2_PLUGIN_VXLAN_TYPE_OPTIONS="vni_ranges=$TRICIRCLE_DEFAULT_VXLAN_RANGE"
        Q_ML2_PLUGIN_FLAT_TYPE_OPTIONS="flat_networks=$TRICIRCLE_DEFAULT_FLAT_NETWORKS"

        local vlan_mapping="bridge:$TRICIRCLE_DEFAULT_VLAN_BRIDGE"
        local ext_mapping="extern:$TRICIRCLE_DEFAULT_EXT_BRIDGE"
        OVS_BRIDGE_MAPPINGS=$vlan_mapping,$ext_mapping

    fi
    if [ "$TRICIRCLE_ENABLE_TRUNK" == "True" ]; then
        _neutron_service_plugin_class_add trunk
    fi
}

function add_default_bridges {

    if [ "$TRICIRCLE_ADD_DEFAULT_BRIDGES" == "True" ]; then
        _neutron_ovs_base_add_bridge $TRICIRCLE_DEFAULT_VLAN_BRIDGE
        _neutron_ovs_base_add_bridge $TRICIRCLE_DEFAULT_EXT_BRIDGE
    fi
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

# configure_tricircle_api_wsgi() - Set WSGI config files
function configure_tricircle_api_wsgi {
    local tricircle_api_apache_conf
    local venv_path=""
    local tricircle_bin_dir=""
    local tricircle_ssl_listen="#"

    tricircle_bin_dir=$(get_python_exec_prefix)
    tricircle_api_apache_conf=$(apache_site_config_for tricircle-api)

    if is_ssl_enabled_service "tricircle-api"; then
        tricircle_ssl_listen=""
        tricircle_ssl="SSLEngine On"
        tricircle_certfile="SSLCertificateFile $TRICIRCLE_SSL_CERT"
        tricircle_keyfile="SSLCertificateKeyFile $TRICIRCLE_SSL_KEY"
    fi

    # configure venv bin if VENV is used
    if [[ ${USE_VENV} = True ]]; then
        venv_path="python-path=${PROJECT_VENV["tricircle"]}/lib/$(python_version)/site-packages"
        tricircle_bin_dir=${PROJECT_VENV["tricircle"]}/bin
    fi

    sudo cp $TRICIRCLE_API_APACHE_TEMPLATE $tricircle_api_apache_conf
    sudo sed -e "
        s|%TRICIRCLE_BIN%|$tricircle_bin_dir|g;
        s|%PUBLICPORT%|$TRICIRCLE_API_PORT|g;
        s|%APACHE_NAME%|$APACHE_NAME|g;
        s|%PUBLICWSGI%|$tricircle_bin_dir/tricircle-api-wsgi|g;
        s|%SSLENGINE%|$tricircle_ssl|g;
        s|%SSLCERTFILE%|$tricircle_certfile|g;
        s|%SSLKEYFILE%|$tricircle_keyfile|g;
        s|%SSLLISTEN%|$tricircle_ssl_listen|g;
        s|%USER%|$STACK_USER|g;
        s|%VIRTUALENV%|$venv_path|g
        s|%APIWORKERS%|$API_WORKERS|g
    " -i $tricircle_api_apache_conf
}

# start_tricircle_api_wsgi() - Start the API processes ahead of other things
function start_tricircle_api_wsgi {
    enable_apache_site tricircle-api
    restart_apache_server
    tail_log tricircle-api /var/log/$APACHE_NAME/tricircle-api.log

    echo "Waiting for tricircle-api to start..."
    if ! wait_for_service $SERVICE_TIMEOUT $TRICIRCLE_API_PROTOCOL://$TRICIRCLE_API_HOST/tricircle; then
        die $LINENO "tricircle-api did not start"
    fi
}

# stop_tricircle_api_wsgi() - Disable the api service and stop it.
function stop_tricircle_api_wsgi {
    disable_apache_site tricircle-api
    restart_apache_server
}

# cleanup_tricircle_api_wsgi() - Remove residual data files, anything left over from previous
# runs that a clean run would need to clean up
function cleanup_tricircle_api_wsgi {
    sudo rm -f $(apache_site_config_for tricircle-api)
}

function configure_tricircle_xjob {
    if is_service_enabled t-job ; then
        echo "Configuring Tricircle xjob"

        init_common_tricircle_conf $TRICIRCLE_XJOB_CONF

        setup_colorized_logging $TRICIRCLE_XJOB_CONF DEFAULT
    fi
}

function start_central_nova_server {
    local local_region=$1
    local central_region=$2
    local central_neutron_port=$3

    # reconfigure central neutron server to use our own central plugin
    echo "Configuring Nova API for Tricircle to work with cell V2"

    cp $NOVA_CONF $NOVA_CONF.0
    iniset $NOVA_CONF.0 neutron region_name $central_region
    iniset $NOVA_CONF.0 neutron url "$Q_PROTOCOL://$SERVICE_HOST:$central_neutron_port"

    nova_endpoint_id=$(openstack endpoint list --service compute --interface public --region $local_region -c ID -f value)
    openstack endpoint set --region $central_region $nova_endpoint_id
    nova_legacy_endpoint_id=$(openstack endpoint list --service compute_legacy --interface public --region $local_region -c ID -f value)
    openstack endpoint set --region $central_region $nova_legacy_endpoint_id
    image_endpoint_id=$(openstack endpoint list --service image --interface public --region $local_region -c ID -f value)
    openstack endpoint set --region $central_region $image_endpoint_id
    place_endpoint_id=$(openstack endpoint list --service placement --interface public --region $local_region -c ID -f value)
    openstack endpoint set --region $central_region $place_endpoint_id

    stop_process n-api
    # remove previous failure flag file since we are going to restart service
    rm -f "$SERVICE_DIR/$SCREEN_NAME"/n-api.failure
    sleep 20
    run_process n-api "$NOVA_BIN_DIR/nova-api --config-file $NOVA_CONF.0"

    restart_apache_server
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
    iniset $NEUTRON_CONF.$server_index client top_region_name $CENTRAL_REGION_NAME

    local service_plugins=''
    if [ "$TRICIRCLE_ENABLE_TRUNK" == "True" ]; then
        service_plugins+=",tricircle.network.central_trunk_plugin.TricircleTrunkPlugin"
    fi
    if [ "$TRICIRCLE_ENABLE_SFC" == "True" ]; then
        service_plugins+=",networking_sfc.services.flowclassifier.plugin.FlowClassifierPlugin,tricircle.network.central_sfc_plugin.TricircleSfcPlugin"
        iniset $NEUTRON_CONF.$server_index sfc drivers tricircle_sfc
        iniset $NEUTRON_CONF.$server_index flowclassifier drivers tricircle_fc
    fi
    if [ -n service_plugins ]; then
        service_plugins=$(echo $service_plugins| sed 's/^,//')
        iniset $NEUTRON_CONF.$server_index DEFAULT service_plugins "$service_plugins"
    fi

    local type_drivers=''
    local tenant_network_types=''
    if [ "$Q_ML2_PLUGIN_VXLAN_TYPE_OPTIONS" != "" ]; then
        type_drivers+=,vxlan
        tenant_network_types+=,vxlan
        iniset $NEUTRON_CONF.$server_index tricircle vni_ranges `echo $Q_ML2_PLUGIN_VXLAN_TYPE_OPTIONS | awk -F= '{print $2}'`
    fi
    if [ "$Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS" != "" ]; then
        type_drivers+=,vlan
        tenant_network_types+=,vlan
        iniset $NEUTRON_CONF.$server_index tricircle network_vlan_ranges `echo $Q_ML2_PLUGIN_VLAN_TYPE_OPTIONS | awk -F= '{print $2}'`
    fi
    if [ "Q_ML2_PLUGIN_FLAT_TYPE_OPTIONS" != "" ]; then
        type_drivers+=,flat
        tenant_network_types+=,flat
        iniset $NEUTRON_CONF.$server_index tricircle flat_networks `echo $Q_ML2_PLUGIN_FLAT_TYPE_OPTIONS | awk -F= '{print $2}'`
    fi
    type_drivers+=,local
    tenant_network_types+=,local
    # remove the heading ","
    type_drivers=$(echo $type_drivers | sed 's/^,//')
    tenant_network_types=$(echo $tenant_network_types | sed 's/^,//')

    iniset $NEUTRON_CONF.$server_index tricircle type_drivers $type_drivers
    iniset $NEUTRON_CONF.$server_index tricircle tenant_network_types $tenant_network_types
    iniset $NEUTRON_CONF.$server_index tricircle enable_api_gateway False
    # default value of bridge_network_type is vxlan

    recreate_database $Q_DB_NAME$server_index
    $NEUTRON_BIN_DIR/neutron-db-manage --config-file $NEUTRON_CONF.$server_index --config-file /$Q_PLUGIN_CONF_FILE upgrade head

    enable_service q-svc$server_index
    run_process q-svc$server_index "$NEUTRON_BIN_DIR/neutron-server --config-file $NEUTRON_CONF.$server_index --config-file /$Q_PLUGIN_CONF_FILE"
}

# install_tricircleclient() - Collect source and prepare
function install_tricircleclient {
    if use_library_from_git "python-tricircleclient"; then
        git_clone_by_name "python-tricircleclient"
        setup_dev_lib "python-tricircleclient"
    else
        pip_install_gr tricircleclient
    fi
}


# if the plugin is enabled to run, that means the Tricircle is enabled
# by default, so no need to judge the variable Q_ENABLE_TRICIRCLE

if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
    echo_summary "Tricircle pre-install"

    # init_local_neutron_variables before installation
    init_local_neutron_variables

elif [[ "$1" == "stack" && "$2" == "install" ]]; then
    echo_summary "Installing Tricircle"
elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then

    echo_summary "Configuring Tricircle"
    install_tricircleclient
    export NEUTRON_CREATE_INITIAL_NETWORKS=False
    sudo install -d -o $STACK_USER -m 755 $TRICIRCLE_CONF_DIR

    if [[ "$TRICIRCLE_START_SERVICES" == "True" ]]; then
        enable_service t-api t-job
        configure_tricircle_api
        configure_tricircle_xjob

        if [[ "$TRICIRCLE_DEPLOY_WITH_WSGI" == "True" ]]; then
            configure_tricircle_api_wsgi
        fi
    fi

    echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto

    setup_package $TRICIRCLE_DIR -e

    if [[ "$TRICIRCLE_START_SERVICES" == "True" ]]; then
        recreate_database tricircle
        tricircle-db-manage --config-file="$TRICIRCLE_API_CONF" db_sync

        if is_service_enabled q-svc ; then
            start_central_neutron_server $CENTRAL_REGION_NAME $TRICIRCLE_NEUTRON_PORT
        fi
    fi

    # update the local neutron.conf after the central Neutron has started
    init_local_neutron_conf

    if [[ "$TRICIRCLE_DEPLOY_WITH_CELL" == "True" ]]; then
        # update the local nova.conf
        init_local_nova_conf
    fi

    # add default bridges br-vlan, br-ext if needed, ovs-vsctl
    # is just being installed before this stage
    add_default_bridges

elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
    echo_summary "Initializing Tricircle Service"

    if [[ ${USE_VENV} = True ]]; then
        PROJECT_VENV["tricircle"]=${TRICIRCLE_DIR}.venv
        TRICIRCLE_BIN_DIR=${PROJECT_VENV["tricircle"]}/bin
    else
        TRICIRCLE_BIN_DIR=$(get_python_exec_prefix)
    fi

    if is_service_enabled t-api; then

        create_tricircle_accounts

        if [[ "$TRICIRCLE_DEPLOY_WITH_WSGI" == "True" ]]; then
            start_tricircle_api_wsgi
        else
            run_process t-api "$TRICIRCLE_BIN_DIR/tricircle-api --config-file $TRICIRCLE_API_CONF"
        fi

        if [[ "$TRICIRCLE_DEPLOY_WITH_CELL" == "True" && "$TRICIRCLE_START_SERVICES" == "True" ]]; then
            start_central_nova_server $REGION_NAME $CENTRAL_REGION_NAME $TRICIRCLE_NEUTRON_PORT
        fi
    fi

    if is_service_enabled t-job; then
        run_process t-job "$TRICIRCLE_BIN_DIR/tricircle-xjob --config-file $TRICIRCLE_XJOB_CONF"
    fi
fi

if [[ "$1" == "unstack" ]]; then

    if is_service_enabled t-api; then
        if [[ "$TRICIRCLE_DEPLOY_WITH_WSGI" == "True" ]]; then
            stop_tricircle_api_wsgi
            clean_tricircle_api_wsgi
        else
            stop_process t-api
        fi
    fi

    if is_service_enabled t-job; then
       stop_process t-job
    fi

    if is_service_enabled q-svc0; then
       stop_process q-svc0
    fi
fi
