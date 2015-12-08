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
                "$TRICIRCLE_REGION_NAME" \
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
            get_or_create_endpoint $tricircle_nova_apigw \
                "$TRICIRCLE_REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_NOVA_APIGW_HOST:$TRICIRCLE_NOVA_APIGW_PORT/v2.1/" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_NOVA_APIGW_HOST:$TRICIRCLE_NOVA_APIGW_PORT/v2.1/" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_NOVA_APIGW_HOST:$TRICIRCLE_NOVA_APIGW_PORT/v2.1/"
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
                "volume" "Cinder Volume Service")
            get_or_create_endpoint $tricircle_cinder_apigw \
                "$TRICIRCLE_REGION_NAME" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CINDER_APIGW_HOST:$TRICIRCLE_CINDER_APIGW_PORT/v2/" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CINDER_APIGW_HOST:$TRICIRCLE_CINDER_APIGW_PORT/v2/" \
                "$SERVICE_PROTOCOL://$TRICIRCLE_CINDER_APIGW_HOST:$TRICIRCLE_CINDER_APIGW_PORT/v2/"
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

function configure_tricircle_api {
    if is_service_enabled t-api ; then
        echo "Configuring Tricircle API"

        touch $TRICIRCLE_API_CONF
        iniset $TRICIRCLE_API_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
        iniset $TRICIRCLE_API_CONF DEFAULT verbose True
        iniset $TRICIRCLE_API_CONF DEFAULT use_syslog $SYSLOG
        iniset $TRICIRCLE_API_CONF database connection `database_connection_url tricircle`

        iniset $TRICIRCLE_API_CONF client admin_username admin
        iniset $TRICIRCLE_API_CONF client admin_password $ADMIN_PASSWORD
        iniset $TRICIRCLE_API_CONF client admin_tenant demo
        iniset $TRICIRCLE_API_CONF client auto_refresh_endpoint True
        iniset $TRICIRCLE_API_CONF client top_site_name $TRICIRCLE_REGION_NAME

        iniset $TRICIRCLE_API_CONF oslo_concurrency lock_path $TRICIRCLE_STATE_PATH/lock

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

        touch $TRICIRCLE_NOVA_APIGW_CONF
        iniset $TRICIRCLE_NOVA_APIGW_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
        iniset $TRICIRCLE_NOVA_APIGW_CONF DEFAULT verbose True
        iniset $TRICIRCLE_NOVA_APIGW_CONF DEFAULT use_syslog $SYSLOG
        iniset $TRICIRCLE_NOVA_APIGW_CONF database connection `database_connection_url tricircle`

        iniset $TRICIRCLE_NOVA_APIGW_CONF oslo_concurrency lock_path $TRICIRCLE_STATE_PATH/lock

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

        touch $TRICIRCLE_CINDER_APIGW_CONF
        iniset $TRICIRCLE_CINDER_APIGW_CONF DEFAULT debug $ENABLE_DEBUG_LOG_LEVEL
        iniset $TRICIRCLE_CINDER_APIGW_CONF DEFAULT verbose True
        iniset $TRICIRCLE_CINDER_APIGW_CONF DEFAULT use_syslog $SYSLOG
        iniset $TRICIRCLE_CINDER_APIGW_CONF database connection `database_connection_url tricircle`

        iniset $TRICIRCLE_CINDER_APIGW_CONF oslo_concurrency lock_path $TRICIRCLE_STATE_PATH/lock

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


if [[ "$Q_ENABLE_TRICIRCLE" == "True" ]]; then
    if [[ "$1" == "stack" && "$2" == "pre-install" ]]; then
        echo summary "Tricircle pre-install"
    elif [[ "$1" == "stack" && "$2" == "install" ]]; then
        echo_summary "Installing Tricircle"
    elif [[ "$1" == "stack" && "$2" == "post-config" ]]; then
        echo_summary "Configuring Tricircle"

        sudo install -d -o $STACK_USER -m 755 $TRICIRCLE_CONF_DIR

        configure_tricircle_api
        configure_tricircle_nova_apigw
        configure_tricircle_cinder_apigw

        echo export PYTHONPATH=\$PYTHONPATH:$TRICIRCLE_DIR >> $RC_DIR/.localrc.auto

        recreate_database tricircle
        python "$TRICIRCLE_DIR/cmd/manage.py" "$TRICIRCLE_API_CONF"

    elif [[ "$1" == "stack" && "$2" == "extra" ]]; then
        echo_summary "Initializing Tricircle Service"

        if is_service_enabled t-api; then

            create_tricircle_accounts

            run_process t-api "python $TRICIRCLE_API --config-file $TRICIRCLE_API_CONF"
        fi

        if is_service_enabled t-ngw; then

            create_nova_apigw_accounts

            run_process t-ngw "python $TRICIRCLE_NOVA_APIGW --config-file $TRICIRCLE_NOVA_APIGW_CONF"
        fi

        if is_service_enabled t-cgw; then

            create_cinder_apigw_accounts

            run_process t-cgw "python $TRICIRCLE_CINDER_APIGW --config-file $TRICIRCLE_CINDER_APIGW_CONF"
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
    fi
fi
